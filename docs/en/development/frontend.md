# Frontend development

[Home](../index.md) · [Русский](../../ru/development/frontend.md)

The client lives in `apps/frontend/`. It uses React and TypeScript with Vite. Users enter through the Telegram bot; the server verifies launch data and issues a session. The bot token is used only by the server.

## Run and build

Development requires Node.js 24.13.0 and the API running as described in the [backend instructions](backend.md).

From the repository root:

```sh
npm --prefix apps/frontend ci --ignore-scripts
npm --prefix apps/frontend run dev
```

Vite serves the interface at `http://127.0.0.1:5173` and proxies `/api` requests to `http://127.0.0.1:8000`. Employee login uses the application's HTTPS address in Telegram. Use the [installer](hosting.md) for hosting.

```sh
npm --prefix apps/frontend run build
```

The build checks TypeScript and creates files in `apps/frontend/dist/`. The timer updates locally; state refreshes after actions, returning to the application, and a date change.

## Directories

| Path within `apps/frontend/src/` | Contents |
| --- | --- |
| `app/` | Shell, navigation, and shared styles |
| `features/day/` | Working day, entries, and departure confirmation |
| `features/profile/` | First launch and preferences |
| `features/statistics/` | Personal statistics |
| `features/admin/` | Users, access, and individual accounting |
| `shared/api/` | Requests and API types |
| `shared/api/generated/` | Types from the server's OpenAPI |
| `shared/ui/` | Shared interface elements |
| `shared/lib/` | Time and Telegram integration |

## Contract and checks

Types are generated from the actual FastAPI code:

```sh
uv run --project apps/backend python scripts/export_api.py
npm --prefix apps/frontend run generate:api
```

Generated files are checked alongside API changes. They are not edited manually.

```sh
npm --prefix apps/frontend run check:format
npm --prefix apps/frontend test
npm --prefix apps/frontend run test:browser
```

Browser checks use an installed Google Chrome and test API responses. They cover first launch without automatic arrival, entering an earlier time, retrying after a connection failure, confirming a missed departure, and user management. Server checks perform these operations against real PostgreSQL. A narrow screen is checked at 320 pixels.
