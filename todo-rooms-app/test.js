// Smoke test: node test.js  (uses a temporary database)
process.env.DATA_DIR = require("os").tmpdir() + "/todo-test-" + Date.now();
const assert = require("assert");
const app = require("./server");
const srv = app.listen(0, async () => {
  const base = `http://localhost:${srv.address().port}/api`;
  const call = async (m, u, b, t) => { const r = await fetch(base + u, { method: m, headers: { "Content-Type": "application/json", ...(t ? { Authorization: "Bearer " + t } : {}) }, body: b ? JSON.stringify(b) : undefined }); return { s: r.status, j: await r.json() }; };
  try {
    const a = (await call("POST", "/signup", { username: "alice", password: "secret1" })).j.token;
    const b = (await call("POST", "/signup", { username: "bob", password: "secret2" })).j.token;
    assert.equal((await call("POST", "/signup", { username: "alice", password: "x12345" })).s, 409);
    assert.equal((await call("POST", "/login", { username: "alice", password: "bad" })).s, 401);
    const { id } = (await call("POST", "/rooms", { name: "Exam prep" }, a)).j;
    await call("POST", `/rooms/${id}/todos`, { text: "Read ch.1" }, a);
    await call("POST", `/rooms/${id}/todos`, { text: "Practice" }, a);
    const todos = (await call("GET", `/rooms/${id}`, null, a)).j.todos;
    await call("PATCH", `/rooms/${id}/todos/${todos[0].id}`, { done: true }, a);
    assert.equal((await call("GET", `/rooms/${id}`, null, b)).s, 403);               // not joined
    assert.equal((await call("POST", "/rooms/join", { id, name: "wrong" }, b)).s, 404); // wrong name
    assert.equal((await call("POST", "/rooms/join", { id, name: "exam PREP" }, b)).s, 200);
    const seen = (await call("GET", `/rooms/${id}`, null, b)).j;
    assert.equal(seen.todos.filter(t => t.done).length, 1);
    assert.equal(seen.isOwner, false);
    assert.equal((await call("PATCH", `/rooms/${id}/todos/${todos[1].id}`, { done: true }, b)).s, 403); // friend can't edit
    assert.equal((await call("DELETE", `/rooms/${id}`, null, b)).s, 403);
    assert.equal((await call("DELETE", `/rooms/${id}`, null, a)).s, 200);
    assert.equal((await call("GET", `/rooms/${id}`, null, a)).s, 404);
    console.log("All tests passed ✔");
  } catch (e) { console.error("FAILED", e); process.exitCode = 1; }
  srv.close(); process.exit(process.exitCode || 0);
});
