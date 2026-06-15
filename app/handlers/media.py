"""Обробник фото зі штрих-кодами ТТН."""
import asyncio
import logging
import os
from datetime import datetime

from aiogram import F, Router
from aiogram.types import Message

from .. import settings
from ..services.barcode import decode_barcodes
from ..services.ttn import TTNService, extract_ttn
from ..storage.users import AdminNotifier, UserRepository

router = Router()
log = logging.getLogger(__name__)


def _maybe_save_debug(image_bytes: bytes) -> None:
    if not settings.DEBUG_SAVE_IMAGES:
        return
    try:
        os.makedirs(settings.DEBUG_IMAGE_DIR, exist_ok=True)
        path = os.path.join(
            settings.DEBUG_IMAGE_DIR,
            datetime.now().strftime("%Y%m%d_%H%M%S_%f") + ".jpg",
        )
        with open(path, "wb") as f:
            f.write(image_bytes)
        log.info("DEBUG: saved incoming photo -> %s", path)
    except Exception as e:  # noqa: BLE001
        log.warning("DEBUG save failed: %s", e)


@router.message(F.photo)
async def handle_barcode_image(
    message: Message,
    users: UserRepository,
    ttn: TTNService,
    notifier: AdminNotifier,
) -> None:
    chat_id = str(message.chat.id)
    user = users.get(chat_id)
    if not user.role:
        await message.answer("Спочатку встановіть роль за допомогою /start")
        return

    try:
        buffer = await message.bot.download(message.photo[-1])
        image_bytes = buffer.read()
        _maybe_save_debug(image_bytes)
        barcodes = await asyncio.to_thread(decode_barcodes, image_bytes)
    except Exception as e:
        await message.answer("❌ Помилка обробки зображення, спробуйте ще раз!")
        log.exception("Error in handle_barcode_image for chat %s: %s", chat_id, e)
        await notifier.notify(f"Error in handle_barcode_image for chat {chat_id}: {e}")
        return

    if not barcodes:
        await message.answer("❌ Не вдалося розпізнати штрих-коди!")
        return

    success_count = 0
    error_count = 0
    for raw in barcodes:
        try:
            ttn_num = extract_ttn(raw)
            if ttn_num is None:
                log.info("Відсіяно штрих-код (не схожий на ТТН): %r", raw)
                continue
            await ttn.handle_ttn(chat_id, ttn_num, user.username, user.role)
            success_count += 1
        except Exception as e:
            error_count += 1
            log.warning("Помилка обробки штрих-коду %r: %s", raw, e)

    await message.answer(
        f"Оброблено штрих-кодів: успішно: {success_count}, з помилками: {error_count}"
    )
