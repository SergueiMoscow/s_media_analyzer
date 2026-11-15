import contextlib

from sqlalchemy import Engine, NullPool, create_engine
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker, create_async_engine
from sqlalchemy.ext.asyncio import AsyncSession as AsyncSessionType
from sqlalchemy.orm import Session as SessionType
from sqlalchemy.orm import sessionmaker

from common.settings import settings


class DatabaseConnector:
    @staticmethod
    def get_engine(database_schema: str | None = None) -> Engine:
        db_schema = database_schema or settings.ANALYSIS_SCHEMA
        return create_engine(
            url=settings.DATABASE_URL,
            poolclass=NullPool,
            connect_args={'options': f'-csearch_path={db_schema}'},
        )

    @staticmethod
    def get_async_engine(database_schema: str | None = None) -> AsyncEngine:
        # asyncpg ожидает диалект 'postgresql+asyncpg://'.
        url = settings.DATABASE_URL.replace('postgresql://', 'postgresql+asyncpg://', 1)
        db_schema = database_schema or settings.ANALYSIS_SCHEMA
        return create_async_engine(
            url=url,
            poolclass=NullPool,
            echo=False,
            connect_args={'server_settings': {'search_path': f'{db_schema}, public'}},
        )

    @staticmethod
    def get_session(
        session_engine: Engine | AsyncEngine, is_async: bool = False
    ) -> sessionmaker | async_sessionmaker:
        sessionmaker_func, session_class = (
            (async_sessionmaker, AsyncSessionType) if is_async else (sessionmaker, SessionType)
        )
        return sessionmaker_func(
            bind=session_engine,
            autocommit=False,
            autoflush=False,
            expire_on_commit=False,
            class_=session_class,
        )

    @classmethod
    @contextlib.contextmanager
    def get_sync_session(cls, schema: str | None = None) -> SessionType:
        engine = cls.get_engine(database_schema=schema)
        session = cls.get_session(session_engine=engine)
        with session() as sync_session:
            try:
                yield sync_session
            finally:
                sync_session.close()

    @classmethod
    @contextlib.asynccontextmanager
    async def get_async_session(cls, schema: str | None = None) -> AsyncSessionType:
        """Асинхронный контекстный менеджер подключения к базе данных."""
        session = cls.get_session(
            session_engine=cls.get_async_engine(database_schema=schema), is_async=True
        )
        async with session() as async_session:
            try:
                yield async_session
            finally:
                await async_session.close()


Session = DatabaseConnector.get_sync_session
AsyncSession = DatabaseConnector.get_async_session
