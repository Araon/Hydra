import json
import pytest
from datetime import datetime, timedelta
from src.scheduler.app import app, db, Tasks


@pytest.fixture
def client():
    app.config['TESTING'] = True
    app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///:memory:'
    with app.test_client() as client:
        with app.app_context():
            db.create_all()
        yield client


def test_post_schedule(client):
    data = {
        'command': 'echo "Hello World"',
        'scheduled_at': (datetime.utcnow() + timedelta(minutes=5)).isoformat()
    }
    response = client.post('/schedule', json=data)

    assert response.status_code == 201
    assert 'task_id' in response.json


def test_post_schedule_invalid_data(client):
    data = {
        'scheduled_at': 'invalid_date_format'
    }
    response = client.post('/schedule', json=data)

    assert response.status_code == 400
    assert 'error' in response.json


def test_get_schedule(client):
    task_id = 1
    data = {
        'command': 'echo "Hello World"',
        'scheduled_at': (datetime.utcnow() + timedelta(minutes=5)).isoformat()
    }
    client.post('/schedule', json=data)

    response = client.get(f'/schedule/{task_id}')

    assert response.status_code == 200
    assert 'task' in response.json
    assert response.json['task']['id'] == task_id
