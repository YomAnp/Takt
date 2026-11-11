from datetime import UTC, datetime
from urllib.parse import parse_qs, urlsplit

import pytest
from aiogram import Bot
from aiogram.client.session.base import BaseSession
from aiogram.methods import SendMessage
from aiogram.types import Message, Update

from takt.bot import make_dispatcher


class RecordingSession(BaseSession):
    def __init__(self):
        super().__init__()
        self.sent = []

    async def close(self):
        pass

    async def make_request(self, bot, method, timeout=None):
        self.sent.append(method)
        return Message(message_id=1, date=datetime.now(UTC), chat={"id": 42, "type": "private"})

    async def stream_content(self, *args, **kwargs):
        if False:
            yield b""


@pytest.mark.asyncio
@pytest.mark.parametrize("command", ["/start", "/help"])
async def test_bot_commands_open_configured_application_in_private_chat(command):
    session = RecordingSession()
    bot = Bot("123456:local_test_token", session=session)
    dispatcher = make_dispatcher("https://independent.example.org")
    update = Update.model_validate(
        {
            "update_id": 1,
            "message": {
                "message_id": 1,
                "date": int(datetime.now(UTC).timestamp()),
                "from": {"id": 42, "first_name": "Test", "is_bot": False},
                "chat": {"id": 42, "type": "private"},
                "text": command,
                "entities": [{"type": "bot_command", "offset": 0, "length": len(command)}],
            },
        }
    )
    await dispatcher.feed_update(bot, update)
    assert len(session.sent) == 1
    reply = session.sent[0]
    assert isinstance(reply, SendMessage)
    assert reply.reply_markup.inline_keyboard[0][0].web_app.url == "https://independent.example.org"
    if command == "/help":
        assert "Перерывы и перекуры" in reply.text
        assert "входят в общее время" in reply.text
        assert "по вашему желанию" in reply.text
    else:
        assert "фактическое время" in reply.text
        assert "Как пользоваться" not in reply.text


@pytest.mark.asyncio
@pytest.mark.parametrize("command", ["/start", "/help"])
async def test_bot_does_not_send_private_app_keyboard_to_groups(command):
    session = RecordingSession()
    bot = Bot("123456:local_test_token", session=session)
    dispatcher = make_dispatcher("https://independent.example.org")
    update = Update.model_validate(
        {
            "update_id": 2,
            "message": {
                "message_id": 2,
                "date": int(datetime.now(UTC).timestamp()),
                "from": {"id": 42, "first_name": "Test", "is_bot": False},
                "chat": {"id": -42, "type": "group", "title": "Group"},
                "text": command,
                "entities": [{"type": "bot_command", "offset": 0, "length": len(command)}],
            },
        }
    )
    await dispatcher.feed_update(bot, update)
    assert not session.sent


@pytest.mark.asyncio
@pytest.mark.parametrize("argument", ["friend_" + "A" * 32, "friend_invalid?role=admin"])
async def test_bot_carries_only_valid_friend_invites_into_the_mini_app(argument):
    session = RecordingSession()
    bot = Bot("123456:local_test_token", session=session)
    dispatcher = make_dispatcher("https://independent.example.org/?source=bot")
    update = Update.model_validate(
        {
            "update_id": 3,
            "message": {
                "message_id": 3,
                "date": int(datetime.now(UTC).timestamp()),
                "from": {"id": 42, "first_name": "Test", "is_bot": False},
                "chat": {"id": 42, "type": "private"},
                "text": "/start " + argument,
                "entities": [{"type": "bot_command", "offset": 0, "length": 6}],
            },
        }
    )
    await dispatcher.feed_update(bot, update)
    query = parse_qs(urlsplit(session.sent[0].reply_markup.inline_keyboard[0][0].web_app.url).query)
    assert query["source"] == ["bot"]
    assert query.get("invite") == (["A" * 32] if argument.endswith("A" * 32) else None)
    assert "role" not in query
    assert ("пригласили в друзья" in session.sent[0].text) == argument.endswith("A" * 32)
