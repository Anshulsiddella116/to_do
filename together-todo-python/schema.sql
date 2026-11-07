CREATE TABLE rooms (id TEXT PRIMARY KEY, name TEXT NOT NULL, created_at TEXT NOT NULL);
CREATE TABLE tasks (id TEXT PRIMARY KEY, room_id TEXT NOT NULL REFERENCES rooms(id), title TEXT NOT NULL, owner TEXT NOT NULL, priority TEXT NOT NULL DEFAULT 'Medium', completed INTEGER NOT NULL DEFAULT 0, created_at TEXT NOT NULL);
CREATE INDEX tasks_room ON tasks(room_id);
