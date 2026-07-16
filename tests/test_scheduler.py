from datetime import datetime

import pytest

from src.scheduler import app as scheduler_module
from src.scheduler.app import Tasks, app, db


@pytest.fixture
def client(monkeypatch):
    app.config.update(TESTING=True, SQLALCHEMY_DATABASE_URI="sqlite:///:memory:")
    monkeypatch.setattr(scheduler_module, "notify_coordinator", lambda: None)
    with app.app_context():
        db.drop_all()
        db.create_all()
        yield app.test_client()
        db.session.remove()


def schedule(client, job_type="echo", payload=None, **extra):
    return client.post(
        "/schedule",
        json={
            "job_type": job_type,
            "payload": payload or {"message": "hello"},
            "scheduled_at": datetime.utcnow().isoformat(),
            **extra,
        },
    )


def test_post_schedule_creates_typed_job(client):
    response = schedule(client)
    assert response.status_code == 201
    task_id = response.json["task_id"]

    task = client.get(f"/schedule/{task_id}")
    assert task.status_code == 200
    assert task.json["task"]["job_type"] == "echo"
    assert task.json["task"]["status"] == "queued"


@pytest.mark.parametrize(
    "job_type,payload",
    [
        ("command", {"command": "rm -rf /"}),
        ("sleep", {"duration_seconds": 301}),
        ("echo", {"message": ""}),
        ("sha256", {}),
    ],
)
def test_post_schedule_rejects_invalid_or_untrusted_jobs(client, job_type, payload):
    response = schedule(client, job_type, payload)
    assert response.status_code == 400
    assert "error" in response.json


def test_post_schedule_validates_retry_budget(client):
    assert schedule(client, max_attempts=0).status_code == 400
    assert schedule(client, max_attempts=4).status_code == 201
