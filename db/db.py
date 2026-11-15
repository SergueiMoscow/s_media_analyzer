import sys
import uuid

from sqlalchemy import create_engine
from sqlalchemy.orm import declarative_base, sessionmaker

from common.settings import settings


def _mutate_schemas_for_tests() -> None:
    """Под pytest каждый процесс получает свою схему, чтобы тесты были изолированы."""
    if 'pytest' in sys.modules:
        suffix = '_test_' + str(uuid.uuid4()).replace('-', '_')
        if '_test_' not in settings.ANALYSIS_SCHEMA:
            settings.ANALYSIS_SCHEMA += suffix


def get_dsn() -> str:
    """Возвращает DSN, мутируя схемы в уникальные тестовые под pytest."""
    _mutate_schemas_for_tests()
    return settings.DATABASE_URL


db_url = get_dsn()

engine = create_engine(
    db_url,
    echo=False,
    pool_size=6,
    max_overflow=10,
    connect_args={'options': f'-csearch_path={settings.ANALYSIS_SCHEMA}'},
)
session = sessionmaker(bind=engine, autocommit=False, autoflush=False)
Base = declarative_base()
