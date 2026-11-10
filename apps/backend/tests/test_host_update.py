import importlib.util
import os
import subprocess
from pathlib import Path

import pytest

PATH = Path(__file__).resolve().parents[3] / "scripts" / "host.py"
SPEC = importlib.util.spec_from_file_location("host_update", PATH)
assert SPEC is not None and SPEC.loader is not None
host = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(host)


@pytest.fixture
def deployment(monkeypatch, tmp_path):
    calls = []
    config = tmp_path / ".env.host"
    values = {
        "TAKT_PUBLIC_URL": "http://127.0.0.1:8080",
        "TAKT_POSTGRES_PASSWORD": "saved-password",
    }
    monkeypatch.setattr(host, "ROOT", tmp_path)
    monkeypatch.setattr(host, "compose", lambda config, project, *args: calls.append(args))

    def output(config, project, *args):
        return "api\nweb\ndb" if "ps" in args else "t"

    monkeypatch.setattr(host, "compose_output", output)

    def backup(config, project):
        calls.append(("backup",))
        return tmp_path / "original.dump"

    monkeypatch.setattr(host, "database_backup", backup)
    monkeypatch.setattr(host, "verify_public_url", lambda url: calls.append(("ready",)))
    return config, values, calls


def test_update_quiesces_writers_and_backs_up_before_migration(deployment):
    config, values, calls = deployment
    host.deploy(config, "installation", values, setup=False)
    backup = calls.index(("backup",))
    migration = calls.index(("run", "--rm", "--no-deps", "migrate"))
    assert calls.index(("build", "api", "web")) < calls.index(("stop", "api"))
    assert calls.index(("stop", "api")) < backup < migration
    assert calls[migration + 1] == ("up", "-d", "--wait", "--no-deps", "api", "web")


def test_backup_failure_resumes_old_containers_without_migrating(deployment, monkeypatch):
    config, values, calls = deployment

    def fail(*args):
        raise host.SetupError("backup failed")

    monkeypatch.setattr(host, "database_backup", fail)
    with pytest.raises(host.SetupError, match="backup failed"):
        host.deploy(config, "installation", values, setup=False)
    assert calls[-1] == ("start", "api")
    assert not any("migrate" in call for call in calls)


def test_migration_failure_keeps_writers_stopped_and_reports_backup(deployment, monkeypatch):
    config, values, calls = deployment

    def compose(config, project, *args):
        calls.append(args)
        if args == ("run", "--rm", "--no-deps", "migrate"):
            raise subprocess.CalledProcessError(1, ["migration"])

    monkeypatch.setattr(host, "compose", compose)
    with pytest.raises(host.SetupError, match="API and bot remain stopped.*original.dump"):
        host.deploy(config, "installation", values, setup=False)
    assert not any(call[0] == "start" for call in calls)
    assert ("up", "-d", "--wait", "--no-deps", "api", "web") not in calls


def test_build_failure_does_not_stop_or_backup_the_working_app(deployment, monkeypatch):
    config, values, calls = deployment

    def compose(config, project, *args):
        calls.append(args)
        raise subprocess.CalledProcessError(1, ["build"])

    monkeypatch.setattr(host, "compose", compose)
    with pytest.raises(subprocess.CalledProcessError):
        host.deploy(config, "installation", values, setup=False)
    assert calls == [("build", "api", "web")]


def test_new_database_needs_no_old_schema_backup(deployment, monkeypatch):
    config, values, calls = deployment
    monkeypatch.setattr(host, "compose_output", lambda *args: "")
    host.deploy(config, "installation", values, setup=True)
    assert ("backup",) not in calls
    assert not any(call[0] == "stop" for call in calls)


