import logging
import os
import uuid
from datetime import datetime

import requests
from flask import Flask, jsonify, request
from flask_migrate import Migrate
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import text

from config import SQLALCHEMY_DATABASE_URI

app = Flask(__name__)
app.config["SQLALCHEMY_DATABASE_URI"] = SQLALCHEMY_DATABASE_URI
db = SQLAlchemy()
migrate = Migrate()
db.init_app(app)
migrate.init_app(app, db)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

COORDINATOR_URL = os.environ.get("COORDINATOR_URL", "http://coordinator:5001")
ALLOWED_JOB_TYPES = {"echo", "sleep", "sha256"}


class Tasks(db.Model):
    __tablename__ = "tasks"

    id = db.Column(db.String, primary_key=True, default=lambda: str(uuid.uuid4()))
    # Retained so an existing v1 database can be upgraded in place.
    command = db.Column(db.String, nullable=False)
    job_type = db.Column(db.String, nullable=False, default="legacy_command")
    payload = db.Column(db.JSON, nullable=False, default=dict)
    scheduled_at = db.Column(db.DateTime, nullable=False)
    picked_at = db.Column(db.DateTime)
    started_at = db.Column(db.DateTime)
    completed_at = db.Column(db.DateTime)
    failed_at = db.Column(db.DateTime)
    status = db.Column(db.String, nullable=False, default="queued")
    attempts = db.Column(db.Integer, nullable=False, default=0)
    max_attempts = db.Column(db.Integer, nullable=False, default=3)
    lease_expires_at = db.Column(db.DateTime)
    assigned_worker_id = db.Column(db.String)


def validate_job(job_type, payload):
    if job_type not in ALLOWED_JOB_TYPES:
        return "job_type must be one of echo, sleep, sha256"
    if not isinstance(payload, dict):
        return "payload must be an object"
    if job_type == "echo":
        message = payload.get("message")
        if not isinstance(message, str) or not message or len(message) > 1024:
            return "echo payload requires a message up to 1024 characters"
    elif job_type == "sleep":
        duration = payload.get("duration_seconds")
        if not isinstance(duration, int) or isinstance(duration, bool) or not 0 <= duration <= 300:
            return "sleep payload requires duration_seconds between 0 and 300"
    elif job_type == "sha256":
        path = payload.get("path")
        if not isinstance(path, str) or not path:
            return "sha256 payload requires a path"
    return None


def notify_coordinator():
    try:
        requests.post(f"{COORDINATOR_URL}/dispatch", timeout=2)
    except requests.RequestException as error:
        # The task stays queued in PostgreSQL and the coordinator's one-second
        # fallback scan will recover it.
        logger.warning("Could not notify coordinator: %s", error)


@app.route("/schedule", methods=["POST"])
def post_schedule():
    data = request.get_json(silent=True) or {}
    job_type = data.get("job_type")
    payload = data.get("payload", {})
    scheduled_at_value = data.get("scheduled_at")
    max_attempts = data.get("max_attempts", 3)

    validation_error = validate_job(job_type, payload)
    if validation_error:
        return jsonify({"error": validation_error}), 400
    if not scheduled_at_value:
        return jsonify({"error": "scheduled_at is required"}), 400
    if not isinstance(max_attempts, int) or isinstance(max_attempts, bool) or not 1 <= max_attempts <= 10:
        return jsonify({"error": "max_attempts must be between 1 and 10"}), 400
    try:
        scheduled_at = datetime.fromisoformat(scheduled_at_value)
    except ValueError:
        return jsonify({"error": "Invalid ISO date format"}), 400

    task = Tasks(
        command=job_type,
        job_type=job_type,
        payload=payload,
        scheduled_at=scheduled_at,
        status="queued",
        max_attempts=max_attempts,
    )
    db.session.add(task)
    db.session.commit()
    notify_coordinator()
    return jsonify({"message": "Task scheduled successfully", "task_id": str(task.id)}), 201


@app.route("/schedule/<string:task_id>", methods=["GET"])
def get_schedule(task_id):
    task = db.session.get(Tasks, task_id)
    if not task:
        return jsonify({"error": "Task not found"}), 404
    return jsonify(
        {
            "task": {
                "id": str(task.id),
                "job_type": task.job_type,
                "payload": task.payload,
                "scheduled_at": task.scheduled_at,
                "picked_at": task.picked_at,
                "started_at": task.started_at,
                "completed_at": task.completed_at,
                "failed_at": task.failed_at,
                "status": task.status,
                "attempts": task.attempts,
                "max_attempts": task.max_attempts,
                "assigned_worker_id": task.assigned_worker_id,
            }
        }
    ), 200


def ensure_schema():
    """Perform the same additive upgrade as the coordinator for v1 volumes."""
    if db.engine.dialect.name != "postgresql":
        return
    upgrades = (
        "ALTER TABLE tasks ADD COLUMN IF NOT EXISTS job_type VARCHAR NOT NULL DEFAULT 'legacy_command'",
        "ALTER TABLE tasks ADD COLUMN IF NOT EXISTS payload JSONB NOT NULL DEFAULT '{}'::jsonb",
        "ALTER TABLE tasks ADD COLUMN IF NOT EXISTS status VARCHAR NOT NULL DEFAULT 'queued'",
        "ALTER TABLE tasks ADD COLUMN IF NOT EXISTS attempts INTEGER NOT NULL DEFAULT 0",
        "ALTER TABLE tasks ADD COLUMN IF NOT EXISTS max_attempts INTEGER NOT NULL DEFAULT 3",
        "ALTER TABLE tasks ADD COLUMN IF NOT EXISTS lease_expires_at TIMESTAMP",
        "ALTER TABLE tasks ADD COLUMN IF NOT EXISTS assigned_worker_id VARCHAR",
    )
    with db.engine.begin() as connection:
        for statement in upgrades:
            connection.execute(text(statement))


if __name__ == "__main__":
    with app.app_context():
        db.create_all()
        ensure_schema()
    app.run(host="0.0.0.0", port=5000)
