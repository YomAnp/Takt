# Takt project documentation

[Русский](../ru/index.md)

Takt is a Telegram Mini App for personal time accounting by college employees. Its purpose is to help employees understand how much time has been credited, how much remains, and when the required time will be completed.

## Main workflow

An employee sets their required attendance time and records their arrival. Entries and applicable rules determine credited time, remaining time, and estimated completion time. The workflow includes finishing the day, correcting entries, and reviewing history and statistics based on personal records.

Personal time accounting is not equivalent to an official timesheet or proof of physical presence. Access to colleagues' records and administrative authority require separate definition.

## Project structure

The selected stack is React, TypeScript, and Vite for the client, Python and FastAPI for the server, and PostgreSQL for storage. The client and server communicate through a REST API using HTTP and JSON, with an OpenAPI contract.

| Directory | Purpose |
| --- | --- |
| `backend/` | Server: access, time rules, entries, and calculations |
| `frontend/` | Telegram Mini App interface |
| `docs/ru/` | Russian documentation |
| `docs/en/` | English documentation |

The [project overview](project.md) explains terminology, a calculation example, the selected stack, and component boundaries.

## Documentation

The Russian and English versions contain the same information. The language link opens the corresponding page; changes update both versions in the same pull request.

Wiki sources live in `docs/`; no separate GitHub Wiki or documentation site has been published.
