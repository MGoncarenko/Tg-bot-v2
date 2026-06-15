"""Декодування штрих-кодів ТТН — головний компонент реврайту.

Замість одної спроби pyzbar на кольоровому фото використовуємо zxing-cpp
(сильніший на реальних фото під кутом/розмитих) із вбудованими try_rotate/
try_downscale, плюс каскад передобробки OpenCV (grayscale, контраст, апскейл,
повороти 90°/270° для вертикальних кодів).

Ключова логіка: на щільних етикетках (Розетка/НП) поруч кілька кодів — частина
«сміттєва» (короткі внутрішні номери). Тому ми НЕ зупиняємось на першому-ліпшому
коді, а збираємо коди з усіх варіантів і зупиняємось лише коли знайдено
ТТН-подібний (10–18 цифр). Звичайне НП-фото читається з 1-го варіанта (швидко),
складна етикетка — проходить агресивнішу обробку.

Функції синхронні/CPU-важкі — викликати з async через asyncio.to_thread(...).
"""
import logging
import re

import cv2
import numpy as np
import zxingcpp

log = logging.getLogger(__name__)

# Формати, що реально трапляються на ТТН (Нова Пошта — Code128) + поширені сусіди.
_FORMATS = (
    zxingcpp.BarcodeFormat.Code128
    | zxingcpp.BarcodeFormat.Code39
    | zxingcpp.BarcodeFormat.EAN13
    | zxingcpp.BarcodeFormat.ITF
    | zxingcpp.BarcodeFormat.QRCode
)


def _looks_like_ttn(text: str) -> bool:
    digits = re.sub(r"\D", "", text)
    return 10 <= len(digits) <= 18


def _read(img) -> list[str]:
    results = zxingcpp.read_barcodes(
        img,
        formats=_FORMATS,
        try_rotate=True,
        try_downscale=True,
    )
    return [r.text for r in results if r.valid and r.text]


def _variants(img):
    """Дедалі агресивніша передобробка. Порядок: дешеве -> дороге."""
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    clahe = cv2.createCLAHE(clipLimit=3.0, tileGridSize=(8, 8)).apply(gray)
    up = cv2.resize(clahe, None, fx=2, fy=2, interpolation=cv2.INTER_CUBIC)
    yield "color", img                                            # 1) як є
    yield "gray", gray                                            # 2) grayscale
    yield "clahe", clahe                                          # 3) контраст
    yield "clahe+up2x", up                                        # 4) контраст + апскейл
    yield "rot90", cv2.rotate(clahe, cv2.ROTATE_90_CLOCKWISE)     # 5) вертикальні коди
    yield "rot270", cv2.rotate(clahe, cv2.ROTATE_90_COUNTERCLOCKWISE)  # 6) вертикальні коди


def decode_barcodes(image_bytes: bytes) -> list[str]:
    """Повертає список текстів знайдених штрих-кодів (дедуплікований, може бути порожнім).

    Зупиняється рано, щойно з'явився ТТН-подібний код; інакше проходить усі варіанти.
    """
    img = cv2.imdecode(np.frombuffer(image_bytes, np.uint8), cv2.IMREAD_COLOR)
    if img is None:
        log.warning("Не вдалося декодувати зображення (cv2.imdecode -> None).")
        return []

    found: dict[str, None] = {}  # збереження порядку + дедуплікація
    for name, variant in _variants(img):
        for text in _read(variant):
            found.setdefault(text, None)
        if any(_looks_like_ttn(t) for t in found):
            log.info("Штрих-код знайдено на варіанті '%s'. Усі коди: %s", name, list(found))
            return list(found)

    if found:
        log.info("ТТН-подібного коду не знайдено. Прочитані коди: %s", list(found))
    return list(found)
