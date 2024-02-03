import grpc
from datetime import datetime, timedelta
import time
from concurrent import futures
import threading
import hydra_pb2
import hydra_pb2_grpc
from sqlalchemy import create_engine, DateTime, Column, Integer, String
from sqlalchemy.orm import sessionmaker
from sqlalchemy.ext.declarative import declarative_base
from config import SQLALCHEMY_DATABASE_URI

PORT = 5001
MAX_WORKER = 10
HEARTBEAT_TIMEOUT = 10
TASK_PICKED_LIMIT = 10


Base = declarative_base()


class Tasks(Base):
    __tablename__ = "tasks"

    id = Column(Integer, primary_key=True)
    command = Column(String(), nullable=False)
    scheduled_at = Column(DateTime, nullable=False)
    picked_at = Column(DateTime)
    started_at = Column(DateTime)
    completed_at = Column(DateTime)
    failed_at = Column(DateTime)


class CoordinatorServicer(hydra_pb2_grpc.CoordinatorServiceServicer):
    def __init__(self):
        self.registered_workers = {}
        self.heartbeat_timeout = HEARTBEAT_TIMEOUT
        self.last_assigned_worker_index = -1  # doing some round-robin masti!

        self.engine = create_engine(SQLALCHEMY_DATABASE_URI)
        Base.metadata.create_all(self.engine)
        self.Session = sessionmaker(bind=self.engine)

        self.fetch_tasks_interval = 5  # Fetch tasks every 10 seconds
        # Start a background thread for fetching tasks
        self.fetch_tasks_thread = threading.Thread(target=self.fetch_tasks_periodically, daemon=True)
        self.fetch_tasks_thread.start()

    def RegisterWorker(self, request, context):
        worker_id = request.worker_id
        self.registered_workers[worker_id] = time.time()
        return hydra_pb2.WorkerStatus(success=True, message=f"Worker {worker_id} registered.")

    def UnregisterWorker(self, request, context):
        worker_id = request.worker_id
        if worker_id in self.registered_workers:
            del self.registered_workers[worker_id]
            return hydra_pb2.WorkerStatus(success=True, message=f"Worker {worker_id} unregistered")
        else:
            return hydra_pb2.WorkerStatus(success=False, message=f"Worker{worker_id} not found")

    def CheckHeartbeats(self):
        while True:
            current_time = time.time()
            expired_workers = [worker_id for worker_id, last_heartbeat_time in self.registered_workers.items() if current_time - last_heartbeat_time > self.heartbeat_timeout]

            for worker_id in expired_workers:
                del self.registered_workers[worker_id]
                print(f'Unregistering worker {worker_id} due to hearbeat timeoout')

            time.sleep(1)

    def SendHeartbeat(self, request, context):
        worker_id = request.worker_id
        if worker_id in self.registered_workers:
            self.registered_workers[worker_id] = time.time()
            return hydra_pb2.HeartbeatResponse(acknowledged=True)
        else:
            return hydra_pb2.HeartbeatResponse(acknowledged=False)

    def fetchTasks(self):
        print('Inside fetch task')
        with self.Session() as session:
            current_time = datetime.utcnow() + timedelta(seconds=30)

            query = (
                session.query(Tasks.id, Tasks.command)
                .filter(Tasks.scheduled_at < current_time, Tasks.picked_at.is_(None))
                .order_by(Tasks.scheduled_at)
                .limit(TASK_PICKED_LIMIT)
                .with_for_update(skip_locked=True)
            )

            tasks = [Tasks(id=task.id, command=task.command) for task in query]

            # this will call the submit function and submit the taskid

            return tasks

    def fetch_tasks_periodically(self):
        while True:
            print('Fetching jobs')

            self.fetchTasks()
            time.sleep(self.fetch_tasks_interval)

    def UpdateTaskStatus(self, request, context):
        task_id = request.task_id
        status = request.status
        current_time = datetime.utcnow()

        with self.Session() as session:
            task = session.query(Tasks).filter_by(id=task_id).first()

            if not task:
                return hydra_pb2.TaskUpdateResponse(success=False, message=f"Task {task_id} not found")

            if status == hydra_pb2.TaskStatus.STARTED:
                task.started_at = current_time
            elif status == hydra_pb2.TaskStatus.COMPLETED:
                task.completed_at = current_time
            elif status == hydra_pb2.TaskStatus.FAILED:
                task.failed_at = current_time
            else:
                return hydra_pb2.TaskUpdateResponse(success=False, message=f"Invalid task status for {task_id}")

            session.commit()

            return hydra_pb2.TaskUpdateResponse(success=True, message=f"Task {task_id} updated successfully")

    def SubmitTask(self, task_id):

        available_workers = list(self.registered_workers.keys())

        if not available_workers:
            return hydra_pb2.TaskAssignmentResponse(success=False, message="No available workers")

        # https://en.wikipedia.org/wiki/Round-robin_scheduling
        self.last_assigned_worker_index = (self.last_assigned_worker_index + 1) % len(available_workers)
        selected_worker = available_workers[self.last_assigned_worker_index]

        # else , we always have democracy
        # selected_worker = random.choice(available_workers)

        with self.Session() as session:
            task = session.query(Tasks).filter_by(id=task_id).first()

            if not task:
                return hydra_pb2.TaskAssignmentResponse(success=False, message=f"Task {task_id} not found")

            task.picked_at = datetime.utcnow()
            task_command = task.command
            session.commit()

        submit_task_request = hydra_pb2.TaskRequest(task_id=task_id, data=task_command)

        worker_channel = grpc.insecure_channel(f"localhost:{WORKER_PORT}")

        try:
            # Create a stub for the WorkerService
            worker_stub = hydra_pb2_grpc.WorkerServiceStub(worker_channel)

            # Call the SubmitTask RPC on the worker
            response = worker_stub.SubmitTask(submit_task_request)

            # Handle the response accordingly
            if response.success:
                with self.Session() as session:
                    task.picked_at = datetime.utcnow()
                    session.commit()

                return hydra_pb2.TaskAssignmentResponse(success=True, message=f"Task {task_id} assigned to Worker {selected_worker}", worker_id=selected_worker)
            else:
                return hydra_pb2.TaskAssignmentResponse(success=False, message=f"Failed to assign Task {task_id} to Worker. Reason: {response.message}")

        except grpc.RpcError as e:
            return hydra_pb2.TaskAssignmentResponse(success=False, message=f"Failed to connect to Worker. Reason: {str(e)}")

        finally:
            worker_channel.close()


def serve():
    server = grpc.server(futures.ThreadPoolExecutor(max_workers=MAX_WORKER))
    coordinator_servicer = CoordinatorServicer()
    hydra_pb2_grpc.add_CoordinatorServiceServicer_to_server(coordinator_servicer, server)
    server.add_insecure_port(f'[::]:{PORT}')
    server.start()

    # Start a background thread for checking heartbeats
    heartbeat_thread = threading.Thread(target=coordinator_servicer.CheckHeartbeats, daemon=True)
    heartbeat_thread.start()

    print(f"Coordinator listening on port {PORT}")
    server.wait_for_termination()


if __name__ == '__main__':
    serve()
