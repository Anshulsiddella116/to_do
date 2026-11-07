# TO DO :) — Vercel + login edition

This edition fixes the original deployment mismatch. The earlier ZIP used a standalone `http.server` process and a local SQLite file. Vercel instead loads the Flask `app` exported by `app.py` as a Python Function. It uses PostgreSQL for durable hosted data. No Node.js is needed to run this app locally or to deploy it through Vercel's Git import.

## Deploy on Vercel

1. Extract this ZIP. Upload the CONTENTS of this folder to a Git repository, including the dotfiles. Your repository root should contain `app.py`, `app.html`, `login.html`, `schema.sql`, `pyproject.toml`, `requirements.txt`, and `vercel.json`. Do not upload the ZIP itself.
2. Import the repository into Vercel. Select the **Flask** framework preset. Set **Root Directory** to the folder containing `app.py` (repository root if you followed step 1). Remove old build/output/start overrides from the previous project. Leave Build Command and Output Directory at the Flask defaults; do not use `dist` or an npm build command.
3. Connect a PostgreSQL database, such as Neon through Vercel's Storage/Marketplace. Add its connection string as **DATABASE_URL** in Project Settings → Environment Variables. A pooled connection string with `sslmode=require` is recommended. `POSTGRES_URL` is also supported. Keep the connection string private; do not put it in browser code or commit it.
4. Add **AUTH_SECRET** as another environment variable. Generate a value locally with:

   ```sh
   python -c "import secrets; print(secrets.token_hex(32))"
   ```

   Use `py` or `python3` instead if needed. Set both variables for Production (and Preview if you want preview deployments to work). Keep AUTH_SECRET stable across redeployments. Changing it signs everyone out.
5. Deploy or redeploy after saving the environment variables. Visit the domain: `/` redirects to `/login`. Select **Create account**, register, and enter your workspace. Tables are created automatically on first database access, so the database user needs permission to create tables in the default schema.

### If something goes wrong

- **404 at the root:** verify the selected Root Directory contains `app.py` and Vercel detected Flask. Remove any previous project routing/build overrides and redeploy this entire package.
- **Login page shows DATABASE_URL or AUTH_SECRET setup instructions:** set that variable for the deployment's environment, then redeploy.
- **Database error:** inspect Vercel's Function Logs; confirm the connection string, SSL settings, provider availability, and table-creation permissions. Do not share database passwords publicly.
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
- Rooms you create are listed across devices after login. Recently joined room details and your chosen display name are saved per account in each browser.
- Click **Log out** in the top bar to end the current session.

This is basic email/password authentication. It does not include email verification, password reset, or an administrator interface. Use a unique password and save it securely.

## Features retained

Shared rooms, tasks, filters, sorting, priority, progress bars, completed-task strike-through, task deletion, room deletion, invitations by room ID/name, and six-second shared refresh. The initial demo room is temporary sample data.

## Tests and verification

```sh
python -m unittest -v test_app
```

The tests cover Flask routing, authentication, password hashing, CSRF rejection, rate limiting, room sharing, creator-only room deletion, task cleanup, and missing Vercel configuration. They run against an isolated local SQLite database. PostgreSQL connectivity and deployment into your Vercel account must be verified after you set the connection string; those were not available during packaging.

Official references:
- https://vercel.com/docs/frameworks/backend/flask
- https://vercel.com/docs/functions/runtimes/python
- https://vercel.com/kb/guide/is-sqlite-supported-in-vercel

No existing hosted or local room data is included or migrated by this package. It uses new `todo_`-prefixed database tables.
