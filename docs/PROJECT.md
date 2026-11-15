# s_media_analyzer — документация проекта

Полная картина проекта для человека и для агента (LLM/разработчика), которому
нужно вносить правки. Дополняет `docs/INTEGRATION.md` (интеграция с комплексом
s_media) и `docs/db-role.sql` (права БД).

---

## 1. Что это

`s_media_analyzer` — компонент комплекса **s_media** (каталогизатор фото/видео).
Работает на каждом узле рядом с `s_media_service` (FastAPI), читает те же файлы
**с диска** (только чтение) и ту же PostgreSQL. Задачи:

- находить лица на фото, нормализованные рамки (bbox) и **вырезки лиц на диске**;
- строить 512-мерные эмбеддинги, группировать в кластеры, присваивать человеку
  **несколько имён**;
- опознавать уже названных людей (по эталонным эмбеддингам из `s_media_api`);
- извлекать геотеги из EXIF фото и метаданных видео.

Анализатор работает **раньше каталога**: сканирует директории и ведёт собственный
реестр файлов. В каталог s_media_service файлы попадают только после «продвижения»
(выполняет `s_media_api`, не этот проект — раздел 11 ТЗ v2).

Стек: Python 3.12, FastAPI, Pydantic v2, SQLAlchemy 2.x (async/asyncpg) + Alembic,
PostgreSQL 15+ с pgvector, InsightFace (`buffalo_l`, onnxruntime CPU), Pillow +
pillow-heif, exiftool/ffprobe, numpy, pytest, Docker.

---

## 2. Архитектура

Один пакет, две точки входа + CLI. Структура — как в `s_media_service`
(шаблон `api/common/db/repositories/schemas/services/tests`), **не** пакет `app/` из ТЗ.

```
api/            # FastAPI: app.py, deps.py, views/ (роуты)
common/         # settings.py (конфиг), exceptions.py
db/             # db.py (Base+engine), connector.py (сессии), models.py
repositories/   # доступ к данным (scanned_files, analysis, faces, persons, catalog)
schemas/        # Pydantic-схемы (common, files, geo, faces, clusters, persons)
services/       # логика (scanner, crops, reconcile, clustering, geo_service,
                #          faces_service, model, thumbnails)
worker/         # main.py, discovery.py, queue.py, processors/{faces,geo}.py
imaging.py      # открытие, EXIF-ориентация, масштаб, RGB->BGR
cli.py          # python -m cli analyze|reconcile|cleanup-crops
alembic/        # миграции (version_table=alembic_version_analysis, schema analysis)
docs/           # INTEGRATION.md, PROJECT.md, db-role.sql
tests/          # unit/, integration/, views/
```

**Точки входа:**
- `api.app:app` — FastAPI (чтение/правка данных анализа, миниатюры).
- `python -m worker.main` — фоновая обработка (discovery + очередь + процессоры).
- `python -m cli` — ручной запуск для проверки.

**Сессии БД** (`db/connector.py`): синхронная (`psycopg2`, для Alembic/тестов) и
асинхронная (`asyncpg`, для приложения/воркера). У asyncpg `search_path =
<ANALYSIS_SCHEMA>, public` задаётся через `server_settings` (важно: так тип `vector`
из `public` доступен без квалификации схемы).

---

## 3. Конфигурация (.env)

Переменные читаются `common/settings.py` (pydantic-settings, файл `.env`).
Полный список — в `env.example`.

