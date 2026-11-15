"""Реестр файлов анализатора (scanned_files) и путь к файлу на диске."""
import os
from uuid import UUID

from sqlalchemy import func, select, text, update
from sqlalchemy.ext.asyncio import AsyncSession

from common.settings import settings
from db.models import Face, ScannedFile


def full_path(storage_id: UUID, folder_path: str, filename: str) -> str:
    """Абсолютный путь файла в контейнере анализатора (SCAN_ROOTS + относительный)."""
    root = settings.scan_roots.get(str(storage_id))
    if not root:
        raise KeyError(f'storage {storage_id} не найден в SCAN_ROOTS')
    return os.path.join(root, folder_path, filename)


async def get_by_id(session: AsyncSession, file_id: int) -> ScannedFile | None:
    return await session.get(ScannedFile, file_id)


async def get_by_catalog_id(session: AsyncSession, catalog_file_id: UUID) -> ScannedFile | None:
    result = await session.execute(
        select(ScannedFile).where(ScannedFile.catalog_file_id == catalog_file_id)
    )
    return result.scalars().first()


async def get_by_path(
    session: AsyncSession, storage_id: UUID, folder_path: str, filename: str
) -> ScannedFile | None:
    result = await session.execute(
        select(ScannedFile).where(
            ScannedFile.storage_id == storage_id,
            ScannedFile.folder_path == folder_path,
            ScannedFile.filename == filename,
        )
    )
    return result.scalars().first()


async def upsert_file(
    session: AsyncSession,
    storage_id: UUID,
    folder_path: str,
    filename: str,
    size: int,
    mtime_ns: int,
    kind: str,
) -> tuple[ScannedFile, bool, bool]:
    """Вставляет или обновляет файл; возвращает (file, created, changed)."""
    existing = await get_by_path(session, storage_id, folder_path, filename)
    if existing is None:
        scanned = ScannedFile(
            storage_id=storage_id,
            folder_path=folder_path,
            filename=filename,
            size=size,
            mtime_ns=mtime_ns,
            kind=kind,
            status='present',
        )
        session.add(scanned)
        await session.flush()
        return scanned, True, False

    changed = (
        existing.size != size or existing.mtime_ns != mtime_ns or existing.status != 'present'
    )
    existing.size = size
    existing.mtime_ns = mtime_ns
    existing.kind = kind
    existing.status = 'present'
    await session.flush()
    return existing, False, changed


async def list_files(
    session: AsyncSession,
    *,
    storage_id: UUID | None = None,
    folder_path: str | None = None,
    status: str | None = None,
    has_faces: bool | None = None,
    limit: int = 100,
    offset: int = 0,
) -> tuple[list[ScannedFile], int]:
    stmt = select(ScannedFile)
    if storage_id is not None:
        stmt = stmt.where(ScannedFile.storage_id == storage_id)
    if folder_path is not None:
        stmt = stmt.where(ScannedFile.folder_path == folder_path)
    if status is not None:
        stmt = stmt.where(ScannedFile.status == status)
    if has_faces is not None:
        exists = select(Face.id).where(Face.file_id == ScannedFile.id).exists()
        stmt = stmt.where(exists if has_faces else ~exists)

    total = await session.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    result = await session.execute(stmt.order_by(ScannedFile.id).limit(limit).offset(offset))
    return list(result.scalars().all()), total


async def present_in_prefix(
    session: AsyncSession, storage_id: UUID, folder_path: str
) -> list[tuple[int, str, str]]:
    """id, folder_path, filename файлов present под префиксом folder_path."""
    if folder_path:
        stmt = text(
            f"""
            SELECT id, folder_path, filename FROM {settings.ANALYSIS_SCHEMA}.scanned_files
            WHERE storage_id = :sid AND status = 'present'
              AND (folder_path = :prefix OR folder_path LIKE :prefix || '/%')
            """
        )
        result = await session.execute(stmt, {'sid': storage_id, 'prefix': folder_path})
    else:
        stmt = text(
            f"""
            SELECT id, folder_path, filename FROM {settings.ANALYSIS_SCHEMA}.scanned_files
            WHERE storage_id = :sid AND status = 'present'
            """
        )
        result = await session.execute(stmt, {'sid': storage_id})
    return [(row.id, row.folder_path, row.filename) for row in result.all()]


async def mark_missing(session: AsyncSession, file_ids: list[int]) -> int:
    if not file_ids:
        return 0
    result = await session.execute(
        update(ScannedFile).where(ScannedFile.id.in_(file_ids)).values(status='missing')
    )
    return result.rowcount


async def set_catalog_file_id(
    session: AsyncSession, file_id: int, catalog_file_id: UUID | None
) -> None:
    await session.execute(
        update(ScannedFile)
        .where(ScannedFile.id == file_id)
        .values(catalog_file_id=catalog_file_id)
    )
