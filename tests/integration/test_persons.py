"""Интеграционные тесты: sync, перематчинг, файлы человека."""
import uuid

import pytest
from PIL import Image

from common.settings import settings
from db.connector import AsyncSession
from repositories.analysis import claim_tasks
from repositories.faces import get_faces_for_file, rematch_faces
from repositories.persons import (
    add_person_embedding,
    get_person_catalog_file_ids,
    list_people,
    upsert_person_name,
    upsert_person_ref,
)
from repositories.scanned_files import set_catalog_file_id
from services.model import Detection
from services.scanner import scan_folder
from worker.processors import faces as faces_processor

EMBEDDING_ONE = [1.0] + [0.0] * 511


@pytest.mark.usefixtures('apply_migrations')
async def test_sync_rematches_auto_faces(scan_dirs, monkeypatch):
    storage_id, photos, _ = scan_dirs
    Image.new('RGB', (100, 100), (255, 0, 0)).save(photos / 'p.jpg', 'JPEG')
    monkeypatch.setattr(
        faces_processor,
        'detect_and_embed',
        lambda bgr, det_score_min: [
            Detection(bbox=(10.0, 10.0, 60.0, 60.0), det_score=0.9, embedding=EMBEDDING_ONE)
        ],
    )

    async with AsyncSession() as session:
        await scan_folder(session, storage_id)
        tasks = await claim_tasks(session, 'faces', 10, settings.LOCK_TIMEOUT_SEC)
    await faces_processor.process_faces_task(tasks[0])

    person_id = uuid.uuid4()
    async with AsyncSession() as session:
        await upsert_person_ref(session, person_id)
        await upsert_person_name(session, person_id, 'Папа')
        await add_person_embedding(session, person_id, EMBEDDING_ONE)
        await session.commit()

        matched = await rematch_faces(session)
        assert matched == 1
        face = (await get_faces_for_file(session, tasks[0].file_id))[0]
        assert face.person_id == person_id


@pytest.mark.usefixtures('apply_migrations')
async def test_person_files_returns_linked_catalog_ids(scan_dirs, monkeypatch):
    storage_id, photos, _ = scan_dirs
    Image.new('RGB', (100, 100), (255, 0, 0)).save(photos / 'p.jpg', 'JPEG')
    monkeypatch.setattr(
        faces_processor,
        'detect_and_embed',
        lambda bgr, det_score_min: [
            Detection(bbox=(10.0, 10.0, 60.0, 60.0), det_score=0.9, embedding=EMBEDDING_ONE)
        ],
    )

    async with AsyncSession() as session:
        await scan_folder(session, storage_id)
        tasks = await claim_tasks(session, 'faces', 10, settings.LOCK_TIMEOUT_SEC)
    await faces_processor.process_faces_task(tasks[0])

    person_id = uuid.uuid4()
    catalog_file_id = uuid.uuid4()
    async with AsyncSession() as session:
        face = (await get_faces_for_file(session, tasks[0].file_id))[0]
        face.person_id = person_id
        await set_catalog_file_id(session, tasks[0].file_id, catalog_file_id)
        await session.commit()

        ids, cursor = await get_person_catalog_file_ids(session, person_id)
        assert ids == [catalog_file_id]
        assert cursor is None


