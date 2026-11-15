"""Обнаружение файлов: сканирование SCAN_ROOTS (по диску, не по БД)."""
from uuid import UUID

from common.settings import settings
from db.connector import AsyncSession
from repositories.analysis import requeue_by_version
from services.scanner import scan_folder


async def run_discovery() -> dict:
    """Сканирует корни хранилищ и переоткрывает устаревшие по версии задачи."""
    total = {'registered': 0, 'updated': 0, 'marked_missing': 0, 'queued': 0}
    for storage_id_str in settings.scan_roots:
        async with AsyncSession() as session:
            result = await scan_folder(session, UUID(storage_id_str))
            for key in total:
                total[key] += getattr(result, key)

    async with AsyncSession() as session:
        total['queued'] += await requeue_by_version(session)
        await session.commit()
    return total
