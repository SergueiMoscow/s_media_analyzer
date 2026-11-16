"""Юнит-тесты вырезок лиц (services/crops.py)."""
import io

from PIL import Image

from services.crops import resize_jpeg


def test_resize_jpeg_preserves_aspect_ratio():
    landscape = io.BytesIO()
    Image.new('RGB', (200, 100), (255, 0, 0)).save(landscape, 'JPEG')
    out = Image.open(io.BytesIO(resize_jpeg(landscape.getvalue(), 64)))
    assert out.size == (64, 32)  # вписывание без растяжения

    portrait = io.BytesIO()
    Image.new('RGB', (100, 200), (0, 255, 0)).save(portrait, 'JPEG')
    out = Image.open(io.BytesIO(resize_jpeg(portrait.getvalue(), 64)))
    assert out.size == (32, 64)
