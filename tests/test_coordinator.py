import json
from unittest.mock import MagicMock, patch

from coordinator_service import CoordinatorServicer


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
