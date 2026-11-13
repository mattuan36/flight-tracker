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
| M4b SerpAPI adapter, stops schema, budget guard, probe CLI | done |
| M5 live checks, auto-relax, USD daily demo data | done |
| M6 alerts and mailer | done |

## Requirements

- Python 3.11 or newer (developed on 3.14, deployed on PythonAnywhere's 3.13)
- No external services needed for the mock path; live checks and the probe use SerpAPI

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

**Password reset:** `/forgot-password` creates a single-use token (60 minutes)
and emails the link through the same mailer as price alerts. The response is the
same whether the address exists or delivery fails. An admin can still print a
link with `flask reset-link` as an emergency fallback. Invite emails remain
CLI-only in this milestone: `flask invite` prints a link to pass on.

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

# Live probe: prints one itinerary, writes only ApiUsage, never a PriceCheck
flask --app wsgi probe-prices --route PDX-OAK --max-stops 0
flask --app wsgi probe-prices --route PDX-MDW --depart 2027-01-08 --return 2027-01-15
flask --app wsgi probe-prices --route PDX-OAK --airline AS --airline WN
```

Web requests never call a fare provider: the dashboard only reads the database.
`check-prices` fetches and records quotes, then evaluates and sends alerts. Set
`PRICE_PROVIDER=serpapi` and a `SERPAPI_KEY` for live checks; `mock` remains the
free local default. The check service reserves one search for a one-way and two
for a return before calling the provider. It stops at the hard monthly cap and
at `CHECK_MAX_CALLS_PER_RUN`, and reports skipped trackers instead of exceeding
the budget. The same pipeline is exposed as `python -m jobs.check_prices` for
the hourly scheduled task; it retries failed alert emails even when no fare is
due.

The form defaults to non-stop, USD and a daily check. It also has a per-tracker
airline filter: choose one or more IATA codes, or leave the list empty to search
every carrier. All selected airlines go into one SerpAPI request, so an extra
airline does not cost another search. The winning carrier is read from the chosen
itinerary and shown on the dashboard and detail page; a mixed-carrier trip is
labelled as such.

Stops are a ceiling: `0` is non-stop, `1` is one stop or fewer, and blank is any
number of stops. A clean no-fare answer for `0` or `1` relaxes the tracker to any
number of stops, records the failed check, and shows the warning until the flight
is edited. There is no second provider call in the relaxing run; the next
scheduled check uses the relaxed setting. Provider failures and timeouts do not
relax anything.

Adding, editing, pausing, resuming and deleting all live under `/flights`. Every
page is scoped to the signed-in account, and another account's tracker answers
404 rather than 403 so ids cannot be probed. The old free-text `airline` column
is kept only for existing data; new trackers use `airline_filter` and
`last_airline`.

## Alerts and email

A successful check is evaluated immediately. Failed checks, paused trackers,
past-dated flights and budget-skipped flights never create an alert.

- **Below a target:** alert on the first crossing from above the target to
  at/below it, then only on a new low while the fare stays below target. If the
  fare goes back above the target, the next crossing is a fresh alert.
- **Any drop:** the first successful fare becomes the baseline and never alerts.
  Later emails need a genuinely lower fare than the previous alert.
- Failed delivery keeps the alert and retries it at the start of the next
  scheduled run, up to **3 attempts** total. The tracker's last-alert marker only
  moves after a successful send, and a pending retry blocks a duplicate alert
  from stacking behind it.

The mailer has two transports. `console` prints the full message to stdout and
is the safe local/test default. `smtp` uses a normal relay with STARTTLS (587) or
implicit TLS (465). Production refuses to start with `MAIL_BACKEND=console`, so a
real deployment cannot silently stop sending. Alert and reset links are built
from `BASE_URL`; when the app is mounted at `/flight/`, that setting must include
the prefix.

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
| `tracked_flights` | route, airline filter, last winning carrier, dates, stops ceiling, target price, last known price |
| `price_checks` | append-only observation history, including failures and the winning carrier |
| `alerts` | one row per email we decided to send, with delivery attempts, last error and an idempotency key |
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

Creates (or reuses) an admin account, four Southwest domestic trackers in USD,
~360 price checks over 45 days and sent alerts, all from a fixed random seed. One
tracker is auto-relaxed and one is paused, so both warning and next-check states
appear in the dashboard demo. `--reset` wipes that user's tracked flights first.
It refuses to run when `APP_ENV=prod` without `--force`.

## Configuration

`app/config.py` reads everything from the environment at request time and loads
`.env` if present. Three environments: `dev` (default), `test`, `prod`.
`prod` refuses to start without `SECRET_KEY` and `DATABASE_URL`, and refuses a
`localhost` `BASE_URL` — invite links are built from it.

| Key | Default | Notes |
|---|---|---|
| `APP_ENV` | `dev` | `production` is accepted as an alias for `prod` |
| `BASE_URL` | `http://localhost:5000` | Must be the public https URL in prod; include the mount path |
| `APPLICATION_ROOT` | `/` | URL prefix; production uses `/flight` |
| `SESSION_COOKIE_NAME` | `flight_session` | Keeps the session separate from the host app |
| `SESSION_COOKIE_PATH` | `APPLICATION_ROOT` | Blank derives the path from the mount |
| `REMEMBER_COOKIE_NAME` | `flight_remember` | Keeps "remember me" separate too |
| `REMEMBER_COOKIE_PATH` | `APPLICATION_ROOT` | Blank derives the path from the mount |
| `BACK_TO_PROJECTS_URL` | `/` | Footer link to the host site or projects index |
| `BACK_TO_PROJECTS_LABEL` | `All projects` | Footer link label |
| `DATABASE_URL` | blank → `instance/dev.sqlite3` | `mysql://` is rewritten to `mysql+pymysql://` |
| `SECRET_KEY` | dev-only fallback | Required in prod |
| `PRICE_PROVIDER` | `mock` | `mock` or `serpapi`; live checks need `SERPAPI_KEY` |
| `SERPAPI_KEY` | blank | From serpapi.com; never printed or used by a web request |
| `SERPAPI_GL` / `SERPAPI_HL` | `us` / `en` | Google Flights market and language |
| `SERPAPI_MONTHLY_CAP` | `250` | Hard-capped at 250 in code; no paid overage |
| `SERPAPI_TIMEOUT_SECONDS` | `20` | One retry on timeout/5xx, never on 4xx |
| `CHECK_TASK_MINUTE` | `0` | The hourly task's minute, used for next-check wording |
| `CHECK_MAX_CALLS_PER_RUN` | `20` | Stays below SerpAPI's 50/hour limit |
| `MAIL_BACKEND` | `console` | `console` locally; production requires `smtp` |
| `MAIL_FROM` | `ADMIN_EMAIL` or `flight-tracker@localhost` | Envelope sender |
| `SMTP_HOST` / `SMTP_PORT` | blank / `587` | Relay host and port; required with `smtp` |
| `SMTP_USER` / `SMTP_PASSWORD` | blank | Optional if the relay authenticates another way |
| `SMTP_USE_TLS` / `SMTP_USE_SSL` | `true` / `false` | STARTTLS or implicit TLS (465) |
| `SMTP_TIMEOUT_SECONDS` | `20` | Connection and send timeout |
| `ADMIN_EMAIL` | blank | Shown in "ask for a new invite" messages |
| `INVITE_TTL_DAYS` | `7` | Invite lifetime, printed by `flask invite` |
| `RESET_TTL_MINUTES` | `60` | Reset link lifetime |
| `LOGIN_MAX_ATTEMPTS` | `5` | Failures per email inside the window |
| `LOGIN_WINDOW_MINUTES` | `15` | Email throttle window |
| `LOGIN_IP_MAX_ATTEMPTS` | `20` | Failures per IP per hour |

## Deploying to PythonAnywhere (M7)

Not wired up yet. The shape it will take:

- virtualenv at `/home/<user>/.virtualenvs/flight-tracker`
- a `DispatcherMiddleware` mount at `/flight` inside the existing
  `web-projects` WSGI app, with `/flight/static/` mapped to this project's
  `app/static/`
- `APPLICATION_ROOT=/flight`, `BASE_URL=https://<user>.pythonanywhere.com/flight`,
  and the `flight_*` cookies scoped to `/flight`
- `git pull` + **Reload** in the Web tab
- `.env` in the project root, read by both the WSGI app and the scheduled task
  (the WSGI file's environment is *not* inherited by tasks)
- `MAIL_BACKEND=smtp` with a working relay in production; the app refuses to
  start with the console transport there
- scheduled task:
  `cd /home/<user>/flight-tracker && /home/<user>/.virtualenvs/flight-tracker/bin/python -m jobs.check_prices`
- `/flight/health` used as the post-deploy smoke check

## License

MIT. See `LICENSE`.
