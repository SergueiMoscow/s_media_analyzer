"""Интеграционные тесты: лица, вырезки, кластеры, имена (требуется БД с pgvector)."""
import uuid

import pytest
from PIL import Image
from sqlalchemy import text

from common.settings import settings
from db.connector import AsyncSession
from repositories.analysis import claim_tasks
from repositories.faces import get_cluster, get_faces_for_file
from repositories.persons import get_names
from services.clustering import assign_cluster_service
from services.model import Detection
from services.scanner import scan_folder
from worker.processors import faces as faces_processor

EMBEDDING_ONE = [1.0] + [0.0] * 511


@pytest.mark.usefixtures('apply_migrations')
async def test_faces_processor_creates_face_cluster_and_crop(scan_dirs, monkeypatch):
    storage_id, photos, faces_dir = scan_dirs
    path = photos / 'photo.jpg'
    Image.new('RGB', (100, 100), (255, 0, 0)).save(path, 'JPEG')

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
        assert len(tasks) == 1

    await faces_processor.process_faces_task(tasks[0])

    async with AsyncSession() as session:
        faces = await get_faces_for_file(session, tasks[0].file_id)
        assert len(faces) == 1
        face = faces[0]
        assert face.cluster_id is not None
        assert face.crop_path is not None
        # вырезка реально записана на диск
        assert (faces_dir / face.crop_path).exists()
        status = await session.scalar(
            text(
                f'SELECT status FROM {settings.ANALYSIS_SCHEMA}.media_analysis '
                f"WHERE file_id = :f AND kind = 'faces'"
            ),
            {'f': tasks[0].file_id},
        )
        assert status == 'done'


@pytest.mark.usefixtures('apply_migrations')
async def test_assign_cluster_and_multiple_names(scan_dirs, monkeypatch):
    storage_id, photos, _ = scan_dirs
    Image.new('RGB', (100, 100), (0, 255, 0)).save(photos / 'p.jpg', 'JPEG')
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
        face = (await get_faces_for_file(session, tasks[0].file_id))[0]
        cluster_id = face.cluster_id

        result = await assign_cluster_service(
            session, cluster_id, person_id, 'Папа', promote=False
        )
        assert result.faces_updated >= 1
        assert result.reference_embedding is not None

        # добавим ещё имена (алиасы)
        from repositories.persons import upsert_person_name

        await upsert_person_name(session, person_id, 'Сергей')
        await upsert_person_name(session, person_id, 'Муж')
        await session.commit()

        names = await get_names(session, person_id)
        assert 'Папа' in names and 'Сергей' in names and 'Муж' in names

        cluster = await get_cluster(session, cluster_id)
        assert cluster.person_id == person_id


@pytest.mark.usefixtures('apply_migrations')
async def test_faces_and_scanned_files_endpoints(scan_dirs, monkeypatch):
    import httpx

    from api.app import app

    storage_id, photos, _ = scan_dirs
    Image.new('RGB', (100, 100), (0, 0, 255)).save(photos / 'p.jpg', 'JPEG')
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
        file_id = tasks[0].file_id
    await faces_processor.process_faces_task(tasks[0])

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url='http://test') as client:
        headers = {'X-API-Key': settings.API_KEY}

        resp = await client.get('/scanned-files', headers=headers)
        assert resp.status_code == 200
        assert resp.json()['total'] == 1

        resp = await client.get(f'/scanned-files/{file_id}/faces', headers=headers)
        assert resp.status_code == 200
        faces = resp.json()
        assert len(faces) == 1
        assert faces[0]['has_crop'] is True
        assert faces[0]['scanned_file_id'] == file_id

        resp = await client.get(f"/faces/{faces[0]['id']}/thumbnail", headers=headers)
        assert resp.status_code == 200
        assert resp.headers['content-type'] == 'image/jpeg'


@pytest.mark.usefixtures('apply_migrations')
async def test_faces_processor_skips_confirmed_duplicate(scan_dirs, monkeypatch):
    from repositories.faces import insert_face

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
        file_id = (
            await session.execute(
                text(f'SELECT id FROM {settings.ANALYSIS_SCHEMA}.scanned_files LIMIT 1')
            )
        ).scalar()
        await insert_face(
            session,
            file_id,
            {'x': 0.1, 'y': 0.1, 'w': 0.5, 'h': 0.5},
            EMBEDDING_ONE,
            0.9,
            cluster_id=None,
            person_id=None,
            match_score=None,
            status='confirmed',
        )
        await session.commit()
        tasks = await claim_tasks(session, 'faces', 10, settings.LOCK_TIMEOUT_SEC)

    await faces_processor.process_faces_task(tasks[0])

    async with AsyncSession() as session:
        faces = await get_faces_for_file(session, file_id, include_rejected=True)
        assert len(faces) == 1  # дубль отброшен, осталась только confirmed
        assert faces[0].status == 'confirmed'


@pytest.mark.usefixtures('apply_migrations')
async def test_faces_processor_skips_unreadable_image(scan_dirs):
    storage_id, photos, _ = scan_dirs
    # файл с расширением изображения, но битый (PIL не может его прочитать)
    (photos / 'broken.jpg').write_bytes(b'not an image')

    async with AsyncSession() as session:
        await scan_folder(session, storage_id)
        tasks = await claim_tasks(session, 'faces', 10, settings.LOCK_TIMEOUT_SEC)
        assert len(tasks) == 1
        file_id = tasks[0].file_id

    await faces_processor.process_faces_task(tasks[0])

    async with AsyncSession() as session:
        status = await session.scalar(
            text(
                f'SELECT status FROM {settings.ANALYSIS_SCHEMA}.media_analysis '
                f"WHERE file_id = :f AND kind = 'faces'"
            ),
            {'f': file_id},
        )
        assert status == 'skipped'


@pytest.mark.usefixtures('apply_migrations')
async def test_thumbnail_returns_404_for_unknown_storage(scan_dirs):
    import httpx

    from api.app import app
    from db.models import Face, ScannedFile

    scan_dirs  # SCAN_ROOTS = {TEST_STORAGE_ID: photos}

    async with AsyncSession() as session:
        scanned = ScannedFile(
            storage_id=uuid.uuid4(),  # нет в SCAN_ROOTS
            folder_path='',
            filename='x.jpg',
            kind='image',
            status='present',
        )
        session.add(scanned)
        await session.flush()
        face = Face(
            file_id=scanned.id,
            bbox_x=0.1,
            bbox_y=0.1,
            bbox_w=0.5,
            bbox_h=0.5,
            embedding=[0.0] * 512,
            det_score=0.9,
            model_name='test',
            analyzer_version=1,
            status='auto',
        )
        session.add(face)
        await session.flush()
        face_id = face.id
        await session.commit()

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url='http://test') as client:
        headers = {'X-API-Key': settings.API_KEY}
        resp = await client.get(f'/faces/{face_id}/thumbnail', headers=headers)
        assert resp.status_code == 404
        assert resp.json()['error']['error_code'] == 'storage_not_configured'
