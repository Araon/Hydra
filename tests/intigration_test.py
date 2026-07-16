from datetime import datetime

from src.scheduler import app as scheduler_module
from src.scheduler.app import app, db


def test_schedule_round_trip(monkeypatch):
    app.config.update(TESTING=True, SQLALCHEMY_DATABASE_URI="sqlite:///:memory:")
    monkeypatch.setattr(scheduler_module, "notify_coordinator", lambda: None)
    with app.app_context():
        db.drop_all()
        db.create_all()
        client = app.test_client()
        response = client.post(
            "/schedule",
            json={
                "job_type": "sleep",
                "payload": {"duration_seconds": 1},
                "scheduled_at": datetime.utcnow().isoformat(),
                "max_attempts": 2,
            },
        )
        assert response.status_code == 201
        task = client.get(f"/schedule/{response.json['task_id']}")
        assert task.status_code == 200
        assert task.json["task"]["payload"] == {"duration_seconds": 1}
