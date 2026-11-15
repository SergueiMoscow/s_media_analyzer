"""Интеграционные тесты: сканирование и геотеги (требуется БД с pgvector)."""
from datetime import datetime, timezone

import pytest
from sqlalchemy import text

from common.settings import settings
from db.connector import AsyncSession
from repositories.analysis import claim_tasks, get_media_geo, get_stats, upsert_media_geo
from repositories.scanned_files import get_by_id
from services.geo_service import GeoData
from services.scanner import scan_folder
from worker.processors import geo as geo_processor


@pytest.mark.usefixtures('apply_migrations')
async def test_scan_registers_files_and_queues_tasks(scan_dirs):
    storage_id, photos, _ = scan_dirs
    (photos / 'a.jpg').write_bytes(b'fake')
    (photos / 'b.mp4').write_bytes(b'fake')
    (photos / 'c.txt').write_bytes(b'fake')

    async with AsyncSession() as session:
        result = await scan_folder(session, storage_id)
        assert result.registered == 2  # jpg + mp4, txt — other
        rows = await session.execute(
            text(
                f'SELECT kind, count(*) FROM {settings.ANALYSIS_SCHEMA}.media_analysis '
                f'GROUP BY kind ORDER BY kind'
            )
        )
        assert dict(rows.all()) == {'faces': 1, 'geo': 2}


@pytest.mark.usefixtures('apply_migrations')
async def test_geo_processor_upserts_and_marks_done(scan_dirs, monkeypatch):
    storage_id, photos, _ = scan_dirs
    (photos / 'p.jpg').write_bytes(b'fake')
    monkeypatch.setattr(
        geo_processor,
        'extract_geo',
        lambda path, video: GeoData(
            lat=55.75,
            lon=37.61,
            alt=10.0,
            taken_at=datetime(2023, 5, 1, 12, 0, tzinfo=timezone.utc),
        ),
    )

    async with AsyncSession() as session:
        await scan_folder(session, storage_id)
        tasks = await claim_tasks(session, 'geo', 10, settings.LOCK_TIMEOUT_SEC)
        assert len(tasks) == 1

    await geo_processor.process_geo_task(tasks[0])

    async with AsyncSession() as session:
        scanned = await get_by_id(session, tasks[0].file_id)
        geo = await get_media_geo(session, scanned.id)
        assert geo is not None and geo.lat == 55.75 and geo.source == 'exif'
        status = await session.scalar(
            text(
                f'SELECT status FROM {settings.ANALYSIS_SCHEMA}.media_analysis '
                f"WHERE file_id = :f AND kind = 'geo'"
            ),
            {'f': scanned.id},
        )
        assert status == 'done'


@pytest.mark.usefixtures('apply_migrations')
async def test_upsert_geo_does_not_overwrite_manual(scan_dirs):
    storage_id, photos, _ = scan_dirs
    (photos / 'p.jpg').write_bytes(b'fake')

    async with AsyncSession() as session:
        await scan_folder(session, storage_id)
        scanned = await get_by_id(session, (await session.execute(
            text(f'SELECT id FROM {settings.ANALYSIS_SCHEMA}.scanned_files LIMIT 1')
        )).scalar())

        await upsert_media_geo(session, scanned.id, 1.0, 1.0, None, None, 'manual')
        await upsert_media_geo(session, scanned.id, 2.0, 2.0, None, None, 'exif')
        geo = await get_media_geo(session, scanned.id)
        assert geo.lat == 1.0 and geo.source == 'manual'


@pytest.mark.usefixtures('apply_migrations')
async def test_scan_is_idempotent(scan_dirs):
    storage_id, photos, _ = scan_dirs
    (photos / 'p.jpg').write_bytes(b'fake')

    async with AsyncSession() as session:
        first = await scan_folder(session, storage_id)
        second = await scan_folder(session, storage_id)
        assert first.registered == 1
        assert second.registered == 0  # дублей нет


@pytest.mark.usefixtures('apply_migrations')
async def test_geo_search_and_stats(scan_dirs):
    storage_id, photos, _ = scan_dirs
    (photos / 'a.jpg').write_bytes(b'fake')
    (photos / 'b.jpg').write_bytes(b'fake')

    async with AsyncSession() as session:
        await scan_folder(session, storage_id)
        files = (await session.execute(
            text(f'SELECT id FROM {settings.ANALYSIS_SCHEMA}.scanned_files ORDER BY id')
        )).scalars().all()
        await upsert_media_geo(session, files[0], 55.75, 37.61, None, None, 'exif')
        await upsert_media_geo(session, files[1], 40.0, -74.0, None, None, 'exif')

        stats = await get_stats(session)
        assert stats['scanned_files'] == 2
        assert stats['geo_total'] == 2


@pytest.mark.usefixtures('apply_migrations')
async def test_claim_sets_processing_and_not_reclaimed(scan_dirs):
    storage_id, photos, _ = scan_dirs
    (photos / 'p.jpg').write_bytes(b'fake')

    async with AsyncSession() as session:
        await scan_folder(session, storage_id)
        tasks = await claim_tasks(session, 'geo', 10, settings.LOCK_TIMEOUT_SEC)
        assert len(tasks) == 1
        assert tasks[0].status == 'processing'
        assert tasks[0].attempts == 1
        # свежая processing-задача не захватывается повторно
        assert await claim_tasks(session, 'geo', 10, settings.LOCK_TIMEOUT_SEC) == []


@pytest.mark.usefixtures('apply_migrations')
async def test_claim_recovers_stale_processing(scan_dirs):
    storage_id, photos, _ = scan_dirs
    (photos / 'p.jpg').write_bytes(b'fake')

    async with AsyncSession() as session:
        await scan_folder(session, storage_id)
        await claim_tasks(session, 'geo', 10, settings.LOCK_TIMEOUT_SEC)
        # эмулируем зависшую задачу
        await session.execute(
            text(
                f"UPDATE {settings.ANALYSIS_SCHEMA}.media_analysis "
                f"SET locked_at = now() - interval '1 hour' WHERE kind = 'geo'"
            )
        )
        await session.commit()
        tasks = await claim_tasks(session, 'geo', 10, 60)  # LOCK_TIMEOUT=60с < 1ч
        assert len(tasks) == 1
        assert tasks[0].attempts == 2
