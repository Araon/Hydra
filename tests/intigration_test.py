import os
import pytest
import requests
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


def test_integration(client):
    data = {
        'command': 'echo "Hello World"',
        'scheduled_at': (datetime.utcnow() + timedelta(minutes=5)).isoformat()
    }

    response = client.post('/schedule', json=data)
    assert response.status_code == 201
    task_id = response.json['task_id']

    response = client.get(f'/schedule/{task_id}')
    assert response.status_code == 200
    assert 'task' in response.json
    assert response.json['task']['id'] == task_id
