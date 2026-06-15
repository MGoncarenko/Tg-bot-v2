"""Обробник текстового ТТН (НП 10–18 цифр або код PRM-...)."""
from aiogram import F, Router
from aiogram.types import Message

from ..services.ttn import TTNService, extract_ttn
from ..storage.users import UserRepository

router = Router()


@router.message(F.text)
async def handle_text_message(message: Message, users: UserRepository, ttn: TTNService) -> None:
    text = message.text or ""
    if text.startswith("/"):
        return
    ttn_num = extract_ttn(text)
    if ttn_num is None:
        return
    chat_id = str(message.chat.id)
    user = users.get(chat_id)
    if not user.role:
        await message.answer("Спочатку встановіть роль за допомогою /start")
        return
    await ttn.handle_ttn(chat_id, ttn_num, user.username, user.role)
