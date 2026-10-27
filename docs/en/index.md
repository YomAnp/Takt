# Takt project documentation

[Русский](../ru/index.md)

Takt is a Telegram Mini App for personal time accounting for MGRI employees. It helps users see total attendance, their selected working-day end time, and time beyond that point.

## Main workflow

An employee saves a working-day end time and records arrival and departure. Delayed entries use the actual event time. Total attendance includes breaks, which users can record separately for themselves. Calculation rules, missed entries, and first launch are described in the [accounting workflows](product/time-accounting.md).

Personal accounting does not replace an official timesheet or prove physical presence. Employees see their own entries; administrators manage access and view individual accounting.

## Project structure

The selected stack is React, TypeScript, and Vite for the client, Python and FastAPI for the server, and PostgreSQL for storage. The client and server communicate through a REST API using HTTP and JSON, with an OpenAPI contract.

| Directory | Purpose |
| --- | --- |
| `apps/backend/` | Server: access, time rules, entries, and calculations |
| `apps/frontend/` | Telegram Mini App interface |
| `docs/ru/` | Russian documentation |
| `docs/en/` | English documentation |

The [project overview](project.md) explains the selected stack and component boundaries.

[Backend development](development/backend.md): PostgreSQL and API startup, storage, and checks.

## Documentation

The Russian and English versions contain the same information. The language link opens the corresponding page; changes update both versions in the same pull request.

Wiki sources live in `docs/`; no separate GitHub Wiki or documentation site has been published.
