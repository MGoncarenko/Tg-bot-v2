"""Ізольований тест декодера штрих-кодів.

Прогоняє app/services/barcode.decode_barcodes на переданих фото й друкує
результат. Головне — перевірити ТТН, що раніше НЕ читались pyzbar.

Запуск:
    python -m scripts.test_barcode path/to/img1.jpg path/to/img2.png ...
    python -m scripts.test_barcode samples/   # усі зображення з папки
"""
import sys
from pathlib import Path

from app.services.barcode import decode_barcodes

_EXTS = {".jpg", ".jpeg", ".png", ".bmp", ".webp", ".tif", ".tiff"}


def _iter_paths(args):
    for arg in args:
        p = Path(arg)
        if p.is_dir():
            yield from (f for f in sorted(p.iterdir()) if f.suffix.lower() in _EXTS)
        else:
            yield p


def main(args) -> None:
    paths = list(_iter_paths(args))
    if not paths:
        print("Передайте шляхи до зображень або папку з ними.")
        return
    ok = 0
    for path in paths:
        try:
            codes = decode_barcodes(path.read_bytes())
        except Exception as e:  # noqa: BLE001
            print(f"[ERR ] {path.name}: {e}")
            continue
        if codes:
            ok += 1
            print(f"[ OK ] {path.name}: {codes}")
        else:
            print(f"[MISS] {path.name}: не зчитано")
    print(f"\nЗчитано {ok}/{len(paths)}")


if __name__ == "__main__":
    main(sys.argv[1:])
