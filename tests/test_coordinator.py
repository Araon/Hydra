import unittest
from unittest.mock import MagicMock, patch
from coordinator_service import CoordinatorServicer, app
import json
import time


class TestCoordinatorService(unittest.TestCase):

    def setUp(self):
        self.coordinator_servicer = CoordinatorServicer()

    def test_worker_registration(self):

        mock_request = MagicMock()
        mock_request.json.return_value = {
            'worker_id': '123',
            'ip': '127.0.0.1',
            'port': 8080,
            'metadata': {}
        }

        with patch('coordinator_service.request', mock_request):
            response = self.coordinator_servicer.register_worker(mock_request)
            response_data = json.loads(response)
            self.assertTrue(response_data['success'])
            self.assertEqual(response_data['message'], 'Worker 123 registered.')

    def test_worker_heartbeat(self):
        self.coordinator_servicer.registered_workers = {
            '123': {
                'lastHeartBeatTime': time.time(),
                'heartBeatMissed': 0,
                'workerIp': '127.0.0.1',
                'workerPort': 8080,
                'metadata': {}
            }
        }

        self.coordinator_servicer.sendHeartBeat('123')
        self.assertEqual(self.coordinator_servicer.registered_workers['123']['heartBeatMissed'], 0)

    def test_fetching_and_submitting_tasks(self):
        self.coordinator_servicer.registered_workers = {
            '123': {
                'lastHeartBeatTime': time.time(),
                'heartBeatMissed': 0,
                'workerIp': '127.0.0.1',
                'workerPort': 8080,
                'metadata': {}
            }
        }
        self.coordinator_servicer.last_assigned_worker_index = -1  # Reset index

        mock_session = MagicMock()
        mock_task = MagicMock()
        mock_task.id = 1
        mock_task.command = "some_command"
        mock_session.query.return_value.filter.return_value.order_by.return_value.limit.return_value.with_for_update.return_value.all.return_value = [mock_task]

        with patch('coordinator_service.Session', MagicMock(return_value=mock_session)):
            self.coordinator_servicer.fetch_tasks()

        self.assertEqual(self.coordinator_servicer.last_assigned_worker_index, 0)

    def test_updating_job_status(self):
        mock_session = MagicMock()
        mock_task = MagicMock()
        mock_task.id = 1
        mock_session.query.return_value.filter_by.return_value.first.return_value = mock_task

        with patch('coordinator_service.Session', MagicMock(return_value=mock_session)):
            response = self.coordinator_servicer.update_job_status({'task_id': 1, 'status': 'STARTED'})
            response_data = json.loads(response)
            self.assertTrue(response_data['success'])
            self.assertEqual(response_data['message'], 'Task 1 updated successfully')


if __name__ == '__main__':
    unittest.main()
