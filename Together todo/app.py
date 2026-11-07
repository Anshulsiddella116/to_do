"""Flask entrypoint for Vercel. PostgreSQL in production; SQLite for local use."""
import hashlib
import hmac
import os
import re
import secrets
import sqlite3
import threading
import time
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from flask import Flask, jsonify, redirect, request, send_file, session
from werkzeug.exceptions import BadRequest, RequestEntityTooLarge
from werkzeug.security import check_password_hash, generate_password_hash

ROOT = Path(__file__).resolve().parent
app = Flask(__name__, static_folder=None)
PRODUCTION = bool(os.environ.get("VERCEL"))


def clean_database_url(url):
    """Drop query parameters that hosting integrations add but libpq rejects."""
    if not url or "://" not in url:
        return url
    parts = urlsplit(url)
    pairs = parse_qsl(parts.query, keep_blank_values=True)
    kept = [(key, value) for key, value in pairs if key.lower() not in ("supa", "pgbouncer")]
    if len(kept) == len(pairs):
        return url
    return urlunsplit(parts._replace(query=urlencode(kept, safe="/")))


# Vercel's Postgres integrations (Neon, Supabase, ...) set DATABASE_URL and/or POSTGRES_URL.
DATABASE_URL = clean_database_url((os.environ.get("DATABASE_URL") or os.environ.get("POSTGRES_URL") or "").strip()) or None
SQLITE_PATH = Path(os.environ.get("TODO_DB_PATH", str(ROOT / "data" / "todo.sqlite")))
secret = os.environ.get("AUTH_SECRET", "").strip()
if not secret and DATABASE_URL:
    # AUTH_SECRET is recommended, but if it is missing, derive a stable signing key from the
    # private database URL so a Vercel deployment works with only the database connected.
    secret = hmac.new(b"together-todo/session-key/v1", os.environ.get("DATABASE_URL", os.environ.get("POSTGRES_URL", "")).encode(), hashlib.sha256).hexdigest()
elif not secret and not PRODUCTION:
    SQLITE_PATH.parent.mkdir(parents=True, exist_ok=True)
    key_file = SQLITE_PATH.parent / "session.key"
    try:
        with key_file.open("x", encoding="utf-8") as stream:
            stream.write(secrets.token_hex(32))
    except FileExistsError:
        pass
    secret = key_file.read_text(encoding="utf-8").strip()
app.config.update(SECRET_KEY=secret or None, MAX_CONTENT_LENGTH=65536,
                  SESSION_COOKIE_HTTPONLY=True, SESSION_COOKIE_SECURE=PRODUCTION,
                  SESSION_COOKIE_SAMESITE="Lax", PERMANENT_SESSION_LIFETIME=timedelta(days=7))
_schema_ready = False
_schema_lock = threading.Lock()
SCHEMA = [part.strip() for part in (ROOT / "schema.sql").read_text().split(";") if part.strip()]


class Database:
    def __init__(self, connection, postgres):
        self.connection, self.postgres = connection, postgres

    def execute(self, sql, args=()):
        return self.connection.execute(sql.replace("?", "%s") if self.postgres else sql, args)


@contextmanager
def database():
    global _schema_ready
    if DATABASE_URL:
        import psycopg
        from psycopg.rows import dict_row
        # prepare_threshold=None keeps this safe behind PgBouncer-style poolers (Neon, Supabase).
        connection = psycopg.connect(DATABASE_URL, row_factory=dict_row, connect_timeout=10, prepare_threshold=None)
    else:
        if PRODUCTION:
            raise RuntimeError("DATABASE_URL is required on Vercel")
        SQLITE_PATH.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(SQLITE_PATH, timeout=15)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys=ON")
    db = Database(connection, bool(DATABASE_URL))
    try:
        with connection:
            if not _schema_ready:
                with _schema_lock:
                    if not _schema_ready:
                        if db.postgres:
                            db.execute("SELECT pg_advisory_xact_lock(685439721)")
                        for statement in SCHEMA:
                            db.execute(statement)
                        connection.commit()
                        _schema_ready = True
            yield db
    finally:
        connection.close()


def configuration_error():
    if PRODUCTION and not DATABASE_URL:
        return "Connect a PostgreSQL database and set DATABASE_URL in Vercel, then redeploy."
    if not app.secret_key or (PRODUCTION and len(str(app.secret_key)) < 32):
        return "Set AUTH_SECRET to a random value of at least 32 characters in Vercel, then redeploy."
    return None


