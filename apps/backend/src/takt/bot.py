"""Telegram entry point for the Mini App."""

import asyncio
import logging
import re
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from aiogram import Bot, Dispatcher, F
from aiogram.filters import Command, CommandObject
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, Message, WebAppInfo

from takt.config import Settings


def make_dispatcher(public_url: str) -> Dispatcher:
    dispatcher = Dispatcher()

    @dispatcher.message(Command("start", "help"), F.chat.type == "private")
    async def welcome(message: Message, command: CommandObject) -> None:
        match = re.fullmatch(r"friend_([A-Za-z0-9_-]{32,64})", command.args or "")
        url = public_url
        if match:
            parts = urlsplit(public_url)
            query = [(key, value) for key, value in parse_qsl(parts.query) if key != "invite"]
            query.append(("invite", match.group(1)))
            url = urlunsplit((parts.scheme, parts.netloc, parts.path or "/", urlencode(query), ""))
        await message.answer(
            "Такт — ваш рабочий день под рукой. "
            "Отмечайте приход и уход, смотрите время и статистику.",
            reply_markup=InlineKeyboardMarkup(
                inline_keyboard=[
                    [InlineKeyboardButton(text="Открыть Такт", web_app=WebAppInfo(url=url))]
                ]
            ),
        )

    return dispatcher


async def run_bot() -> None:
    settings = Settings()
    if settings.bot_token is None or not settings.public_url.startswith("https://"):
        raise RuntimeError("Configure the bot token and public HTTPS URL.")
    bot = Bot(settings.bot_token.get_secret_value())
    dispatcher = make_dispatcher(settings.public_url)
    try:
        webhook = await bot.get_webhook_info()
        if webhook.url:
            raise RuntimeError(
                "This bot already uses a webhook. "
                "Choose a dedicated bot or remove its webhook explicitly."
            )
        await dispatcher.start_polling(bot, allowed_updates=["message"], close_bot_session=False)
    finally:
        await bot.session.close()


if __name__ == "__main__":
    logging.basicConfig(level=logging.WARNING)
    try:
        asyncio.run(run_bot())
    except (RuntimeError, ValueError) as exc:
        raise SystemExit(str(exc)) from None
