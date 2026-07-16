package main

import (
	"bytes"
	"encoding/json"
	"fmt"
	"log"
	"net"
	"net/http"
	"os"
	"os/exec"
	"path/filepath"
	"runtime"
	"strconv"
	"strings"
	"time"

	"github.com/shirou/gopsutil/mem"
)

type HeartbeatResponse struct {
	Uptime string `json:"uptime"`
}

type Task struct {
	ID      string                 `json:"task_id"`
	JobType string                 `json:"job_type"`
	Payload map[string]interface{} `json:"payload"`
}

var (
	port           = ":8081"
	coordinatorURL = os.Getenv("COORDINATOR_URL")
	workerID       string
	workspace      = os.Getenv("HYDRA_WORKSPACE")
	slots          chan struct{}
)

func main() {
	if coordinatorURL == "" {
		coordinatorURL = "http://127.0.0.1:5001"
	}
	if workspace == "" {
		workspace = "/work"
	}

	maxConcurrency := environmentInt("WORKER_MAX_CONCURRENCY", 1)
	slots = make(chan struct{}, maxConcurrency)

	workerIP, err := getLocalIP()
	if err != nil {
		log.Fatalf("Error fetching IP address: %v", err)
	}
	workerID = "WID_" + strings.Join(strings.Split(workerIP, "."), "") + strings.Split(port, ":")[1]
	if err := registerWorker(workerIP, maxConcurrency); err != nil {
		log.Fatalf("Unable to register worker: %v", err)
	}

	http.HandleFunc("/submit", taskHandler)
	http.HandleFunc("/heartbeat", heartbeatHandler)
	log.Printf("Worker %s running on port %s with capacity %d", workerID, port, maxConcurrency)
	log.Fatal(http.ListenAndServe(port, nil))
}

func environmentInt(name string, fallback int) int {
	value, err := strconv.Atoi(os.Getenv(name))
	if err != nil || value < 1 {
		return fallback
	}
	return value
}

func taskHandler(w http.ResponseWriter, r *http.Request) {
	if r.Method != http.MethodPost {
		http.Error(w, "Method not allowed", http.StatusMethodNotAllowed)
		return
	}
	select {
	case slots <- struct{}{}:
		defer func() { <-slots }()
	default:
		http.Error(w, "Worker is at capacity", http.StatusTooManyRequests)
		return
	}

	var task Task
	if err := json.NewDecoder(r.Body).Decode(&task); err != nil {
		http.Error(w, "Invalid request body", http.StatusBadRequest)
		return
	}
	if task.ID == "" {
		http.Error(w, "task_id is required", http.StatusBadRequest)
		return
	}

	if err := updateWorkerStatus(task.ID, "STARTED"); err != nil {
		log.Printf("Unable to report task %s started: %v", task.ID, err)
	}
	if err := runTask(task); err != nil {
		log.Printf("Task %s failed: %v", task.ID, err)
		if updateErr := updateWorkerStatus(task.ID, "FAILED"); updateErr != nil {
			log.Printf("Unable to report task %s failed: %v", task.ID, updateErr)
		}
		http.Error(w, "Task failed", http.StatusInternalServerError)
		return
	}
	if err := updateWorkerStatus(task.ID, "COMPLETED"); err != nil {
		log.Printf("Unable to report task %s completed: %v", task.ID, err)
	}
	w.WriteHeader(http.StatusOK)
}

func runTask(task Task) error {
	switch task.JobType {
	case "echo":
		message, ok := task.Payload["message"].(string)
		if !ok || message == "" || len(message) > 1024 {
			return fmt.Errorf("invalid echo payload")
		}
		return exec.Command("echo", message).Run()
	case "sleep":
		duration, ok := task.Payload["duration_seconds"].(float64)
		if !ok || duration < 0 || duration > 300 || duration != float64(int(duration)) {
			return fmt.Errorf("invalid sleep payload")
		}
		return exec.Command("sleep", strconv.Itoa(int(duration))).Run()
	case "sha256":
		path, ok := task.Payload["path"].(string)
		if !ok || path == "" {
			return fmt.Errorf("invalid sha256 payload")
		}
		resolved, err := workspacePath(path)
		if err != nil {
			return err
		}
		return exec.Command("sha256sum", resolved).Run()
	default:
		return fmt.Errorf("unsupported job type %q", task.JobType)
	}
}

func workspacePath(path string) (string, error) {
	root, err := filepath.Abs(workspace)
	if err != nil {
		return "", err
	}
	resolved, err := filepath.Abs(filepath.Join(root, path))
	if err != nil {
		return "", err
	}
	relative, err := filepath.Rel(root, resolved)
	if err != nil || relative == ".." || strings.HasPrefix(relative, ".."+string(os.PathSeparator)) {
		return "", fmt.Errorf("path must remain inside %s", root)
	}
	return resolved, nil
}

func heartbeatHandler(w http.ResponseWriter, r *http.Request) {
	w.Header().Set("Content-Type", "application/json")
	json.NewEncoder(w).Encode(HeartbeatResponse{Uptime: time.Since(startTime()).String()})
}

func registerWorker(workerIP string, maxConcurrency int) error {
	vmStat, _ := mem.VirtualMemory()
	data := map[string]interface{}{
		"worker_id":       workerID,
		"ip":              workerIP,
		"port":            port,
		"max_concurrency": maxConcurrency,
		"metadata": map[string]interface{}{
			"num_cpu":   runtime.NumCPU(),
			"total_ram": vmStat.Total,
		},
	}
	jsonData, err := json.Marshal(data)
	if err != nil {
		return err
	}

	var lastErr error
	for attempt := 1; attempt <= 30; attempt++ {
		response, err := http.Post(coordinatorURL+"/register", "application/json", bytes.NewBuffer(jsonData))
		if err == nil && response.StatusCode == http.StatusOK {
			response.Body.Close()
			return nil
		}
		if response != nil {
			response.Body.Close()
		}
		lastErr = err
		time.Sleep(2 * time.Second)
	}
	return fmt.Errorf("registration failed after retries: %v", lastErr)
}

func updateWorkerStatus(taskID, status string) error {
	data := map[string]interface{}{"task_id": taskID, "status": status, "worker_id": workerID}
	jsonData, err := json.Marshal(data)
	if err != nil {
		return err
	}
	response, err := http.Post(coordinatorURL+"/jobStatusUpdate", "application/json", bytes.NewBuffer(jsonData))
	if err != nil {
		return err
	}
	defer response.Body.Close()
	if response.StatusCode != http.StatusOK {
		return fmt.Errorf("coordinator returned %s", response.Status)
	}
	return nil
}

func getLocalIP() (string, error) {
	addrs, err := net.InterfaceAddrs()
	if err != nil {
		return "", err
	}
	for _, address := range addrs {
		if ipnet, ok := address.(*net.IPNet); ok && !ipnet.IP.IsLoopback() && ipnet.IP.To4() != nil {
			return ipnet.IP.String(), nil
		}
	}
	return "", fmt.Errorf("no suitable IP address found")
}

func startTime() time.Time {
	return startTimeVar
}

var startTimeVar = time.Now()
