"""Точка входа воркера: discovery + обработка очереди."""
import asyncio
import logging
import os
from datetime import datetime

from common.settings import settings
from worker.discovery import run_discovery
from worker.processors.faces import process_faces_task
from worker.processors.geo import process_geo_task
from worker.queue import claim

logger = logging.getLogger(__name__)

DISCOVERY_INTERVAL_SEC = 60

PROCESSORS = {
    'geo': process_geo_task,
    'faces': process_faces_task,
}


def _within_active_hours() -> bool:
    """Окно работы WORKER_ACTIVE_HOURS в формате 'HH-HH' (пусто = всегда)."""
    window = (settings.WORKER_ACTIVE_HOURS or '').strip()
    if not window:
        return True
    try:
        start_str, end_str = window.split('-', 1)
        start_h, end_h = int(start_str), int(end_str)
    except ValueError:
        return True
    hour = datetime.now().hour
    if start_h <= end_h:
        return start_h <= hour < end_h
    return hour >= start_h or hour < end_h  # окно переходит через полночь


async def process_batch(kind: str) -> int:
    processed = 0
    while True:
        tasks = await claim(kind, settings.WORKER_CONCURRENCY, settings.LOCK_TIMEOUT_SEC)
        if not tasks:
            break
        processor = PROCESSORS[kind]
        for task in tasks:
            await processor(task)
            processed += 1
    return processed


async def run_once() -> None:
    await run_discovery()
    for kind in PROCESSORS:
        await process_batch(kind)


async def main() -> None:
    logging.basicConfig(level=logging.INFO)
    settings.validate_paths()
    while True:
        if _within_active_hours():
            try:
                await run_once()
            except Exception:  # pylint: disable=broad-exception-caught
                logger.exception('worker iteration failed')
        await asyncio.sleep(DISCOVERY_INTERVAL_SEC)


if __name__ == '__main__':
    # Понижаем приоритет процесса, чтобы не мешать s_media_service.
    if settings.WORKER_NICE:
        try:
            os.nice(settings.WORKER_NICE)
        except OSError:
            pass
    asyncio.run(main())