def test_old_config_gets_bot_username_without_replacing_secrets(tmp_path, monkeypatch):
    config = tmp_path / ".env.host"
    original = {
        "TAKT_BOT_TOKEN": "existing-token",
        "TAKT_POSTGRES_PASSWORD": "existing-database-password",
        "TAKT_SUPERADMIN_USERNAME": "ExistingOwner",
        "CUSTOM_SETTING": "keep-me",
    }
    host.save_env(config, original)
    values = host.read_env(config)
    monkeypatch.setattr(
        host, "bot_call", lambda *args: {"is_bot": True, "username": "existing_bot"}
    )
    host.ensure_bot_username(config, values)
    saved = host.read_env(config)
    assert {key: saved[key] for key in original} == original
    assert saved["TAKT_BOT_USERNAME"] == "existing_bot"


def test_existing_installation_updates_without_prompts_and_retains_every_setting(
    deployment, monkeypatch
):
    config, _, calls = deployment
    original = {
        "TAKT_PUBLIC_URL": "https://installed.example.org",
        "TAKT_BOT_TOKEN": "existing-token",
        "TAKT_POSTGRES_PASSWORD": "existing-password",
        "TAKT_SUPERADMIN_USERNAME": "ExistingOwner",
        "TAKT_TIME_ZONE": "Europe/Moscow",
        "CUSTOM_SETTING": "keep-me",
    }
    host.save_env(config, original)
    monkeypatch.setattr(host.shutil, "which", lambda command: command)
    monkeypatch.setattr(
        host.subprocess, "run", lambda command, **kwargs: subprocess.CompletedProcess(command, 0)
    )
    monkeypatch.setattr(
        host, "bot_call", lambda *args: {"is_bot": True, "username": "installed_bot"}
    )
    monkeypatch.setattr("builtins.input", lambda *args: pytest.fail("update asked for input"))
    host.main(["up", "--config", str(config), "--project", "existing-installation"])
    saved = host.read_env(config)
    assert {key: saved[key] for key in original} == original
    assert saved["TAKT_BOT_USERNAME"] == "installed_bot"
    assert saved["TAKT_PROJECT_NAME"] == "existing-installation"
    assert ("--profile", "telegram", "up", "-d", "--no-deps", "bot") in calls


def test_update_runs_the_fetched_installer_with_the_saved_configuration(tmp_path, monkeypatch):
    config = tmp_path / "private.env"
    original = {"TAKT_PUBLIC_URL": "https://installed.example.org", "TAKT_PROJECT_NAME": "saved"}
    host.save_env(config, original)
    monkeypatch.setattr(host, "ROOT", tmp_path)
    monkeypatch.setattr(host.shutil, "which", lambda command: command)
    calls = []

    def run(command, **kwargs):
        calls.append(command)
        return subprocess.CompletedProcess(command, 0)

    monkeypatch.setattr(host.subprocess, "run", run)
    monkeypatch.setattr(host, "update_checkout", lambda: calls.append(["fetched-source"]))
    host.main(["update", "--config", str(config)])
    assert calls[-2] == ["fetched-source"]
    assert calls[-1] == [
        host.sys.executable,
        str(tmp_path / "scripts/host.py"),
        "up",
        "--config",
        str(config),
        "--project",
        "saved",
    ]
    assert host.read_env(config) == original


def test_existing_project_name_prevents_an_accidental_new_database():
    assert (
        host.configured_project(None, {"TAKT_PROJECT_NAME": "custom-install"}) == "custom-install"
    )
    assert host.configured_project(None, {}) == "takt-host"
    with pytest.raises(host.SetupError, match="another Docker project"):
        host.configured_project("different", {"TAKT_PROJECT_NAME": "custom-install"})


def test_installation_lock_rejects_parallel_commands_and_releases(tmp_path):
    config = tmp_path / ".env.host"
    with (
        host.installation_lock(config),
        pytest.raises(host.SetupError, match="already running"),
        host.installation_lock(config),
    ):
        pytest.fail("parallel command acquired the lock")
    with host.installation_lock(config):
        pass


