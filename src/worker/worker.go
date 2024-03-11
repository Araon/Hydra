package main

import (
	"bytes"
	"encoding/json"
	"fmt"
	"log"
	"net"
	"net/http"
	"os/exec"
	"runtime"
	"strings"
	"sync"
	"time"

	"github.com/shirou/gopsutil/mem"
)

type HearttbeatResponse struct {
	Uptime string `json:"uptime"`
}

type Task struct {
	Id      string `json:"task_id"`
	Command string `json:"command"`
}

var port = ":8081"

// var workerIP = "127.0.0.1"
var coordinatorURL = "http://127.0.0.1:5001" // TODO: Pull from config file too

var disAllowedCommands = []string{"rm -rf", "sudo"} // TODO: update or pull from config file.

func main() {

	workerIP, err := getLocalIP()
	if err != nil {
		log.Fatalf("Error fetching IP address: %v", err)
	}
	workerID := "WID_" + strings.Join(strings.Split(workerIP, "."), "") + strings.Split(port, ":")[1]
	registerWorker(workerID, workerIP)
	http.HandleFunc("/submit", taskHandler)
	http.HandleFunc("/heartbeat", heartBeatHandler)
	log.Fatal(http.ListenAndServe(port, nil))
	fmt.Printf("Worker running on port %s", port)
}

func taskHandler(w http.ResponseWriter, r *http.Request) {
	// handle the task with safety

	var wg sync.WaitGroup
	wg.Add(1)

	if r.Method != http.MethodPost {
		http.Error(w, "Method not allowed", http.StatusMethodNotAllowed)
		return
	}

	var task Task
	if err := json.NewDecoder(r.Body).Decode(&task); err != nil {
		http.Error(w, "Invalid request body", http.StatusBadRequest)
		return
	}

	fmt.Printf("Task recevied Id: %s\n", strings.Join(strings.Split(task.Id, "-"), ""))
	fmt.Printf("Command: %s\n", task.Command)

	if !isAllowedCommand(task.Command) {
		http.Error(w, "Command not allowed - please retry with valid error", http.StatusBadRequest)
		fmt.Printf("Command can not be allowed")
		return
	}

	cmd := exec.Command(task.Command)

	go func() {
		go updateWorkerStatus(task.Id, "STARTED")
		fmt.Println("Command execution started for: ", task.Id)
		wg.Done()

	}()

	err := cmd.Run()

	if err != nil {
		fmt.Println("Failed to run command:", err)
		wg.Wait()
		go updateWorkerStatus(task.Id, "FAILED")
		w.WriteHeader(http.StatusInternalServerError)
		return
	}

	wg.Wait()
	go updateWorkerStatus(task.Id, "COMPLETED")
	fmt.Println("Command execution completed successfully")
	w.WriteHeader(http.StatusOK)

}

func isAllowedCommand(command string) bool {
	for _, disallowed := range disAllowedCommands {
		if strings.HasPrefix(command, disallowed) {
			return false
		}
	}
	return true
}

func heartBeatHandler(w http.ResponseWriter, r *http.Request) {
	uptime := time.Since(startTime()).String()

	response := HearttbeatResponse{
		Uptime: uptime,
	}

	w.Header().Set("Content-Type", "application/json")
	json.NewEncoder(w).Encode(response)
}

func registerWorker(workerID, workerIP string) {

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
		log.Fatalf("Error encoding JSON: %v", err)
	}

	registerWorkerURL := coordinatorURL + "/register"

	resp, err := http.Post(registerWorkerURL, "application/json", bytes.NewBuffer(jsonData))
	if err != nil {
		log.Fatalf("Error registering to coordinator: %v", err)
	}

	defer resp.Body.Close()

	if resp.StatusCode != http.StatusOK {
		log.Fatalf("Unable to connect to coordinator: %v", resp.StatusCode)
	}

	log.Printf("Worker %s has been registered\n", workerID)
}

func updateWorkerStatus(taskId, output string) {
	// sends task update to the coordinator
	data := map[string]interface{}{
		"task_id": taskId,
		"status":  output,
	}

	jsonData, err := json.Marshal(data)
	if err != nil {
		log.Fatalf("Error encoding JSON: %v", err)
	}

	jobUpdateURL := coordinatorURL + "/jobStatusUpdate"

	resp, err := http.Post(jobUpdateURL, "application/json", bytes.NewBuffer(jsonData))
	if err != nil {
		log.Fatalf("Error sending task update to coordinator: %v", err)
	}

	defer resp.Body.Close()

	if resp.StatusCode != http.StatusOK {
		log.Fatalf("Unable to connect to coordinator: %v", resp.StatusCode)
	}

	log.Printf("Task_id: %s has been Updated with status: %s\n", taskId, output)
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
