# TO DO :) — Python edition

Python 3.9 or newer is required. No Node.js, npm, pip packages, or database installation is needed.

## Start on Windows

1. Install Python from https://www.python.org/downloads/ (enable “Add Python to PATH”).
2. Extract the ZIP. Open the extracted `together-todo-python` folder.
3. Double-click `start-windows.bat`, or open a terminal in that folder and run:

```bat
py server.py
```

If `py` is unavailable, use `python server.py`.

## Start on macOS / Linux

Open a terminal in the extracted folder and run:

```sh
python3 server.py
```

## Open the application

Visit **http://127.0.0.1:3000** in your browser. Keep the terminal running; press Ctrl+C to stop. If port 3000 is busy, start with `python server.py --port 3001` and open http://127.0.0.1:3001 instead (use `py` or `python3` as appropriate).

## Included features

- Rooms protected by a room ID and exact room name.
- Add, complete, filter, sort, and delete tasks.
- Completed tasks remain visible and crossed out.
- Shared progress bars and per-person progress.
- Delete an entire room and its tasks with exact-name confirmation.
- Shared changes refresh about every six seconds.
- Responsive desktop and mobile interface.

The demo room is temporary. Create a real room to save tasks.

## Saved data

Rooms and tasks are stored in `data/todo.sqlite`, created automatically. They persist after restarting the server. Back up the `data` folder while the server is stopped. Display names and saved room credentials are stored in your browser. This ZIP contains no data from the hosted app.

## Share with friends on the same network

Start with:

```sh
python server.py --host 0.0.0.0
```

Friends open `http://YOUR-COMPUTER-LAN-IP:3000` and join using the room ID and name. Use `py` or `python3` instead of `python` if needed. Your firewall may need to allow port 3000. Room ID and name grant edit and deletion access to the room; share them only with the intended group. This standalone edition has no separate account login. Use localhost or a trusted network; Internet hosting needs HTTPS and access controls.

Clipboard copying may require HTTPS; manual-copy fields are provided as a fallback. The browser uses JavaScript for the interface; the server runs entirely in Python. The interface remains usable if Google Fonts is unavailable.

## Files and tests

- `server.py` — Python HTTP server and SQLite API.
- `app.html` — interface and browser behavior.
- `schema.sql` — database schema.
- `test_app.py` — endpoint, persistence, and room deletion tests.

Run tests with `python -m unittest -v test_app` (or `py` / `python3`). Tests use temporary databases, not your saved rooms.
