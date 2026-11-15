"""Эндпоинты геоданных."""
from uuid import UUID

from fastapi import APIRouter, Depends, Query

from api.deps import (
    get_scanned_by_catalog_or_404,
    get_scanned_file_or_404,
    get_session,
    require_api_key,
)
from common.exceptions import BadRequest, NotFound
from repositories.analysis import get_media_geo, search_geo
from schemas.geo import GeoOut, GeoPoint
from services.geo_service import bbox_for_radius, haversine_m

router = APIRouter(dependencies=[Depends(require_api_key)])


@router.get('/scanned-files/{file_id}/geo', response_model=GeoOut)
async def scanned_file_geo(file_id: int, session=Depends(get_session)):
    await get_scanned_file_or_404(session, file_id)
    geo = await get_media_geo(session, file_id)
    if geo is None:
        raise NotFound(error_code='not_found', error_message='Geo not found')
    return geo


@router.get('/catalog-files/{catalog_file_id}/geo', response_model=GeoOut)
async def catalog_file_geo(catalog_file_id: UUID, session=Depends(get_session)):
    scanned = await get_scanned_by_catalog_or_404(session, catalog_file_id)
    geo = await get_media_geo(session, scanned.id)
    if geo is None:
        raise NotFound(error_code='not_found', error_message='Geo not found')
    return geo


@router.get('/geo/search', response_model=list[GeoPoint])
async def geo_search(
    session=Depends(get_session),
    lat: float | None = None,
    lon: float | None = None,
    radius_m: float | None = None,
    min_lat: float | None = None,
    min_lon: float | None = None,
    max_lat: float | None = None,
    max_lon: float | None = None,
    include_unindexed: bool = False,
    limit: int = Query(default=100, ge=1, le=5000),
):
    catalog_only = not include_unindexed
    if lat is not None and lon is not None and radius_m is not None:
        if radius_m <= 0:
            raise BadRequest(error_code='incorrect_data', error_message='radius_m must be positive')
        bbox = bbox_for_radius(lat, lon, radius_m)
        rows = await search_geo(
            session,
            min_lat=bbox[0],
            max_lat=bbox[1],
            min_lon=bbox[2],
            max_lon=bbox[3],
            catalog_only=catalog_only,
            limit=limit,
        )
        points = [_to_point(geo) for geo in rows]
        return [p for p in points if haversine_m(lat, lon, p.lat, p.lon) <= radius_m]

    if all(v is not None for v in (min_lat, min_lon, max_lat, max_lon)):
        rows = await search_geo(
            session,
            min_lat=min_lat,
            max_lat=max_lat,
            min_lon=min_lon,
            max_lon=max_lon,
            catalog_only=catalog_only,
            limit=limit,
        )
        return [_to_point(geo) for geo in rows]

    raise BadRequest(error_code='incorrect_data', error_message='Specify lat/lon/radius_m or bbox')


def _to_point(geo):
    return GeoPoint(
        scanned_file_id=geo.scanned_file_id,
        catalog_file_id=geo.catalog_file_id,
        lat=geo.lat,
        lon=geo.lon,
    )
