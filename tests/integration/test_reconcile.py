"""Интеграционные тесты сверки с каталогом."""
import uuid

import pytest
from sqlalchemy import text

from common.settings import settings
from db.connector import AsyncSession
from repositories.scanned_files import get_by_id
from services.reconcile import reconcile_catalog
from services.scanner import scan_folder


@pytest.mark.usefixtures('apply_migrations')
async def test_reconcile_links_catalog(scan_dirs, catalog_stub):
    storage_id, photos, _ = scan_dirs
    (photos / 'p.jpg').write_bytes(b'fake')

    catalog_file_id = uuid.uuid4()
    async with AsyncSession() as session:
        await session.execute(
            text(f'INSERT INTO {settings.CATALOG_SCHEMA}.storages (id, path) VALUES (:sid, :path)'),
            {'sid': storage_id, 'path': str(photos)},
        )
        await session.execute(
            text(f'INSERT INTO {settings.CATALOG_SCHEMA}.files (id, name) VALUES (:fid, :name)'),
            {'fid': catalog_file_id, 'name': str(photos / 'p.jpg')},
        )
        await session.commit()

        await scan_folder(session, storage_id)
        linked = await reconcile_catalog(session)
        assert linked == 1

        scanned = await get_by_id(
            session,
            (
                await session.execute(
                    text(f'SELECT id FROM {settings.ANALYSIS_SCHEMA}.scanned_files LIMIT 1')
                )
            ).scalar(),
        )
        assert scanned.catalog_file_id == catalog_file_id


@pytest.mark.usefixtures('apply_migrations')
async def test_reconcile_resets_missing_link(scan_dirs, catalog_stub):
    storage_id, photos, _ = scan_dirs
    (photos / 'p.jpg').write_bytes(b'fake')

    catalog_file_id = uuid.uuid4()
    async with AsyncSession() as session:
        await session.execute(
            text(f'INSERT INTO {settings.CATALOG_SCHEMA}.storages (id, path) VALUES (:sid, :path)'),
            {'sid': storage_id, 'path': str(photos)},
        )
        await session.commit()
        await scan_folder(session, storage_id)

        # свяжем вручную, а запись каталога удалим — сверка должна сбросить связь
        await session.execute(
            text(f'UPDATE {settings.ANALYSIS_SCHEMA}.scanned_files SET catalog_file_id = :fid'),
            {'fid': catalog_file_id},
        )
        await session.commit()

        await reconcile_catalog(session)
        scanned = await get_by_id(
            session,
            (
                await session.execute(
                    text(f'SELECT id FROM {settings.ANALYSIS_SCHEMA}.scanned_files LIMIT 1')
                )
            ).scalar(),
        )
        assert scanned.catalog_file_id is None
