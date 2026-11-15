"""Общие зависимости FastAPI."""
from uuid import UUID

from fastapi import Header

from common.exceptions import NotAllowed, NotFound
from common.settings import settings
from db.connector import AsyncSession
from db.models import ScannedFile
from repositories.scanned_files import get_by_catalog_id, get_by_id


async def get_session():
    """Асинхронная сессия БД (схема analysis)."""
    async with AsyncSession() as session:
        yield session


async def require_api_key(x_api_key: str | None = Header(default=None)) -> None:
    """Проверяет заголовок X-API-Key (если API_KEY задан в настройках)."""
    if settings.API_KEY and x_api_key != settings.API_KEY:
        raise NotAllowed(error_code='invalid_key', error_message='Invalid API key')


async def get_scanned_file_or_404(session, file_id: int) -> ScannedFile:
    scanned = await get_by_id(session, file_id)
    if scanned is None:
        raise NotFound(error_code='not_found', error_message='File not found')
    return scanned


async def get_scanned_by_catalog_or_404(session, catalog_file_id: UUID) -> ScannedFile:
    scanned = await get_by_catalog_id(session, catalog_file_id)
    if scanned is None:
        raise NotFound(error_code='not_found', error_message='Catalog file not linked')
    return scanned
