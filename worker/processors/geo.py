"""Процессор геотегов (вид 'geo')."""
import asyncio
import logging
import os

from db.connector import AsyncSession
from repositories.analysis import complete_task, record_error, upsert_media_geo
from repositories.scanned_files import full_path, get_by_id
from services.geo_service import extract_geo

logger = logging.getLogger(__name__)

MAX_ATTEMPTS = 3


async def process_geo_task(task) -> None:
    """Обрабатывает одну задачу вида 'geo'."""
    file_id = task.file_id
    task_id = task.id
    attempts = task.attempts or 0
    try:
        async with AsyncSession() as session:
            scanned = await get_by_id(session, file_id)
            if scanned is None:
                await complete_task(session, task_id, 'skipped', 'file not found in DB')
                return

            try:
                path = full_path(scanned.storage_id, scanned.folder_path, scanned.filename)
            except KeyError as exc:
                await complete_task(session, task_id, 'failed', str(exc))
                return
            if not os.path.exists(path):
                await complete_task(session, task_id, 'skipped', 'file missing on disk')
                return

            is_video = scanned.kind == 'video'
            geo = await asyncio.to_thread(extract_geo, path, is_video)
            if geo is None:
                await complete_task(session, task_id, 'skipped', None)
                return

            source = 'video' if is_video else 'exif'
            await upsert_media_geo(
                session, file_id, geo.lat, geo.lon, geo.alt, geo.taken_at, source
            )
            await complete_task(session, task_id, 'done')
    except Exception as exc:  # pylint: disable=broad-exception-caught
        logger.exception('geo task %s failed', task_id)
        async with AsyncSession() as session:
            if attempts >= MAX_ATTEMPTS:
                await complete_task(session, task_id, 'failed', str(exc))
            else:
                await record_error(session, task_id, str(exc))
