const express = require("express");
const { DatabaseSync } = require("node:sqlite"); // built into Node 22.13+ (no native build needed)
const bcrypt = require("bcryptjs");
const jwt = require("jsonwebtoken");
const crypto = require("crypto");
const fs = require("fs");
const path = require("path");

const PORT = process.env.PORT || 3000;
const DATA_DIR = process.env.DATA_DIR || path.join(__dirname, "data");
fs.mkdirSync(DATA_DIR, { recursive: true });

// JWT secret: from env, or generated once and kept in data/.secret
const SECRET = process.env.JWT_SECRET || (() => {
  const f = path.join(DATA_DIR, ".secret");
  if (!fs.existsSync(f)) fs.writeFileSync(f, crypto.randomBytes(32).toString("hex"), { mode: 0o600 });
  return fs.readFileSync(f, "utf8");
})();

// ---------- database ----------
const db = new DatabaseSync(path.join(DATA_DIR, "todo.db"));
db.exec("PRAGMA journal_mode = WAL; PRAGMA foreign_keys = ON;");
db.exec(`
CREATE TABLE IF NOT EXISTS users (username TEXT PRIMARY KEY, hash TEXT NOT NULL, created_at INTEGER NOT NULL);
CREATE TABLE IF NOT EXISTS rooms (id TEXT PRIMARY KEY, name TEXT NOT NULL, owner TEXT NOT NULL REFERENCES users(username), created_at INTEGER NOT NULL);
CREATE TABLE IF NOT EXISTS members (room_id TEXT NOT NULL REFERENCES rooms(id) ON DELETE CASCADE, username TEXT NOT NULL REFERENCES users(username), PRIMARY KEY (room_id, username));
CREATE TABLE IF NOT EXISTS todos (id INTEGER PRIMARY KEY AUTOINCREMENT, room_id TEXT NOT NULL REFERENCES rooms(id) ON DELETE CASCADE, text TEXT NOT NULL, done INTEGER NOT NULL DEFAULT 0, created_at INTEGER NOT NULL);
`);
const q = {
  user: db.prepare("SELECT * FROM users WHERE username = ?"),
  addUser: db.prepare("INSERT INTO users VALUES (?, ?, ?)"),
  room: db.prepare("SELECT * FROM rooms WHERE id = ?"),
  addRoom: db.prepare("INSERT INTO rooms VALUES (?, ?, ?, ?)"),
  delRoom: db.prepare("DELETE FROM rooms WHERE id = ?"),
  isMember: db.prepare("SELECT 1 FROM members WHERE room_id = ? AND username = ?"),
  addMember: db.prepare("INSERT OR IGNORE INTO members VALUES (?, ?)"),
  todos: db.prepare("SELECT id, text, done FROM todos WHERE room_id = ? ORDER BY id"),
  todo: db.prepare("SELECT * FROM todos WHERE id = ?"),
  addTodo: db.prepare("INSERT INTO todos (room_id, text, done, created_at) VALUES (?, ?, 0, ?)"),
  setDone: db.prepare("UPDATE todos SET done = ? WHERE id = ?"),
  delTodo: db.prepare("DELETE FROM todos WHERE id = ?"),
  mine: db.prepare("SELECT * FROM rooms WHERE owner = ? ORDER BY created_at DESC"),
  joined: db.prepare("SELECT r.* FROM rooms r JOIN members m ON m.room_id = r.id WHERE m.username = ? ORDER BY r.created_at DESC"),
};
const todosOf = id => q.todos.all(id).map(t => ({ id: t.id, text: t.text, done: !!t.done }));
const view = (r, user) => ({ id: r.id, name: r.name, owner: r.owner, isOwner: r.owner === user, todos: todosOf(r.id) });
const ID_CHARS = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789";
const newId = () => Array.from(crypto.randomBytes(6), b => ID_CHARS[b % ID_CHARS.length]).join("");

// ---------- app ----------
const app = express();
app.use(express.json({ limit: "10kb" }));
app.use(express.static(path.join(__dirname, "public")));

const fail = (res, code, error) => res.status(code).json({ error });
const sign = u => jwt.sign({ u }, SECRET, { expiresIn: "30d" });

// naive in-memory rate limit for auth endpoints (10 tries / minute / IP)
const hits = new Map();
const limit = (req, res, next) => {
  const k = req.ip, now = Date.now(), a = (hits.get(k) || []).filter(t => now - t < 60000);
  if (a.length >= 10) return fail(res, 429, "Too many attempts. Try again in a minute.");
  a.push(now); hits.set(k, a); next();
};

