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
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


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


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "action",
        choices=["setup", "up", "status", "logs", "stop", "backup", "configure-bot"],
    )
    parser.add_argument("--config", type=Path, default=ROOT / ".env.host")
    parser.add_argument("--project", default="takt-host")
    parser.add_argument(
        "--local",
        action="store_true",
        help="HTTP smoke-test installation, without Telegram registration",
    )
    parser.add_argument("--port", type=int, default=8080, help="HTTP port for --local")
    args = parser.parse_args(argv)
    if not re.fullmatch(r"[a-z0-9][a-z0-9_-]{0,39}", args.project):
        raise SetupError("Use a lowercase Docker project name.")
    if not 1 <= args.port < 65535:
        raise SetupError("Invalid local port.")
    if shutil.which("docker") is None:
        raise SetupError(
            "Install Docker Engine and its Compose plugin: https://docs.docker.com/engine/install/"
        )
    subprocess.run(["docker", "compose", "version"], check=True)
    subprocess.run(["docker", "info", "--format", "{{.ServerVersion}}"], check=True)
    config = args.config.expanduser().resolve()
    values = read_env(config)
    if args.action == "setup":
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
                TAKT_SUPERADMIN_USERNAME="",
            )
        else:
            previous = values.get("TAKT_SITE_ADDRESS", "")
            host = domain_name(
                input("Domain" + (" [" + previous + "]" if previous else "") + ": ") or previous
            )
            token = getpass.getpass(
                "Bot token (hidden; Enter keeps the saved token): "
            ) or values.get("TAKT_BOT_TOKEN", "")
            if not re.fullmatch(r"[0-9]+:[A-Za-z0-9_-]{20,}", token):
                raise SetupError("Invalid bot token format.")
            previous_owner = values.get("TAKT_SUPERADMIN_USERNAME", "")
            owner = owner_name(
                input(
                    "Owner @username"
                    + (" [" + previous_owner + "]" if previous_owner else "")
                    + ": "
                )
                or previous_owner
            )
            identity = bot_call(token, "getMe")
            webhook = bot_call(token, "getWebhookInfo")
            if not isinstance(identity, dict) or not identity.get("is_bot"):
                raise SetupError("This token does not identify a bot.")
            if not isinstance(webhook, dict) or webhook.get("url"):
                raise SetupError(
                    "This bot already has a webhook. "
                    "Use a dedicated bot or remove its webhook explicitly before setup."
                )
            print("Bot: @" + str(identity.get("username", "")))
            values.update(
                TAKT_SITE_ADDRESS=host,
                TAKT_PUBLIC_URL="https://" + host,
                TAKT_HTTP_PORT="80",
                TAKT_HTTPS_PORT="443",
                TAKT_BOT_TOKEN=token,
                TAKT_SUPERADMIN_USERNAME=owner,
            )
        values.setdefault("TAKT_POSTGRES_PASSWORD", secrets.token_hex(32))
        values.setdefault("TAKT_TIME_ZONE", "Europe/Moscow")
        save_env(config, values)
        print("Configuration saved:", config)
    if not values:
        raise SetupError("Run 'python3 scripts/host.py setup' first.")
    production = values.get("TAKT_PUBLIC_URL", "").startswith("https://")
    profile = ("--profile", "telegram") if production else ()
    if args.action in {"setup", "up"}:
        compose(config, args.project, "build", "api", "web")
        # Explicit migration on every update, including when a previous migrate container exited.
        compose(config, args.project, "up", "-d", "--wait", "db")
        compose(config, args.project, "run", "--rm", "--no-deps", "migrate")
        compose(config, args.project, "up", "-d", "--wait", "api", "web")
        verify_public_url(values["TAKT_PUBLIC_URL"])
        if production:
            configure_bot(values)
            compose(config, args.project, *profile, "up", "-d", "bot")
        print("Takt is ready:", values["TAKT_PUBLIC_URL"])
        if production:
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
        if not production:
            raise SetupError("Telegram requires the production HTTPS configuration.")
        verify_public_url(values["TAKT_PUBLIC_URL"])
        configure_bot(values)
        print("Telegram menu and commands configured.")
    elif args.action == "status":
        compose(config, args.project, *profile, "ps", "-a")
    elif args.action == "logs":
        compose(config, args.project, *profile, "logs", "--tail", "100")
    elif args.action == "stop":
        compose(config, args.project, *profile, "stop")
    elif args.action == "backup":
        destination = ROOT / "backups"
        destination.mkdir(exist_ok=True)
        target = destination / ("takt-" + time.strftime("%Y%m%d-%H%M%S", time.gmtime()) + ".dump")
        with target.open("xb") as output:
            subprocess.run(
                [
                    "docker",
                    "compose",
                    "--project-name",
                    args.project,
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
        os.chmod(target, 0o600)
        print("Backup:", target)


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
