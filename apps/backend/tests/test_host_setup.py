import importlib.util
import io
import json
from email import policy
from email.parser import BytesParser
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


@pytest.mark.parametrize("photo", [None, b"private-image-bytes"])
def test_telegram_errors_never_include_token_in_message(monkeypatch, photo):
    secret = "123456:very_private_token"

    def fail(*args, **kwargs):
        raise host.urllib.error.URLError("https://api.telegram.org/bot" + secret)

    monkeypatch.setattr(host.urllib.request, "urlopen", fail)
    with pytest.raises(host.SetupError) as result:
        host.bot_call(secret, "getMe", photo=photo)
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
    monkeypatch.setattr(host, "configure_bot_photo", lambda values, config: None)
    host.configure_bot(
        {"TAKT_BOT_TOKEN": "secret", "TAKT_PUBLIC_URL": "https://independent.example.org"}
    )
    menu = next(body for method, body in calls if method == "setChatMenuButton")
    assert menu["menu_button"]["web_app"]["url"] == "https://independent.example.org"
    commands = next(body for method, body in calls if method == "setMyCommands")
    assert {command["command"] for command in commands["commands"]} == {"start", "help"}
    assert commands["scope"] == {"type": "all_private_chats"}
    for language in ("", "ru"):
        localized = {
            method: body
            for method, body in calls
            if body is not None and body.get("language_code") == language
        }
        assert localized["setMyName"]["name"] == "Такт"
        assert 0 < len(localized["setMyDescription"]["description"]) <= 512
        assert 0 < len(localized["setMyShortDescription"]["short_description"]) <= 120
        assert localized["setMyCommands"]["scope"] == {"type": "all_private_chats"}


def test_avatar_upload_uses_telegram_multipart_attachment_and_preserves_image(monkeypatch):
    image = b"\xff\xd8\xff\x00\r\n\x80avatar\xff\xd9"
    requests = []

    def response(request, **kwargs):
        requests.append(request)
        return io.BytesIO(b'{"ok": true, "result": true}')

    monkeypatch.setattr(host.urllib.request, "urlopen", response)
    result = host.bot_call(
        "123456:secret",
        "setMyProfilePhoto",
        {"photo": {"type": "static", "photo": "attach://avatar"}},
        photo=image,
    )
    assert result is True
    request = requests[0]
    message = BytesParser(policy=policy.default).parsebytes(
        ("Content-Type: " + request.get_header("Content-type") + "\r\n\r\n").encode() + request.data
    )
    parts = list(message.iter_parts())
    assert len(parts) == 2
    assert parts[0].get_param("name", header="content-disposition") == "photo"
    assert json.loads(parts[0].get_payload(decode=True)) == {
        "type": "static",
        "photo": "attach://avatar",
    }
    assert parts[1].get_param("name", header="content-disposition") == "avatar"
    assert parts[1].get_filename() == "avatar.jpg"
    assert parts[1].get_content_type() == "image/jpeg"
    assert parts[1].get_payload(decode=True) == image


@pytest.fixture
def avatar_registration(tmp_path, monkeypatch):
    avatar = tmp_path / "apps" / "frontend" / "public" / "brand" / "avatar.jpg"
    avatar.parent.mkdir(parents=True)
    avatar.write_bytes(b"\xff\xd8\xffavatar\xff\xd9")
    monkeypatch.setattr(host, "ROOT", tmp_path)
    calls = []
    state = {"bot_id": 42, "photo": "previous-photo"}

    def call(token, method, body=None, **kwargs):
        calls.append(method)
        if method == "getMe":
            return {"id": state["bot_id"], "is_bot": True}
        if method == "getUserProfilePhotos":
            assert body == {"user_id": state["bot_id"], "limit": 1}
            photos = [[{"file_unique_id": state["photo"]}]] if state["photo"] else []
            return {"total_count": len(photos), "photos": photos}
        if method == "setMyProfilePhoto":
            assert kwargs["photo"] == avatar.read_bytes()
            state["photo"] = "new-photo"
            return True
        pytest.fail("Unexpected Telegram method: " + method)

    monkeypatch.setattr(host, "bot_call", call)
    config = tmp_path / ".env.host"
    values = {"TAKT_BOT_TOKEN": "secret", "TAKT_POSTGRES_PASSWORD": "retain-this"}
    host.save_env(config, values)
    return avatar, config, values, calls, state


def test_repeated_registration_does_not_upload_a_duplicate_avatar(avatar_registration):
    _, config, values, calls, _ = avatar_registration
    host.configure_bot_photo(values, config)
    assert host.read_env(config)["TAKT_POSTGRES_PASSWORD"] == "retain-this"
    assert values["TAKT_BOT_AVATAR_FILE_UNIQUE_ID"] == "new-photo"
    calls.clear()
    host.configure_bot_photo(host.read_env(config), config)
    assert calls == ["getMe", "getUserProfilePhotos"]


@pytest.mark.parametrize("change", ["asset", "bot", "removed", "replaced"])
def test_avatar_refreshes_when_asset_bot_or_current_telegram_photo_changes(
    avatar_registration, change
):
    avatar, config, values, calls, state = avatar_registration
    host.configure_bot_photo(values, config)
    if change == "asset":
        avatar.write_bytes(avatar.read_bytes() + b"updated")
    elif change == "bot":
        state["bot_id"] = 43
        values["TAKT_BOT_TOKEN"] = "different-token"
    else:
        state["photo"] = "" if change == "removed" else "manual-replacement"
    calls.clear()
    host.configure_bot_photo(values, config)
    assert calls.count("setMyProfilePhoto") == 1


def test_failed_avatar_upload_leaves_saved_fingerprint_unchanged(avatar_registration, monkeypatch):
    _, config, values, _, _ = avatar_registration
    before = config.read_bytes()
    call = host.bot_call

    def fail(token, method, body=None, **kwargs):
        if method == "setMyProfilePhoto":
            raise host.SetupError("Telegram request failed: setMyProfilePhoto.")
        return call(token, method, body, **kwargs)

    monkeypatch.setattr(host, "bot_call", fail)
    with pytest.raises(host.SetupError):
        host.configure_bot_photo(values, config)
    assert config.read_bytes() == before
    assert "TAKT_BOT_AVATAR_FINGERPRINT" not in values


def test_missing_avatar_confirmation_is_not_saved_as_success(avatar_registration, monkeypatch):
    _, config, values, _, _ = avatar_registration
    before = config.read_bytes()
    monkeypatch.setattr(host, "current_bot_photo", lambda *args: "")
    with pytest.raises(host.SetupError, match="did not confirm"):
        host.configure_bot_photo(values, config)
    assert config.read_bytes() == before
