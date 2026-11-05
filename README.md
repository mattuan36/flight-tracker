# Flight Tracker

A small, invite-only flight price tracker. Add a flight, set the price you would
actually pay, and get an email when the price drops below it.

Hosted on PythonAnywhere (Developer plan: one web app, hourly scheduled tasks,
MySQL). The web app never calls a fare API during a request — an hourly task
does that and writes the results to the database.

## Status

| Milestone | State |
|---|---|
| M0 scaffold, config, CLI skeleton, health check | done |
| M1 models, Alembic migration, demo seeder | done |
| M2 invite-only auth + admin CLI | done |
| M3 trackers, dashboard, mock price checks | done |
| M6 price checker + alerts | planned |

## Requirements

- Python 3.11 or newer (developed on 3.14, deployed on PythonAnywhere's 3.13)
- No external services needed until M6

## Setup

```bash
python -m venv .venv
.venv\Scripts\activate          # Windows
# source .venv/bin/activate     # macOS / Linux
pip install -r requirements-dev.txt

copy .env.example .env          # Windows
# cp .env.example .env          # macOS / Linux

alembic upgrade head
flask --app wsgi seed-demo --email you@example.com --password "pick-something-long"
flask --app wsgi run --debug
```

Open http://localhost:5000. `/health` returns JSON and checks the database.

There is no signup page: `flask --app wsgi invite friend@example.com` prints a
link to paste to them.

`flask` finds the app through `wsgi.py`, so:

```bash
flask --app wsgi config        # resolved settings, secrets masked
flask --app wsgi health        # database check, non-zero exit on failure
flask --app wsgi routes
flask --app wsgi seed-demo --help
```

Set `FLASK_APP=wsgi` in your shell if you would rather not pass `--app`.

## Accounts and sign-in

There is no registration route. The only ways an account appears are an invite
link and `seed-demo`.

```bash
flask --app wsgi invite friend@example.com          # prints a one-time link
flask --app wsgi invites [--all]                    # pending by default
flask --app wsgi reissue-invite friend@example.com  # new link, kills the old
flask --app wsgi revoke-invite friend@example.com
flask --app wsgi users
flask --app wsgi disable-user friend@example.com [--purge]
flask --app wsgi enable-user friend@example.com
flask --app wsgi reset-link friend@example.com      # prints a reset link
```

Invite and reset tokens are 32 random bytes, URL-safe, and stored only as a
SHA-256 hash — the database never holds a working link. Invites expire after
`INVITE_TTL_DAYS` (7) and work exactly once; opening one while signed in as a
different account asks before switching. The link is always built from
`BASE_URL`, never from the request host.

**Password policy:** at least 12 characters, not one of the 10,000 most common
passwords (bundled from SecLists), and must not contain your email address or
display name. No composition rules.

**Sign-in:** failures are counted in the database — 5 per email in 15 minutes,
20 per IP per hour — so throttling works across PythonAnywhere's workers.
Sessions last 30 days and carry `session_version`; bumping it (disable, password
reset) ends every device on its next request, including the remember cookie.

**Password reset:** `flask reset-link` prints the link and the admin sends it by
hand. `/forgot-password` already creates the same single-use token (60 minutes);
M6 replaces the hand-sending with the mailer. Until then the page says so.

## Tracking flights

The dashboard at `/` lists your tracked flights: current fare, the gap to your
target, the lowest fare seen and a sparkline of recent checks. Each row opens a
detail page with the full chart (the dashed line is your target), the recent
checks and any alerts that were sent.

```bash
flask --app wsgi check-prices                 # only flights whose interval is due
flask --app wsgi check-prices --all           # ignore the interval
flask --app wsgi check-prices --email you@example.com
flask --app wsgi check-prices --flight 7      # one tracker, by id
```

Web requests never call a fare provider: the dashboard only reads the database.
`check-prices` is the piece that fetches and records quotes; M6 moves the same
service into the hourly scheduled task and adds the email. Until the vendor is
chosen (M4b), `PRICE_PROVIDER=mock` returns a deliberately fake, deterministic
random walk.

Adding, editing, pausing, resuming and deleting all live under `/flights`. Every
page is scoped to the signed-in account, and another account's tracker answers
404 rather than 403 so ids cannot be probed. The airline is an optional label
shown after the route; fares stay keyed on the airports and dates.

## Tests and linting

```bash
pytest
ruff check .
ruff format --check .
```

The suite runs the real Alembic migration against a temporary SQLite file, so a
migration that does not match the models fails CI rather than production.

## Database

SQLite locally, MySQL on PythonAnywhere. Alembic is the only way the schema
changes — never `db.create_all()` outside tests.

```bash
alembic upgrade head                            # apply migrations
alembic revision --autogenerate -m "add thing"  # write a new one
alembic check                                   # models vs migrations; non-zero if they differ
alembic downgrade base                          # drop everything
```

| Table | Holds |
|---|---|
| `users` | accounts, role, password hash, `session_version` for logging out every device |
| `invites` | one-time signup tokens (stored as a hash) |
| `tracked_flights` | route, airline label, dates, target price, last known price |
| `price_checks` | append-only observation history, including failures |
| `alerts` | one row per email we decided to send, with an idempotency key |
| `api_usage` | per-provider daily call counter for the budget guard |
| `password_resets` | single-use reset tokens (hashed), 60-minute expiry |
| `login_attempts` | sign-in audit; backs the throttling windows |

Conventions: money in integer cents, timestamps timezone-aware in Python and
stored as naive UTC (see `UTCDateTime`), deletes cascade from `users`.

`invites.pending_key` is a stored generated column that equals the email while
an invite is still open and `NULL` otherwise, with a unique index. That is how
"one pending invite per email" works on MySQL, which has no partial indexes.
MariaDB supports indexing stored generated columns; the first `alembic upgrade`
on PythonAnywhere is the moment to confirm it.

### Demo data

```bash
flask --app wsgi seed-demo --email you@example.com --password "..." [--reset]
```

Creates (or reuses) an admin account, three tracked flights with airlines, ~270
price checks over 45 days and sent alerts, all from a fixed random seed.
`--reset` wipes that user's tracked flights first. It refuses to run when
`APP_ENV=prod` without `--force`.

## Configuration

`app/config.py` reads everything from the environment at request time and loads
`.env` if present. Three environments: `dev` (default), `test`, `prod`.
`prod` refuses to start without `SECRET_KEY` and `DATABASE_URL`, and refuses a
`localhost` `BASE_URL` — invite links are built from it.

| Key | Default | Notes |
|---|---|---|
| `APP_ENV` | `dev` | `production` is accepted as an alias for `prod` |
| `BASE_URL` | `http://localhost:5000` | Must be the public https URL in prod |
| `DATABASE_URL` | blank → `instance/dev.sqlite3` | `mysql://` is rewritten to `mysql+pymysql://` |
| `SECRET_KEY` | dev-only fallback | Required in prod |
| `PRICE_PROVIDER` | `mock` | Real vendor wired in after the M4b spike |
| `ADMIN_EMAIL` | blank | Shown in "ask for a new invite" messages |
| `INVITE_TTL_DAYS` | `7` | Invite lifetime, printed by `flask invite` |
| `RESET_TTL_MINUTES` | `60` | Reset link lifetime |
| `LOGIN_MAX_ATTEMPTS` | `5` | Failures per email inside the window |
| `LOGIN_WINDOW_MINUTES` | `15` | Email throttle window |
| `LOGIN_IP_MAX_ATTEMPTS` | `20` | Failures per IP per hour |

## Deploying to PythonAnywhere (M7)

Not wired up yet. The shape it will take:

- virtualenv at `/home/<user>/.virtualenvs/flight-tracker`
- `git pull` + **Reload** in the Web tab
- `.env` in the project root, read by both the WSGI app and the scheduled task
  (the WSGI file's environment is *not* inherited by tasks)
- scheduled task:
  `/home/<user>/.virtualenvs/flight-tracker/bin/python -m jobs.check_prices`
- `/health` used as the post-deploy smoke check

## License

MIT. See `LICENSE`.
