"""Чтение каталога s_media_service (только для сверки, раздел 9.7)."""
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from common.settings import settings


async def get_storage_path(session: AsyncSession, storage_id: UUID) -> str | None:
    stmt = text(f'SELECT path FROM {settings.CATALOG_SCHEMA}.storages WHERE id = :id')
    return (await session.execute(stmt, {'id': storage_id})).scalar()


async def find_catalog_file_id(session: AsyncSession, full_path: str) -> UUID | None:
    stmt = text(f'SELECT id FROM {settings.CATALOG_SCHEMA}.files WHERE name = :name')
    return (await session.execute(stmt, {'name': full_path})).scalar()


async def catalog_file_exists(session: AsyncSession, catalog_file_id: UUID) -> bool:
    stmt = text(f'SELECT 1 FROM {settings.CATALOG_SCHEMA}.files WHERE id = :id')
    return (await session.execute(stmt, {'id': catalog_file_id})).scalar() is not None
