"""Configure and run a Takt installation from any checkout using Docker Compose."""

import argparse
import getpass
import ipaddress
import json
import os
import re
import secrets
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.request
from contextlib import contextmanager, suppress
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LOCAL_OVERLAY_PATHS = {"apps/frontend/Caddyfile"}


class SetupError(RuntimeError):
    pass


def domain_name(value: str) -> str:
    value = value.strip().lower().removeprefix("https://").rstrip("/")
    try:
        value = value.encode("idna").decode("ascii")
        ipaddress.ip_address(value)
    except ValueError:
        pass
    else:
        raise SetupError("Use a public DNS domain, not an IP address.")
    if (
        len(value) > 253
        or "." not in value
        or any(
            not re.fullmatch(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?", label)
            for label in value.split(".")
        )
    ):
        raise SetupError("Enter a domain such as takt.example.org, without a path or port.")
    if value.endswith((".local", ".localhost", ".internal", ".test", ".invalid")):
        raise SetupError("Use a publicly reachable domain for Telegram.")
    return value


def owner_name(value: str) -> str:
    value = value.strip().removeprefix("@")
    if not re.fullmatch(r"[A-Za-z][A-Za-z0-9_]{4,31}", value):
        raise SetupError("Enter the owner's Telegram @username.")
    return value


def read_env(path: Path) -> dict[str, str]:
    if not path.is_file():
        return {}
    result = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip() and not line.startswith("#"):
            key, separator, value = line.partition("=")
            if not separator or not re.fullmatch(r"[A-Z_]+", key):
                raise SetupError("The configuration file contains an invalid entry.")
            result[key] = value
    return result


def save_env(path: Path, values: dict[str, str]) -> None:
    if any(
        "\n" in value or "\r" in value or "$" in value or "#" in value for value in values.values()
    ):
        raise SetupError("Configuration values cannot contain line breaks, # or $.")
    path.parent.mkdir(parents=True, exist_ok=True)
    # Exclusive first creation and atomic replacement retain the existing database password.
    temporary = path.with_name(path.name + ".tmp")
    descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as target:
            target.write("".join(f"{key}={value}\n" for key, value in values.items()))
        os.chmod(temporary, 0o600)
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


def bot_call(token: str, method: str, body: dict[str, object] | None = None) -> object:
    request = urllib.request.Request(
        "https://api.telegram.org/bot" + token + "/" + method,
        data=json.dumps(body or {}).encode(),
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            result = json.load(response)
        if not result.get("ok"):
            raise SetupError(
                "Telegram rejected " + method + ". Check the bot token and permissions."
            )
        return result["result"]
    except (urllib.error.URLError, TimeoutError, ValueError):
        # urllib errors include the request URL, which contains the token.
        raise SetupError(
            "Telegram request failed: " + method + ". Check the token and connection."
        ) from None


def configure_bot(values: dict[str, str]) -> None:
    token = values["TAKT_BOT_TOKEN"]
    webhook = bot_call(token, "getWebhookInfo")
    if not isinstance(webhook, dict) or webhook.get("url"):
        raise SetupError(
            "This bot already has a webhook. Resolve it explicitly before starting polling."
        )
    bot_call(
        token,
        "setMyCommands",
        {
            "commands": [
                {"command": "start", "description": "Открыть Такт"},
                {"command": "help", "description": "Помощь"},
            ],
            "scope": {"type": "all_private_chats"},
        },
    )
    bot_call(
        token,
        "setMyDescription",
        {
            "description": (
                "Такт — личный учёт рабочего времени. Приход, уход, перерывы и статистика."
            )
        },
    )
    bot_call(
        token,
        "setMyShortDescription",
        {"short_description": "Ваш рабочий день под рукой."},
    )
    bot_call(
        token,
        "setChatMenuButton",
        {
            "menu_button": {
                "type": "web_app",
                "text": "Открыть Такт",
                "web_app": {"url": values["TAKT_PUBLIC_URL"]},
            }
        },
    )


def verify_public_url(url: str, *, attempts: int = 30) -> None:
    for attempt in range(attempts):
        try:
            with urllib.request.urlopen(url + "/health/ready", timeout=5) as response:
                if response.status == 200 and json.load(response).get("status") == "ok":
                    return
        except (urllib.error.URLError, TimeoutError, ValueError):
            pass
        if attempt + 1 < attempts:
            time.sleep(2)
    raise SetupError(
        "The public HTTPS endpoint is not ready. "
        "Check DNS, ports 80/443 and 'host.py logs'. "
        "The saved configuration and database are retained."
    )


def compose(config: Path, project: str, *args: str) -> None:
    subprocess.run(
        [
            "docker",
            "compose",
            "--project-name",
            project,
            "--env-file",
            str(config),
            "-f",
            str(ROOT / "compose.host.yaml"),
            *args,
        ],
        cwd=ROOT,
        check=True,
    )


def compose_output(config: Path, project: str, *args: str) -> str:
    result = subprocess.run(
        [
            "docker",
            "compose",
            "--project-name",
            project,
            "--env-file",
            str(config),
            "-f",
            str(ROOT / "compose.host.yaml"),
            *args,
        ],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


@contextmanager
def installation_lock(config: Path):
    """Serialize an installation without leaving a stale lock after a process exits."""
    path = config.with_name(config.name + ".lock")
    descriptor = os.open(path, os.O_CREAT | os.O_RDWR, 0o600)
    locked = False
    try:
        if os.name == "nt":
            import msvcrt

            if os.fstat(descriptor).st_size == 0:
                os.write(descriptor, b"0")
            os.lseek(descriptor, 0, os.SEEK_SET)
            try:
                msvcrt.locking(descriptor, msvcrt.LK_NBLCK, 1)
                locked = True
            except OSError:
                raise SetupError("Another installation command is already running.") from None
        else:
            import fcntl

            try:
                fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
                locked = True
            except OSError:
                raise SetupError("Another installation command is already running.") from None
        yield
    finally:
        if locked:
            if os.name == "nt":
                os.lseek(descriptor, 0, os.SEEK_SET)
                msvcrt.locking(descriptor, msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(descriptor, fcntl.LOCK_UN)
        os.close(descriptor)


def database_backup(config: Path, project: str) -> Path:
    destination = ROOT / "backups"
    destination.mkdir(exist_ok=True)
    stamp = time.strftime("%Y%m%d-%H%M%S", time.gmtime())
    target = destination / f"{project}-{stamp}-{secrets.token_hex(3)}.dump"
    partial = target.with_suffix(".dump.partial")
    descriptor = os.open(partial, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(descriptor, "wb") as output:
            subprocess.run(
                [
                    "docker",
                    "compose",
                    "--project-name",
                    project,
                    "--env-file",
                    str(config),
                    "-f",
                    str(ROOT / "compose.host.yaml"),
                    "exec",
                    "-T",
                    "db",
                    "pg_dump",
                    "-U",
                    "takt",
                    "-d",
                    "takt",
                    "-Fc",
                ],
                cwd=ROOT,
                stdout=output,
                check=True,
            )
        with partial.open("rb") as source:
            if source.read(5) != b"PGDMP":
                raise SetupError("Database backup is incomplete; migration was not started.")
        partial.replace(target)
        print("Backup:", target)
        return target
    finally:
        partial.unlink(missing_ok=True)


def git_output(*args: str) -> str:
    return subprocess.check_output(["git", *args], cwd=ROOT, text=True).strip()


def local_overlay_stash() -> str | None:
    """Temporarily keep the supported host-local Caddy overlay across a fast-forward."""
    status = subprocess.check_output(
        ["git", "status", "--porcelain=v1", "--untracked-files=no"], cwd=ROOT, text=True
    ).rstrip()
    if not status:
        return None
    entries = status.splitlines()
    paths = {entry[3:] for entry in entries if len(entry) >= 4}
    if paths != LOCAL_OVERLAY_PATHS or any(entry[:2] != " M" for entry in entries):
        raise SetupError(
            "Source files contain local changes. Only the host-local apps/frontend/Caddyfile "
            "overlay is preserved automatically. Commit or save other changes before updating."
        )
    subprocess.run(
        [
            "git",
            "stash",
            "push",
            "--message",
            "takt-host-preserved-local-overlay",
            "--",
            "apps/frontend/Caddyfile",
        ],
        cwd=ROOT,
        check=True,
    )
    return git_output("rev-parse", "refs/stash")


def restore_local_overlay(stash: str | None) -> None:
    if stash is None:
        return
    try:
        subprocess.run(["git", "stash", "apply", stash], cwd=ROOT, check=True)
    except subprocess.CalledProcessError:
        raise SetupError(
            "The host-local apps/frontend/Caddyfile overlay conflicts with the new version. "
            "The update is stopped; resolve the Caddyfile conflict and run "
            "'python3 scripts/host.py up'."
        ) from None
    references = git_output("stash", "list", "--format=%gd %H").splitlines()
    reference = next(
        (line.split(" ", 1)[0] for line in references if line.endswith(" " + stash)), None
    )
    if reference is None:
        raise SetupError("The preserved host-local overlay stash could not be found.")
    subprocess.run(["git", "stash", "drop", reference], cwd=ROOT, check=True)


def update_checkout() -> None:
    """Fast-forward only; local source edits and commits are never discarded."""
    if shutil.which("git") is None:
        raise SetupError("Install Git before updating the source checkout.")
    if git_output("branch", "--show-current") != "main":
        raise SetupError(
            "Automatic updates require the main branch. Keep custom branches manually."
        )
    if git_output("status", "--porcelain", "--untracked-files=no"):
        raise SetupError("Source files contain local changes. Commit or save them before updating.")
    subprocess.run(["git", "fetch", "origin", "main"], cwd=ROOT, check=True)
    result = subprocess.run(
        ["git", "merge-base", "--is-ancestor", "HEAD", "FETCH_HEAD"],
        cwd=ROOT,
        capture_output=True,
    )
    if result.returncode:
        raise SetupError("Local main contains commits absent from origin/main; update it manually.")
    subprocess.run(["git", "merge", "--ff-only", "FETCH_HEAD"], cwd=ROOT, check=True)


def ensure_bot_username(config: Path, values: dict[str, str]) -> None:
    if not values.get("TAKT_BOT_TOKEN") or values.get("TAKT_BOT_USERNAME"):
        return
    identity = bot_call(values["TAKT_BOT_TOKEN"], "getMe")
    if not isinstance(identity, dict) or not identity.get("is_bot") or not identity.get("username"):
        raise SetupError("The saved token does not identify a bot with a username.")
    values["TAKT_BOT_USERNAME"] = str(identity["username"])
    save_env(config, values)


def deploy(config: Path, project: str, values: dict[str, str], *, setup: bool) -> None:
    production = values.get("TAKT_PUBLIC_URL", "").startswith("https://")
    profile = ("--profile", "telegram") if production else ()
    ensure_bot_username(config, values)
    # A failed build leaves the running application untouched.
    compose(config, project, "build", "api", "web")
    compose(config, project, "up", "-d", "--wait", "db")
    running = set(
        compose_output(
            config, project, *profile, "ps", "--services", "--status", "running"
        ).splitlines()
    )
    writers = [name for name in ("api", "bot") if name in running]
    if writers:
        compose(config, project, *profile, "stop", *writers)
    backup = None
    try:
        initialized = (
            compose_output(
                config,
                project,
                "exec",
                "-T",
                "db",
                "psql",
                "-U",
                "takt",
                "-d",
                "takt",
                "-tAc",
                "SELECT to_regclass('public.alembic_version') IS NOT NULL",
            )
            == "t"
        )
        if initialized:
            backup = database_backup(config, project)
    except (Exception, KeyboardInterrupt):
        # The schema has not changed, so the previous containers can resume safely.
        if writers:
            compose(config, project, *profile, "start", *writers)
        raise
    try:
        compose(config, project, "run", "--rm", "--no-deps", "migrate")
    except subprocess.CalledProcessError:
        location = str(backup) if backup is not None else "No previous schema was present."
        raise SetupError(
            "Database migration failed. API and bot remain stopped. Backup: "
            + location
            + ". Fix the migration and run 'python3 scripts/host.py up' again."
        ) from None
    # Dependencies are already ready; a second migration is not started by Compose.
    compose(config, project, "up", "-d", "--wait", "--no-deps", "api", "web")
    verify_public_url(values["TAKT_PUBLIC_URL"])
    if production:
        if setup:
            configure_bot(values)
        compose(config, project, *profile, "up", "-d", "--no-deps", "bot")
    print("Takt is ready:", values["TAKT_PUBLIC_URL"])


def configured_project(explicit: str | None, values: dict[str, str]) -> str:
    saved = values.get("TAKT_PROJECT_NAME")
    if explicit and saved and explicit != saved:
        raise SetupError(
            "This configuration belongs to another Docker project. Use a separate --config."
        )
    project = explicit or saved or "takt-host"
    if not re.fullmatch(r"[a-z0-9][a-z0-9_-]{0,39}", project):
        raise SetupError("Use a lowercase Docker project name.")
    return project


def setup_values(config: Path, values: dict[str, str], args: argparse.Namespace) -> None:
    if args.local:
        if values.get("TAKT_PUBLIC_URL", "").startswith("https://"):
            raise SetupError(
                "Use a separate --config for local checks; this file configures production."
            )
        values.update(
            TAKT_SITE_ADDRESS=":80",
            TAKT_PUBLIC_URL="http://127.0.0.1:" + str(args.port),
            TAKT_HTTP_PORT=str(args.port),
            TAKT_HTTPS_PORT=str(args.port + 1),
            TAKT_BOT_TOKEN="",
            TAKT_BOT_USERNAME="",
            TAKT_SUPERADMIN_USERNAME="",
        )
    else:
        previous = values.get("TAKT_SITE_ADDRESS", "")
        host = domain_name(
            input("Domain" + (" [" + previous + "]" if previous else "") + ": ") or previous
        )
        token = getpass.getpass("Bot token (hidden; Enter keeps the saved token): ") or values.get(
            "TAKT_BOT_TOKEN", ""
        )
        if not re.fullmatch(r"[0-9]+:[A-Za-z0-9_-]{20,}", token):
            raise SetupError("Invalid bot token format.")
        previous_owner = values.get("TAKT_SUPERADMIN_USERNAME", "")
        owner = owner_name(
            input(
                "Owner @username" + (" [" + previous_owner + "]" if previous_owner else "") + ": "
            )
            or previous_owner
        )
        identity = bot_call(token, "getMe")
        webhook = bot_call(token, "getWebhookInfo")
        if (
            not isinstance(identity, dict)
            or not identity.get("is_bot")
            or not identity.get("username")
        ):
            raise SetupError("This token does not identify a bot with a username.")
        if not isinstance(webhook, dict) or webhook.get("url"):
            raise SetupError(
                "This bot already has a webhook. "
                "Use a dedicated bot or remove its webhook explicitly before setup."
            )
        print("Bot: @" + str(identity["username"]))
        values.update(
            TAKT_SITE_ADDRESS=host,
            TAKT_PUBLIC_URL="https://" + host,
            TAKT_HTTP_PORT="80",
            TAKT_HTTPS_PORT="443",
            TAKT_BOT_TOKEN=token,
            TAKT_BOT_USERNAME=str(identity["username"]),
            TAKT_SUPERADMIN_USERNAME=owner,
        )
    values.setdefault("TAKT_POSTGRES_PASSWORD", secrets.token_hex(32))
    values.setdefault("TAKT_TIME_ZONE", "Europe/Moscow")
    save_env(config, values)
    print("Configuration saved:", config)


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "action",
        choices=["setup", "up", "update", "status", "logs", "stop", "backup", "configure-bot"],
    )
    parser.add_argument("--config", type=Path, default=ROOT / ".env.host")
    parser.add_argument("--project", help="Docker project; defaults to the saved installation name")
    parser.add_argument(
        "--local",
        action="store_true",
        help="HTTP smoke-test installation, without Telegram registration",
    )
    parser.add_argument("--port", type=int, default=8080, help="HTTP port for --local")
    args = parser.parse_args(argv)
    if not 1 <= args.port < 65535:
        raise SetupError("Invalid local port.")
    if shutil.which("docker") is None:
        raise SetupError(
            "Install Docker Engine and its Compose plugin: https://docs.docker.com/engine/install/"
        )
    subprocess.run(["docker", "compose", "version"], check=True)
    subprocess.run(["docker", "info", "--format", "{{.ServerVersion}}"], check=True)
    config = args.config.expanduser().resolve()
    if args.action in {"status", "logs"}:
        values = read_env(config)
        if not values:
            raise SetupError("Run 'python3 scripts/host.py setup' first.")
        project = configured_project(args.project, values)
        profile = (
            ("--profile", "telegram")
            if values.get("TAKT_PUBLIC_URL", "").startswith("https://")
            else ()
        )
        command = ("ps", "-a") if args.action == "status" else ("logs", "--tail", "100")
        compose(config, project, *profile, *command)
        return
    config.parent.mkdir(parents=True, exist_ok=True)
    with installation_lock(config):
        values = read_env(config)
        project = configured_project(args.project, values)
        if args.action == "setup":
            values.setdefault("TAKT_PROJECT_NAME", project)
            setup_values(config, values, args)
        if not values:
            raise SetupError("Run 'python3 scripts/host.py setup' first.")
        if args.action == "update":
            overlay_stash = local_overlay_stash()
            try:
                update_checkout()
                restore_local_overlay(overlay_stash)
            except Exception:
                if overlay_stash is not None:
                    with suppress(SetupError):
                        restore_local_overlay(overlay_stash)
                raise
        elif args.action in {"setup", "up"}:
            if "TAKT_PROJECT_NAME" not in values:
                values["TAKT_PROJECT_NAME"] = project
                save_env(config, values)
            deploy(config, project, values, setup=args.action == "setup")
            if args.action == "setup" and values.get("TAKT_PUBLIC_URL", "").startswith("https://"):
                print(
                    "Open the bot as @"
                    + values["TAKT_SUPERADMIN_USERNAME"]
                    + " to bind the owner's verified Telegram ID."
                )
                print(
                    "The optional main profile Mini App shortcut is configured in @BotFather. "
                    "The chat menu button is already configured."
                )
        elif args.action == "configure-bot":
            if not values.get("TAKT_PUBLIC_URL", "").startswith("https://"):
                raise SetupError("Telegram requires the production HTTPS configuration.")
            verify_public_url(values["TAKT_PUBLIC_URL"])
            ensure_bot_username(config, values)
            configure_bot(values)
            print("Telegram menu and commands configured.")
        elif args.action == "stop":
            profile = (
                ("--profile", "telegram")
                if values.get("TAKT_PUBLIC_URL", "").startswith("https://")
                else ()
            )
            compose(config, project, *profile, "stop")
        elif args.action == "backup":
            database_backup(config, project)
    if args.action == "update":
        # Reload the fetched installer code, preserving this installation's identity.
        subprocess.run(
            [
                sys.executable,
                str(ROOT / "scripts/host.py"),
                "up",
                "--config",
                str(config),
                "--project",
                project,
            ],
            cwd=ROOT,
            check=True,
        )


if __name__ == "__main__":
    try:
        main()
    except (
        SetupError,
        subprocess.CalledProcessError,
        KeyboardInterrupt,
        EOFError,
    ) as exc:
        print(
            str(exc)
            if isinstance(exc, SetupError)
            else "Installation interrupted or a command failed. Saved data is retained.",
            file=sys.stderr,
        )
        raise SystemExit(1) from None
