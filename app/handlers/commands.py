"""Команди бота: /start /Office /Cklad /subscribe /unsubscribe /help.

Тексти й поведінка збережені 1-в-1 із попередньою версією.
"""
import re

from aiogram import Router
from aiogram.filters import Command, CommandStart
from aiogram.types import Message

from ..storage.users import UserRepository

router = Router()

_SUBSCRIBE_INFO = (
    "\n\nВи можете підписатися на щоденний звіт, ввівши команду /subscribe <час> "
    "(наприклад, /subscribe 22:00). Якщо час не вказано – за замовчуванням 22:00. "
    "Відписатися – командою /unsubscribe."
)


@router.message(CommandStart())
async def cmd_start(message: Message, users: UserRepository) -> None:
    chat_id = str(message.chat.id)
    user = users.get(chat_id)
    if user.role:
        await message.answer(
            f"👋 Вітаю! Ваша роль: *{user.role}*.\n\n"
            "Ви можете змінити роль за допомогою:\n"
            "/Office - Офіс 📑\n"
            "/Cklad - Склад 📦" + _SUBSCRIBE_INFO,
            parse_mode="Markdown",
        )
    else:
        await message.answer(
            "Цей бот спрощує роботу з ТТН.\n\n"
            "Оберіть роль:\n"
            "/Office - Офіс 📑\n"
            "/Cklad - Склад 📦" + _SUBSCRIBE_INFO,
            parse_mode="Markdown",
        )


@router.message(Command("Office"))
async def cmd_office(message: Message, users: UserRepository) -> None:
    chat_id = str(message.chat.id)
    user = users.get(chat_id)
    username = user.username or (message.from_user.username or "")
    await users.update(chat_id, "Офіс", username, user.time, user.last_sent)
    await message.answer(
        "✅ Ви обрали роль: *Офіс*.\n\nНадсилайте TTН (код або фото) для перевірки.",
        parse_mode="Markdown",
    )


@router.message(Command("Cklad"))
async def cmd_cklad(message: Message, users: UserRepository) -> None:
    chat_id = str(message.chat.id)
    user = users.get(chat_id)
    username = user.username or (message.from_user.username or "")
    await users.update(chat_id, "Склад", username, user.time, user.last_sent)
    await message.answer(
        "✅ Ви обрали роль: *Склад*.\n\nНадсилайте TTН (код або фото), вони збережуться в буфер.",
        parse_mode="Markdown",
    )


@router.message(Command("subscribe"))
async def cmd_subscribe(message: Message, users: UserRepository) -> None:
    chat_id = str(message.chat.id)
    args = (message.text or "").split()
    sub_time = "22:00"
    if len(args) > 1:
        candidate = args[1]
        if re.match(r"^\d{1,2}:\d{2}$", candidate):
            hour, minute = candidate.split(":")
            sub_time = f"{hour.zfill(2)}:{minute}"
        else:
            await message.answer(
                "Невірний формат часу. Використовуйте формат HH:MM, наприклад, 22:00."
            )
            return
    user = users.get(chat_id)
    role = user.role or "Офіс"
    username = user.username or (message.from_user.username or "")
    await users.update(chat_id, role, username, sub_time, user.last_sent)
    await message.answer(f"Ви успішно підписалися на звіт о {sub_time}.")


@router.message(Command("unsubscribe"))
async def cmd_unsubscribe(message: Message, users: UserRepository) -> None:
    chat_id = str(message.chat.id)
    user = users.get(chat_id)
    if not user.role:
        await message.answer("Спочатку встановіть роль за допомогою /start")
        return
    await users.update(chat_id, user.role, user.username, "", user.last_sent)
    await message.answer("Ви успішно відписалися від звітів.")


@router.message(Command("help"))
async def cmd_help(message: Message) -> None:
    await message.answer(
        "Доступні команди:\n\n"
        "/start - Початкове налаштування бота та вибір ролі.\n"
        "/Office - Встановити роль 'Офіс'.\n"
        "/Cklad - Встановити роль 'Склад'.\n"
        "/subscribe <час> - Підписатися на щоденний звіт (наприклад, /subscribe 22:00). "
        "Якщо час не вказано – за замовчуванням 22:00.\n"
        "/unsubscribe - Відписатися від звітів.\n"
        "/help - Показати це довідкове повідомлення.\n\n"
        "Додатково:\n"
        "• Бот автоматично обробляє TTН, надсилані як текст або фото (штрих-коди).\n"
        "• Для ролі 'Склад' TTН накопичуються у буфер і після 5-секундної затримки "
        "додаткові записи пушаться до Google таблиці.\n"
        "• Щоденний звіт надсилається користувачам, які підписані, з підрахунком TTН за день."
    )
