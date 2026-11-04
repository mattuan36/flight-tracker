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
| M1 models + migrations | next |
| M2 invite-only auth + admin CLI | planned |
| M3 trackers + dashboard (mock prices) | planned |
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

flask --app wsgi run --debug
```

Open http://localhost:5000. `/health` returns JSON and checks the database.

`flask` finds the app through `wsgi.py`, so:

```bash
flask --app wsgi config        # resolved settings, secrets masked
flask --app wsgi health        # database check, non-zero exit on failure
flask --app wsgi routes
```

Set `FLASK_APP=wsgi` in your shell if you would rather not pass `--app`.

## Tests and linting

```bash
pytest
ruff check .
ruff format --check .
```

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
