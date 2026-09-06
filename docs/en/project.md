# Takt architecture

[Home](index.md) · [Русский](../ru/project.md)

This document describes the selected stack and division of responsibilities in Takt. Personal time accounting based on employee entries is its foundation. Communication and external integrations are outside the scope described here.

## Time accounting

Required time, entries, and calculated results are distinct data. Required time defines a target duration; entries describe events; calculations apply rules to those events. Class schedules and teaching load do not replace attendance requirements.

| Term | Meaning |
| --- | --- |
| Required time | Attendance duration to accumulate over a defined period |
| Attendance interval | The time between arrival and departure; an open interval has no departure entry yet |
| Excluded break | Time within an attendance interval that does not count under the applicable rules |
| Credited time | Duration counted according to entries and rules |
| Remaining time | Time still needed to meet the requirement; zero once the requirement is met |
| Estimated completion time | A forecast of when the requirement will be met, under explicit assumptions about continued attendance |

### Calculation example

An employee arrives at 08:30. The requirement is 6 ordinary hours of 60 minutes each. By 13:10, an excluded break of 30 minutes has already taken place. All entries belong to one day in one time zone; there are no other constraints or subsequent breaks in this example.

| Calculation | Result |
| --- | --- |
| Time since arrival: 13:10 − 08:30 | 4 h 40 min |
| Credited time: 4 h 40 min − 30 min | 4 h 10 min |
| Remaining time: 6 h − 4 h 10 min | 1 h 50 min |
| Completion with continuous attendance: 13:10 + 1 h 50 min | 15:00 |

This illustrates the arithmetic, not a college timetable. Another excluded break or an entry correction will change the forecast.

### Calculation requirements

Overlapping intervals must not count time twice, and repeating a request must not create a duplicate entry. Concurrent corrections must preserve record consistency. Results for an open day must identify the time at which the calculation was made; meeting the required time does not itself mean that the employee has left.

Event time differs from recording time: an arrival at 08:30 can be entered later. The time zone and day boundary must be explicit, including for intervals crossing midnight. Recalculation after a change to required time must explain which records and rules were used.

The source of the requirement, authority to change it, accounting period, and carry-over of hours determine how rules apply. Eligible breaks, work outside the college, and multiple intervals per day determine credited time. Ordinary and academic hours cannot be mixed without an agreed conversion. These rules, rounding, and treatment of time beyond the requirement need agreement. The correction process, approval requirements, and change history have not been defined either.

## Components and dependencies

One repository brings together the client, server, and documentation. The server is organised as one application with internal modules: the known workflow does not require independent services, and changes to calculations and the API are easier to review together in one pull request.

| Component | Responsibility |
| --- | --- |
| Telegram Mini App | Display state, accept employee actions, and call the API |
| Python server | Check access, save entries and rules, perform calculations, and return an explainable result |
| PostgreSQL | Store source records, user data, and applicable rules |
| Telegram integration | Validate Telegram input and connect the verified identity to access checks |

The server owns calculations so that reopening the Mini App restores state from saved data. The local timer displays a forecast; closing the application does not stop time accounting. Updating numbers on screen does not require a server message every second. Statistics read accounting data and use the same rules.

Responsibilities within the server follow subject areas:

| Area | Contents and allowed dependencies |
| --- | --- |
| Identity and access | Employee identity and operation permissions; accepts verified Telegram data and does not calculate time |
| Time rules | Required time and eligibility rules; independent of HTTP and Telegram |
| Accounting | Entries, intervals, and calculations; uses time rules, while write workflows call access checks and storage |
| Telegram | Official API adapter; passes verified identity to the access area and contains no separate copy of accounting rules |

HTTP handlers validate the request shape and call an application workflow. The workflow coordinates access, reads, calculation, and writes. Time arithmetic remains ordinary functions that can be tested without an HTTP server, Telegram, or a database. Code is placed according to responsibility; generic `utils`, `core`, or model directories must not conceal subject boundaries.

### Access through Telegram

