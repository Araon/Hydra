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
	"runtime"
	"strings"
	"sync"
	"time"

	"github.com/shirou/gopsutil/mem"
)

type HeartbeatResponse struct {
	Uptime string `json:"uptime"`
}

type Task struct {
	Id      string `json:"task_id"`
	Command string `json:"command"`
}

var port = ":8081"
var coordinatorURL = os.Getenv("COORDINATOR_URL")

// var workerIP = "127.0.0.1"

// var coordinatorURL = "http://127.0.0.1:5001" // TODO: Pull from config file too

var disAllowedCommands = []string{"rm -rf", "sudo"} // TODO: update or pull from config file.

func main() {

	if coordinatorURL == "" {
		coordinatorURL = "http://127.0.0.1:5001"
	}
	fmt.Println("Coordinator URL:", coordinatorURL)

	workerIP, err := getLocalIP()
	if err != nil {
		log.Fatalf("Error fetching IP address: %v", err)
	}
	workerID := "WID_" + strings.Join(strings.Split(workerIP, "."), "") + strings.Split(port, ":")[1]
	
	for {
		err := registerWorker(workerID, workerIP)
		if err == nil {
			break
		}
		log.Printf("Failed to register worker: %v. Retrying in 5 seconds...", err)
		time.Sleep(5 * time.Second)
	}
	
	http.HandleFunc("/submit", taskHandler)
	http.HandleFunc("/heartbeat", heartBeatHandler)
	log.Fatal(http.ListenAndServe(port, nil))
	fmt.Printf("Worker running on port %s", port)
}

func taskHandler(w http.ResponseWriter, r *http.Request) {
	// handle the task with safety

	if r.Method != http.MethodPost {
		http.Error(w, "Method not allowed", http.StatusMethodNotAllowed)
		return
	}

	var task Task
	if err := json.NewDecoder(r.Body).Decode(&task); err != nil {
		http.Error(w, "Invalid request body", http.StatusBadRequest)
		return
	}

	fmt.Printf("Task received Id: %s\n", strings.Join(strings.Split(task.Id, "-"), ""))
	fmt.Printf("Command: %s\n", task.Command)

	if !isAllowedCommand(task.Command) {
		http.Error(w, "Command not allowed - please retry with valid error", http.StatusBadRequest)
		fmt.Printf("Command can not be allowed")
		return
	}

	// Synchronously update status to STARTED
	if err := updateWorkerStatus(task.Id, "STARTED"); err != nil {
		log.Printf("Failed to send STARTED status: %v", err)
	}
	fmt.Println("Command execution started for: ", task.Id)

	// Use sh -c for command execution to support arguments
	cmd := exec.Command("sh", "-c", task.Command)

	err := cmd.Run()

	if err != nil {
		fmt.Println("Failed to run command:", err)
		if updateErr := updateWorkerStatus(task.Id, "FAILED"); updateErr != nil {
			log.Printf("Failed to send FAILED status: %v", updateErr)
		}
		w.WriteHeader(http.StatusInternalServerError)
		return
	}

	if updateErr := updateWorkerStatus(task.Id, "COMPLETED"); updateErr != nil {
		log.Printf("Failed to send COMPLETED status: %v", updateErr)
	}
	fmt.Println("Command execution completed successfully")
	w.WriteHeader(http.StatusOK)

}

func isAllowedCommand(command string) bool {
	trimmed := strings.TrimSpace(command)
	for _, disallowed := range disAllowedCommands {
		if strings.HasPrefix(trimmed, disallowed) {
			return false
		}
	}
	return true
}

func heartBeatHandler(w http.ResponseWriter, r *http.Request) {
	uptime := time.Since(startTime()).String()

	response := HeartbeatResponse{
		Uptime: uptime,
	}

	w.Header().Set("Content-Type", "application/json")
	json.NewEncoder(w).Encode(response)
}

func registerWorker(workerID, workerIP string) error {

	numCPU := runtime.NumCPU()
	vmStat, _ := mem.VirtualMemory()
	data := map[string]interface{}{
		"worker_id": workerID,
		"ip":        workerIP,
		"port":      port,
		"metadata": map[string]interface{}{
			"num_cpu":   numCPU,
			"total_ram": vmStat.Total,
		},
	}
	jsonData, err := json.Marshal(data)
	if err != nil {
		log.Printf("Error encoding JSON: %v", err)
		return err
	}

	registerWorkerURL := coordinatorURL + "/register"

	resp, err := http.Post(registerWorkerURL, "application/json", bytes.NewBuffer(jsonData))
	if err != nil {
		log.Printf("Error registering to coordinator: %v", err)
		return err
	}

	defer resp.Body.Close()

	if resp.StatusCode != http.StatusOK {
		log.Printf("Unable to connect to coordinator: %v", resp.StatusCode)
		return fmt.Errorf("status code %d", resp.StatusCode)
	}

	log.Printf("Worker %s has been registered\n", workerID)
	return nil
}

func updateWorkerStatus(taskId, output string) error {
	// sends task update to the coordinator
	data := map[string]interface{}{
		"task_id": taskId,
		"status":  output,
	}

	jsonData, err := json.Marshal(data)
	if err != nil {
		log.Printf("Error encoding JSON: %v", err)
		return err
	}

	jobUpdateURL := coordinatorURL + "/jobStatusUpdate"

	resp, err := http.Post(jobUpdateURL, "application/json", bytes.NewBuffer(jsonData))
	if err != nil {
		log.Printf("Error sending task update to coordinator: %v", err)
		return err
	}

	defer resp.Body.Close()

	if resp.StatusCode != http.StatusOK {
		log.Printf("Unable to connect to coordinator: %v", resp.StatusCode)
		return fmt.Errorf("status code %d", resp.StatusCode)
	}

	log.Printf("Task_id: %s has been Updated with status: %s\n", taskId, output)
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
