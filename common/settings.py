import json
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

ROOT_DIR = Path(__file__).parent.parent


class Settings(BaseSettings):
    """Настройки s_media_analyzer (ТЗ v2).

    Переменные окружения задаются в файле ``.env`` (см. ``env.example``).
    """

    ROOT_DIR: Path = ROOT_DIR

    # Подключение к той же PostgreSQL, что и s_media_service (роль analyzer).
    DATABASE_URL: str = ''

    # Схема таблиц анализатора (создаётся миграциями).
    ANALYSIS_SCHEMA: str = 'analysis'

    # Схема каталога s_media_service (таблицы files, storages) — только чтение.
    CATALOG_SCHEMA: str = 'public'

    # JSON-объект: storage_id (uuid) -> путь каталога в контейнере (read-only).
    SCAN_ROOTS: str = ''

    # Каталог для вырезок лиц (вне SCAN_ROOTS, на запись).
    FACES_DIR: str = ''

    # Ключ для заголовка X-API-Key.
    API_KEY: str = ''

    APP_VERSION: str = 'dev'
    SWAGGER_URL: str | None = '/docs'
    REDOC_URL: str | None = None

    # Анализ
    ANALYZER_VERSION: int = 1
    MODEL_NAME: str = 'buffalo_l'
    # Каталог моделей InsightFace (пусто = ~/.insightface/models). В Docker-образе
    # модель предзагружается, MODEL_ROOT указывает на неё.
    MODEL_ROOT: str = ''
    DET_SCORE_MIN: float = 0.6
    MIN_FACE_PX: int = 40
    MAX_IMAGE_SIDE: int = 1600
    T_PERSON: float = 0.45
    T_CLUSTER: float = 0.5

    # Вырезки лиц
    CROP_MARGIN: float = 0.3
    # Дополнительный отступ сверху (доля высоты bbox) — чтобы не обрезать волосы.
    CROP_TOP_MARGIN: float = 0.6
    CROP_MAX_SIDE: int = 256
    CROP_JPEG_QUALITY: int = 90

    # Воркер
    WORKER_CONCURRENCY: int = 1
    WORKER_NICE: int = 10
    WORKER_ACTIVE_HOURS: str = ''
    LOCK_TIMEOUT_SEC: int = 900

    model_config = SettingsConfigDict(
        env_file=ROOT_DIR / '.env',
        env_file_encoding='utf-8',
        extra='allow',
    )

    @property
    def scan_roots(self) -> dict[str, str]:
        """Распарсенный SCAN_ROOTS: storage_id -> путь каталога."""
        if not self.SCAN_ROOTS:
            return {}
        return json.loads(self.SCAN_ROOTS)

    @property
    def faces_dir_path(self) -> Path | None:
        return Path(self.FACES_DIR).resolve() if self.FACES_DIR else None

    def validate_paths(self) -> None:
        """Проверяет SCAN_ROOTS и FACES_DIR; при нарушении — RuntimeError."""
        roots = {storage_id: Path(path).resolve() for storage_id, path in self.scan_roots.items()}
        faces_dir = self.faces_dir_path

        for storage_id, root in roots.items():
            if not root.is_dir():
                raise RuntimeError(f'SCAN_ROOT {storage_id} недоступен на чтение: {root}')
            if faces_dir is None:
                continue
            if faces_dir == root:
                raise RuntimeError(f'FACES_DIR не должен совпадать с SCAN_ROOT {storage_id}')
            if root in faces_dir.parents:
                raise RuntimeError(f'FACES_DIR не должен содержать SCAN_ROOT {storage_id}')
            if faces_dir in root.parents:
                raise RuntimeError(f'FACES_DIR не должен лежать внутри SCAN_ROOT {storage_id}')

        if faces_dir is not None:
            faces_dir.mkdir(parents=True, exist_ok=True)


settings = Settings()
