# INTEGRATION.md — интеграция s_media_analyzer с комплексом s_media

Документ фиксирует, как `s_media_analyzer` встраивается в комплекс `s_media`
(GitHub-пользователь `SergueiMoscow`) и где реализация расходится с ТЗ.
Составлен по итогам изучения репозиториев `s_media_service` и `s_media_api`
(локальные копии в `~/Projects/s_media/`).

---

## Обновление (ТЗ v2, файл `_02.md`)

- Анализатор **не читает** таблицу `files` каталога: он сканирует директории
  (`SCAN_ROOTS`: storage_id → путь) и ведёт собственный реестр
  `analysis.scanned_files`; `catalog_file_id` — связь с каталогом без FK.
- `file_id` в `media_analysis`/`faces`/`media_geo` — `bigint` → `scanned_files.id`.
- Вырезки лиц пишутся в `FACES_DIR` (атомарно, `crop_path`), в каталоги с фото
  ничего не пишется.
- Одному человеку можно дать **несколько имён**: `person_refs` (идентичность) +
  `person_names` (алиасы). Эндпоинты `POST/DELETE /people/{id}/names`.
- Схема каталога настраивается `CATALOG_SCHEMA` (по ТЗ `public`, в s_media_service
  фактически `main` — расхождение, см. `env.example`).
- Сверка с каталогом — `POST /admin/reconcile-catalog` (раздел 9.7 ТЗ).

---

## 1. Таблица файлов s_media_service

В ТЗ таблица названа `public.media_files(id)`. **Реально это `files`**, и она
находится в схеме, задаваемой `DATABASE_SCHEMA` у s_media_service (в его `.env`
это `main`).

| Параметр | ТЗ | Реальность |
| --- | --- | --- |
| Имя таблицы | `media_files` | `files` |
| Схема | `public` | настраиваемая, в `.env` s_media_service — `main` |
| Тип PK | `bigint` | **UUID** (`sa.Uuid()`) |
| Колонка пути | `path` | `name` — **полный абсолютный путь** |
| mime | `mime` | отсутствует |
| размер | `size` | `size` (`integer`) |
| mtime | `mtime` | отсутствует; есть `created` (ctime файла) |

Используемые анализатором колонки `files`:

- `id` (UUID, PK) — тот же идентификатор, что отдаёт фронту/API;
- `name` (text/255) — **полный путь к файлу на диске**;
- `type` (text, ≤4) — расширение без точки (`jpg`, `mp4`, …) — по нему
  определяется «изображение/видео»;
- `size`, `created`, `created_at`, `is_public`, `note`.

Выводы для кода:

- `file_id` во всех таблицах анализатора — **UUID** (не `bigint`);
- «это изображение/видео» определяем по `files.type` (расширение);
- абсолютный путь читаем напрямую из `files.name`.

## 2. Построение абсолютного пути файла

Корневой каталог хранилища — `storages.path`. Но файловая запись уже содержит
полный путь: `files.name = <storages.path>/<относительный путь>` (см.
`repositories/catalog.py::create_file` — туда передаётся `os.path.join(storage.path,
folder_path, filename)`).

Поэтому анализатору **не нужно** конкатенировать корень и относительный путь —
он читает `files.name`. Переменная `MEDIA_ROOT` оставлена для health-check и
для read-only монтирования каталога в контейнер.

## 3. Стек и стиль (перенято из s_media_service)

- **ORM/драйвер:** SQLAlchemy 2.x, **async** (`postgresql+asyncpg`) — как в
  s_media_service; паттерн `DatabaseConnector` + `AsyncSession` (контекстный
  менеджер). Синхронный движок оставлен для Alembic/тестов.
- **Структура проекта:** `api/`, `common/`, `db/`, `repositories/`, `schemas/`,
  `services/`, `tests/`, `alembic/` — **совпадает с s_media_service/шаблоном**,
  а не с пакетом `app/` из раздела 4 ТЗ.
