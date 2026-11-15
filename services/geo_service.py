"""Извлечение и валидация геотегов из фото (EXIF) и видео (QuickTime/ffprobe)."""
import json
import math
import re
import subprocess
from dataclasses import dataclass
from datetime import datetime, timezone

EXIFTOOL_TIMEOUT_SEC = 60

# QuickTime GPS / ffprobe location: "+lat+lon+alt/" (знаки и вещественные числа).
_QT_COORDS_RE = re.compile(r'^([+-]\d+(?:\.\d+)?)([+-]\d+(?:\.\d+)?)([+-]\d+(?:\.\d+)?)?/?$')


@dataclass
class GeoData:
    lat: float
    lon: float
    alt: float | None
    taken_at: datetime | None


def parse_coordinates(lat, lon) -> tuple[float, float] | None:
    """Валидирует широту/долготу; (0,0) и значения вне диапазона недействительны."""
    if lat is None or lon is None:
        return None
    try:
        lat = float(lat)
        lon = float(lon)
    except (TypeError, ValueError):
        return None
    if lat == 0 and lon == 0:
        return None
    if not -90 <= lat <= 90:
        return None
    if not -180 <= lon <= 180:
        return None
    return lat, lon


def parse_alt(value) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def parse_taken_at(value) -> datetime | None:
    """Парсит дату съёмки; если часового пояса нет — храним как UTC (см. INTEGRATION.md)."""
    if value is None:
        return None
    text_value = str(value).strip()
    formats = (
        '%Y:%m:%d %H:%M:%S%z',
        '%Y:%m:%d %H:%M:%S',
        '%Y-%m-%d %H:%M:%S%z',
        '%Y-%m-%d %H:%M:%S',
    )
    for fmt in formats:
        try:
            parsed = datetime.strptime(text_value, fmt)
            return parsed if parsed.tzinfo is not None else parsed.replace(tzinfo=timezone.utc)
        except ValueError:
            continue
    return None


def parse_quicktime_coords(value) -> tuple[float, float, float | None] | None:
    """Парсит QuickTime/ffprobe-строку вида '+37.7749-122.4194+10.0/'."""
    if not value:
        return None
    match = _QT_COORDS_RE.match(str(value).strip())
    if not match:
        return None
    coords = parse_coordinates(match.group(1), match.group(2))
    if coords is None:
        return None
    alt = float(match.group(3)) if match.group(3) else None
    return coords[0], coords[1], alt


def extract_geo_from_exiftool(raw: dict) -> GeoData | None:
    """Извлекает валидные координаты и дату из JSON-объекта exiftool."""
    coords = parse_coordinates(raw.get('GPSLatitude'), raw.get('GPSLongitude'))
    alt = parse_alt(raw.get('GPSAltitude'))

    if coords is None:
        quicktime = raw.get('GPSCoordinates') or raw.get('Keys:GPSCoordinates')
        parsed = parse_quicktime_coords(quicktime) if quicktime else None
        if parsed is None:
            return None
        lat, lon, alt = parsed[0], parsed[1], (parsed[2] if parsed[2] is not None else alt)
    else:
        lat, lon = coords

    taken_at = parse_taken_at(raw.get('DateTimeOriginal') or raw.get('CreateDate'))
    return GeoData(lat=lat, lon=lon, alt=alt, taken_at=taken_at)


def run_exiftool(path: str, video: bool = False) -> dict | None:
    """Запускает exiftool и возвращает первый объект JSON или None."""
    tags = ['-GPSLatitude', '-GPSLongitude', '-GPSAltitude', '-DateTimeOriginal', '-CreateDate']
    if video:
        tags += ['-GPSCoordinates', '-Keys:GPSCoordinates']
    cmd = ['exiftool', '-n', '-j', *tags, path]
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=EXIFTOOL_TIMEOUT_SEC)
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
        return None
    if proc.returncode != 0 or not proc.stdout.strip():
        return None
    try:
        data = json.loads(proc.stdout)
    except json.JSONDecodeError:
        return None
    return data[0] if data else None


def run_ffprobe_location(path: str) -> str | None:
    """Возвращает GPS location из ffprobe (формат format.tags.location) или None."""
    cmd = ['ffprobe', '-v', 'quiet', '-print_format', 'json', '-show_format', path]
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=EXIFTOOL_TIMEOUT_SEC)
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
        return None
    if proc.returncode != 0 or not proc.stdout.strip():
        return None
    try:
        data = json.loads(proc.stdout)
    except json.JSONDecodeError:
        return None
    tags = data.get('format', {}).get('tags', {})
    return tags.get('location')


def extract_geo(path: str, video: bool = False) -> GeoData | None:
    """Точка входа: exiftool, для видео при неудаче — ffprobe."""
    raw = run_exiftool(path, video=video)
    if raw:
        geo = extract_geo_from_exiftool(raw)
        if geo is not None:
            return geo
    if video:
        location = run_ffprobe_location(path)
        if location:
            parsed = parse_quicktime_coords(location)
            if parsed is not None:
                return GeoData(lat=parsed[0], lon=parsed[1], alt=parsed[2], taken_at=None)
    return None


EARTH_RADIUS_M = 6371000.0


def bbox_for_radius(lat: float, lon: float, radius_m: float) -> tuple[float, float, float, float]:
    """Bounding box (min_lat, max_lat, min_lon, max_lon) для окружности радиуса radius_m."""
    lat_delta = math.degrees(radius_m / EARTH_RADIUS_M)
    lon_delta = math.degrees(radius_m / (EARTH_RADIUS_M * math.cos(math.radians(lat))))
    return lat - lat_delta, lat + lat_delta, lon - lon_delta, lon + lon_delta


def haversine_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Расстояние по большому кругу в метрах."""
    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlmbd = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlmbd / 2) ** 2
    return 2 * EARTH_RADIUS_M * math.asin(math.sqrt(a))
