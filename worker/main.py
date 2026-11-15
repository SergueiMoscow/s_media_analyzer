"""Точка входа воркера: discovery + обработка очереди."""
import asyncio
import logging
import os
import time
from datetime import datetime

from sqlalchemy import text

from common.settings import settings
from db.connector import AsyncSession
from worker.discovery import run_discovery
from worker.processors.faces import process_faces_task
from worker.processors.geo import process_geo_task
from worker.queue import claim

logger = logging.getLogger(__name__)

DISCOVERY_INTERVAL_SEC = 60

# Сколько задач одного вида обрабатывать за один «круг», прежде чем переключиться
# на следующий вид. Не даёт длинной geo-очереди на часы отложить faces.
BATCH_PER_KIND = 50

# Как долго воркер ждёт появления схемы analysis (её накатывает API-контейнер
# через `alembic upgrade head`). После таймаута процесс завершается и
# перезапускается (restart: always).
SCHEMA_WAIT_TIMEOUT_SEC = 600

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


async def wait_for_schema() -> None:
    """Ждёт, пока появится таблица ``analysis.scanned_files``.

    Воркер стартует параллельно с API и может опередить ``alembic upgrade head``,
    поэтому до начала обработки дожидаемся, пока схема будет накатана.
    """
    deadline = time.monotonic() + SCHEMA_WAIT_TIMEOUT_SEC
    while True:
        try:
            async with AsyncSession() as session:
                result = await session.execute(
                    text("SELECT to_regclass('analysis.scanned_files')")
                )
                if result.scalar() is not None:
                    logger.info('schema %s is ready', settings.ANALYSIS_SCHEMA)
                    return
        except Exception as exc:  # pylint: disable=broad-exception-caught
            logger.info('schema not ready yet: %s', exc)
        if time.monotonic() >= deadline:
            raise RuntimeError(
                f'schema {settings.ANALYSIS_SCHEMA} did not appear within '
                f'{SCHEMA_WAIT_TIMEOUT_SEC}s'
            )
        await asyncio.sleep(5)


async def process_batch(kind: str, max_tasks: int | None = None) -> int:
    """Обрабатывает задачи вида ``kind`` (не более ``max_tasks``, если задано)."""
    processed = 0
    while max_tasks is None or processed < max_tasks:
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
    # Перемежаем виды обработки, чтобы очередь одного вида не блокировала другой:
    # за «круг» берём по BATCH_PER_KIND задач каждого вида, пока обе очереди не
    # опустеют. Так faces начинает обрабатываться сразу, а не после всей geo-очереди.
    while True:
        progress = 0
        for kind in PROCESSORS:
            progress += await process_batch(kind, BATCH_PER_KIND)
        if progress == 0:
            break


async def main() -> None:
    logging.basicConfig(level=logging.INFO)
    settings.validate_paths()
    await wait_for_schema()
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
