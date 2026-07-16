import json
from datetime import datetime
from unittest.mock import MagicMock, patch

from coordinator_service import CoordinatorServicer, Session
from src.coordinator.app import Base, Tasks, engine


def worker(worker_id="worker-1", capacity=1):
    return {
        "worker_id": worker_id,
        "ip": "127.0.0.1",
        "port": 8081,
        "max_concurrency": capacity,
        "metadata": {},
    }


def test_worker_registration_tracks_capacity():
    service = CoordinatorServicer(start_background_tasks=False)
    response = json.loads(service.register_worker(worker(capacity=2)))
    assert response["success"] is True
    assert service.registered_workers["worker-1"]["max_concurrency"] == 2
    assert service.registered_workers["worker-1"]["in_flight"] == 0


def test_available_worker_respects_concurrency_limit():
    service = CoordinatorServicer(start_background_tasks=False)
    service.register_worker(worker(capacity=1))
    worker_id, _ = service._available_worker()
    assert worker_id == "worker-1"
    assert service._available_worker() == (None, None)
    service._release_worker("worker-1")
    assert service._available_worker()[0] == "worker-1"


def test_completed_status_releases_worker_capacity():
    service = CoordinatorServicer(start_background_tasks=False)
    service.register_worker(worker())
    service.registered_workers["worker-1"]["in_flight"] = 1
    task = MagicMock(id="task-1", assigned_worker_id="worker-1")
    session = MagicMock()
    session.query.return_value.filter_by.return_value.first.return_value = task

    with patch("coordinator_service.Session", MagicMock(return_value=session)):
        response = json.loads(
            service.update_job_status({"task_id": "task-1", "status": "COMPLETED", "worker_id": "worker-1"})
        )

    assert response["success"] is True
    assert task.status == "completed"
    assert service.registered_workers["worker-1"]["in_flight"] == 0


def test_failed_status_requeues_until_retry_budget_is_exhausted():
    service = CoordinatorServicer(start_background_tasks=False)
    task = MagicMock(id="task-1", assigned_worker_id=None, attempts=1, max_attempts=2)
    session = MagicMock()
    session.query.return_value.filter_by.return_value.first.return_value = task

    with patch("coordinator_service.Session", MagicMock(return_value=session)):
        response = json.loads(service.update_job_status({"task_id": "task-1", "status": "FAILED"}))

    assert response["success"] is True
    assert task.status == "queued"


def test_task_transitions_from_lease_to_running_before_completion():
    """A persisted task is leased before a worker can report it as running."""
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    session = Session()
    task = Tasks(
        command="sleep",
        job_type="sleep",
        payload={"duration_seconds": 1},
        scheduled_at=datetime.utcnow(),
        status="queued",
        max_attempts=2,
    )
    session.add(task)
    session.commit()
    task_id = task.id
    session.close()

    service = CoordinatorServicer(start_background_tasks=False)
    service.register_worker(worker())
    # Keep delivery deferred so the persisted lease is observable before the
    # worker's STARTED callback changes it to running.
    service.executor = MagicMock()
    service.fetch_tasks()

    session = Session()
    leased_task = session.query(Tasks).filter_by(id=task_id).first()
    assert leased_task.status == "leased"
    assert leased_task.assigned_worker_id == "worker-1"
    session.close()

    response = json.loads(
        service.update_job_status(
            {"task_id": task_id, "status": "STARTED", "worker_id": "worker-1"}
        )
    )
    assert response["success"] is True

    session = Session()
    running_task = session.query(Tasks).filter_by(id=task_id).first()
    assert running_task.status == "running"
    assert running_task.started_at is not None
    session.close()
