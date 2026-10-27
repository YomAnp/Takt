import importlib.util
from pathlib import Path

import pytest

PATH = Path(__file__).resolve().parents[3] / "scripts" / "host.py"
SPEC = importlib.util.spec_from_file_location("host_setup", PATH)
assert SPEC is not None and SPEC.loader is not None
host = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(host)


@pytest.mark.parametrize(
    "value",
    [
        "http://example.org",
        "example.org/path",
        "127.0.0.1",
        "example.org:8080",
        "example.local",
        "bad domain.org",
    ],
)
def test_setup_rejects_addresses_unsuitable_for_public_telegram(value):
    with pytest.raises(host.SetupError):
        host.domain_name(value)


def test_setup_supports_any_valid_domain_and_owner_without_fixed_account():
    assert host.domain_name("https://TAKT.Example.org/") == "takt.example.org"
    assert host.owner_name("@Another_owner") == "Another_owner"


def test_saved_configuration_retains_database_password_and_hides_sensitive_values(tmp_path):
    path = tmp_path / ".env.host"
    original = {
        "TAKT_POSTGRES_PASSWORD": "saved-database-password",
        "TAKT_BOT_TOKEN": "private-token",
        "TAKT_SITE_ADDRESS": "first.example.org",
    }
    host.save_env(path, original)
    loaded = host.read_env(path)
    loaded["TAKT_SITE_ADDRESS"] = "second.example.org"
    host.save_env(path, loaded)
    assert host.read_env(path)["TAKT_POSTGRES_PASSWORD"] == "saved-database-password"
    assert not path.with_name(path.name + ".tmp").exists()
    with pytest.raises(host.SetupError):
        host.save_env(path, {"TAKT_BOT_TOKEN": "token\nOTHER=value"})
    assert host.read_env(path)["TAKT_BOT_TOKEN"] == "private-token"


def test_telegram_errors_never_include_token_in_message(monkeypatch):
    secret = "123456:very_private_token"

    def fail(*args, **kwargs):
        raise host.urllib.error.URLError("https://api.telegram.org/bot" + secret)

    monkeypatch.setattr(host.urllib.request, "urlopen", fail)
    with pytest.raises(host.SetupError) as result:
        host.bot_call(secret, "getMe")
    assert secret not in str(result.value)


def test_existing_webhook_is_not_silently_replaced(monkeypatch):
    calls = []

    def call(token, method, body=None):
        calls.append(method)
        return {"url": "https://another.example.org/webhook"}

    monkeypatch.setattr(host, "bot_call", call)
    with pytest.raises(host.SetupError):
        host.configure_bot({"TAKT_BOT_TOKEN": "secret", "TAKT_PUBLIC_URL": "https://example.org"})
    assert calls == ["getWebhookInfo"]


def test_configuration_registers_real_chat_menu_and_supported_commands(monkeypatch):
    calls = []

    def call(token, method, body=None):
        calls.append((method, body))
        return {"url": ""} if method == "getWebhookInfo" else True

    monkeypatch.setattr(host, "bot_call", call)
    host.configure_bot(
        {"TAKT_BOT_TOKEN": "secret", "TAKT_PUBLIC_URL": "https://independent.example.org"}
    )
    menu = next(body for method, body in calls if method == "setChatMenuButton")
    assert menu["menu_button"]["web_app"]["url"] == "https://independent.example.org"
    commands = next(body for method, body in calls if method == "setMyCommands")
    assert {command["command"] for command in commands["commands"]} == {"start", "help"}
