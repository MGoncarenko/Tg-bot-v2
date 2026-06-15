"""Фабрики Bot та Dispatcher + реєстрація роутерів."""
from aiogram import Bot, Dispatcher

from . import settings
from .handlers import commands, media, text


def create_bot() -> Bot:
    return Bot(token=settings.TOKEN)


def create_dispatcher() -> Dispatcher:
    dp = Dispatcher()
    # порядок важливий: команди -> текстові ТТН -> фото
    dp.include_router(commands.router)
    dp.include_router(text.router)
    dp.include_router(media.router)
    return dp
