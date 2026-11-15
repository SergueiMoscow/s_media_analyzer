"""Юнит-тест EXIF-ориентаций 1–8 (open_oriented_rgb)."""
from PIL import Image

from imaging import open_oriented_rgb

EXPECTED_SIZES = {
    1: (100, 200),
    2: (100, 200),
    3: (100, 200),
    4: (100, 200),
    5: (200, 100),
    6: (200, 100),
    7: (200, 100),
    8: (200, 100),
}


def test_open_oriented_rgb_orientation(tmp_path):
    for orientation, expected_size in EXPECTED_SIZES.items():
        path = tmp_path / f'o{orientation}.jpg'
        img = Image.new('RGB', (100, 200), (255, 0, 0))
        exif = Image.Exif()
        exif[274] = orientation  # тег Orientation
        img.save(path, 'JPEG', exif=exif)

        opened = open_oriented_rgb(str(path))
        assert opened.size == expected_size, f'orientation {orientation}'
