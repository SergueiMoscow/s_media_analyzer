"""Вырезки лиц: запись в FACES_DIR (атомарно) и чистка осиротевших."""
import io
import os
from pathlib import Path

from PIL import Image

from common.settings import settings
from imaging import open_oriented_rgb


def crop_rel_path(face_id: int) -> str:
    """Относительный путь вырезки: {id // 1000:06d}/{id}.jpg."""
    return f'{face_id // 1000:06d}/{face_id}.jpg'


def crop_abs_path(face_id: int) -> Path:
    assert settings.faces_dir_path is not None
    return settings.faces_dir_path / crop_rel_path(face_id)


def make_crop_bytes(path: str, bbox: dict) -> bytes:
    """Вырезка лица с полями CROP_MARGIN, длинная сторона <= CROP_MAX_SIDE."""
    img = open_oriented_rgb(path)
    width, height = img.size
    x = bbox['x'] * width
    y = bbox['y'] * height
    bw = bbox['w'] * width
    bh = bbox['h'] * height

    pad_x = bw * settings.CROP_MARGIN
    pad_top = bh * settings.CROP_TOP_MARGIN
    pad_bottom = bh * settings.CROP_MARGIN
    left = max(0, int(x - pad_x))
    top = max(0, int(y - pad_top))
    right = min(width, int(x + bw + pad_x))
    bottom = min(height, int(y + bh + pad_bottom))

    crop = img.crop((left, top, right, bottom))
    crop_w, crop_h = crop.size
    scale = min(1.0, settings.CROP_MAX_SIDE / max(crop_w, crop_h))
    if scale < 1.0:
        crop = crop.resize(
            (max(1, int(crop_w * scale)), max(1, int(crop_h * scale))), Image.LANCZOS
        )

    buf = io.BytesIO()
    crop.save(buf, format='JPEG', quality=settings.CROP_JPEG_QUALITY)
    return buf.getvalue()


def resize_jpeg(data: bytes, size: int) -> bytes:
    """Ресайзит JPEG-байты до квадрата size x size."""
    img = Image.open(io.BytesIO(data))
    img = img.resize((size, size), Image.LANCZOS)
    buf = io.BytesIO()
    img.convert('RGB').save(buf, format='JPEG', quality=settings.CROP_JPEG_QUALITY)
    return buf.getvalue()


def thumbnail_from_original(path: str, bbox: dict, size: int) -> bytes:
    """Вырезка лица с полями и ресайз до квадрата size x size."""
    data = make_crop_bytes(path, bbox)
    return resize_jpeg(data, size)


def write_crop(face_id: int, data: bytes) -> str:
    """Атомарно записывает вырезку и возвращает относительный путь."""
    assert settings.faces_dir_path is not None
    rel = crop_rel_path(face_id)
    abs_path = settings.faces_dir_path / rel
    abs_path.parent.mkdir(parents=True, exist_ok=True)
    tmp = abs_path.with_suffix('.tmp')
    tmp.write_bytes(data)
    os.replace(tmp, abs_path)
    return rel


def delete_crop(rel_path: str | None) -> None:
    if not rel_path:
        return
    assert settings.faces_dir_path is not None
    try:
        (settings.faces_dir_path / rel_path).unlink(missing_ok=True)
    except OSError:
        pass


def cleanup_orphan_crops(valid_paths: set[str]) -> int:
    """Удаляет файлы в FACES_DIR, на которые не ссылается ни одна строка faces."""
    assert settings.faces_dir_path is not None
    removed = 0
    for path in settings.faces_dir_path.rglob('*.jpg'):
        rel = str(path.relative_to(settings.faces_dir_path))
        if rel not in valid_paths:
            try:
                path.unlink()
                removed += 1
            except OSError:
                pass
    return removed