def test_backup_is_complete_and_private_before_becoming_visible(tmp_path, monkeypatch):
    monkeypatch.setattr(host, "ROOT", tmp_path)

    def dump(command, **kwargs):
        assert "saved-password" not in command
        kwargs["stdout"].write(b"PGDMPcomplete backup")
        return subprocess.CompletedProcess(command, 0)

    monkeypatch.setattr(host.subprocess, "run", dump)
    target = host.database_backup(tmp_path / ".env.host", "custom")
    assert target.read_bytes() == b"PGDMPcomplete backup"
    assert not list(target.parent.glob("*.partial"))
    if os.name != "nt":
        assert target.stat().st_mode & 0o777 == 0o600


def test_failed_dump_leaves_no_partial_or_valid_looking_backup(tmp_path, monkeypatch):
    monkeypatch.setattr(host, "ROOT", tmp_path)

    def dump(command, **kwargs):
        kwargs["stdout"].write(b"partial")
        raise subprocess.CalledProcessError(1, command)

    monkeypatch.setattr(host.subprocess, "run", dump)
    with pytest.raises(subprocess.CalledProcessError):
        host.database_backup(tmp_path / ".env.host", "custom")
    assert not list((tmp_path / "backups").iterdir())


def git(directory, *args):
    return subprocess.check_output(["git", *args], cwd=directory, text=True).strip()


def commit(directory, message):
    git(directory, "add", ".")
    git(
        directory,
        "-c",
        "user.name=Test",
        "-c",
        "user.email=test@example.invalid",
        "commit",
        "-m",
        message,
    )


@pytest.fixture
def checkout(tmp_path, monkeypatch):
    origin = tmp_path / "origin"
    origin.mkdir()
    git(origin, "init", "-b", "main")
    (origin / ".gitignore").write_text(".env.host\n", encoding="utf-8")
    (origin / "version.txt").write_text("old", encoding="utf-8")
    commit(origin, "initial")
    installed = tmp_path / "installed"
    subprocess.run(["git", "clone", str(origin), str(installed)], check=True, capture_output=True)
    monkeypatch.setattr(host, "ROOT", installed)
    return origin, installed


def test_update_fast_forwards_existing_checkout_and_preserves_config(checkout):
    origin, installed = checkout
    (installed / ".env.host").write_text("TAKT_POSTGRES_PASSWORD=saved\n", encoding="utf-8")
    (origin / "version.txt").write_text("new", encoding="utf-8")
    commit(origin, "release")
    host.update_checkout()
    assert (installed / "version.txt").read_text(encoding="utf-8") == "new"
    assert (installed / ".env.host").read_text(encoding="utf-8") == "TAKT_POSTGRES_PASSWORD=saved\n"
    assert git(installed, "rev-parse", "HEAD") == git(origin, "rev-parse", "HEAD")


def test_update_preserves_uncommitted_source_edits(checkout):
    origin, installed = checkout
    before = git(installed, "rev-parse", "HEAD")
    (installed / "version.txt").write_text("local edit", encoding="utf-8")
    (origin / "version.txt").write_text("release", encoding="utf-8")
    commit(origin, "release")
    with pytest.raises(host.SetupError, match="local changes"):
        host.update_checkout()
    assert git(installed, "rev-parse", "HEAD") == before
    assert (installed / "version.txt").read_text(encoding="utf-8") == "local edit"


def test_update_does_not_merge_or_discard_local_commits(checkout):
    origin, installed = checkout
    (installed / "local.txt").write_text("custom change", encoding="utf-8")
    commit(installed, "custom")
    before = git(installed, "rev-parse", "HEAD")
    (origin / "version.txt").write_text("release", encoding="utf-8")
    commit(origin, "release")
    with pytest.raises(host.SetupError, match="absent from origin/main"):
        host.update_checkout()
    assert git(installed, "rev-parse", "HEAD") == before
    assert (installed / "local.txt").read_text(encoding="utf-8") == "custom change"
