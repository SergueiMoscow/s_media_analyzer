import pytest
from sqlalchemy import inspect

from common.settings import settings
from db.connector import Session

ANALYSIS_TABLES = {
    'scanned_files',
    'media_analysis',
    'face_clusters',
    'faces',
    'person_refs',
    'person_names',
    'person_ref_embeddings',
    'media_geo',
}


@pytest.mark.usefixtures('apply_migrations')
def test_migrations_create_schema_and_tables():
    """apply_migrations должен создать тестовую схему и накатить все миграции."""
    with Session() as session:
        inspector = inspect(session.bind)
        assert inspector.has_schema(settings.ANALYSIS_SCHEMA)
        tables = set(inspector.get_table_names(schema=settings.ANALYSIS_SCHEMA))
        assert ANALYSIS_TABLES <= tables
        assert 'alembic_version_analysis' in tables
