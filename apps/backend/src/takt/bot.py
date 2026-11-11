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

    @dispatcher.message(Command("start"), F.chat.type == "private")
    async def welcome(message: Message, command: CommandObject) -> None:
        match = re.fullmatch(r"friend_([A-Za-z0-9_-]{32,64})", command.args or "")
        url = public_url
        if match:
            parts = urlsplit(public_url)
            query = [(key, value) for key, value in parse_qsl(parts.query) if key != "invite"]
            query.append(("invite", match.group(1)))
            url = urlunsplit((parts.scheme, parts.netloc, parts.path or "/", urlencode(query), ""))
        text = (
            "Такт считает время вашего рабочего дня.\n\n"
            "Откройте приложение, отметьте приход — и занимайтесь своими делами. "
            "Когда будете уходить, завершите день. Часы сохранятся в статистике.\n\n"
            "Если забыли отметиться вовремя, можно указать фактическое время."
        )
        if match:
            text = (
                "Вас пригласили в друзья в Такте.\n\n"
                "Откройте приложение, чтобы посмотреть приглашение. "
                "Вы сами решаете, добавлять ли человека в друзья."
            )
        await message.answer(
            text,
            reply_markup=InlineKeyboardMarkup(
                inline_keyboard=[
                    [InlineKeyboardButton(text="Открыть Такт", web_app=WebAppInfo(url=url))]
                ]
            ),
        )

    @dispatcher.message(Command("help"), F.chat.type == "private")
    async def help_message(message: Message) -> None:
        await message.answer(
            "Как пользоваться Тактом\n\n"
            "В «Моём дне» нажмите «Отметиться», когда пришли, и завершите день, когда уходите. "
            "Если забыли нажать кнопку, укажите фактическое время. "
            "Случайно завершённый день можно возобновить.\n\n"
            "Перерывы и перекуры отмечаются по желанию. Они входят в общее время "
            "и отдельно видны в статистике.\n\n"
            "В «Статистике» — ваши часы и время после окончания дня. "
            "В «Людях» — друзья и рейтинги. Общий рейтинг включается в настройках "
            "только по вашему желанию.\n\n"
            "Время окончания рабочего дня и тему приложения можно поменять в «Настройках».",
            reply_markup=InlineKeyboardMarkup(
                inline_keyboard=[
                    [InlineKeyboardButton(text="Открыть Такт", web_app=WebAppInfo(url=public_url))]
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
