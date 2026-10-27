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

`users` stores the user, their `member` or `admin` role, and active access status. `work_schedules` stores the local working-day end time with an effective date. `set_schedule` changes it from the current date in one transaction with `audit_log`; repeating the same value creates no redundant entry. Past days use the earlier rule.

`attendance` stores attendance intervals, and `breaks` stores explicitly recorded breaks. PostgreSQL prevents overlapping intervals for one user, overlapping breaks, and breaks outside attendance boundaries. An open interval never receives a fabricated departure time.

`get_summary` reads stored records and passes them to the calculation module. Employees can access their own accounting; active administrators can access employees' individual accounting. Disabled accounts cannot access records.

Time is stored as `timestamptz`; durations are calculated in UTC, while the arrival date and scheduled ending use the application's time zone. An interval belongs entirely to its arrival date, including departure after midnight. Breaks count toward total attendance and are summed separately for personal statistics. A current-day open interval gives a provisional total. For a previous open day, the total is unknown until departure is confirmed; the sum of closed intervals is returned separately. Departure preview uses the proposed ending without writing to the database.

`POST /api/v1/time/day` calculates supplied intervals against a working-day end time. The duration calculation `POST /api/v1/time/calculate`, `time_goals`, and `set_goal` retain the earlier data format; they do not configure a new working day. Both calculations include breaks in the total. Detailed [accounting rules](../product/time-accounting.md) contain examples.

HTTP exposes calculation of supplied intervals and health checks. Operations on stored personal data remain internal to the application and require a verified user.

## Attendance commands

Internal commands receive a verified user and server time in `now`. Arrival and departure also accept `occurred_at`, the actual event time when recorded later. It cannot be in the future; the audit log separately retains `recorded_at`.

| Operation | Purpose |
| --- | --- |
| `check_in` | Start attendance after saving the working-day end time |
| `start_break` | Start a break within open attendance |
| `end_break` | End the specified current break |
| `preview_checkout` | Obtain the total for confirmation and whether the break will end |
| `check_out` | After explicit confirmation, end attendance and its current break together |
| `reopen_attendance` | Undo the latest departure and restore the preceding state |
| `current_attendance` | Read current open attendance after reopening the application |
| `pending_departure` | Obtain a previous open day and whether its saved ending can be used |

Each modifying command receives a `request_id`. Its successful result is saved in `time_command_receipts` in the same transaction as the entries and `audit_log`. Retrying the same request returns its original result; its identifier cannot be reused for another operation or different parameters. Rejected commands leave no partial changes.

Commands on existing attendance include `expected_revision`. If another device has changed the record, the command is rejected with `stale_revision`: refresh the data and confirmation. Departure requires `confirmed`; the preview's `will_end_break` flag lets the caller explicitly explain that the break will also end.

Undoing departure also restores the break that departure ended automatically. Breaks ended independently beforehand remain closed. If a subsequent attendance interval already exists, undo is rejected to avoid an overlap. The audit log retains the state before and after each change.

A saved retry response does not replace current state: after reconnecting, the caller reads `current_attendance`. For example, retrying an old departure command after undo returns its original response but does not close attendance again.

Commands modify only the user's own attendance. An administrator's permission to read individual accounting does not let these commands change someone else's entries.

`pending_departure` never closes attendance automatically. Users confirm that day's saved end time or actual departure. The suggested time is unavailable if it precedes recorded events. Open attendance must be closed before a new arrival.

## Checks

```sh
python scripts/dev.py check
```

The command creates a separate `takt_test` database and runs Ruff, mypy, and pytest. Tests apply and roll back migrations; test tables are recreated. Checks do not use the working `takt` database.

Set `TAKT_TEST_DATABASE_URL` to test in another environment. The test database name must end in `_test`; otherwise checks stop. Coverage includes optional breaks without pausing total time, missed departure, actual event times, crossing midnight, end-time changes preserving past days, administrator access, PostgreSQL constraints, and concurrent write conflicts. GitHub Actions runs the same checks.
