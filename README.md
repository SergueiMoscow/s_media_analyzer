# s_media_analyzer

Анализатор фото/видео комплекса **s_media**: находит лица на фотографиях,
строит эмбеддинги и кластеры «людей», извлекает геотеги из EXIF фото и
метаданных видео.

Работает на каждом узле рядом с `s_media_service`: читает те же файлы
(только чтение) и ту же PostgreSQL, но пишет только в собственную схему
`analysis`.

## Стек

- Python 3.12, [Poetry](https://python-poetry.org/)
- FastAPI + Uvicorn
- SQLAlchemy 2.x (sync — `psycopg2`, async — `asyncpg`) + Alembic
- PostgreSQL 15+ с расширением **pgvector** (тип `vector(512)`)
- Pydantic v2 / pydantic-settings
- InsightFace (onnxruntime, CPU) + Pillow / pillow-heif + numpy
- exiftool / ffprobe (нативные, ставятся в Dockerfile)

## Структура

```
api/          # FastAPI приложение и роутеры (views)
common/       # настройки, исключения, утилиты
db/           # подключение к БД и ORM-модели (схема analysis)
repositories/ # доступ к данным
schemas/      # Pydantic-схемы
services/     # бизнес-логика
tests/        # тесты
alembic/      # миграции (version_table = alembic_version_analysis)
docs/         # INTEGRATION.md, db-role.sql
```

## Конфигурация

Скопируйте `env.example` в `.env` и заполните. Ключевые переменные:

| Переменная | Назначение | По умолчанию |
| --- | --- | --- |
| `DATABASE_URL` | строка подключения (роль `analyzer`) | — |
| `ANALYSIS_SCHEMA` | схема таблиц анализатора | `analysis` |
| `CATALOG_SCHEMA` | схема каталога s_media_service (files, storages) | `main` |
| `SCAN_ROOTS` | JSON: storage_id → путь каталога (read-only) | — |
| `FACES_DIR` | каталог вырезок лиц (вне SCAN_ROOTS) | — |
| `API_KEY` | ключ для заголовка `X-API-Key` | — |
| `ANALYZER_VERSION` | версия логики/модели анализа | `1` |

Полный список — в `env.example`.

## Быстрый старт

1. Создайте роль БД и схему (см. `docs/db-role.sql`), установите зависимости:

   ```bash
   poetry install
   ```

2. Накатите миграции (создаст схему `analysis` и таблицы):

   ```bash
   alembic upgrade head
   ```

3. Запустите API:

   ```bash
   uvicorn api.app:app --reload
   ```

Либо через Docker:

```bash
docker compose -f docker-compose.example.yml up --build -d
```

## Миграции

Модели описаны в `db/models.py`. Alembic настроен на отдельную таблицу версий
`alembic_version_analysis` в схеме `analysis`. Первая миграция создаёт
расширение `vector`, все таблицы анализатора и HNSW-индексы для эмбеддингов.

## Тесты

Тесты изолированы: фикстура `apply_migrations` под pytest создаёт уникальные
тестовые схемы (для анализатора и заглушки таблицы `files`), накатывает
миграции и удаляет схемы после теста.

```bash
pytest
```

Для тестов нужен PostgreSQL с pgvector (например, `docker compose -f docker-compose.example.yml up -d db`).

## Документация

- `docs/PROJECT.md` — полная картина проекта (архитектура, схема БД, потоки,
  эндпоинты, конфиг, запуск, тесты, решения и подводные камни) — для человека и агента.
- `docs/INTEGRATION.md` — интеграция с комплексом s_media.
- `docs/db-role.sql` — роль БД `analyzer` и права.