| Переменная | Назначение | По умолчанию |
| --- | --- | --- |
| `DATABASE_URL` | подключение (роль `analyzer`) | — |
| `ANALYSIS_SCHEMA` | схема таблиц анализатора | `analysis` |
| `CATALOG_SCHEMA` | схема каталога s_media_service (files, storages) | `main` |
| `SCAN_ROOTS` | JSON: storage_id → путь каталога (read-only) | — |
| `FACES_DIR` | каталог вырезок лиц (вне SCAN_ROOTS, на запись) | — |
| `API_KEY` | ключ заголовка `X-API-Key` (пусто = без проверки) | — |
| `ANALYZER_VERSION` | версия логики/модели (растёт → пересканирование) | `1` |
| `MODEL_NAME` | модель InsightFace | `buffalo_l` |
| `MODEL_ROOT` | каталог моделей InsightFace (пусто = `~/.insightface`) | — |
| `DET_SCORE_MIN` | мин. уверенность детектора | `0.6` |
| `MIN_FACE_PX` | мин. сторона лица в пикселях исходника | `40` |
| `MAX_IMAGE_SIDE` | масштаб перед детекцией | `1600` |
| `T_PERSON` | порог cosine для опознавания по эталону | `0.45` |
| `T_CLUSTER` | порог cosine для присоединения к кластеру | `0.5` |
| `CROP_MARGIN` | поля вокруг лица (бока/низ) | `0.2` |
| `CROP_TOP_MARGIN` | доп. поле сверху (чтобы не резать волосы) | `0.4` |
| `CROP_MAX_SIDE` | длинная сторона вырезки, px | `256` |
| `CROP_JPEG_QUALITY` | качество JPEG | `90` |
| `WORKER_CONCURRENCY` / `WORKER_NICE` / `WORKER_ACTIVE_HOURS` / `LOCK_TIMEOUT_SEC` | параметры воркера | `1`/`10`/—/`900` |

**Проверка путей при старте** (`settings.validate_paths()`): вызывается в lifespan
API, в `worker.main` и в CLI; завершается с ошибкой, если `FACES_DIR` внутри/равен
или содержит SCAN_ROOT, либо SCAN_ROOT недоступен на чтение. `FACES_DIR` создаётся.

## 4. Схема БД (схема `analysis`)

Всё в схеме `analysis`. Роль `analyzer` — полные права на `analysis`, `SELECT` на
каталог. **Внешних ключей на таблицы s_media_service нет**; связь с каталогом —
колонка `catalog_file_id` (uuid, без FK).

| Таблица | Назначение | Ключевые поля |
| --- | --- | --- |
| `scanned_files` | реестр файлов со сканирования | `id` bigserial PK; `storage_id` uuid; `folder_path`; `filename`; `size`; `mtime_ns`; `kind` (image/video/other); `status` (present/missing); `catalog_file_id`; `UNIQUE(storage_id,folder_path,filename)` |
| `media_analysis` | очередь/учёт обработки | `id`; `file_id`→scanned_files (CASCADE); `kind` (faces/geo); `status` (pending/processing/done/failed/skipped); `analyzer_version`; `attempts`; `locked_at`; `error`; `UNIQUE(file_id,kind)` |
| `face_clusters` | кластеры лиц | `id`; `centroid` vector(512); `size`; `person_id` uuid; `ignored` bool |
| `faces` | лица | `id`; `file_id`→scanned_files; `bbox_x/y/w/h` real (0..1); `embedding` vector(512); `det_score`; `model_name`; `analyzer_version`; `cluster_id`; `person_id` uuid; `match_score`; `status` (auto/confirmed/rejected); `crop_path` (относительно FACES_DIR) |
| `person_refs` | кэш глобальных людей (из s_media_api) | `person_id` uuid PK; `synced_at` |
| `person_names` | **имена (алиасы) человека** | `id`; `person_id`→person_refs (CASCADE); `name`; `UNIQUE(person_id,name)` |
| `person_ref_embeddings` | эталонные эмбеддинги людей | `id`; `person_id`; `embedding` vector(512) |
| `media_geo` | геоданные (одна на файл) | `file_id` PK→scanned_files; `lat`; `lon`; `alt`; `taken_at`; `source` (exif/video/manual) |

Индексы: b-tree (`ix_*`) + HNSW (`ix_faces_embedding`, `ix_person_ref_emb`,
`vector_cosine_ops`).

Миграции: `version_table=alembic_version_analysis`, `version_table_schema=analysis`,
таблицы создаются в `analysis` через `schema_translate_map`. Первая миграция делает
`CREATE EXTENSION IF NOT EXISTS vector` (через отдельное autocommit-подключение).

