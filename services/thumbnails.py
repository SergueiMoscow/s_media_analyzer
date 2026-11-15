"""Миниатюры лиц (JPEG-вырезка с полями)."""
import io

from PIL import Image

from imaging import open_oriented_rgb


def make_face_thumbnail(path: str, bbox: dict, size: int = 160, padding: float = 0.2) -> bytes:
    """Вырезает лицо по нормализованному bbox с полями и отдаёт JPEG-байты."""
    img = open_oriented_rgb(path)
    width, height = img.size

    x = bbox['x'] * width
    y = bbox['y'] * height
    w = bbox['w'] * width
    h = bbox['h'] * height

    pad_x = w * padding
    pad_y = h * padding
    left = max(0, int(x - pad_x))
    top = max(0, int(y - pad_y))
    right = min(width, int(x + w + pad_x))
    bottom = min(height, int(y + h + pad_y))

    crop = img.crop((left, top, right, bottom))
    crop = crop.resize((size, size), Image.LANCZOS)

    buf = io.BytesIO()
    crop.save(buf, format='JPEG', quality=90)
    return buf.getvalue()