@pytest.mark.usefixtures('apply_migrations')
async def test_list_people_pagination_and_search():
    p1 = uuid.uuid4()
    p2 = uuid.uuid4()
    p3 = uuid.uuid4()

    async with AsyncSession() as session:
        await upsert_person_name(session, p1, 'Anna')
        await upsert_person_name(session, p1, 'Аня')
        await upsert_person_name(session, p2, 'Boris')
        await upsert_person_name(session, p3, 'Vera')
        await session.commit()

        # список и сортировка по первому имени (Anna < Boris < Vera)
        items, total = await list_people(session, limit=100, offset=0)
        assert total == 3
        assert [it['person_id'] for it in items] == [p1, p2, p3]
        assert items[0]['names'] == ['Anna', 'Аня']

        # пагинация
        page1, total1 = await list_people(session, limit=2, offset=0)
        page2, total2 = await list_people(session, limit=2, offset=2)
        assert total1 == 3 and total2 == 3
        assert [it['person_id'] for it in page1] == [p1, p2]
        assert [it['person_id'] for it in page2] == [p3]

        # поиск: case-insensitive по любому имени
        found, found_total = await list_people(session, limit=100, offset=0, search='anna')
        assert found_total == 1
        assert found[0]['person_id'] == p1

        # поиск по второму имени (алиасу)
        found, found_total = await list_people(session, limit=100, offset=0, search='ня')
        assert found_total == 1
        assert found[0]['person_id'] == p1


@pytest.mark.usefixtures('apply_migrations')
async def test_people_endpoint():
    import httpx

    from api.app import app

    p1 = uuid.uuid4()
    p2 = uuid.uuid4()
    async with AsyncSession() as session:
        await upsert_person_name(session, p1, 'Anna')
        await upsert_person_name(session, p2, 'Boris')
        await session.commit()

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url='http://test') as client:
        headers = {'X-API-Key': settings.API_KEY}

        resp = await client.get('/people', headers=headers)
        assert resp.status_code == 200
        body = resp.json()
        assert body['total'] == 2
        assert body['limit'] == 100
        assert body['offset'] == 0
        assert body['items'] == [
            {'person_id': str(p1), 'names': ['Anna']},
            {'person_id': str(p2), 'names': ['Boris']},
        ]

        resp = await client.get('/people', params={'search': 'bor'}, headers=headers)
        body = resp.json()
        assert body['total'] == 1
        assert body['items'][0]['person_id'] == str(p2)


@pytest.mark.usefixtures('apply_migrations')
async def test_person_candidates_filters_and_sorting():
    from sqlalchemy import text

    from repositories.faces import (
        add_cluster_rejection,
        create_cluster,
        get_person_candidates,
    )

    person_id = uuid.uuid4()
    other_person = uuid.uuid4()

    async with AsyncSession() as session:
        await upsert_person_name(session, person_id, 'Аня')
        await add_person_embedding(session, person_id, [1.0] + [0.0] * 511)

        top = await create_cluster(session, [1.0] + [0.0] * 511)  # sim 1.0
        second = await create_cluster(session, [1.0, 1.0] + [0.0] * 510)  # sim ~0.707
        assigned = await create_cluster(session, [1.0] + [0.0] * 511)
        ignored = await create_cluster(session, [1.0] + [0.0] * 511)
        rejected = await create_cluster(session, [1.0] + [0.0] * 511)

        # назначенный — исключается
        await session.execute(
            text(
                f'UPDATE {settings.ANALYSIS_SCHEMA}.face_clusters '
                f'SET person_id = :pid WHERE id = :cid'
            ),
            {'pid': other_person, 'cid': assigned},
        )
        # ignored — исключается
        await session.execute(
            text(
                f'UPDATE {settings.ANALYSIS_SCHEMA}.face_clusters '
                f'SET ignored = true WHERE id = :cid'
            ),
            {'cid': ignored},
        )
        # отклонённый — исключается
        await add_cluster_rejection(session, person_id, rejected)
        await session.commit()

        items, total = await get_person_candidates(session, person_id, limit=20)
        assert total == 2
        assert [it['cluster_id'] for it in items] == [top, second]
        assert items[0]['similarity'] > items[1]['similarity']


@pytest.mark.usefixtures('apply_migrations')
async def test_reject_cluster_idempotent():
    from repositories.faces import add_cluster_rejection

    person_id = uuid.uuid4()
    cluster_id = 12345  # логическая связь, FK нет

    async with AsyncSession() as session:
        assert await add_cluster_rejection(session, person_id, cluster_id) is True
        assert await add_cluster_rejection(session, person_id, cluster_id) is False
        await session.commit()
