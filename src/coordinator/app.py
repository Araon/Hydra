import logging
from datetime import datetime, timedelta
import time
import threading
from flask import Flask, request, jsonify
import json
from sqlalchemy import create_engine, DateTime, Column, Integer, String
from sqlalchemy.orm import sessionmaker
from sqlalchemy.sql.expression import text, func
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.exc import SQLAlchemyError
import requests
from config import SQLALCHEMY_DATABASE_URI

app = Flask(__name__)
PORT = 5001
MAX_WORKER = 10
HEARTBEAT_TIMEOUT = 3
TASK_PICKED_LIMIT = 10

logging.basicConfig(level=logging.INFO)
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
        self.last_assigned_worker_index = -1

        self.fetch_tasks_interval = 5
        self.heartbeatInterval = 3

        self.fetch_tasks_thread = threading.Thread(target=self.fetch_tasks_periodically, daemon=True)
        self.fetch_tasks_thread.start()

        self.heartbeat_check_thread = threading.Thread(target=self.check_heartbeats, daemon=True)

        self.heartbeat_check_thread.start()

    def register_worker(self, request):
        worker_id = request.json['worker_id']
        '''
        Worker data that needs to be saved on registration
        - worker_id -> key
        - worker ip
        - worker port
        - optional worker metadata
        '''

        if worker_id in self.registered_workers:
            logger.info('Worker is already registered')
            response_data = {"success": True, "message": f"Worker {worker_id} already registered."}
            return json.dumps(response_data)
        else:
            self.registered_workers[worker_id] = {
                "lastHeartBeatTime": time.time(),
                "heartBeatMissed": 0,
                "workerIp": request.json['ip'],
                "workerPort": request.json['port'].replace(":", ""),
                "metadata": request.json['metadata']
            }
            print(self.registered_workers)
            response_data = {"success": True, "message": f"Worker {worker_id} registered."}
            logger.info(f'Worker: {worker_id} registered.')
            return json.dumps(response_data)

    def unregister_worker(self, worker_id):
        if worker_id in self.registered_workers:
            del self.registered_workers[worker_id]
            logger.info(f"Worker {worker_id} unregistered, Missed heartbeat {HEARTBEAT_TIMEOUT}")
        else:
            logger.info(f'Worker {worker_id} is not found')

    def sendHeartBeat(self, worker_id):
        worker_info = self.registered_workers[worker_id]
        worker_ip = worker_info['workerIp']
        worker_port = worker_info['workerPort']

        url = f'http://{worker_ip}:{worker_port}/heartbeat'

        try:
            response = requests.get(url)

            if response.status_code == 200:
                current_time = time.time()

                self.registered_workers[worker_id]["lastHeartBeatTime"] = current_time
                self.registered_workers[worker_id]["heartBeatMissed"] = 0

            else:
                logger.info(f'Worker {worker_id} did not responce to heartbeat')
                self.registered_workers[worker_id]['heartBeatMissed'] += 1
        except Exception as e:
            logger.error(f'Error occurred while sending heartbeat to worker: {worker_id} - {str(e)}')
            self.registered_workers[worker_id]['heartBeatMissed'] += 1  # Increment missed count on error

    def check_heartbeats(self):

        while True:
            for workerId in list(self.registered_workers.keys()):
                heartBeatMissed = self.registered_workers[workerId].get('heartBeatMissed')

                if heartBeatMissed >= HEARTBEAT_TIMEOUT:
                    self.unregister_worker(workerId)
                    break

                self.sendHeartBeat(workerId)
            time.sleep(self.heartbeatInterval)

    def update_worker_status(self, request):
        worker_id = request.json['worker_id']
        if worker_id in self.registered_workers:
            response_data = {"acknowledged": True}
        else:
            response_data = {"acknowledged": False}
        return json.dumps(response_data)

    def fetch_tasks_periodically(self):
        while True:
            self.fetch_tasks()
            time.sleep(self.fetch_tasks_interval)

    def fetch_tasks(self):
        with Session() as session:

            thirty_secounds_delta = datetime.utcnow() + timedelta(seconds=30)

            tasks = (
                session.query(Tasks)
                .filter(Tasks.scheduled_at >= datetime.utcnow())
                .filter(Tasks.scheduled_at <= thirty_secounds_delta)
                .filter(Tasks.picked_at.is_(None))
                .order_by(Tasks.scheduled_at)
                .limit(TASK_PICKED_LIMIT)
                .with_for_update(skip_locked=True)
                .all()
            )

        if tasks and len(tasks) > 0:
            for task in tasks:
                self.submit_task(task)

    def submit_task(self, task):

        available_workers = list(self.registered_workers.keys())

        if available_workers and len(available_workers) > 0:
            # task picked up to be sent to worker
            self.update_picked_at(task_id=task.id)

            # https://en.wikipedia.org/wiki/Round-robin_scheduling
            self.last_assigned_worker_index = (self.last_assigned_worker_index + 1) % len(available_workers)
            selected_worker = available_workers[self.last_assigned_worker_index]

            logger.info(f'task:{task.id} has been assigned to {selected_worker} with command {task.command}')

            worker_info = self.registered_workers[selected_worker]
            worker_ip = worker_info['workerIp']
            worker_port = worker_info['workerPort']

            url = f'http://{worker_ip}:{worker_port}/submit'

            payload = {
                'task_id': str(task.id),
                'command': task.command
            }

            try:
                response = requests.post(url, json=payload)
                if response.status_code == 200:
                    logger.info(f'Task {task.id} submitted to {selected_worker}')
                else:
                    logger.error(f'Faild to submit task {task.id} to {selected_worker}')
            except Exception as e:
                logger.error(f'Error occurred while submitting task {task.id} to {selected_worker}: {str(e)}')

        else:
            logger.error('No worker present')

    def update_picked_at(self, task_id):

        with Session() as session:
            try:

                task = session.query(Tasks).filter_by(id=task_id).first()

                if not task:
                    logger.error(f'Task: {task_id} not found to update picked_at')
                    return

                task.picked_at = datetime.utcnow()

                session.commit()
                logger.info(f'{task_id} updated with picked_at {task.picked_at.isoformat()}')

            except SQLAlchemyError as e:
                logger.error(f'Error updating picked_at for task {task_id}: {str(e)}')
                return

    def update_job_status(self, request):
        task_id = request.json['task_id']
        status = request.json['status']
        current_time = datetime.utcnow().isoformat()
        logger.info(f'Updating task status for task_id: {task_id}')

        with Session() as session:
            task = session.query(Tasks).filter_by(id=task_id).first()

            if not task:
                task_status = {"success": False, "message": f"Task {task_id} not found"}
                return jsonify(task_status), 404

            if status == "STARTED":
                task.started_at = current_time
            elif status == "COMPLETED":
                task.completed_at = current_time
            elif status == "FAILED":
                task.failed_at = current_time
            else:
                task_status = {"success": False, "message": f"Invalid task status for {task_id}"}
                return jsonify(task_status), 404

            session.commit()
            task_status = {"success": True, "message": f"Task {task_id} updated successfully"}
            logger.info(f'{task_id} updated with status {status} at {current_time}')
            return jsonify(task_status), 200


coordinator_servicer = CoordinatorServicer()


@app.route('/register', methods=['POST'])
def register_worker_route():
    return coordinator_servicer.register_worker(request)


@app.route('/jobStatusUpdate', methods=['POST'])
def update_job_status():
    return coordinator_servicer.update_job_status(request)


if __name__ == '__main__':
    app.run(host='0.0.0.0', port=PORT)