---

## 5. Поток обработки (воркер)

1. **Discovery** (`worker/discovery.py` → `services/scanner.py`): обход папки из
   `SCAN_ROOTS[storage_id]`, для каждого файла `UPSERT` в `scanned_files`
   (по `storage_id, folder_path, filename`). `kind` по расширению
   (изображения: jpg/jpeg/png/webp/heic/heif/tiff/tif/bmp/gif; видео:
   mp4/mov/m4v/avi/mkv/webm/3gp; остальное `other`). Новые/изменённые (`size`,
   `mtime_ns`) → задачи `media_analysis` (`faces` только для изображений, `geo` для
   изображений и видео). Файлы, которых нет под обойдённым префиксом → `missing`.
   Плюс периодический `requeue_by_version` (задачи со старой `analyzer_version` → pending).
   Скрытые файлы и папки (имя начинается с `.`: `._*`, `.DS_Store`, `.localized` и т.п.)
   **не сканируются** — пропускаются и не попадают в `scanned_files`.

2. **Очередь** (`repositories/analysis.py::claim_tasks`): `SELECT … FOR UPDATE
   SKIP LOCKED` по `status='pending'` или `status='processing' AND locked_at <
   now()-LOCK_TIMEOUT`; ставит `processing`, `locked_at`, `attempts+=1`. После 3
   неудач — `failed`, отсутствие файла — `skipped`.

3. **Процессор гео** (`worker/processors/geo.py`): exiftool (`-n -j`), для видео —
   QuickTime-теги, fallback ffprobe; валидация (отбрасывание `(0,0)` и вне
   диапазона); UPSERT в `media_geo` (не перезаписывать `source='manual'`);
   `taken_at` без зоны хранится как UTC.

4. **Процессор лиц** (`worker/processors/faces.py`): открыть+`exif_transpose`+RGB →
   масштаб до `MAX_IMAGE_SIDE` → детекция/эмбеддинги (`services/model.py`) → фильтр
   по `DET_SCORE_MIN` и `MIN_FACE_PX` → нормализация bbox. Повторный анализ:
   `confirmed`/`rejected` сохраняются, дубли новых детекций с IoU>0.5 отбрасываются,
   `auto` удаляются вместе с вырезками. Для каждого нового лица — матчинг по
   эталонам (`T_PERSON`), присоединение/создание кластера (`T_CLUSTER`,
   скользящее среднее центроида с L2-нормировкой), наследование `person_id` от
   названного кластера. Вырезка пишется в `FACES_DIR` атомарно (`os.replace`),
   `crop_path` — `{id//1000:06d}/{id}.jpg`; при сбое файл удаляется, транзакция
   откатывается.

5. **Кластеризация/имена** (`services/clustering.py`, `api/views/persons.py`):
   `assign` назначает кластеру `person_id`, создаёт `person_refs` + `person_names`,
   кладёт центроид в эталоны; `merge` пересчитывает центроид/size и переносит лица;
   `ignore` — пометка «неинтересный». Одному человеку — несколько имён
   (`POST/DELETE /people/{id}/names`).

6. **Сверка с каталогом** (`services/reconcile.py`): для файлов без
   `catalog_file_id` строит полный путь как сервис (`os.path.join(storage.path,
   folder_path, filename)`) и ищет `files.id` по `files.name`; также сбрасывает
   `catalog_file_id`, если записи в каталоге больше нет.

## 6. API-эндпоинты

Аутентификация: заголовок `X-API-Key` (если `API_KEY` задан). Формат ошибок —
`{"error": {"error_code", "error_message"}}` (как в s_media_service). Префикса
`/api/v1` нет.