The server must verify the authenticity of `initData` using the official algorithm and check the freshness of `auth_date`. Values in `initDataUnsafe` are not a trusted source for authorisation. See [Mini App data validation](https://core.telegram.org/bots/webapps#validating-data-received-via-the-mini-app).

A verified Telegram user is not necessarily a college employee and does not gain access to other people's records through that fact. College membership verification, the session model, and individual record visibility require separate decisions. Supporting one college or several affects data access boundaries.

## Selected stack

| Area | Tools | Purpose |
| --- | --- | --- |
| Server | Python, FastAPI | HTTP handlers, dependencies, and application workflow calls |
| Contract | Pydantic 2, OpenAPI | Data shape validation, request and response schemas, API description |
| Settings | pydantic-settings | Typed settings from the environment |
| Storage | PostgreSQL | Persistent accounting and user data |
| Database access | SQLAlchemy 2.0, Psycopg 3 | Queries, storage models, and transactions |
| Migrations | Alembic | Database schema changes |
| Client | React, TypeScript, Vite | Interface and application build for Telegram WebView |
| API client | Hey API: `@hey-api/openapi-ts` | TypeScript client and type generation from OpenAPI |
| Server data in the interface | TanStack Query | Data fetching, caching, and updates |
| Styles | CSS | Interface styling |
| Python environment | uv | Dependency management and locking |
| Server checks | pytest, HTTPX, Ruff, mypy | Behaviour and HTTP API tests, formatting, static analysis, and type checking |

FastAPI handles requests, REST defines the approach to organising the HTTP API, and OpenAPI describes the contract. They serve different purposes. The relationship between operations, schemas, and OpenAPI is described in the [FastAPI documentation](https://fastapi.tiangolo.com/features/).

Database access uses SQLAlchemy `AsyncSession` with asynchronous Psycopg 3. The application workflow defines the transaction boundary; one session is not shared between concurrent tasks. Asynchrony here concerns input and output and does not promise faster calculations. See the [Psycopg dialect](https://docs.sqlalchemy.org/en/20/dialects/postgresql.html#module-sqlalchemy.dialects.postgresql.psycopg) and [AsyncSession concurrency rules](https://docs.sqlalchemy.org/en/20/orm/extensions/asyncio.html#using-asyncsession-with-concurrent-tasks).

The client uses the official Telegram WebApp API. Aiogram 3 is selected for bot command handling when such a task is within the agreed scope. A bot library does not replace `initData` validation; delayed notifications require a separate mechanism for persistent jobs and retries. See [Telegram Mini Apps](https://core.telegram.org/bots/webapps) and [aiogram](https://docs.aiogram.dev/en/latest/).

Exact Python, Node.js, PostgreSQL, and library versions are pinned together after compatibility checks. Dependencies and their updates must be reproducible.

### API contract

FastAPI operations and Pydantic schemas are the contract source. They produce an OpenAPI export, which generates TypeScript types and the Hey API client. Operations must have stable `operationId` values, and generation must be reproducible and verifiable. Generated files are not edited manually. Contract changes include a client update and compatibility checks. See [FastAPI client generation](https://fastapi.tiangolo.com/advanced/generate-clients/) and [Hey API](https://heyapi.dev/docs/openapi/typescript/get-started).

TanStack Query manages loading and freshness of server data, not accounting rules. The wiki explains domain rules and architecture; no separate manual copy of the API specification is maintained. The library's purpose is described in the [TanStack Query overview](https://tanstack.com/query/latest/docs/framework/react/overview).

## Code layout

The directory layout separates application areas with different dependencies and verification needs.

| Path | Purpose |
| --- | --- |
| `backend/src/takt/` | Python application package organised by responsibility |
| `backend/tests/` | Checks for calculations, workflows, access, and the HTTP API |
| `backend/migrations/` | Alembic migrations, separate from application code |
| `frontend/src/` | Interface code and Telegram integration |
| `frontend/src/api/generated/` | Generated client; handwritten API integration code belongs outside this directory |
| `frontend/tests/` | Checks for the interface and its interaction with the server |
| `docs/ru/`, `docs/en/` | Home page and project overview in both languages |

Tests belong beside the corresponding application area. A path's purpose determines which changes belong there.

## Interface

The interface must have a distinct Takt identity, a clear hierarchy of time and actions, deliberate information density, and convenient entry correction. User workflows determine screen composition.

Composition must account for the day's states: not started, accounting in progress, on a break, requirement met, entry needs correction, and server unavailable. Data presentation must consider Telegram's limited width, the on-screen keyboard, theme, accessibility, and reopening the Mini App. Visual styling is undefined; the earlier card mockup is not an accepted reference.

## Documentation maintenance

Documentation lives alongside code so that a behaviour, API, or settings change and its explanation can be reviewed in one pull request. A separate GitHub Wiki has [its own Git repository](https://docs.github.com/en/communities/documenting-your-project-with-wikis/adding-or-editing-wiki-pages); a parallel editable copy of these materials is not maintained there.

The same relative paths are used under `docs/ru/` and `docs/en/`. File names are English, in lowercase-kebab-case; internal links are relative and point to existing pages in the selected language. A change in meaning updates both versions: requirements, limitations, numbers, examples, and decision status must match. Identifiers and API names are not translated. Terminology remains aligned: “интервал присутствия / attendance interval”, “учтённое время / credited time”.

Each rule has one primary place of description. The overview explains the system and links to details without duplicating them.

Significant architectural decisions use short ADRs (architecture decision records): context, decision, consequences, and status — Proposed, Accepted, Rejected, or Superseded. Accepting a decision does not mean its implementation is complete. A superseded record retains its context and links to its replacement.

Technical text explains component behaviour, reasons for decisions, and material conditions. Examples include inputs, units, and results; claims about technologies link to their documentation. English headings use sentence case. Before merging, review translations, calculations, links, and Markdown rendering. Setup instructions describe verified commands.

## Documentation checks

[GitHub Actions](../../.github/workflows/documentation.yml) runs four checks: Markdown formatting, UTF-8, internal links, and Russian/English documentation consistency. The translation check compares page sets, numbers, technical identifiers, sources, and language links. Translation meaning is reviewed by reading the text.

Local check tools use Node.js 24.13.0. Run these commands from the repository root:

```sh
npm --prefix .github/checks ci --ignore-scripts
npm --prefix .github/checks run check:markdown
npm --prefix .github/checks run check:encoding
npm --prefix .github/checks run check:links
npm --prefix .github/checks run check:translations
npm --prefix .github/checks test
```
