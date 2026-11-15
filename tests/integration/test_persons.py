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
