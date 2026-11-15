"""Интеграционные тесты эндпоинтов /stats и /queue (требуется БД с pgvector)."""
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from api.app import app
from common.settings import settings
from db.connector import AsyncSession
from db.models import MediaAnalysis
from repositories.analysis import claim_tasks, complete_task
from repositories.scanned_files import get_by_id
from services.scanner import scan_folder


@pytest.fixture
def client(monkeypatch):
    """TestClient без обязательного заголовка X-API-Key."""
    monkeypatch.setattr(settings, 'API_KEY', '')
    return TestClient(app)


@pytest.mark.usefixtures('apply_migrations')
async def test_stats_processing_field(client, scan_dirs):
    storage_id, photos, _ = scan_dirs
    (photos / 'a.jpg').write_bytes(b'fake')
    (photos / 'b.jpg').write_bytes(b'fake')

    async with AsyncSession() as session:
        await scan_folder(session, storage_id)
        tasks = await claim_tasks(session, 'faces', 10, settings.LOCK_TIMEOUT_SEC)
        assert len(tasks) == 1
        file_id = tasks[0].file_id
        scanned = await get_by_id(session, file_id)
        catalog_file_id = scanned.catalog_file_id
        folder_path = scanned.folder_path
        filename = scanned.filename

    resp = client.get('/stats')
    assert resp.status_code == 200
    body = resp.json()
    assert len(body['processing']) == 1
    item = body['processing'][0]
    assert item['scanned_file_id'] == file_id
    assert item['catalog_file_id'] == catalog_file_id
    assert item['storage_id'] == str(storage_id)
    assert item['folder_path'] == folder_path
    assert item['filename'] == filename
    assert item['kind'] == 'faces'
    assert item['attempts'] == 1
    assert item['locked_at'] is not None


@pytest.mark.usefixtures('apply_migrations')
async def test_queue_filters_and_total(client, scan_dirs):
    storage_id, photos, _ = scan_dirs
    for name in ('a.jpg', 'b.jpg', 'c.jpg'):
        (photos / name).write_bytes(b'fake')

    async with AsyncSession() as session:
        await scan_folder(session, storage_id)
        await claim_tasks(session, 'faces', 10, settings.LOCK_TIMEOUT_SEC)
        geo = await claim_tasks(session, 'geo', 10, settings.LOCK_TIMEOUT_SEC)
        await complete_task(session, geo[0].id, 'done')

    # без фильтров — все 6 задач (3 файла × faces/geo)
    body = client.get('/queue').json()
    assert body['total'] == 6
    assert body['limit'] == 50
    assert body['offset'] == 0
    assert len(body['items']) == 6

    # новые поля: storage_id и faces_count (null для geo; 0 — лиц пока нет)
    for it in body['items']:
        assert it['storage_id'] == str(storage_id)
        if it['kind'] == 'faces':
            assert it['faces_count'] == 0
        else:
            assert it['faces_count'] is None

    assert client.get('/queue', params={'kind': 'faces'}).json()['total'] == 3
    assert client.get('/queue', params={'status': 'pending'}).json()['total'] == 4
    assert (
        client.get('/queue', params={'kind': 'faces', 'status': 'pending'}).json()['total']
        == 2
    )
    assert client.get('/queue', params={'kind': 'geo', 'status': 'done'}).json()['total'] == 1


@pytest.mark.usefixtures('apply_migrations')
async def test_queue_pagination_and_order(client, scan_dirs):
    storage_id, photos, _ = scan_dirs
    for name in ('a.jpg', 'b.jpg', 'c.jpg'):
        (photos / name).write_bytes(b'fake')

    async with AsyncSession() as session:
        await scan_folder(session, storage_id)
        rows = await session.execute(select(MediaAnalysis).order_by(MediaAnalysis.id))
        expected = [(t.file_id, t.kind) for t in rows.scalars().all()]

    # сортировка FIFO по media_analysis.id asc
    body = client.get('/queue').json()
    got = [(it['scanned_file_id'], it['kind']) for it in body['items']]
    assert got == expected

    # пагинация: limit/offset стабильно нарезают ту же последовательность
    page1 = client.get('/queue', params={'limit': 2, 'offset': 0}).json()
    page2 = client.get('/queue', params={'limit': 2, 'offset': 2}).json()
    page3 = client.get('/queue', params={'limit': 2, 'offset': 4}).json()
    assert all(p['total'] == 6 for p in (page1, page2, page3))
    assert [it['scanned_file_id'] for it in page1['items']] == [expected[0][0], expected[1][0]]
    assert [it['scanned_file_id'] for it in page2['items']] == [expected[2][0], expected[3][0]]
    assert [it['scanned_file_id'] for it in page3['items']] == [expected[4][0], expected[5][0]]
