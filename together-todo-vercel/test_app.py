import os
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

_test_root = tempfile.TemporaryDirectory()
os.environ['TODO_DB_PATH'] = str(Path(_test_root.name) / 'import.sqlite')
import app as module


class AppTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.patch = patch.multiple(module, SQLITE_PATH=Path(self.directory.name) / 'todo.sqlite', DATABASE_URL=None, PRODUCTION=False, _schema_ready=False)
        self.patch.start()
        module.app.config.update(TESTING=True, SECRET_KEY='test-only-secret-value-of-more-than-32-characters', SESSION_COOKIE_SECURE=False)
        self.client = module.app.test_client()
        self.csrf = self.client.get('/api/auth').json['csrf']

    def tearDown(self):
        self.patch.stop()
        self.directory.cleanup()

    def post(self, path, data, client=None, csrf=None, method='POST'):
        return (client or self.client).open(path, method=method, json=data, headers={'X-CSRF-Token': csrf or self.csrf})

    def signup(self, email='sam@example.com', client=None, csrf=None):
        response = self.post('/api/signup', {'name': 'Sam', 'email': email, 'password': 'correct horse battery'}, client, csrf)
        self.assertEqual(response.status_code, 201)
        if client is None:
            self.csrf = response.json['csrf']
        return response.json['csrf']

    def test_entrypoint_login_and_signup(self):
        self.assertEqual(self.client.get('/').status_code, 302)
        with self.client.get('/login') as response:
            self.assertIn('Create account', response.text)
        self.assertEqual(self.client.get('/api/rooms').status_code, 401)
        self.assertEqual(self.client.post('/api/signup', json={}).status_code, 403)
        self.signup()
        state = self.client.get('/api/auth').json
        self.assertTrue(state['authenticated'])
        self.assertEqual(state['user']['name'], 'Sam')
        with self.client.get('/') as response:
            self.assertIn('Delete room', response.text)
        with sqlite3.connect(module.SQLITE_PATH) as db:
            hashed = db.execute('SELECT password_hash FROM todo_users').fetchone()[0]
            self.assertNotEqual(hashed, 'correct horse battery')
            self.assertTrue(hashed.startswith('scrypt:'))
        self.assertEqual(self.client.get('/app.py').status_code, 404)
        self.assertEqual(self.post('/api/signup', {'name': 'Duplicate', 'email': 'SAM@example.com', 'password': 'correct horse battery'}).status_code, 409)
        self.assertEqual(self.post('/api/logout', {}).status_code, 200)
        self.csrf = self.client.get('/api/auth').json['csrf']
        self.assertFalse(self.client.get('/api/auth').json['authenticated'])
        self.assertEqual(self.post('/api/login', {'email': 'sam@example.com', 'password': 'incorrect'}).status_code, 401)
        response = self.post('/api/login', {'email': 'SAM@example.com', 'password': 'correct horse battery'})
        self.assertEqual(response.status_code, 200)
        self.assertTrue(self.client.get('/api/auth').json['authenticated'])

    def test_rooms_tasks_and_owner_only_deletion(self):
        self.signup()
        room = self.post('/api/rooms', {'name': 'Python Club'}).json
        credentials = dict(roomId=room['id'], roomName=room['name'])
        self.assertEqual(self.client.get('/api/rooms').json['rooms'][0]['id'], room['id'])
        result = self.post('/api/tasks', {**credentials, 'title': 'Learn Python', 'owner': 'Sam'})
        task = result.json['tasks'][0]
        result = self.post('/api/tasks', {**credentials, 'taskId': task['id'], 'completed': True}, method='PATCH')
        self.assertEqual(result.json['tasks'][0]['completed'], 1)
        other = module.app.test_client()
        other_csrf = other.get('/api/auth').json['csrf']
        other_csrf = self.signup('friend@example.com', other, other_csrf)
        joined = other.get('/api/room', query_string=credentials)
        self.assertEqual(joined.status_code, 200)
        self.assertFalse(joined.json['canDelete'])
        self.assertEqual(len(joined.json['tasks']), 1)
        self.assertEqual(self.post('/api/room', {**credentials, 'confirmName': 'Python Club'}, other, other_csrf, 'DELETE').status_code, 403)
        self.assertEqual(self.post('/api/room', {**credentials, 'confirmName': 'Wrong'}, method='DELETE').status_code, 400)
        self.assertEqual(self.client.get('/api/room', query_string={**credentials, 'roomName': 'Wrong'}).status_code, 404)
        keep = self.post('/api/rooms', {'name': 'Keep this room'}).json
        result = self.post('/api/room', {**credentials, 'confirmName': 'Python Club'}, method='DELETE')
        self.assertTrue(result.json['deleted'])
        self.assertEqual(self.client.get('/api/room', query_string=credentials).status_code, 404)
        self.assertEqual(self.client.get('/api/room', query_string={'roomId': keep['id'], 'roomName': keep['name']}).status_code, 200)
        with sqlite3.connect(module.SQLITE_PATH) as db:
            self.assertEqual(db.execute('SELECT count(*) FROM todo_tasks WHERE room_id=?', (room['id'],)).fetchone()[0], 0)

    def test_rate_limit_and_vercel_configuration(self):
        for attempt in range(11):
            response = self.post('/api/login', {'email': 'nobody@example.com', 'password': 'wrong password'})
        self.assertEqual(response.status_code, 429)
        with patch.object(module, 'PRODUCTION', True):
            self.assertEqual(self.client.get('/api/auth').status_code, 503)
            self.assertIn('DATABASE_URL', self.client.get('/api/auth').json['error'])
            with self.client.get('/login') as response:
                self.assertEqual(response.status_code, 200)
        self.assertEqual(self.post('/api/signup', {'name': 'A', 'email': 'a@example.com', 'password': 'short'}).status_code, 400)
        self.assertEqual(self.post('/api/signup', {'name': 'A', 'email': 'bad', 'password': 'long enough password'}).status_code, 400)


if __name__ == '__main__':
    unittest.main()
