from logging.config import fileConfig

from sqlalchemy import engine_from_config, pool
from sqlalchemy.sql.ddl import CreateSchema

from alembic import context
from common.settings import settings

# add your model's MetaData object here for 'autogenerate' support
from db import models  # noqa: F401
from db.db import db_url

# this is the Alembic Config object, which provides
# access to the values within the .ini file in use.
config = context.config

# Interpret the config file for Python logging.
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = models.Base.metadata

VERSION_TABLE = 'alembic_version_analysis'


def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode."""
    url = db_url
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={'paramstyle': 'named'},
        version_table=VERSION_TABLE,
        version_table_schema=settings.ANALYSIS_SCHEMA,
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Run migrations in 'online' mode.

    Схема ``settings.ANALYSIS_SCHEMA`` создаётся, если её ещё нет, и все
    миграции применяются внутри этой схемы. Под pytest схема уникальная и
    потом удаляется фикстурой ``apply_migrations``.
    """
    configuration = config.get_section(config.config_ini_section)
    configuration['sqlalchemy.url'] = db_url

    connectable = engine_from_config(
        configuration,
        prefix='sqlalchemy.',
        poolclass=pool.NullPool,
    )

    # Создаём схему анализатора на отдельном autocommit-подключении, чтобы в неё
    # поместилась таблица версий alembic_version_analysis. search_path при этом
    # остаётся по умолчанию (public), поэтому тип vector из расширения pgvector
    # доступен без квалификации схемы.
    with connectable.connect() as setup_conn:
        setup_conn = setup_conn.execution_options(isolation_level='AUTOCOMMIT')
        if not setup_conn.dialect.has_schema(setup_conn, settings.ANALYSIS_SCHEMA):
            setup_conn.execute(CreateSchema(settings.ANALYSIS_SCHEMA))

    # Основное транзакционное подключение для миграций (схема таблиц переводится
    # через schema_translate_map в settings.ANALYSIS_SCHEMA).
    with connectable.connect() as connection:
        connection = connection.execution_options(
            schema_translate_map={None: settings.ANALYSIS_SCHEMA},
        )
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            version_table=VERSION_TABLE,
            version_table_schema=settings.ANALYSIS_SCHEMA,
        )

        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
