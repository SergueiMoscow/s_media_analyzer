"""Сверка с каталогом s_media_service (раздел 9.7)."""
import os
import logging

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from db.models import ScannedFile
from repositories import catalog

logger = logging.getLogger(__name__)


async def reconcile_catalog(session: AsyncSession) -> int:
    """Связывает scanned_files с каталогом по полному пути; возвращает число связей."""
    linked = 0

    result = await session.execute(
        select(ScannedFile).where(ScannedFile.catalog_file_id.is_(None))
    )
    for scanned in result.scalars().all():
        storage_path = await catalog.get_storage_path(session, scanned.storage_id)
        if storage_path is None:
            logger.warning('storage %s не найден в каталоге', scanned.storage_id)
            continue
        full = os.path.join(storage_path, scanned.folder_path, scanned.filename)
        catalog_id = await catalog.find_catalog_file_id(session, full)
        if catalog_id is not None:
            scanned.catalog_file_id = catalog_id
            linked += 1

    # Сбросить связь, если записи в каталоге больше нет.
    result = await session.execute(
        select(ScannedFile).where(ScannedFile.catalog_file_id.is_not(None))
    )
    for scanned in result.scalars().all():
        if not await catalog.catalog_file_exists(session, scanned.catalog_file_id):
            scanned.catalog_file_id = None

    await session.commit()
    return linked
