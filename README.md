<p align="center">
   <img src="https://ik.imagekit.io/ara0n/for_exceptional_broski.png" width="250" height="250">
</p>

# Hydra
<img src="https://skillicons.dev/icons?i=python,go,flask,postgresql,docker" alt="https://skillicons.dev/icons?i=python,go,flask,postgresql,docker" /> 

</br>

Hydra is a task scheduler designed for handling high task volumes across multiple workers.

![Hydra Hero](docs/HLD.png)

## Run locally 💻
create a .env file with the following details
```.env
POSTGRES_DB=
POSTGRES_USER=
POSTGRES_PASSWORD=
```
and then run the following command to build and run using docker

```bash
docker compose up --scale worker=3
```

## Details
Written in Python and GO, it comprises:

- Scheduler: Receives tasks and schedules them for execution.
- Coordinator: Manages task selection, worker registration, and distribution of tasks for execution.
- Worker: Executes assigned tasks, reporting status back to the Coordinator.
- Database: PostgreSQL database stores task details, aiding task management.

Communication between components uses https for scalability and fault tolerance.

### Scheduler 🗓️
This is a simple Flask application that provides a RESTful API for scheduling tasks. The application uses SQLAlchemy as an ORM for interacting with the database.
The scheduler acts as the i/o for the system and has the has the following responsibilities

- Schedule a task with a command and a scheduled time.
- Retrieve a task by its ID.

Below are the endpoints avaliable
```curl
POST /schedule
{
   "command":"./run_cleanup.sh",
   "scheduled_at": ""
}
```

Schedule a new task. The request body should be a JSON object with a command and a scheduled_at field. The scheduled_at should be in ISO format.

```curl
GET /schedule/<task_id>
```
Retrieve a task status by its ID.

### Coordinator 🧠
This is a Flask application that provides a RESTful API for a task coordinator service. The coordinator service is responsible for managing tasks and workers. It schedules tasks to be executed by workers, maintains the status of tasks, and handles worker registration and heartbeats.

Below are the responsibities

- Register and unregister workers
- Schedule tasks to be picked up by workers
- Update task status (started, completed, failed)
- Periodically fetch tasks and assign them to available workers
- Handle worker heartbeats to monitor their availability

Background Tasks

The coordinator periodically fetches tasks that are scheduled to run within the next 30 seconds and assigns them to available workers using round-robin scheduling.
The coordinator checks worker heartbeats periodically to monitor their availability and unregisters workers that have missed too many heartbeats.

### Worker 💪

This is a Go application that provides a RESTful API for a worker service. The worker service is responsible for executing tasks assigned to it by the coordinator service, sending heartbeats to the coordinator, and updating the status of tasks it is executing.

Below are the responsibities
- Register with the coordinator service
- Receive tasks from the coordinator service
- Execute tasks and update their status
- Send heartbeats to the coordinator service

Background Tasks

- The worker registers itself with the coordinator service when it starts.
- The worker sends heartbeats to the coordinator service to monitor its availability.
- The worker updates the status of tasks it is executing (started, completed, failed).

