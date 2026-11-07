import json
import sqlite3
import tempfile
import threading
import unittest
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen
from server import create_server


class AppTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.database = Path(self.temp.name) / 'test.sqlite'
        self.start()

    def start(self):
        self.server = create_server(port=0, database=self.database)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.base = 'http://127.0.0.1:' + str(self.server.server_port)

    def stop(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join()

    def tearDown(self):
        self.stop()
        self.temp.cleanup()

    def call(self, route, method='GET', **data):
        from urllib.parse import urlencode
        target = self.base + '/api/' + route
        body = None
        if method == 'GET':
            target += '?' + urlencode(data)
        else:
            body = json.dumps(data).encode()
        request = Request(target, data=body, method=method, headers={'Content-Type': 'application/json'})
        try:
            response = urlopen(request)
        except HTTPError as error:
            response = error
        with response:
            return response.status, json.load(response)

    def room(self, name):
        status, room = self.call('rooms', 'POST', name=name)
        self.assertEqual(status, 201)
        return dict(roomId=room['id'], roomName=room['name'])

    def test_ui_persistence_and_room_deletion(self):
        with urlopen(self.base) as response:
            self.assertIn('Delete room', response.read().decode())
        credentials = self.room('Python Club')
        other = self.room('Keep this room')
        status, result = self.call('tasks', 'POST', **credentials, title='Try Python', owner='Sam', priority='High')
        self.assertEqual(status, 200)
        task_id = result['tasks'][0]['id']
        _, result = self.call('tasks', 'PATCH', **credentials, taskId=task_id, completed=True)
        self.assertEqual(result['tasks'][0]['completed'], 1)
        self.assertEqual(len(result['tasks']), 1)
        self.call('tasks', 'DELETE', **other, taskId=task_id)
        self.assertEqual(len(self.call('room', **credentials)[1]['tasks']), 1)
        self.assertEqual(self.call('room', 'DELETE', **credentials, confirmName='Wrong')[0], 400)
        wrong = dict(credentials, roomName='Wrong')
        self.assertEqual(self.call('room', 'DELETE', **wrong, confirmName='Python Club')[0], 403)
        self.stop()
        self.start()
        self.assertEqual(self.call('room', **credentials)[1]['tasks'][0]['completed'], 1)
        self.assertTrue(self.call('room', 'DELETE', **credentials, confirmName='Python Club')[1]['deleted'])
        self.assertEqual(self.call('room', **credentials)[0], 403)
        self.assertEqual(self.call('tasks', 'POST', **credentials, title='No access')[0], 403)
        self.assertEqual(self.call('room', **other)[0], 200)
        with sqlite3.connect(self.database) as db:
            self.assertEqual(db.execute('SELECT count(*) FROM tasks WHERE room_id=?', (credentials['roomId'],)).fetchone()[0], 0)

    def test_validation_and_individual_delete(self):
        self.assertEqual(self.call('rooms', 'POST', name='')[0], 400)
        credentials = self.room('Tasks')
        self.assertEqual(self.call('tasks', 'POST', **credentials, title='')[0], 400)
        _, result = self.call('tasks', 'POST', **credentials, title='Remove me')
        task_id = result['tasks'][0]['id']
        _, result = self.call('tasks', 'DELETE', **credentials, taskId=task_id)
        self.assertEqual(result['tasks'], [])
        self.assertEqual(self.call('room', 'DELETE', **credentials)[0], 400)
        with self.assertRaises(HTTPError) as error:
            urlopen(self.base + '/server.py')
        self.assertEqual(error.exception.code, 404)


if __name__ == '__main__':
    unittest.main()
