import pytest
import requests
from datetime import datetime, timedelta
from your_scheduler_module import app, db, Tasks


@pytest.fixture
def base_url():
    return 'http://localhost:5000'


def test_integration(base_url):
    data = {
        'command': 'echo "Hello World"',
        'scheduled_at': (datetime.utcnow() + timedelta(minutes=5)).isoformat()
    }
    # Schedule a task
    response = requests.post(f'{base_url}/schedule', json=data)
    assert response.status_code == 201
    task_id = response.json['task_id']

    # Retrieve the scheduled task
    response = requests.get(f'{base_url}/schedule/{task_id}')
    assert response.status_code == 200
    assert 'task' in response.json
    assert response.json['task']['id'] == task_id
