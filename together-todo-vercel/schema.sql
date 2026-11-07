CREATE TABLE IF NOT EXISTS todo_users (id TEXT PRIMARY KEY, email TEXT NOT NULL UNIQUE, name TEXT NOT NULL, password_hash TEXT NOT NULL, created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS todo_rooms (id TEXT PRIMARY KEY, name TEXT NOT NULL, owner_id TEXT NOT NULL REFERENCES todo_users(id), created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS todo_tasks (id TEXT PRIMARY KEY, room_id TEXT NOT NULL REFERENCES todo_rooms(id), title TEXT NOT NULL, owner TEXT NOT NULL, priority TEXT NOT NULL DEFAULT 'Medium', completed INTEGER NOT NULL DEFAULT 0, created_at TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS todo_tasks_room ON todo_tasks(room_id);
CREATE TABLE IF NOT EXISTS todo_login_attempts (key TEXT PRIMARY KEY, attempts INTEGER NOT NULL, started_at BIGINT NOT NULL);
