import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

_test_root = tempfile.TemporaryDirectory()
os.environ['TODO_DB_PATH'] = str(Path(_test_root.name) / 'import.sqlite')
import app as module

# Set TEST_DATABASE_URL to run this suite against a real PostgreSQL database (tables are reset first).
TEST_DATABASE_URL = os.environ.get('TEST_DATABASE_URL') or None
ROOT = Path(__file__).resolve().parent


class AppTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.patch = patch.multiple(module, SQLITE_PATH=Path(self.directory.name) / 'todo.sqlite', DATABASE_URL=TEST_DATABASE_URL, PRODUCTION=False, _schema_ready=False)
        self.patch.start()
        module.app.config.update(TESTING=True, SECRET_KEY='test-only-secret-value-of-more-than-32-characters', SESSION_COOKIE_SECURE=False)
        if TEST_DATABASE_URL:
            with module.database() as db:
                db.execute('DROP TABLE IF EXISTS todo_tasks, todo_rooms, todo_login_attempts, todo_users CASCADE')
            module._schema_ready = False
        self.client = module.app.test_client()
        self.csrf = self.client.get('/api/auth').json['csrf']

    def scalar(self, sql, args=()):
        with module.database() as db:
            row = db.execute(sql, args).fetchone()
        return list(row.values())[0] if isinstance(row, dict) else row[0]

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
        hashed = self.scalar('SELECT password_hash FROM todo_users')
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
        self.assertEqual(self.scalar('SELECT count(*) FROM todo_tasks WHERE room_id=?', (room['id'],)), 0)

    def test_rate_limit_and_vercel_configuration(self):
        for attempt in range(11):
            response = self.post('/api/login', {'email': 'nobody@example.com', 'password': 'wrong password'})
        self.assertEqual(response.status_code, 429)
        with patch.object(module, 'PRODUCTION', True), patch.object(module, 'DATABASE_URL', None):
            self.assertEqual(self.client.get('/api/auth').status_code, 503)
            self.assertIn('DATABASE_URL', self.client.get('/api/auth').json['error'])
            with self.client.get('/login') as response:
                self.assertEqual(response.status_code, 200)
        self.assertEqual(self.post('/api/signup', {'name': 'A', 'email': 'a@example.com', 'password': 'short'}).status_code, 400)
        self.assertEqual(self.post('/api/signup', {'name': 'A', 'email': 'bad', 'password': 'long enough password'}).status_code, 400)

    def test_stale_login_attempts_are_purged(self):
        self.post('/api/login', {'email': 'a@example.com', 'password': 'wrong password'})
        with module.database() as db:
            db.execute('UPDATE todo_login_attempts SET started_at=1')
        self.post('/api/login', {'email': 'b@example.com', 'password': 'wrong password'})
        self.assertEqual(self.scalar('SELECT count(*) FROM todo_login_attempts'), 1)

    def test_favicon_and_health(self):
        self.assertEqual(self.client.get('/favicon.ico').status_code, 204)
        self.assertEqual(self.client.get('/api/health').json, {'ok': True})
        with self.client.get('/login') as response:
            self.assertIn('rel="icon"', response.text)

    def test_clean_database_url(self):
        clean = module.clean_database_url
        self.assertEqual(clean('postgres://u:p%40ss@h.example.com:5432/db?sslmode=require'),
                         'postgres://u:p%40ss@h.example.com:5432/db?sslmode=require')
        self.assertEqual(clean('postgres://u:p@h/db?sslmode=require&supa=base-pooler.x'), 'postgres://u:p@h/db?sslmode=require')
        self.assertEqual(clean('postgres://u:p@h/db?pgbouncer=true&sslmode=require'), 'postgres://u:p@h/db?sslmode=require')
        self.assertEqual(clean('postgres://u:p@h/db?supa=x'), 'postgres://u:p@h/db')
        self.assertIsNone(clean(None))

    def test_session_secret_selection(self):
        def secret(**env):
            clean_env = {k: v for k, v in os.environ.items() if k not in ('AUTH_SECRET', 'DATABASE_URL', 'POSTGRES_URL', 'VERCEL')}
            clean_env.update(env, TODO_DB_PATH=str(Path(_test_root.name) / 'sub.sqlite'))
            out = subprocess.run([sys.executable, '-c', 'import app; print(app.app.secret_key)'], cwd=ROOT, env=clean_env, capture_output=True, text=True)
            self.assertEqual(out.returncode, 0, out.stderr)
            return out.stdout.strip()
        db = 'postgresql://user:pw@host.example.com/db?sslmode=require'
        explicit = 'e' * 40
        self.assertEqual(secret(VERCEL='1', DATABASE_URL=db, AUTH_SECRET=explicit), explicit)
        derived = secret(VERCEL='1', DATABASE_URL=db)
        self.assertRegex(derived, r'^[0-9a-f]{64}$')
        self.assertEqual(derived, secret(VERCEL='1', DATABASE_URL=db))
        self.assertNotEqual(derived, secret(VERCEL='1', DATABASE_URL=db.replace('pw', 'other')))
        self.assertEqual(secret(VERCEL='1', POSTGRES_URL=db), secret(VERCEL='1', POSTGRES_URL=db))
        self.assertEqual(secret(VERCEL='1'), 'None')


if __name__ == '__main__':
    unittest.main()