| Метод/путь | Назначение |
| --- | --- |
| `GET /health` | `{status, db, model, scan_roots, faces_dir}`; 503 при недоступной БД |
| `POST /admin/scan` | обход папки (`ScanRequest` → `ScanResult`), 202 |
| `POST /admin/reconcile-catalog` | сверка с каталогом (`{linked}`) |
| `GET /scanned-files` | список (фильтры `storage_id`, `folder_path`, `status`, `has_faces`, `limit/offset`) → `Page[ScannedFileOut]` |
| `GET /scanned-files/{id}/faces` | лица файла (`include_rejected`) |
| `GET /scanned-files/{id}/geo` | геоданные файла |
| `GET /scanned-files/{id}/analysis` | статусы обработки |
| `POST /scanned-files/{id}/rescan` | повторный анализ, 202 |
| `PUT /scanned-files/catalog-links` | записать связь с каталогом (идемпотентно) |
| `GET /catalog-files/{catalog_file_id}/faces` и `/geo` | данные по уже связанному файлу (404 если нет связи) |
| `PATCH /faces/{id}` | подтвердить/отклонить/назначить/снять; `promote` → `FaceUpdateResult` |
| `GET /faces/{id}/thumbnail` | вырезка (`size`, кэш-заголовки; при отсутствии файла — on-the-fly) |
| `GET /clusters` | фильтры `unassigned`, `ignored`, `min_size`, сортировка по size desc → `Page[ClusterOut]` |
| `GET /clusters/{id}/faces` | лица кластера |
| `POST /clusters/{id}/assign` | назвать кластер (`person_id`, `name`, `promote`) → `ClusterAssignResult` |
| `POST /clusters/{id}/merge` | слить в другой кластер |
| `POST/DELETE /clusters/{id}/ignore` | пометить/снять «неинтересный» |
| `GET /people/{id}` / `POST /people/{id}/names` / `DELETE /people/{id}/names/{name}` | человек и его имена |
| `GET /people/{id}/files` | `catalog_file_id` файлов человека (без rejected), курсорная пагинация |
| `PUT /persons/sync` | справочник людей + эталоны; после — перематчинг (`faces_matched`) |
| `GET /geo/search` | `lat,lon,radius_m` или bbox; `include_unindexed`, `limit` ≤ 5000 |
| `GET /stats` | очередь + счётчики + `processing` (задачи в обработке прямо сейчас) |
| `GET /queue` | детальная очередь: фильтры `kind`/`status`, `limit` (1..500, default 50), `offset`; сортировка по `media_analysis.id` asc → `Page[QueueItemOut]` |

## 7. CLI

```
python -m cli analyze --storage <uuid> --path <folder> [--limit N] [--kinds faces,geo] [--no-save-crops] [--dry-run]
python -m cli reconcile
python -m cli cleanup-crops
```
`analyze` сканирует, прогоняет очередь до опустошения и печатает итог
(зарегистрировано/обновлено/отсутствуют/задач/лиц). `--dry-run` только считает файлы.
`cleanup-crops` удаляет файлы в `FACES_DIR`, на которые не ссылается ни одна строка `faces`.

## 8. Запуск

```bash
# 1. роль БД (один раз, суперпользователем): docs/db-role.sql
# 2. миграции
alembic upgrade head
# 3. API
uvicorn api.app:app --reload
# 4. воркер (отдельный процесс)
python -m worker.main
# 5. ручная проверка
python -m cli analyze --storage <uuid> --path <folder>
```
Docker: `docker compose -f docker-compose.example.yml up --build -d`
(`analyzer-api`, `analyzer-worker`, `db` pgvector; `SCAN_ROOTS` монтируются `:ro`,
`FACES_DIR` — отдельный volume; модель предзагружена в образ, `MODEL_ROOT=/opt/insightface`).

## 9. Тесты

```bash
pytest                      # юнит (без БД) + views
DATABASE_URL=... pytest     # интеграционные — нужна PostgreSQL с pgvector
```
- Юнит (`tests/unit/`): парсинг GPS/(0,0), bbox, IoU, cosine, центроид, миниатюра,
  определение типа файла, нормализация folder_path, EXIF-ориентации 1–8, хелперы модели.
