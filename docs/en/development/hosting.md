# Server installation

[Home](../index.md) · [Русский](../../ru/development/hosting.md)

`scripts/host.py` builds and runs Takt from an ordinary repository clone. The domain, bot, and owner are supplied during setup. The server needs Python 3.10 or newer, Docker Engine, and the Compose plugin. Docker instructions cover [Ubuntu](https://docs.docker.com/engine/install/ubuntu/) and [Debian](https://docs.docker.com/engine/install/debian/).

## Preparation

Create a bot through [BotFather](https://t.me/BotFather) and obtain its token. The domain must point to the server, with ports 80 and 443 reachable. Caddy obtains and renews an HTTPS certificate under these conditions, as described in its [documentation](https://caddyserver.com/docs/automatic-https).

From the clone's root:

```sh
python3 scripts/host.py setup
```

The installer asks for the domain, hidden token, and the owner's `@username`. It verifies the bot, saves parameters in `.env.host`, generates a random PostgreSQL password, builds the client and server, applies migrations, and starts containers. After checking application availability, it configures the bot name, avatar, description, commands, and Mini App button.

Settings and the token are not passed into the client build. The `.env.host` file is excluded from Git and accessible only to its owner on Linux. Reconfiguration retains the existing database password.

## Owner and administrators

After installation, the owner opens the Mini App from their Telegram account. The server matches the signed `username` against the setting and binds that Telegram ID once. Renaming the account does not transfer rights to another person. Changing the configured username does not transfer an existing ownership binding either.

| Role | Permissions |
| --- | --- |
| Member | Own entries, preferences, and statistics |
| Administrator | User list, individual accounting, and member access management |
| Owner | The same operations, appointing and removing administrators, and managing their access |

Management is available under “Users” in application settings. Users cannot block themselves or the owner. Blocking revokes sessions; restoring access requires a new login.

## Telegram

The installer sets the name “Такт”, full and short descriptions, avatar, commands, and launch button. Setup and updates apply this profile. The chat button opens the application's HTTPS address. The separate main Mini App shortcut on the profile is configured through BotFather; see [Mini App settings](https://core.telegram.org/bots/webapps).

The logo source is `apps/frontend/public/brand/logo.svg`; the avatar is `apps/frontend/public/brand/avatar.jpg`. Repeated runs retain the current avatar when the file is unchanged. If it was replaced or removed in Telegram, the installer restores the project image.

The bot responds to `/start` and `/help` in private chats. It uses one long-polling process. The installer does not delete an existing webhook: Takt needs a dedicated bot or an explicitly released connection.

## Updates and maintenance

For an existing Takt installation, run from the project directory:

```sh
git pull --ff-only
python3 scripts/host.py up
```

Settings from `.env.host`, the database password, users, and entries are retained. Images are built before stopping the application. The API and bot then pause, a database backup is created, migrations are applied, and the new version starts. Updating does not ask for the domain, token, or owner again.

After the first update, one command can fetch a new version from `origin/main` and run its installer:

```sh
python3 scripts/host.py update
```

The command requires the `main` branch and permits only a fast-forward. Local source edits and custom commits are retained; when present, update the sources manually. For an archive-based installation, obtain the new sources and use `up`.

The host-local `apps/frontend/Caddyfile` overlay is supported: the updater temporarily stashes it, fast-forwards the checkout, and restores it before building containers. If the new version touches the same section, the update stops so the conflict can be resolved.

The Docker project name is stored in `TAKT_PROJECT_NAME`. If an older installation used `--project`, pass the same name on its first update; subsequent commands use the saved value. Concurrent installation commands for one configuration are blocked.

```sh
python3 scripts/host.py status
python3 scripts/host.py logs
python3 scripts/host.py backup
python3 scripts/host.py stop
```

Backups are created under `backups/` in `pg_dump -Fc` format; an incomplete file does not become a completed backup. The directory is excluded from Git. Keep copies outside the server as well.

If backup creation fails, the previous containers resume. If a migration fails, the API and bot remain stopped; the backup path is printed in the terminal. Fix the cause and repeat `up`. Data and certificates remain in their existing volumes.

The `--config` and `--project` parameters select a separate settings file and name for a new installation. A separate configuration supports container checks over HTTP:

```sh
python3 scripts/host.py setup --local --config .env.host.local --project takt-local --port 8080
```

This mode checks building, startup, and availability; Telegram connectivity uses the main HTTPS mode. To apply the bot profile without rebuilding containers:

```sh
python3 scripts/host.py configure-bot
```
