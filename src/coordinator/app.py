import json
import logging
import os
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta

import requests
from flask import Flask, jsonify, request
from sqlalchemy import JSON, Column, DateTime, Integer, String, and_, create_engine, or_, text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import declarative_base, sessionmaker

from config import SQLALCHEMY_DATABASE_URI

app = Flask(__name__)
PORT = 5001
HEARTBEAT_TIMEOUT = 3
TASK_BATCH_SIZE = int(os.environ.get("TASK_BATCH_SIZE", "100"))
LEASE_SECONDS = int(os.environ.get("LEASE_SECONDS", "300"))

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

Base = declarative_base()


class Tasks(Base):
    __tablename__ = "tasks"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    # Kept for v1 database compatibility. New jobs use job_type and payload.
    command = Column(String, nullable=False)
    job_type = Column(String, nullable=False, default="legacy_command")
    payload = Column(JSON, nullable=False, default=dict)
    scheduled_at = Column(DateTime, nullable=False)
    picked_at = Column(DateTime)
    started_at = Column(DateTime)
    completed_at = Column(DateTime)
    failed_at = Column(DateTime)
    status = Column(String, nullable=False, default="queued")
    attempts = Column(Integer, nullable=False, default=0)
    max_attempts = Column(Integer, nullable=False, default=3)
    lease_expires_at = Column(DateTime)
    assigned_worker_id = Column(String)


engine = create_engine(SQLALCHEMY_DATABASE_URI)


def ensure_schema():
    """Apply the additive v1-to-v2 task-table upgrade for existing databases."""
    Base.metadata.create_all(engine)
    if engine.dialect.name != "postgresql":
        return

    upgrades = (
        "ALTER TABLE tasks ADD COLUMN IF NOT EXISTS job_type VARCHAR NOT NULL DEFAULT 'legacy_command'",
        "ALTER TABLE tasks ADD COLUMN IF NOT EXISTS payload JSONB NOT NULL DEFAULT '{}'::jsonb",
        "ALTER TABLE tasks ADD COLUMN IF NOT EXISTS status VARCHAR NOT NULL DEFAULT 'queued'",
        "ALTER TABLE tasks ADD COLUMN IF NOT EXISTS attempts INTEGER NOT NULL DEFAULT 0",
        "ALTER TABLE tasks ADD COLUMN IF NOT EXISTS max_attempts INTEGER NOT NULL DEFAULT 3",
        "ALTER TABLE tasks ADD COLUMN IF NOT EXISTS lease_expires_at TIMESTAMP",
        "ALTER TABLE tasks ADD COLUMN IF NOT EXISTS assigned_worker_id VARCHAR",
        "CREATE INDEX IF NOT EXISTS idx_tasks_dispatch ON tasks (status, scheduled_at)",
    )
    with engine.begin() as connection:
        for statement in upgrades:
            connection.execute(text(statement))


ensure_schema()
Session = sessionmaker(bind=engine)


def _get_session_factory():
    """Allow the existing unit tests to patch the session factory."""
    try:
        import coordinator_service as coordinator_module

        return getattr(coordinator_module, "Session", Session)
    except Exception:
        return Session