def failure(message, status=400):
    return jsonify(error=message), status


def payload():
    data = request.args.to_dict() if request.method == "GET" else request.get_json()
    if not isinstance(data, dict):
        raise BadRequest()
    return data


def text(data, key, default=""):
    value = data.get(key, default)
    return value if isinstance(value, str) else ""


def csrf_token():
    if "csrf" not in session:
        session["csrf"] = secrets.token_hex(32)
    return session["csrf"]


@app.before_request
def protect_api():
    if not request.path.startswith("/api/"):
        return None
    error = configuration_error()
    if error:
        return failure(error, 503)
    if request.method not in ("GET", "HEAD", "OPTIONS"):
        token = request.headers.get("X-CSRF-Token", "")
        if not session.get("csrf") or not hmac.compare_digest(token, session["csrf"]):
            return failure("Your session expired. Refresh the page and try again.", 403)
    public = {"/api/auth", "/api/login", "/api/signup", "/api/health"}
    if request.path not in public and not session.get("user_id"):
        return failure("Please sign in to access your rooms.", 401)


@app.after_request
def response_headers(response):
    response.headers["Cache-Control"] = "no-store"
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "SAMEORIGIN"
    response.headers["Referrer-Policy"] = "same-origin"
    return response


@app.errorhandler(BadRequest)
def bad_request(_):
    return failure("Invalid request. Please send valid JSON.")


@app.errorhandler(RequestEntityTooLarge)
def large_request(_):
    return failure("Request too large.", 413)


@app.errorhandler(500)
def server_error(_):
    return failure("The server could not complete this request. Check the database settings and try again.", 500)


@app.get("/")
def home():
    if not session.get("user_id"):
        return redirect("/login")
    return send_file(ROOT / "app.html")


@app.get("/login")
def login_page():
    if session.get("user_id"):
        return redirect("/")
    return send_file(ROOT / "login.html")


@app.get("/favicon.ico")
def favicon():
    return "", 204


@app.get("/api/health")
def health():
    with database() as db:
        db.execute("SELECT 1")
    return jsonify(ok=True)


@app.get("/api/auth")
def auth_state():
    user = None
    if session.get("user_id"):
        with database() as db:
            row = db.execute("SELECT id,email,name FROM todo_users WHERE id=?", (session["user_id"],)).fetchone()
            user = dict(row) if row else None
        if not user:
            session.clear()
    return jsonify(authenticated=bool(user), user=user, csrf=csrf_token())


@app.post("/api/signup")
def signup():
    data = payload()
    name, email, password = text(data, "name").strip(), text(data, "email").strip().lower(), text(data, "password")
    if not 1 <= len(name) <= 40:
        return failure("Enter a display name of up to 40 characters.")
    if len(email) > 254 or not re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]+", email):
        return failure("Enter a valid email address.")
    if not 10 <= len(password) <= 128:
        return failure("Use a password between 10 and 128 characters.")
    user_id = secrets.token_hex(16)
    password_hash = generate_password_hash(password)
    with database() as db:
        inserted = db.execute("INSERT INTO todo_users (id,email,name,password_hash,created_at) VALUES (?,?,?,?,?) ON CONFLICT(email) DO NOTHING", (user_id, email, name, password_hash, datetime.now(timezone.utc).isoformat()))
        if inserted.rowcount == 0:
            return failure("That email is already registered. Sign in instead.", 409)
    session.clear()
    session["user_id"] = user_id
    session.permanent = True
    return jsonify(ok=True, csrf=csrf_token()), 201


