"""Работа с изображениями: открытие, EXIF-ориентация, масштаб, конвертация."""
import numpy as np
from PIL import Image, ImageOps


def open_oriented_rgb(path: str) -> Image.Image:
    """Открывает изображение, применяет EXIF-ориентацию и приводит к RGB."""
    with Image.open(path) as img:
        oriented = ImageOps.exif_transpose(img)
        oriented = oriented.convert('RGB')
        oriented.load()
        return oriented.copy()


def resize_to_max_side(img: Image.Image, max_side: int) -> tuple[Image.Image, float]:
    """Уменьшает длинную сторону до max_side; возвращает (изображение, масштаб)."""
    width, height = img.size
    scale = min(1.0, max_side / max(width, height))
    if scale >= 1.0:
        return img, 1.0
    new_size = (max(1, round(width * scale)), max(1, round(height * scale)))
    return img.resize(new_size, Image.LANCZOS), scale


def to_bgr_numpy(img: Image.Image) -> np.ndarray:
    """Конвертирует RGB PIL-изображение в numpy BGR (для InsightFace)."""
    rgb = np.asarray(img, dtype=np.uint8)
    return rgb[:, :, ::-1]
