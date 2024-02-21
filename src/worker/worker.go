package main

import (
	"bytes"
	"encoding/json"
	"fmt"
	"log"
	"net/http"
	"time"
)

type HearttbeatResponse struct {
	Uptime string `json:"uptime"`
}

var port = ":8081"
var workerID = "workerId2"
var workerIP = "127.0.0.1"
var coordinatorURL = "http://127.0.0.1:5001/register"

func main() {
	registerWorker()
	http.HandleFunc("/heartbeat", heartBeatHandler)
	log.Fatal(http.ListenAndServe(port, nil))
	fmt.Printf("Worker running on port %s", port)
}

func heartBeatHandler(w http.ResponseWriter, r *http.Request) {
	fmt.Printf("got heatbeat request\n")
	uptime := time.Since(startTime()).String()

	response := HearttbeatResponse{
		Uptime: uptime,
	}

	w.Header().Set("Content-Type", "application/json")
	json.NewEncoder(w).Encode(response)
}

func registerWorker() {
	data := map[string]interface{}{
		"worker_id": workerID,
		"ip":        workerIP,
		"port":      port,
		"metadata":  "test worker",
	}
	jsonData, err := json.Marshal(data)
	if err != nil {
		log.Fatalf("Error encoding JSON: %v", err)
	}

	resp, err := http.Post(coordinatorURL, "application/json", bytes.NewBuffer(jsonData))
	if err != nil {
		log.Fatalf("Error registering to coordinator: %v", err)
	}

	defer resp.Body.Close()

	if resp.StatusCode != http.StatusOK {
		log.Fatalf("Unable to connect to coordinator: %v", resp.StatusCode)
	}

	log.Printf("Worker %s has been registered\n", workerID)
}

func startTime() time.Time {
	return startTimeVar
}

var startTimeVar = time.Now()
