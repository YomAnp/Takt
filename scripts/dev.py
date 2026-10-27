"""Start local PostgreSQL and the API, or run the backend checks."""

import argparse
import os
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LOCAL_URL = "postgresql+psycopg://takt:takt_local@127.0.0.1:5432/"
parser = argparse.ArgumentParser()
parser.add_argument("mode", choices=["start", "check"], default="start", nargs="?")
args = parser.parse_args()
env = os.environ.copy()


def run(*command: str) -> None:
    subprocess.run(command, cwd=ROOT, env=env, check=True)


run("docker", "compose", "up", "-d", "--wait", "db")
run("uv", "sync", "--project", "apps/backend", "--frozen", "--link-mode", "copy")

if args.mode == "check":
    if not env.get("TAKT_TEST_DATABASE_URL"):
        result = subprocess.run(
            [
                "docker",
                "compose",
                "exec",
                "-T",
                "db",
                "psql",
                "-U",
                "takt",
                "-d",
                "postgres",
                "-tAc",
                "SELECT 1 FROM pg_database WHERE datname = 'takt_test'",
            ],
            cwd=ROOT,
            env=env,
            text=True,
            capture_output=True,
            check=True,
        )
        if result.stdout.strip() != "1":
            run(
                "docker",
                "compose",
                "exec",
                "-T",
                "db",
                "createdb",
                "-U",
                "takt",
                "takt_test",
            )
        env["TAKT_TEST_DATABASE_URL"] = LOCAL_URL + "takt_test"
    run(
        "uv",
        "run",
        "--project",
        "apps/backend",
        "ruff",
        "check",
        "apps/backend",
        "scripts",
    )
    run(
        "uv",
        "run",
        "--project",
        "apps/backend",
        "ruff",
        "format",
        "--check",
        "apps/backend",
        "scripts",
    )
    run(
        "uv",
        "run",
        "--project",
        "apps/backend",
        "mypy",
        "--config-file",
        "apps/backend/pyproject.toml",
        "apps/backend/src",
    )
    run(
        "uv",
        "run",
        "--project",
        "apps/backend",
        "pytest",
        "apps/backend/tests",
        "--tb=short",
        "--maxfail=1",
    )
else:
    env.setdefault("TAKT_DATABASE_URL", LOCAL_URL + "takt")
    run(
        "uv",
        "run",
        "--project",
        "apps/backend",
        "alembic",
        "-c",
        "apps/backend/alembic.ini",
        "upgrade",
        "head",
    )
    run(
        "uv",
        "run",
        "--project",
        "apps/backend",
        "uvicorn",
        "takt.app:create_app",
        "--loop",
        "takt.runtime:new_event_loop",
        "--factory",
        "--reload",
        "--reload-dir",
        "apps/backend/src",
    )
