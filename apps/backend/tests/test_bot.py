from datetime import UTC, datetime

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


@pytest.mark.asyncio
async def test_bot_does_not_send_private_app_keyboard_to_groups():
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
                "text": "/start",
                "entities": [{"type": "bot_command", "offset": 0, "length": 6}],
            },
        }
    )
    await dispatcher.feed_update(bot, update)
    assert not session.sent
