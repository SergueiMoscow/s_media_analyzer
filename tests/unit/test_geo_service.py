"""Юнит-тесты парсинга геотегов (без БД)."""
from services.geo_service import (
    bbox_for_radius,
    extract_geo_from_exiftool,
    haversine_m,
    parse_alt,
    parse_coordinates,
    parse_quicktime_coords,
    parse_taken_at,
)


def test_parse_coordinates_valid():
    assert parse_coordinates(55.75, 37.61) == (55.75, 37.61)


def test_parse_coordinates_rejects_zero_point():
    assert parse_coordinates(0, 0) is None


def test_parse_coordinates_rejects_out_of_range():
    assert parse_coordinates(91, 0) is None
    assert parse_coordinates(-91, 0) is None
    assert parse_coordinates(0, 181) is None
    assert parse_coordinates(0, -181) is None


def test_parse_coordinates_rejects_missing():
    assert parse_coordinates(None, 1) is None
    assert parse_coordinates(1, None) is None


def test_parse_alt():
    assert parse_alt('123.5') == 123.5
    assert parse_alt(None) is None
    assert parse_alt('abc') is None


def test_parse_taken_at_without_tz_is_utc():
    dt = parse_taken_at('2023:05:01 12:34:56')
    assert dt.isoformat() == '2023-05-01T12:34:56+00:00'


def test_parse_taken_at_with_tz():
    dt = parse_taken_at('2023:05:01 12:34:56+03:00')
    assert dt.utcoffset().total_seconds() == 3 * 3600


def test_parse_taken_at_invalid():
    assert parse_taken_at('not a date') is None
    assert parse_taken_at(None) is None


def test_parse_quicktime_coords():
    assert parse_quicktime_coords('+37.7749-122.4194+10.0/') == (37.7749, -122.4194, 10.0)
    assert parse_quicktime_coords('+55.75+37.61/') == (55.75, 37.61, None)
    assert parse_quicktime_coords('+0+0/') is None  # нулевая точка недействительна


def test_extract_geo_from_exiftool_full():
    geo = extract_geo_from_exiftool(
        {
            'GPSLatitude': 55.75,
            'GPSLongitude': 37.61,
            'GPSAltitude': 10,
            'DateTimeOriginal': '2023:05:01 12:34:56',
        }
    )
    assert geo.lat == 55.75
    assert geo.lon == 37.61
    assert geo.alt == 10
    assert geo.taken_at is not None


def test_extract_geo_from_exiftool_zero_coords():
    assert extract_geo_from_exiftool({'GPSLatitude': 0, 'GPSLongitude': 0}) is None


def test_extract_geo_from_exiftool_quicktime():
    geo = extract_geo_from_exiftool({'GPSCoordinates': '+37.7749-122.4194+10.0/'})
    assert geo.lat == 37.7749
    assert geo.lon == -122.4194
    assert geo.alt == 10.0


def test_haversine_known_distance():
    # ~1.2 км по долготе на широте Москвы.
    distance = haversine_m(55.75, 37.61, 55.75, 37.63)
    assert 1000 < distance < 2000


def test_bbox_for_radius_contains_center():
    bbox = bbox_for_radius(55.75, 37.61, 1000)
    min_lat, max_lat, min_lon, max_lon = bbox
    assert min_lat < 55.75 < max_lat
    assert min_lon < 37.61 < max_lon