class CoordinatorServicer:
    def __init__(self, start_background_tasks=None):
        if start_background_tasks is None:
            start_background_tasks = os.environ.get("SKIP_BACKGROUND_TASKS", "0") not in ("1", "true", "True")

        self.registered_workers = {}
        self.lock = threading.Lock()
        self.last_assigned_worker_index = -1
        self.executor = ThreadPoolExecutor(max_workers=20)
        self.fetch_tasks_interval = 1
        self.heartbeat_interval = 3

        if start_background_tasks:
            threading.Thread(target=self.fetch_tasks_periodically, daemon=True).start()
            threading.Thread(target=self.check_heartbeats, daemon=True).start()

    @staticmethod
    def _request_json(req):
        if isinstance(req, dict):
            return req
        return req.json() if callable(getattr(req, "json", None)) else req.json

    def register_worker(self, req):
        data = self._request_json(req)
        worker_id = data["worker_id"]
        max_concurrency = max(1, int(data.get("max_concurrency", 1)))

        with self.lock:
            current = self.registered_workers.get(worker_id, {})
            self.registered_workers[worker_id] = {
                "last_heartbeat_time": time.time(),
                "heartbeat_missed": 0,
                "worker_ip": data["ip"],
                "worker_port": str(data["port"]).replace(":", ""),
                "max_concurrency": max_concurrency,
                "in_flight": current.get("in_flight", 0),
                "metadata": data.get("metadata", {}),
            }

        logger.info("Worker %s registered with capacity %s", worker_id, max_concurrency)
        return json.dumps({"success": True, "message": f"Worker {worker_id} registered."})

    def unregister_worker(self, worker_id):
        with self.lock:
            self.registered_workers.pop(worker_id, None)
        logger.info("Worker %s unregistered", worker_id)

    def _available_worker(self):
        with self.lock:
            worker_ids = [
                worker_id
                for worker_id, worker in self.registered_workers.items()
                if worker["in_flight"] < worker["max_concurrency"]
            ]
            if not worker_ids:
                return None, None
            self.last_assigned_worker_index = (self.last_assigned_worker_index + 1) % len(worker_ids)
            worker_id = worker_ids[self.last_assigned_worker_index]
            worker = self.registered_workers[worker_id]
            worker["in_flight"] += 1
            return worker_id, dict(worker)

    def _release_worker(self, worker_id):
        with self.lock:
            worker = self.registered_workers.get(worker_id)
            if worker:
                worker["in_flight"] = max(0, worker["in_flight"] - 1)

    def send_heartbeat(self, worker_id):
        with self.lock:
            worker = self.registered_workers.get(worker_id)
        if not worker:
            return

        if os.environ.get("SKIP_NETWORK_CALLS", "0") in ("1", "true", "True"):
            with self.lock:
                if worker_id in self.registered_workers:
                    self.registered_workers[worker_id]["last_heartbeat_time"] = time.time()
                    self.registered_workers[worker_id]["heartbeat_missed"] = 0
            return

        try:
            response = requests.get(
                f"http://{worker['worker_ip']}:{worker['worker_port']}/heartbeat", timeout=5
            )
            with self.lock:
                current = self.registered_workers.get(worker_id)
                if not current:
                    return
                if response.status_code == 200:
                    current["last_heartbeat_time"] = time.time()
                    current["heartbeat_missed"] = 0
                else:
                    current["heartbeat_missed"] += 1
        except requests.RequestException:
            with self.lock:
                if worker_id in self.registered_workers:
                    self.registered_workers[worker_id]["heartbeat_missed"] += 1

    # Backwards-compatible name used by the original unit tests.
    sendHeartBeat = send_heartbeat

    def check_heartbeats(self):
        while True:
            with self.lock:
                worker_ids = list(self.registered_workers)
            for worker_id in worker_ids:
                with self.lock:
                    worker = self.registered_workers.get(worker_id)
                    missed = worker["heartbeat_missed"] if worker else HEARTBEAT_TIMEOUT
                if missed >= HEARTBEAT_TIMEOUT:
                    self.unregister_worker(worker_id)
                else:
                    self.executor.submit(self.send_heartbeat, worker_id)
            time.sleep(self.heartbeat_interval)

    def fetch_tasks_periodically(self):
        while True:
            self.fetch_tasks()
            time.sleep(self.fetch_tasks_interval)

    def fetch_tasks(self):
        session = _get_session_factory()()
        now = datetime.utcnow()
        try:
            tasks = (
                session.query(Tasks)
                .filter(
                    or_(
                        and_(Tasks.status == "queued", Tasks.scheduled_at <= now),
                        and_(Tasks.status.in_(("leased", "running")), Tasks.lease_expires_at < now),
                    )
                )
                .order_by(Tasks.scheduled_at)
                .limit(TASK_BATCH_SIZE)
                .with_for_update(skip_locked=True)
                .all()
            )

            claimed = []
            for task in tasks:
                if task.attempts >= task.max_attempts:
                    task.status = "failed"
                    task.failed_at = now
                    continue
                if task.assigned_worker_id:
                    self._release_worker(task.assigned_worker_id)
                worker_id, worker = self._available_worker()
                if not worker:
                    break
                task.status = "leased"
                task.picked_at = now
                task.lease_expires_at = now + timedelta(seconds=LEASE_SECONDS)
                task.assigned_worker_id = worker_id
                task.attempts += 1
                claimed.append((str(task.id), task.job_type, task.payload, worker_id, worker))
            session.commit()
        except SQLAlchemyError as error:
            session.rollback()
            logger.error("Unable to claim scheduled tasks: %s", error)
            return
        finally:
            session.close()

        for task_id, job_type, payload, worker_id, worker in claimed:
            self.executor.submit(self._submit_task, task_id, job_type, payload, worker_id, worker)

    def _submit_task(self, task_id, job_type, payload, worker_id, worker):
        try:
            response = requests.post(
                f"http://{worker['worker_ip']}:{worker['worker_port']}/submit",
                json={"task_id": task_id, "job_type": job_type, "payload": payload},
                timeout=10,
            )
            if response.status_code == 200:
                logger.info("Task %s submitted to %s", task_id, worker_id)
                return
            logger.error("Task %s rejected by %s: %s", task_id, worker_id, response.status_code)
        except requests.RequestException as error:
            logger.error("Unable to submit task %s to %s: %s", task_id, worker_id, error)
        self._requeue_delivery_failure(task_id, worker_id)

    def _requeue_delivery_failure(self, task_id, worker_id):
        session = Session()
        try:
            task = session.query(Tasks).filter_by(id=task_id).first()
            if task and task.status == "leased":
                task.status = "queued"
                task.assigned_worker_id = None
                task.lease_expires_at = None
                session.commit()
        finally:
            session.close()
            self._release_worker(worker_id)

    def update_job_status(self, req):
        data = self._request_json(req)
        task_id = data["task_id"]
        status = data["status"]
        worker_id = data.get("worker_id")
        now = datetime.utcnow()
        session = _get_session_factory()()
        try:
            task = session.query(Tasks).filter_by(id=task_id).first()
            if not task:
                return self._status_response(req, False, f"Task {task_id} not found", 404)
            if worker_id and task.assigned_worker_id and worker_id != task.assigned_worker_id:
                return self._status_response(req, False, f"Task {task_id} is leased by another worker", 409)

            if status == "STARTED":
                task.status = "running"
                task.started_at = now
            elif status == "COMPLETED":
                task.status = "completed"
                task.completed_at = now
                task.lease_expires_at = None
                self._release_worker(task.assigned_worker_id)
            elif status == "FAILED":
                task.failed_at = now
                task.lease_expires_at = None
                self._release_worker(task.assigned_worker_id)
                if task.attempts < task.max_attempts:
                    task.status = "queued"
                    task.scheduled_at = now
                    task.assigned_worker_id = None
                else:
                    task.status = "failed"
            else:
                return self._status_response(req, False, f"Invalid task status {status}", 400)
            session.commit()
            return self._status_response(req, True, f"Task {task_id} updated successfully", 200)
        except SQLAlchemyError as error:
            session.rollback()
            logger.error("Unable to update task %s: %s", task_id, error)
            return self._status_response(req, False, "Database error", 500)
        finally:
            session.close()

    @staticmethod
    def _status_response(req, success, message, code):
        payload = {"success": success, "message": message}
        if isinstance(req, dict):
            return json.dumps(payload)
        return jsonify(payload), code


coordinator_servicer = CoordinatorServicer()


@app.route("/register", methods=["POST"])
def register_worker_route():
    return coordinator_servicer.register_worker(request)


@app.route("/jobStatusUpdate", methods=["POST"])
def update_job_status_route():
    return coordinator_servicer.update_job_status(request)


@app.route("/dispatch", methods=["POST"])
def dispatch_route():
    coordinator_servicer.fetch_tasks()
    return jsonify({"success": True}), 202


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=PORT)