function auth(req, res, next) {
  const h = req.headers.authorization || "";
  try {
    const { u } = jwt.verify(h.replace(/^Bearer /, ""), SECRET);
    if (!q.user.get(u)) throw 0;
    req.user = u; next();
  } catch { fail(res, 401, "Please log in again."); }
}

// ----- auth -----
app.post("/api/signup", limit, (req, res) => {
  const u = String(req.body.username || "").trim().toLowerCase(), p = String(req.body.password || "");
  if (!/^[a-z0-9_]{3,20}$/.test(u)) return fail(res, 400, "Username: 3–20 letters, numbers or underscores.");
  if (p.length < 6 || p.length > 100) return fail(res, 400, "Password must be 6–100 characters.");
  if (q.user.get(u)) return fail(res, 409, "That username is taken.");
  q.addUser.run(u, bcrypt.hashSync(p, 10), Date.now());
  res.json({ token: sign(u), username: u });
});

app.post("/api/login", limit, (req, res) => {
  const u = String(req.body.username || "").trim().toLowerCase(), row = q.user.get(u);
  if (!row || !bcrypt.compareSync(String(req.body.password || ""), row.hash)) return fail(res, 401, "Wrong username or password.");
  res.json({ token: sign(u), username: u });
});

// ----- rooms -----
const withProgress = r => ({ id: r.id, name: r.name, owner: r.owner, todos: todosOf(r.id) });
app.get("/api/rooms/mine", auth, (req, res) => res.json(q.mine.all(req.user).map(withProgress)));
app.get("/api/rooms/joined", auth, (req, res) => res.json(q.joined.all(req.user).map(withProgress)));

app.post("/api/rooms", auth, (req, res) => {
  const name = String(req.body.name || "").trim().slice(0, 40);
  if (!name) return fail(res, 400, "Give your room a name.");
  let id; do { id = newId(); } while (q.room.get(id));
  q.addRoom.run(id, name, req.user, Date.now());
  res.status(201).json({ id });
});

// Join requires BOTH the Room ID and the exact Room name.
app.post("/api/rooms/join", auth, (req, res) => {
  const id = String(req.body.id || "").trim().toUpperCase(), name = String(req.body.name || "").trim().toLowerCase();
  const r = q.room.get(id);
  if (!r || r.name.trim().toLowerCase() !== name) return fail(res, 404, "No room matches that ID and name.");
  if (r.owner !== req.user) q.addMember.run(id, req.user);
  res.json({ id });
});

// Only the owner or someone who joined with ID + name can read a room.
function roomAccess(req, res, next) {
  const r = q.room.get(String(req.params.id).toUpperCase());
  if (!r) return fail(res, 404, "This room no longer exists.");
  if (r.owner !== req.user && !q.isMember.get(r.id, req.user)) return fail(res, 403, "Join this room with its ID and name first.");
  req.room = r; next();
}
const ownerOnly = (req, res, next) => req.room.owner === req.user ? next() : fail(res, 403, "Only the room owner can do that.");

app.get("/api/rooms/:id", auth, roomAccess, (req, res) => res.json(view(req.room, req.user)));
app.delete("/api/rooms/:id", auth, roomAccess, ownerOnly, (req, res) => { q.delRoom.run(req.room.id); res.json({ ok: true }); });

// ----- todos (owner only) -----
app.post("/api/rooms/:id/todos", auth, roomAccess, ownerOnly, (req, res) => {
  const text = String(req.body.text || "").trim().slice(0, 120);
  if (!text) return fail(res, 400, "Task can't be empty.");
  const r = q.addTodo.run(req.room.id, text, Date.now());
  res.status(201).json({ id: Number(r.lastInsertRowid) });
});
app.patch("/api/rooms/:id/todos/:tid", auth, roomAccess, ownerOnly, (req, res) => {
  const t = q.todo.get(req.params.tid);
  if (!t || t.room_id !== req.room.id) return fail(res, 404, "Task not found.");
  q.setDone.run(req.body.done ? 1 : 0, t.id); res.json({ ok: true });
});
app.delete("/api/rooms/:id/todos/:tid", auth, roomAccess, ownerOnly, (req, res) => {
  const t = q.todo.get(req.params.tid);
  if (!t || t.room_id !== req.room.id) return fail(res, 404, "Task not found.");
  q.delTodo.run(t.id); res.json({ ok: true });
});

app.use("/api", (req, res) => fail(res, 404, "Not found."));
if (require.main === module) app.listen(PORT, () => console.log(`To Do :) Rooms running at http://localhost:${PORT}`));
module.exports = app;
