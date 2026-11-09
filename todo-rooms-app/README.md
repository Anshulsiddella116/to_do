# To Do :) Rooms

Full-stack app: **Node.js + Express + SQLite** backend, plain HTML/CSS/JS frontend.

## Run
```bash
npm install
npm start          # http://localhost:3000
npm test           # API smoke test
```
Requires Node 18+. Data is stored in `data/todo.db` (created automatically).

## Features
- Sign up / log in (bcrypt-hashed passwords, JWT sessions)
- Create rooms with an auto Room ID + Room name
- Progress bar; completed tasks are crossed out but stay visible
- Friends join with the exact Room ID **and** Room name, then see live progress (view only)
- Owner can add/tick/delete tasks and delete the room

## API (all JSON; `Authorization: Bearer <token>`)
| Method | Path | Notes |
|---|---|---|
| POST | /api/signup, /api/login | `{username,password}` |
| GET | /api/rooms/mine, /api/rooms/joined | |
| POST | /api/rooms | `{name}` |
| POST | /api/rooms/join | `{id,name}` both must match |
| GET | /api/rooms/:id | owner or joined members only |
| DELETE | /api/rooms/:id | owner only |
| POST | /api/rooms/:id/todos | owner only, `{text}` |
| PATCH/DELETE | /api/rooms/:id/todos/:tid | owner only, `{done}` |

## Config (env vars)
`PORT` (3000), `DATA_DIR` (./data), `JWT_SECRET` (auto-generated if unset — set it in production).

## Production notes
Serve behind HTTPS, set `JWT_SECRET`, and back up `data/`.
