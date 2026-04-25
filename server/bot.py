"""Aiogram bot — entry point with WebApp button and invite links."""
from __future__ import annotations

import os

from aiogram import Bot, Dispatcher, F
from aiogram.client.default import DefaultBotProperties
from aiogram.filters import CommandStart, CommandObject
from aiogram.types import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
    WebAppInfo,
)


def build_dispatcher(webapp_url: str) -> Dispatcher:
    dp = Dispatcher()

    def main_kb(start_param: str | None = None) -> InlineKeyboardMarkup:
        url = webapp_url
        if start_param:
            sep = "&" if "?" in url else "?"
            url = f"{url}{sep}tgWebAppStartParam={start_param}"
        return InlineKeyboardMarkup(inline_keyboard=[[
            InlineKeyboardButton(text="Играть", web_app=WebAppInfo(url=url)),
        ]])

    @dp.message(CommandStart())
    async def start(msg: Message, command: CommandObject) -> None:
        text = (
            "<b>ДУРАК</b>\n"
            "минимализм. ничего лишнего.\n\n"
            "жми «Играть» — попадёшь в комнату."
        )
        await msg.answer(text, reply_markup=main_kb(command.args))

    @dp.message(F.text == "/invite")
    async def invite(msg: Message) -> None:
        bot_user = await msg.bot.me()
        link = f"https://t.me/{bot_user.username}?startapp=create"
        await msg.answer(
            f"кинь ссылку другу — он попадёт в твою комнату:\n<code>{link}</code>"
        )

    return dp


async def run_bot(token: str, webapp_url: str) -> None:
    bot = Bot(token=token, default=DefaultBotProperties(parse_mode="HTML"))
    dp = build_dispatcher(webapp_url)
    await dp.start_polling(bot)
