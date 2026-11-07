"""TO DO :) — Python standard library server with persistent SQLite storage."""
import argparse
import json
import secrets
import sqlite3
from contextlib import closing
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

ROOT = Path(__file__).resolve().parent


def create_server(host="127.0.0.1", port=3000, database=None):
    database = Path(database) if database else ROOT / "data" / "todo.sqlite"
    database.parent.mkdir(parents=True, exist_ok=True)
    with closing(sqlite3.connect(database)) as db:
        db.execute("PRAGMA journal_mode=WAL")
        if db.execute("PRAGMA user_version").fetchone()[0] == 0:
            db.executescript("BEGIN;\n" + (ROOT / "schema.sql").read_text(encoding="utf-8") + "\nPRAGMA user_version=1;\nCOMMIT;")

    class Handler(BaseHTTPRequestHandler):
        def reply(self, status, value, content_type="application/json"):
            body = json.dumps(value).encode("utf-8") if content_type == "application/json" else value
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.end_headers()
            if self.command != "HEAD":
                self.wfile.write(body)

        def handle_request(self):
            url = urlsplit(self.path)
            if url.path in ("/", "/index.html") and self.command in ("GET", "HEAD"):
                self.reply(200, (ROOT / "app.html").read_bytes(), "text/html; charset=utf-8")
                return
            if not url.path.startswith("/api/"):
                self.reply(404, {"error": "Not found"})
                return
            try:
                if self.command == "GET":
                    data = {key: values[0] for key, values in parse_qs(url.query).items()}
                else:
                    length = int(self.headers.get("Content-Length", "0"))
                    if length < 0 or length > 65536:
                        self.reply(413, {"error": "Request too large."})
                        return
                    data = json.loads(self.rfile.read(length))
                if not isinstance(data, dict):
                    raise ValueError("Expected an object")
            except (ValueError, UnicodeDecodeError):
                self.reply(400, {"error": "Invalid request. Please send valid JSON."})
                return
            try:
                with closing(sqlite3.connect(database, timeout=10)) as db:
                    db.row_factory = sqlite3.Row
                    db.execute("PRAGMA foreign_keys=ON")
                    with db:
                        status, result = self.api(db, url.path, data)
                self.reply(status, result)
            except sqlite3.Error:
                self.reply(500, {"error": "We could not save that change. Please try again."})

        def api(self, db, route, data):
            def text(key, default=""):
                value = data.get(key, default)
                return value if isinstance(value, str) else ""

            if route == "/api/rooms" and self.command == "POST":
                name = text("name").strip()
                if not 2 <= len(name) <= 80:
                    return 400, {"error": "Use a room name between 2 and 80 characters."}
                room_id = secrets.token_hex(8).upper()
                db.execute("INSERT INTO rooms (id,name,created_at) VALUES (?,?,?)", (room_id, name, datetime.now(timezone.utc).isoformat()))
                return 201, {"id": room_id, "name": name, "tasks": []}
            room_id, room_name = text("roomId").strip().upper(), text("roomName").strip()
            room = db.execute("SELECT id,name FROM rooms WHERE id=? AND name=?", (room_id, room_name)).fetchone()
            if room is None:
                return 403, {"error": "Room not found. Check both the room ID and exact room name."}
            if route == "/api/room" and self.command == "DELETE":
                if text("confirmName") != room["name"]:
                    return 400, {"error": "Type the exact room name to confirm deletion."}
                db.execute("DELETE FROM tasks WHERE room_id=?", (room_id,))
                db.execute("DELETE FROM rooms WHERE id=?", (room_id,))
                return 200, {"deleted": True, "id": room_id}
            if route == "/api/tasks" and self.command == "POST":
                title, owner = text("title").strip(), text("owner", "You").strip()[:40] or "You"
                if not title or len(title) > 200:
                    return 400, {"error": "Enter a task of up to 200 characters."}
                priority = text("priority", "Medium")
                if priority not in ("High", "Medium", "Low"):
                    priority = "Medium"
                db.execute("INSERT INTO tasks (id,room_id,title,owner,priority,created_at) VALUES (?,?,?,?,?,?)", (secrets.token_hex(16), room_id, title, owner, priority, datetime.now(timezone.utc).isoformat()))
            elif route == "/api/tasks" and self.command == "PATCH":
                db.execute("UPDATE tasks SET completed=? WHERE id=? AND room_id=?", (int(bool(data.get("completed"))), text("taskId"), room_id))
            elif route == "/api/tasks" and self.command == "DELETE":
                db.execute("DELETE FROM tasks WHERE id=? AND room_id=?", (text("taskId"), room_id))
            elif route != "/api/room" or self.command != "GET":
                return 404, {"error": "Not found"}
            tasks = db.execute("SELECT * FROM tasks WHERE room_id=? ORDER BY created_at ASC, rowid ASC", (room_id,)).fetchall()
            return 200, {"id": room["id"], "name": room["name"], "tasks": [dict(task) for task in tasks]}

        do_GET = handle_request
        do_HEAD = handle_request
        do_POST = handle_request
        do_PATCH = handle_request
        do_DELETE = handle_request

    return ThreadingHTTPServer((host, port), Handler)


def main():
    parser = argparse.ArgumentParser(description="Run the TO DO :) app without Node.js or pip packages.")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", default=3000, type=int)
    parser.add_argument("--database", type=Path)
    args = parser.parse_args()
    try:
        server = create_server(args.host, args.port, args.database)
    except OSError as error:
        parser.exit(1, "Could not start server: " + str(error) + "\nTry another port with --port 3001.\n")
    print("TO DO :) is running at http://{}:{}".format(args.host, server.server_port), flush=True)
    print("Keep this terminal open. Press Ctrl+C to stop.", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
