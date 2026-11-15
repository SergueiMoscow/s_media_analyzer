import json
import uuid

from sqlalchemy import text as sa_text

import pytest
from alembic import command
from alembic.config import Config

from common.settings import ROOT_DIR, settings
from db import models  # noqa: F401  # triggers db.db import -> test schema mutation
from db.connector import Session

TEST_STORAGE_ID = uuid.UUID('00000000-0000-0000-0000-000000000001')


@pytest.fixture
def apply_migrations():
    """Накатывает миграции в тестовую схему и удаляет её после теста."""
    assert 'TEST' in settings.ANALYSIS_SCHEMA.upper(), 'Попытка использовать не тестовую схему.'

    alembic_cfg = Config(str(ROOT_DIR / 'alembic.ini'))
    alembic_cfg.set_main_option('script_location', str(ROOT_DIR / 'alembic'))
    command.upgrade(alembic_cfg, 'head')

    yield command, alembic_cfg

    command.downgrade(alembic_cfg, 'base')

    with Session() as session:
        session.execute(sa_text(f'DROP SCHEMA IF EXISTS {settings.ANALYSIS_SCHEMA} CASCADE;'))
        session.commit()


@pytest.fixture
def scan_dirs(tmp_path):
    """Создаёт каталоги для сканирования и вырезок; настраивает SCAN_ROOTS/FACES_DIR."""
    photos = tmp_path / 'photos'
    faces = tmp_path / 'faces'
    photos.mkdir()
    faces.mkdir()
    settings.SCAN_ROOTS = json.dumps({str(TEST_STORAGE_ID): str(photos)})
    settings.FACES_DIR = str(faces)
    return TEST_STORAGE_ID, photos, faces


@pytest.fixture
def catalog_stub():
    """Создаёт заглушку каталога s_media_service (storages, files) в отдельной схеме."""
    schema = 'catalog_' + settings.ANALYSIS_SCHEMA
    settings.CATALOG_SCHEMA = schema
    with Session() as session:
        session.execute(sa_text(f'CREATE SCHEMA IF NOT EXISTS {schema};'))
        session.execute(
            sa_text(
                f'CREATE TABLE IF NOT EXISTS {schema}.storages '
                f'(id uuid PRIMARY KEY, path text);'
            )
        )
        session.execute(
            sa_text(f'CREATE TABLE IF NOT EXISTS {schema}.files (id uuid PRIMARY KEY, name text);')
        )
        session.commit()
    yield schema
    with Session() as session:
        session.execute(sa_text(f'DROP SCHEMA IF EXISTS {schema} CASCADE;'))
        session.commit()
    settings.CATALOG_SCHEMA = 'public'