@app.post("/api/login")
def login():
    data = payload()
    email, password = text(data, "email").strip().lower(), text(data, "password")
    if not email or len(email) > 254 or not password or len(password) > 128:
        return failure("Enter your email and password.")
    key = hashlib.sha256(email.encode()).hexdigest()
    now = int(time.time())
    with database() as db:
        # The database counter also applies across separate serverless instances.
        db.execute("DELETE FROM todo_login_attempts WHERE started_at<?", (now - 900,))
        db.execute("INSERT INTO todo_login_attempts (key,attempts,started_at) VALUES (?,1,?) ON CONFLICT(key) DO UPDATE SET attempts=CASE WHEN todo_login_attempts.started_at<? THEN 1 ELSE todo_login_attempts.attempts+1 END, started_at=CASE WHEN todo_login_attempts.started_at<? THEN ? ELSE todo_login_attempts.started_at END", (key, now, now-900, now-900, now))
        count = db.execute("SELECT attempts FROM todo_login_attempts WHERE key=?", (key,)).fetchone()["attempts"]
        if count > 10:
            return failure("Too many sign-in attempts. Try again in 15 minutes.", 429)
        user = db.execute("SELECT id,password_hash FROM todo_users WHERE email=?", (email,)).fetchone()
        valid = user is not None and check_password_hash(user["password_hash"], password)
        if valid:
            db.execute("DELETE FROM todo_login_attempts WHERE key=?", (key,))
    if not valid:
        return failure("Email or password is incorrect.", 401)
    session.clear()
    session["user_id"] = user["id"]
    session.permanent = True
    return jsonify(ok=True, csrf=csrf_token())


@app.post("/api/logout")
def logout():
    session.clear()
    return jsonify(ok=True)


@app.route("/api/rooms", methods=["GET", "POST"])
@app.route("/api/room", methods=["GET", "DELETE"])
@app.route("/api/tasks", methods=["POST", "PATCH", "DELETE"])
def room_api():
    data = payload()
    user_id = session["user_id"]
    with database() as db:
        if request.path == "/api/rooms" and request.method == "GET":
            rooms = db.execute("SELECT id,name FROM todo_rooms WHERE owner_id=? ORDER BY created_at", (user_id,)).fetchall()
            return jsonify(rooms=[dict(room) for room in rooms])
        if request.path == "/api/rooms":
            name = text(data, "name").strip()
            if not 2 <= len(name) <= 80:
                return failure("Use a room name between 2 and 80 characters.")
            room_id = secrets.token_hex(8).upper()
            db.execute("INSERT INTO todo_rooms (id,name,owner_id,created_at) VALUES (?,?,?,?)", (room_id, name, user_id, datetime.now(timezone.utc).isoformat()))
            return jsonify(id=room_id, name=name, tasks=[], canDelete=True), 201
        room_id, name = text(data, "roomId").strip().upper(), text(data, "roomName").strip()
        lock = " FOR UPDATE" if db.postgres else ""
        room = db.execute("SELECT id,name,owner_id FROM todo_rooms WHERE id=? AND name=?" + lock, (room_id, name)).fetchone()
        if room is None:
            return failure("Room not found. Check both the room ID and exact room name.", 404)
        if request.path == "/api/room" and request.method == "DELETE":
            if room["owner_id"] != user_id:
                return failure("Only the person who created this room can delete it.", 403)
            if text(data, "confirmName") != room["name"]:
                return failure("Type the exact room name to confirm deletion.")
            db.execute("DELETE FROM todo_tasks WHERE room_id=?", (room_id,))
            db.execute("DELETE FROM todo_rooms WHERE id=?", (room_id,))
            return jsonify(deleted=True, id=room_id)
        if request.path == "/api/tasks":
            if request.method == "POST":
                title, owner = text(data, "title").strip(), text(data, "owner", "You").strip()[:40] or "You"
                if not title or len(title) > 200:
                    return failure("Enter a task of up to 200 characters.")
                priority = text(data, "priority", "Medium")
                if priority not in ("High", "Medium", "Low"):
                    priority = "Medium"
                db.execute("INSERT INTO todo_tasks (id,room_id,title,owner,priority,created_at) VALUES (?,?,?,?,?,?)", (secrets.token_hex(16), room_id, title, owner, priority, datetime.now(timezone.utc).isoformat()))
            elif request.method == "PATCH":
                db.execute("UPDATE todo_tasks SET completed=? WHERE id=? AND room_id=?", (int(bool(data.get("completed"))), text(data, "taskId"), room_id))
            else:
                db.execute("DELETE FROM todo_tasks WHERE id=? AND room_id=?", (text(data, "taskId"), room_id))
        tasks = db.execute("SELECT * FROM todo_tasks WHERE room_id=? ORDER BY created_at,id", (room_id,)).fetchall()
        return jsonify(id=room["id"], name=room["name"], canDelete=room["owner_id"] == user_id, tasks=[dict(task) for task in tasks])


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=int(os.environ.get("PORT", "3000")), debug=False)
