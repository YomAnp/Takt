# Backend development

[Home](../index.md) · [Русский](../../ru/development/backend.md)

The server lives in `apps/backend/`. Development requires Python 3.12.12, uv 0.10.2, and Docker with Compose running. PostgreSQL 17 runs in a separate container; its data persists in the `postgres-data` volume.

## Start the server

From the repository root:

```sh
python scripts/dev.py start
```

The command starts the database, installs dependencies from `apps/backend/uv.lock`, applies Alembic migrations, and starts the API with source reloading. The API is available at `http://127.0.0.1:8000`; OpenAPI and the request form are at `http://127.0.0.1:8000/docs`. Stop the server with Ctrl+C; stop the container with `docker compose stop db`.

Local database parameters are shown in `env.example`. Set the `TAKT_DATABASE_URL` environment variable for another connection; `TAKT_TIME_ZONE` selects the time zone and defaults to `Europe/Moscow`. The `env.example` file is an example and is not loaded automatically. Container credentials are for local development; the database port is exposed only on `127.0.0.1`.

## Data and calculations

`users` stores the user, their `member` or `admin` role, and active access status. Required time is stored in `time_goals` with an effective date: a new value applies today and onward, while earlier dates use the previous rule. Repeating the same value creates no entry in `audit_log`.

`attendance` stores attendance intervals, and `breaks` stores explicitly recorded breaks. PostgreSQL prevents overlapping intervals for one user, overlapping breaks, and breaks outside attendance boundaries. An open interval never receives a fabricated departure time.

`get_summary` reads stored records and passes them to the calculation module. Employees can access their own accounting; active administrators can access employees' individual accounting. Disabled accounts cannot access records. `set_goal` changes the user's own required time in one transaction with the audit entry.

Time is stored as `timestamptz`; calculation uses actual elapsed time in UTC and calendar-day boundaries in the selected time zone. Break seconds are excluded. No completion forecast is given during an open break. When the requirement is met, the calculation returns the time it was reached; closed intervals stop accumulating time.

HTTP exposes calculation of supplied intervals and health checks. Operations on stored personal data remain internal to the application and require a verified user.

## Checks

```sh
python scripts/dev.py check
```

The command creates a separate `takt_test` database and runs Ruff, mypy, and pytest. Tests apply and roll back migrations; test tables are recreated. Checks do not use the working `takt` database.

Set `TAKT_TEST_DATABASE_URL` to test in another environment. The test database name must end in `_test`; otherwise checks stop. Coverage includes calculation and paused time, goal changes preserving past days, administrator access, PostgreSQL constraints, and concurrent write conflicts. GitHub Actions runs the same checks.
