import logging
from datetime import datetime, timedelta
import time
import threading
from flask import Flask, request
import json
from sqlalchemy import create_engine, DateTime, Column, Integer, String
from sqlalchemy.orm import sessionmaker
from sqlalchemy.ext.declarative import declarative_base
import requests
from config import SQLALCHEMY_DATABASE_URI

app = Flask(__name__)
PORT = 5001
MAX_WORKER = 10
HEARTBEAT_TIMEOUT = 10
TASK_PICKED_LIMIT = 10

logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__name__)

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


engine = create_engine(SQLALCHEMY_DATABASE_URI)
Base.metadata.create_all(engine)
Session = sessionmaker(bind=engine)


class CoordinatorServicer:
    def __init__(self):
        self.registered_workers = {}
        self.heartbeat_timeout = HEARTBEAT_TIMEOUT
        self.last_assigned_worker_index = -1  # doing some round-robin masti!

        self.fetch_tasks_interval = 5  # Fetch tasks every 5 seconds

        # Start a background thread for fetching tasks
        self.fetch_tasks_thread = threading.Thread(target=self.fetch_tasks_periodically, daemon=True)
        self.fetch_tasks_thread.start()

    def register_worker(self, request):
        worker_id = request.json['worker_id']
        '''
        Worker data that needs to be saved on registration
        - worker_id - key
        - worker ip
        - worker port
        - optional worker metadata
        '''
        self.registered_workers[worker_id] = {
            "lastHeartBeatTime": time.time(),
            "workerIp": request.json['ip'],
            "workerPort": request.json['port'],
            "metadata": request.json['metadata']
        }
        response_data = {"success": True, "message": f"Worker {worker_id} registered."}
        return json.dumps(response_data)

    def unregister_worker(self):
        worker_id = request.json['worker_id']
        if worker_id in self.registered_workers:
            del self.registered_workers[worker_id]
            response_data = {"success": True, "message": f"Worker {worker_id} unregistered"}
        else:
            response_data = {"success": False, "message": f"Worker{worker_id} not found"}

        return json.dumps(response_data)

    def check_heartbeats(self):
        current_time = time.time()
        expired_workers = [worker_id for worker_id, last_heartbeat_time in self.registered_workers.items() if current_time - last_heartbeat_time > self.heartbeat_timeout]

        for worker_id in expired_workers:
            del self.registered_workers[worker_id]
            logger.info(f'Unregistering worker {worker_id} due to hearbeat timeoout')

    def send_heartbeat(self, request):
        worker_id = request.json['worker_id']
        if worker_id in self.registered_workers:
            response_data = {"acknowledged": True}
        else:
            response_data = {"acknowledged": False}
        return json.dumps(response_data)

    def fetch_tasks_periodically(self):
        while True:
            print('Fetching jobs')
            self.fetch_tasks()
            time.sleep(self.fetch_tasks_interval)

    def fetch_tasks(self):
        with Session() as session:
            current_time = datetime.utcnow() + timedelta(seconds=30)

            tasks = (
                session.query(Tasks)
                .filter(Tasks.scheduled_at > current_time, Tasks.picked_at.is_(None))
                .order_by(Tasks.scheduled_at)
                .limit(TASK_PICKED_LIMIT)
                .with_for_update(skip_locked=True)
                .all()
            )

            if tasks and len(tasks) > 0:
                for task in tasks:
                    self.submit_task(task)
            else:
                logger.error('No task found')

    def submit_task(self, task):

        available_workers = list(self.registered_workers.keys())

        if available_workers and len(available_workers) > 0:

            # https://en.wikipedia.org/wiki/Round-robin_scheduling
            self.last_assigned_worker_index = (self.last_assigned_worker_index + 1) % len(available_workers)
            selected_worker = available_workers[self.last_assigned_worker_index]

            logger.info(f'task:{task.id} has been assigned to {selected_worker} with command {task.command}')

            worker_info = self.registered_workers[selected_worker]
            worker_ip = worker_info['workerIp']
            worker_port = worker_info['workerPort']

            url = f'http://{worker_ip}:{worker_port}/submit'

            payload = {
                'task_id': task.id,
                'command': task.command
            }

            try:
                response = request.post(url, json=payload)
                print(payload)
                if response.status_code == 200:
                    logger.info(f'Task {task.id} submitted to {selected_worker}')
                else:
                    logger.error(f'Faild to submit task {task.id} to {selected_worker}')
            except Exception as e:
                logger.error(f'Error occurred while submitting task {task.id} to {selected_worker}: {str(e)}')
        else:
            logger.error('No worker present')

    def update_job_status(self, request):
        task_id = request.json['task_id']
        status = request.json['status']
        current_time = datetime.utcnow()

        with Session() as session:
            task = session.query(Tasks).filter_by(id=task_id).first()

            if not task:
                res_status = {"success": False, "message": f"Task {task_id} not found"}
                return json.dumps(res_status)

            if status == "STARTED":
                task.started_at = current_time
            elif status == "COMPLETED":
                task.completed_at = current_time
            elif status == "FAILED":
                task.failed_at = current_time
            else:
                task_status = {"success": False, "message": f"Invalid task status for {task_id}"}
                return json.dumps(task_status)

            session.commit()
            status = {"success": True, "message": f"Task {task_id} updated successfully"}
            return status


coordinator_servicer = CoordinatorServicer()  # Create a single instance of CoordinatorServicer


@app.route('/register', methods=['POST'])
def register_worker_route():
    return coordinator_servicer.register_worker(request)


@app.route('/sendHeartBeat', methods=['POST'])
def send_heartbeat_route():
    return coordinator_servicer.send_heartbeat(request)


@app.route('/jobStatusUpdate', methods=['POST'])
def update_job_status():
    return coordinator_servicer.update_job_status(request)


if __name__ == '__main__':
    app.run(port=PORT)