- **Конфигурация:** pydantic-settings, файл `.env`. В ТЗ имена `DATABASE_URL`,
  `API_KEY` и т.д.; в s_media_service — `DB_DSN`, `KEY`. Используем имена ТЗ,
  маппинг: `DATABASE_URL ↔ DB_DSN`, `API_KEY ↔ KEY`, `ANALYSIS_SCHEMA ↔ DATABASE_SCHEMA`.
- **Формат ошибок:** `{"error": {"error_code": ..., "error_message": ...}}`
  (исключения `BadRequest`/`NotFound`/`NotAllowed`/`InternalServerError` из
  `common/exceptions.py`).
- **Префикс URL:** глобального `/api/v1` в комплексе **нет** — обычные пути
  (`/catalog`, `/storages`, …). Эндпоинты анализатора идут без `/api/v1`.
- **Аутентификация:** s_media_service использует заголовок `X-USER-ID` (UUID) и
  поле `key` в теле на запись; глобального API-key middleware нет. Анализатор
  вводит заголовок `X-API-Key` (`API_KEY`) — **расхождение с существующим
  стилем**, требуется доработка в s_media_api при проксировании.

## 4. Как s_media_api находит узлы и ходит в сервис

- Узлы хранятся в Django-модели `Server` (`url`, `name`, `can_add`).
- Проксирование — `requests` на `{server.url}/<путь>` с заголовками `X-USER-ID`
  и `X-REQUEST-ID` (см. `s_media_proxy/proxy_view_mixin.py`).
- Следствие: анализатор вызывается напрямую по `{server.url}/...`, без `/api/v1`,
  и должен принимать `X-USER-ID` (для совместимости) наравне с `X-API-Key`.

## 5. Схема БД анализатора

Отдельная схема `analysis` (настраивается через `ANALYSIS_SCHEMA`). Роль
`analyzer`: `SELECT`/`REFERENCES` на `files`, полные права только на `analysis`.

Таблицы (полностью описаны в `db/models.py` и `alembic/versions/0001_analysis.py`):

- `media_analysis` — очередь/учёт обработки (`file_id UUID`, `kind`, `status`,
  `analyzer_version`, `attempts`, …; `UNIQUE(file_id, kind)`);
- `face_clusters` — кластеры лиц (`centroid vector(512)`, `size`, `person_id`);
- `faces` — лица (`file_id`, `bbox_*`, `embedding vector(512)`, `cluster_id`,
  `person_id`, `match_score`, `status`);
- `person_refs` — кэш глобальных людей из s_media_api;
- `person_ref_embeddings` — эталонные эмбеддинги (`vector(512)`);
- `media_geo` — геоданные (`lat`, `lon`, `alt`, `taken_at`, `source`).

FK на `files` — `ON DELETE CASCADE` (для этого роль `analyzer` получает
`REFERENCES`). Alembic использует отдельную таблицу версий
`alembic_version_analysis` в схеме `analysis`.

Геотеги (реализация `services/geo_service.py`):
- источник `source` = `exif` для фото, `video` для видео;
- дата съёмки без часового пояса хранится как UTC (см. ТЗ 8.4);
- записи `media_geo` с `source='manual'` не перезаписываются (UPSERT с
  `WHERE source <> 'manual'`).

## 6. Расхождения с ТЗ (сводка)

1. `public.media_files` → `{FILES_SCHEMA}.{FILES_TABLE}` (по умолчанию `main.files`).
2. PK файла `bigint` → **UUID**.
3. Колонки `path/mime/mtime` → `name` (полный путь) / `type` (расширение) / `created`.
4. Структура `app/...` → структура шаблона `api/common/db/...`.
5. Префикс `/api/v1` отсутствует.
6. Аутентификация `X-API-Key` введена в анализаторе (в s_media_service её нет).

## 7. Порядок развёртывания на узле

1. s_media_service создаёт свою схему (`main`) и таблицу `files`.
2. Суперпользователь выполняет `docs/db-role.sql` (расширение `vector`, роль
   `analyzer`, схема `analysis`, гранты на `files`).
3. Анализатор накатывает миграции: `alembic upgrade head`.

> В `docker-compose.example.yml` PostgreSQL общий с s_media_service; роль и
> расширение создаются через `docs/db-role.sql`.
