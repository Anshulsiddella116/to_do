# TO DO :) — Vercel + login edition

This edition fixes the original deployment mismatch. The earlier ZIP used a standalone `http.server` process and a local SQLite file. Vercel instead loads the Flask `app` exported by `app.py` as a Python Function. It uses PostgreSQL for durable hosted data. No Node.js is needed to run this app locally or to deploy it through Vercel's Git import.

## Deploy on Vercel

1. Extract this ZIP and upload the CONTENTS of the folder to a Git repository, including the dotfiles (`.python-version`, `.gitignore`, `.env.example`). The repository root should contain `app.py`, `app.html`, `login.html`, `schema.sql`, `pyproject.toml`, `requirements.txt` and `vercel.json`. Do not upload the ZIP itself.
2. Import the repository at https://vercel.com/new. Vercel detects Flask automatically from `requirements.txt`/`pyproject.toml`; there is no framework preset, build command or output directory to set. Leave **Root Directory** at the repository root and do not add a `dist` or npm build command.
3. Add a PostgreSQL database. The easiest way is **Storage → Create Database → Neon** (Marketplace) and connect it to this project. That sets `DATABASE_URL` and `POSTGRES_URL` for you. If you use another provider, add its connection string yourself as **DATABASE_URL**. Keep it private; never commit it.
4. Deploy. Visit your domain: `/` redirects to `/login`. Select **Create account**, register, and enter your workspace. Tables are created automatically on the first database access, so the database user needs permission to create tables in the default schema.
5. *(Recommended)* Add **AUTH_SECRET** under Project Settings → Environment Variables (Production, and Preview if you use preview deployments), then redeploy:

   ```sh
   python -c "import secrets; print(secrets.token_hex(32))"
   ```

   AUTH_SECRET is optional: when it is missing, the app derives a stable session-signing key from your private database URL. Setting your own lets you rotate the database password without signing everyone out. Once you set AUTH_SECRET, keep it stable: changing it signs everyone out.

Tip: for the lowest latency, set the function region to match your database region (Project Settings → Functions → Function Region).

### If something goes wrong

- **404 at the root:** confirm the repository root (or the selected Root Directory) contains `app.py`, and that Vercel shows the Flask framework in the project's Build settings. Remove any old build/output/routing overrides from a previous project and redeploy.
- **The login page shows a setup message:** a database connection string is not set for that environment. Set `DATABASE_URL` (or connect a database integration), then redeploy.
- **Database error:** inspect Vercel's Function Logs; confirm the connection string, SSL settings (`sslmode=require`), provider availability, and table-creation permissions. Do not share database passwords publicly.
- **Health check:** `/api/health` returns `{"ok":true}` once the server can connect to its database.

## Run locally

Requires Python 3.12 or newer.

```sh
python -m venv .venv
```

Activate the environment:

Windows PowerShell:

```powershell
.\.venv\Scripts\Activate.ps1
```

Windows Command Prompt:

```bat
.venv\Scripts\activate.bat
```

macOS/Linux:

```sh
source .venv/bin/activate
```

Then:

```sh
python -m pip install -r requirements.txt
python app.py
```

Open http://127.0.0.1:3000. Without DATABASE_URL, local development creates `data/todo.sqlite` and a persistent signing key in `data/session.key`. Vercel never falls back to a local SQLite file. The `.env.example` file is a reference; environment variables must be set in your shell or the Vercel dashboard, not merely copied into that file.

## Accounts and permissions

- Sign up using a display name, email, and a password of at least 10 characters.
- Passwords use Werkzeug's salted scrypt hashes; plain passwords are not stored.
- Signed sessions use HTTP-only cookies, HTTPS-only on Vercel, with CSRF protection for writes.
- Login attempts are limited per email over a 15-minute window.
- A signed-in friend can join a room with its ID and exact name, and edit its tasks.
- Only the creator can delete a whole room, after exact-name confirmation.
- Rooms you create are listed across devices after login. Rooms you joined with an ID and name, and your chosen display name, are remembered per account in each browser. On phones, use the room selector under the page heading to switch rooms.
- Click **Log out** in the top bar to end the current session.

This is basic email/password authentication. It does not include email verification, password reset, or an administrator interface. Use a unique password and save it securely.

## Features retained

Shared rooms, tasks, filters, sorting, priority, progress bars, completed-task strike-through, task deletion, room deletion, invitations by room ID/name, and six-second shared refresh. The initial demo room is temporary sample data.

## Tests and verification

```sh
python -m unittest -v test_app
```

The tests cover Flask routing, authentication, password hashing, CSRF rejection, rate limiting (and cleanup of stale attempts), room sharing, creator-only room deletion, task cleanup, database-URL cleanup, session-secret selection, and missing Vercel configuration. By default they use an isolated local SQLite database. To run the same suite against a real PostgreSQL database (this resets the `todo_` tables in it, so use a scratch database):

```sh
TEST_DATABASE_URL="postgresql://user:pass@host/scratch_db" python -m unittest -v test_app
```

Before packaging, this suite was run against both SQLite and PostgreSQL 16, and the full browser flow (sign up, create a room, add and complete tasks, a second user joining and seeing live updates, owner-only deletion, log out and in, mobile layout) was exercised in headless Chromium against PostgreSQL with Vercel's production settings. Deployment into your own Vercel account and your hosted database provider could not be exercised from here, so check `/api/health` after your first deploy.

Official references:
- https://vercel.com/docs/frameworks/backend/flask
- https://vercel.com/docs/functions/runtimes/python
- https://vercel.com/kb/guide/is-sqlite-supported-in-vercel

No existing hosted or local room data is included or migrated by this package. It uses new `todo_`-prefixed database tables.
