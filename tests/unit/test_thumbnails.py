"""Юнит-тест миниатюр лиц."""
import io

from PIL import Image

from services.thumbnails import make_face_thumbnail


def test_make_face_thumbnail(tmp_path):
    path = tmp_path / 'img.jpg'
    Image.new('RGB', (200, 100), color=(255, 0, 0)).save(path, 'JPEG')

    jpeg = make_face_thumbnail(str(path), {'x': 0.25, 'y': 0.25, 'w': 0.5, 'h': 0.5}, size=64)
    assert jpeg[:2] == b'\xff\xd8'  # JPEG magic

    result = Image.open(io.BytesIO(jpeg))
    assert result.size == (64, 64)