- Интеграционные (`tests/integration/`): сканер (идемпотентность), очередь
  (SKIP LOCKED, зависшие задачи), гео-процессор, лица+вырезки, повторный анализ
  с сохранением confirmed/rejected, assign+имена, sync/перематчинг, сверка каталога,
  эндпоинты.

Фикстуры `tests/conftest.py`: `apply_migrations` (изолированная тестовая схема),
`scan_dirs` (tmp-каталоги + SCAN_ROOTS/FACES_DIR), `catalog_stub` (заглушка каталога).

## 10. Ключевые решения и конвенции

- **Асинхронная БД** (asyncpg) — как в s_media_service; `schema_translate_map` не
  используется для рантайма (задаётся `search_path` через `server_settings`).
- **Векторы**: тип `vector(512)` (pgvector); поиск ближайшего — raw SQL через
  оператор `<=>` и `CAST(:emb AS vector)` (важно: `:emb::vector` ломает привязку
  параметра в SQLAlchemy `text()` — используй `CAST`).
- **`file_id` = bigint** → `scanned_files.id`; `catalog_file_id` = uuid без FK.
- **Много имён на персону**: `person_refs` (идентичность) + `person_names` (алиасы).
  Первое имя — основное (отображается как `person_name`).
- **Вырезки атомарны**: вставка строки (flush → id) → запись во временный файл →
  `os.replace` → `crop_path`. При сбое — удаление созданных файлов + откат.
- **Идемпотентность**: повторный `analyze` не плодит дубли (`UNIQUE(storage_id,
  folder_path, filename)`, `UNIQUE(file_id, kind)`, пересканирование по `size`/`mtime_ns`).
- **Безопасность**: эмбеддинги не возвращаются в API (кроме `reference_embedding`
  при `assign`); в логи эмбеддинги не пишутся.
- Стиль кода: `Makefile` (`format`/`lint`/`test`), flake8 (max-complexity 10),
  black/isort; длинные строки ≤ 100.

## 11. Интеграция с комплексом (см. `docs/INTEGRATION.md`)

- Продвижение файла в каталог выполняет **s_media_api**, не этот проект: оно
  вызывает `POST /clusters/{id}/assign` с `promote=true`, получает `files_to_promote`,
  затем `POST /fileinfo` сервиса и `PUT /scanned-files/catalog-links` обратно.
- `reconcile-catalog` связывает уже существующие в каталоге файлы по полному пути.
- `PUT /persons/sync` получает справочник людей + эталоны от s_media_api.

## 12. Развёртывание

- `docs/db-role.sql` — роль `analyzer` (полные права на `analysis`, `SELECT` на каталог),
  расширение `vector` (суперпользователь).
- `Dockerfile` — нативные зависимости (exiftool, ffmpeg, libheif, libgl) + предзагрузка
  модели InsightFace (`MODEL_ROOT=/opt/insightface`).
- `docker-compose.example.yml` — `analyzer-api` + `analyzer-worker` (один образ, разные
  команды), `db` (pgvector). `SCAN_ROOTS` монтируются `:ro`, `FACES_DIR` — volume.

## 13. Расхождения с ТЗ / подводные камни

- **Схема каталога**: ТЗ говорит `public.files`/`public.storages`, фактически в
  s_media_service — `main`. Сделано настраиваемым (`CATALOG_SCHEMA`).
- **Структура проекта** — шаблон `api/common/db/...`, а не пакет `app/` из ТЗ.
- `storage_id` в `SCAN_ROOTS` должен совпадать с `storages.id` s_media_service,
  чтобы работала сверка; при пустой таблице `storages` это placeholder.
- Переименование/перенос файлов не отслеживается (переименованный файл = новый);
  пропавший файл помечается `missing` (данные не удаляются).
- Параметризованные pytest-тесты с `asyncio_mode=auto` (pytest-asyncio 0.23) падают
  на коллекции — используй цикл в тесте вместо `@pytest.mark.parametrize`.
- `cleanup-crops` нужен, т.к. `ON DELETE CASCADE` в БД не удаляет файлы вырезок с диска.



