# s\_media\_analyzer — техническое задание для генерации кода

Документ предназначен для модели (или разработчика), которая будет создавать приложение с нуля. Сначала прочитай раздел 1 и выполни пункты «Сначала изучить», только потом пиши код.

## 1. Контекст: комплекс s\_media

Каталогизатор фото и видео из трёх приложений (GitHub-пользователь SergueiMoscow):

| Приложение | Репозиторий | Роль |
| --- | --- | --- |
| s\_media\_front | https://github.com/SergueiMoscow/s\_media\_front | Веб-интерфейс |
| s\_media\_api | https://github.com/SergueiMoscow/s\_media\_api | Прослойка между фронтом и одним или несколькими сервисами (узлами) |
| s\_media\_service | https://github.com/SergueiMoscow/s\_media\_service | Работает на компьютере, где лежат файлы; индексирует каталог, хранит его в PostgreSQL |

Новое приложение: **s\_media\_analyzer** — отдельный компонент, который работает на каждом узле рядом с s\_media\_service, читает те же файлы (только чтение) и ту же PostgreSQL, находит лица на фото и извлекает геотеги из фото и видео.

Топология: сейчас 2 узла, планируется 5–10. Предполагается **своя PostgreSQL на каждом узле** (см. раздел 12, допущения). На каждом узле: s\_media\_service + s\_media\_analyzer (два процесса: api и worker). Фронт обращается только к s\_media\_api, а тот проксирует запросы к нужному узлу.

### Сначала изучить (обязательно)

Автор ТЗ не читал код репозиториев. Перед началом работы изучи s\_media\_service и s\_media\_api и зафиксируй в `docs/INTEGRATION.md`:

1. Имя таблицы файлов, её PK и тип (далее в ТЗ: `public.media_files(id)`; **замени на реальное**), колонки пути, типа/mime, размера, mtime.
2. Как строится абсолютный путь файла (корневой каталог + относительный путь?), где хранится конфиг корня.
3. Используемые ORM/драйвер (SQLAlchemy sync/async, psycopg/asyncpg), стиль конфигурации, структуру проекта, линтеры, схему аутентификации между API и сервисом, формат ошибок и префикс URL.
4. Как s\_media\_api находит узлы и ходит в сервис (чтобы эндпоинты анализатора были совместимы по стилю).

Везде, где ТЗ расходится с реальным кодом комплекса, следуй стилю существующих приложений и отмечай расхождение в `docs/INTEGRATION.md`.

## 2. Цели и не-цели

**Цели**

- Обнаружение лиц на фотографиях, нормализованные рамки (bbox) для подсветки на фронте.
- Эмбеддинги лиц, автоматическая группировка в кластеры, присвоение кластеру имени человека.
- Опознавание уже названных людей на новых фото, включая людей, названных на других узлах.
- Извлечение геотегов (lat/lon/alt, дата съёмки) из EXIF фото и метаданных видео.
- Идемпотентная фоновая обработка с учётом версий модели, повторный запуск после обновления.

**Не-цели (первая версия)**

- Лица в видео (только геотеги видео).
- Обязательный GPU (должен работать на CPU).
- Кластеризация лиц между узлами (только локально + эталоны человека).
- Обратное геокодирование (название места).
- Любая запись в файлы каталога и в таблицы s\_media\_service.

## 3. Стек

- Python 3.12, FastAPI, Pydantic v2, Uvicorn.
- SQLAlchemy 2.x + Alembic (sync/async выбрать как в s\_media\_service), PostgreSQL 15+ с расширением **pgvector**.
- InsightFace (модель `buffalo_l`: детекция + эмбеддинг 512-мерный) через onnxruntime (CPU).
- Pillow + pillow-heif (чтение изображений, `ImageOps.exif_transpose`), exiftool (вызов через subprocess, `-n -j`) для EXIF и метаданных видео; ffprobe как запасной вариант для видео.
- numpy. pytest. Docker.

## 4. Архитектура приложения

Один кодовый пакет, две точки входа:

- `api` — FastAPI, только чтение/правка данных анализа, миниатюры лиц.
- `worker` — фоновая обработка: обнаружение новых файлов, анализ, кластеризация.

```
s_media_analyzer/
  app/
    main.py                 # FastAPI app
    config.py               # pydantic-settings
    db/ (session.py, models.py)
    schemas/ (faces.py, geo.py, clusters.py, persons.py, common.py)
    api/ (deps.py, routes_faces.py, routes_geo.py, routes_clusters.py, routes_persons.py, routes_admin.py)
    services/ (faces_service.py, clustering.py, matching.py, geo_service.py, thumbnails.py)
    worker/ (main.py, discovery.py, queue.py, processors/faces.py, processors/geo.py)
    imaging.py              # открытие картинки, EXIF-ориентация, масштаб
  migrations/               # alembic, version_table = alembic_version_analysis, schema analysis
  tests/
  docs/INTEGRATION.md
  Dockerfile
  docker-compose.example.yml
```

### Конфигурация (переменные окружения)

| Переменная | Назначение | По умолчанию |
| --- | --- | --- |
| DATABASE\_URL | Строка подключения (роль analyzer) | — |
| MEDIA\_ROOT | Корень файлов, как в s\_media\_service (монтируется read-only) | — |
| API\_KEY | Ключ для заголовка X-API-Key (или схема из s\_media\_service) | — |
| FILES\_TABLE | Полное имя таблицы файлов | public.media\_files |
| ANALYZER\_VERSION | Целое, растёт при смене логики/модели | 1 |
| MODEL\_NAME | Имя модели InsightFace | buffalo\_l |
| DET\_SCORE\_MIN | Минимальная уверенность детектора | 0.6 |
| MIN\_FACE\_PX | Минимальная сторона лица в пикселях | 40 |
| MAX\_IMAGE\_SIDE | Масштаб изображения перед детекцией | 1600 |
| T\_PERSON | Порог cosine similarity для опознавания человека по эталону | 0.45 |
| T\_CLUSTER | Порог cosine similarity для присоединения к кластеру | 0.5 |
| WORKER\_CONCURRENCY | Число параллельных задач | 1 |
| WORKER\_NICE | Приоритет процесса | 10 |
| WORKER\_ACTIVE\_HOURS | Окно работы, например 22-07 (пусто = всегда) | пусто |
| LOCK\_TIMEOUT\_SEC | Через сколько задача считается зависшей | 900 |

Пороги T\_PERSON и T\_CLUSTER — стартовые значения, их нужно выносить в настройки и подбирать на реальных фото.

## 5. Схема БД

Всё в схеме `analysis`. Отдельная роль БД `analyzer`: `SELECT` на таблицу файлов, полные права только на схему `analysis`. Миграции Alembic с `version_table='alembic_version_analysis'`, `version_table_schema='analysis'`. Первая миграция: `CREATE EXTENSION IF NOT EXISTS vector;`.

```sql
CREATE SCHEMA IF NOT EXISTS analysis;

-- Учёт обработки: идемпотентность, очередь, повторный запуск по версии
CREATE TABLE analysis.media_analysis (
    id            bigserial PRIMARY KEY,
    file_id       bigint NOT NULL REFERENCES public.media_files(id) ON DELETE CASCADE,
    kind          text   NOT NULL CHECK (kind IN ('faces','geo')),
    status        text   NOT NULL DEFAULT 'pending'
                  CHECK (status IN ('pending','processing','done','failed','skipped')),
    analyzer_version integer NOT NULL DEFAULT 0,
    attempts      integer NOT NULL DEFAULT 0,
    error         text,
    locked_at     timestamptz,
    processed_at  timestamptz,
    created_at    timestamptz NOT NULL DEFAULT now(),
    UNIQUE (file_id, kind)
);
CREATE INDEX ix_media_analysis_queue ON analysis.media_analysis (kind, status, locked_at);

-- Кластеры похожих лиц (локальные для узла)
CREATE TABLE analysis.face_clusters (
    id          bigserial PRIMARY KEY,
    centroid    vector(512) NOT NULL,
    size        integer NOT NULL DEFAULT 1,
    person_id   uuid,                       -- глобальный человек, если кластер назван
    created_at  timestamptz NOT NULL DEFAULT now(),
    updated_at  timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX ix_face_clusters_person ON analysis.face_clusters (person_id);

-- Лица
CREATE TABLE analysis.faces (
    id            bigserial PRIMARY KEY,
    file_id       bigint NOT NULL REFERENCES public.media_files(id) ON DELETE CASCADE,
    bbox_x        real NOT NULL CHECK (bbox_x >= 0 AND bbox_x <= 1),
    bbox_y        real NOT NULL CHECK (bbox_y >= 0 AND bbox_y <= 1),
    bbox_w        real NOT NULL CHECK (bbox_w > 0 AND bbox_w <= 1),
    bbox_h        real NOT NULL CHECK (bbox_h > 0 AND bbox_h <= 1),
    embedding     vector(512) NOT NULL,
    det_score     real NOT NULL,
    model_name    text NOT NULL,
    analyzer_version integer NOT NULL,
    cluster_id    bigint REFERENCES analysis.face_clusters(id) ON DELETE SET NULL,
    person_id     uuid,                     -- глобальный человек (без FK, живёт в БД API)
    match_score   real,                     -- similarity, по которому присвоен person/cluster
    status        text NOT NULL DEFAULT 'auto'
                  CHECK (status IN ('auto','confirmed','rejected')),
    created_at    timestamptz NOT NULL DEFAULT now(),
    updated_at    timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX ix_faces_file ON analysis.faces (file_id);
CREATE INDEX ix_faces_person ON analysis.faces (person_id) WHERE person_id IS NOT NULL;
CREATE INDEX ix_faces_cluster ON analysis.faces (cluster_id);
CREATE INDEX ix_faces_embedding ON analysis.faces USING hnsw (embedding vector_cosine_ops);

-- Локальный кэш глобальных людей (синхронизируется из s_media_api)
CREATE TABLE analysis.person_refs (
    person_id  uuid PRIMARY KEY,
    name       text NOT NULL,
    synced_at  timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE analysis.person_ref_embeddings (
    id         bigserial PRIMARY KEY,
    person_id  uuid NOT NULL REFERENCES analysis.person_refs(person_id) ON DELETE CASCADE,
    embedding  vector(512) NOT NULL
);
CREATE INDEX ix_person_ref_emb ON analysis.person_ref_embeddings USING hnsw (embedding vector_cosine_ops);

-- Геоданные (одна запись на файл)
CREATE TABLE analysis.media_geo (
    file_id     bigint PRIMARY KEY REFERENCES public.media_files(id) ON DELETE CASCADE,
    lat         double precision NOT NULL CHECK (lat BETWEEN -90 AND 90),
    lon         double precision NOT NULL CHECK (lon BETWEEN -180 AND 180),
    alt         real,
    taken_at    timestamptz,
    source      text NOT NULL CHECK (source IN ('exif','video','manual')),
    created_at  timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX ix_media_geo_latlon ON analysis.media_geo (lat, lon);
```

Замечания:

- Если тип PK файла в s\_media\_service не `bigint`, подставь реальный.
- PostGIS не требуется. Поиск по радиусу: сначала bounding box по индексу (lat, lon), затем точный расчёт расстояния (haversine) в SQL или Python.
- `person_id` не имеет FK, потому что справочник людей находится в БД s\_media\_api.

## 6. Pydantic-схемы (v2)

```python
from datetime import datetime
from typing import Literal
from uuid import UUID
from pydantic import BaseModel, ConfigDict, Field

FaceStatus = Literal['auto', 'confirmed', 'rejected']
AnalysisKind = Literal['faces', 'geo']
AnalysisStatus = Literal['pending', 'processing', 'done', 'failed', 'skipped']


class BBox(BaseModel):
    """Нормализованные координаты 0..1 относительно изображения после EXIF-ориентации."""
    x: float = Field(ge=0, le=1)
    y: float = Field(ge=0, le=1)
    w: float = Field(gt=0, le=1)
    h: float = Field(gt=0, le=1)


class FaceOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    file_id: int
    bbox: BBox
    det_score: float
    cluster_id: int | None
    person_id: UUID | None
    person_name: str | None = None      # из person_refs, если известен
    match_score: float | None
    status: FaceStatus


class FaceUpdate(BaseModel):
    """PATCH /faces/{id}. Хотя бы одно поле."""
    person_id: UUID | None = None
    status: FaceStatus | None = None
    unassign: bool = False              # снять привязку к человеку


class ClusterOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    size: int
    person_id: UUID | None
    person_name: str | None = None
    sample_face_ids: list[int]          # до 6 лиц с лучшим det_score


class ClusterAssignRequest(BaseModel):
    person_id: UUID
    name: str = Field(min_length=1, max_length=200)


class ClusterAssignResult(BaseModel):
    cluster_id: int
    person_id: UUID
    faces_updated: int
    reference_embedding: list[float] = Field(min_length=512, max_length=512)  # центроид для глобального справочника


class ClusterMergeRequest(BaseModel):
    target_cluster_id: int


class PersonRefIn(BaseModel):
    person_id: UUID
    name: str
    embeddings: list[list[float]] = Field(default_factory=list)   # каждый 512


class PersonSyncRequest(BaseModel):
    persons: list[PersonRefIn]
    full: bool = False                  # true = заменить весь кэш


class PersonSyncResult(BaseModel):
    upserted: int
    removed: int
    faces_matched: int                  # сколько лиц получили person_id после синхронизации


class GeoOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    file_id: int
    lat: float
    lon: float
    alt: float | None
    taken_at: datetime | None
    source: Literal['exif', 'video', 'manual']


class GeoPoint(BaseModel):
    file_id: int
    lat: float
    lon: float


class AnalysisStatusOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    file_id: int
    kind: AnalysisKind
    status: AnalysisStatus
    analyzer_version: int
    attempts: int
    error: str | None
    processed_at: datetime | None


class RescanRequest(BaseModel):
    kinds: list[AnalysisKind] = Field(default_factory=lambda: ['faces', 'geo'])


class PersonFilesOut(BaseModel):
    person_id: UUID
    file_ids: list[int]
    next_cursor: int | None


class StatsOut(BaseModel):
    queue: dict[str, dict[str, int]]    # kind -> status -> count
    faces_total: int
    faces_unassigned: int
    clusters_total: int
    geo_total: int
    analyzer_version: int


class Page[T](BaseModel):
    items: list[T]
    total: int
    limit: int
    offset: int
```

Эмбеддинги лиц **никогда** не возвращаются в ответах API, кроме `reference_embedding` при назначении имени кластеру (нужен для глобального справочника).

## 7. Эндпоинты

Префикс (например `/api/v1`) и формат ошибок взять из s\_media\_service. Аутентификация: заголовок `X-API-Key` (или схема из s\_media\_service). Идентификаторы файлов (`file_id`) те же, что в таблице файлов s\_media\_service.

| Метод и путь | Описание | Запрос / ответ | Ошибки |
| --- | --- | --- | --- |
| GET /health | Проверка БД, наличия модели и MEDIA\_ROOT | `{status, db, model, media_root}` | 503 |
| GET /files/{file\_id}/faces | Лица файла (кроме rejected, если не `include_rejected=true`) | `list[FaceOut]` | 404 если файла нет |
| GET /files/{file\_id}/geo | Геоданные файла | `GeoOut` | 404 если нет |
| GET /files/{file\_id}/analysis | Статус обработки по видам | `list[AnalysisStatusOut]` | 404 |
| POST /files/{file\_id}/analysis/rescan | Поставить файл на повторный анализ | тело `RescanRequest`; 202 | 404 |
| PATCH /faces/{face\_id} | Подтвердить, отклонить, назначить или снять человека | тело `FaceUpdate`; ответ `FaceOut` | 404, 422 |
| GET /faces/{face\_id}/thumbnail | JPEG-вырезка лица с полями 20%; параметр `size` (по умолчанию 160) | image/jpeg, кэш-заголовки | 404 |
| GET /clusters | Кластеры; фильтры `unassigned=true`, `min_size`, `limit`, `offset`; сортировка по размеру убыв. | `Page[ClusterOut]` |  |
| GET /clusters/{id}/faces | Лица кластера (постранично) | `Page[FaceOut]` | 404 |
| POST /clusters/{id}/assign | Назначить кластеру человека: обновляет `cluster.person_id`, `faces.person_id` (кроме rejected), кладёт человека в `person_refs` и центроид в эталоны, статус лиц остаётся `auto` | тело `ClusterAssignRequest`; ответ `ClusterAssignResult` | 404, 409 если кластер уже назван другим |
| POST /clusters/{id}/merge | Слить кластер в другой (пересчёт центроида и size, перенос лиц) | `ClusterMergeRequest`; ответ `ClusterOut` | 404, 409 |
| GET /people/{person\_id}/files | file\_id файлов, где есть этот человек (статус не rejected); курсорная пагинация `limit`, `cursor` | `PersonFilesOut` |  |
| PUT /persons/sync | s\_media\_api передаёт справочник людей и эталонные эмбеддинги; после применения воркер перематчит неназначенные лица | `PersonSyncRequest`; ответ `PersonSyncResult` | 422 |
| GET /geo/search | Поиск по координатам: либо `lat,lon,radius_m`, либо `min_lat,min_lon,max_lat,max_lon`; `limit` до 5000 | `list[GeoPoint]` | 422 |
| GET /stats | Состояние очереди и счётчики | `StatsOut` |  |
| POST /admin/scan | Запустить обнаружение новых файлов вне расписания | 202 |  |

Порядок взаимодействия при назначении имени (для справки, реализует s\_media\_api):

1. Фронт показывает «неопознанные» кластеры узла и просит имя.
2. s\_media\_api создаёт человека (uuid) в своей БД и вызывает `POST /clusters/{id}/assign` на узле.
3. Из ответа берёт `reference_embedding`, сохраняет в справочнике и рассылает `PUT /persons/sync` на остальные узлы.

## 8. Алгоритм воркера

### 8.1 Обнаружение (discovery)

Периодически (раз в N минут и по `POST /admin/scan`) вставлять задачи для новых файлов-изображений и видео, а также для файлов с `analyzer_version` ниже текущей:

```sql
INSERT INTO analysis.media_analysis (file_id, kind)
SELECT f.id, k.kind FROM public.media_files f
CROSS JOIN (VALUES ('faces'), ('geo')) AS k(kind)
WHERE (k.kind = 'geo' OR f.<признак изображения>)
ON CONFLICT (file_id, kind) DO NOTHING;

UPDATE analysis.media_analysis SET status='pending'
WHERE status IN ('done','failed','skipped') AND analyzer_version < :current;
```

Условие «это изображение/видео» определить по реальным колонкам s\_media\_service (mime или расширение). Для `faces` брать только фото.

### 8.2 Очередь

Захват пачки: `SELECT ... FOR UPDATE SKIP LOCKED LIMIT n` по `status='pending'` или `status='processing' AND locked_at < now() - LOCK_TIMEOUT`; установить `processing`, `locked_at`, `attempts += 1`. После 3 неудач статус `failed` с текстом ошибки. Отсутствие файла на диске: `skipped`, а не `failed`.

### 8.3 Обработка лиц

1. Открыть файл по `MEDIA_ROOT` + путь, применить `ImageOps.exif_transpose`, привести к RGB, уменьшить длинную сторону до `MAX_IMAGE_SIDE`.
2. Детекция и эмбеддинги InsightFace. Отбросить лица с `det_score < DET_SCORE_MIN` и стороной меньше `MIN_FACE_PX` (в пикселях исходного изображения).
3. Перевести bbox в нормализованные координаты (0..1) относительно изображения после ориентации; обрезать по границам.
4. Эмбеддинг нормализовать (L2).
5. Если у файла уже есть лица со статусом `confirmed` или `rejected` (повторный анализ), сохранить их, а новые детекции с IoU > 0.5 относительно сохранённых отбросить. Лица со статусом `auto` удалить и записать заново (в одной транзакции).
6. Для каждого нового лица:
   - искать ближайший эталон в `person_ref_embeddings` (cosine similarity); если `>= T_PERSON`, то `person_id` по нему, `match_score`, статус `auto`;
   - независимо от этого найти ближайший центроид в `face_clusters`; если `>= T_CLUSTER`, присоединить к кластеру и обновить центроид (скользящее среднее с нормировкой) и `size`; иначе создать новый кластер;
   - если кластер уже назван (`person_id`), лицо наследует `person_id`.
7. Записать `media_analysis`: `done`, `analyzer_version`, `processed_at`.

`rejected`-лица в дальнейшем матчинге не участвуют и не пересчитываются.

### 8.4 Обработка геотегов

1. `exiftool -n -j -GPSLatitude -GPSLongitude -GPSAltitude -DateTimeOriginal -CreateDate <файл>`; для видео дополнительно QuickTime-теги (`-GPSCoordinates`, `-Keys:GPSCoordinates`); при неудаче ffprobe.
2. Если координат нет, `skipped`. Нулевая точка (0,0) и значения вне диапазона недействительны.
3. `UPSERT` в `media_geo` (`source='exif'` для фото, `'video'` для видео). Записи с `source='manual'` не перезаписывать.
4. Дату съёмки приводить к `timestamptz` (если нет зоны, считать как есть и хранить как UTC; отметить в документации).

### 8.5 Перематчинг после PUT /persons/sync

После применения справочника воркер находит лица без `person_id` и статусом `auto`, сравнивает с новыми эталонами и обновляет `person_id`, `match_score`. Лица `confirmed` и `rejected` не затрагивать.

## 9. Развёртывание

- Образ с предзагруженной моделью InsightFace (не скачивать при старте).
- `docker-compose.example.yml`: сервисы `analyzer-api` и `analyzer-worker`, один образ, разные команды; `MEDIA_ROOT` монтируется `:ro`; для воркера лимиты CPU/памяти и `WORKER_NICE`.
- Подключение к той же PostgreSQL, что у s\_media\_service, но под ролью `analyzer`. SQL создания роли и прав приложить в `docs/db-role.sql`.
- Нативные зависимости (exiftool, ffmpeg, libheif) ставить в Dockerfile.

## 10. Нефункциональные требования

- Приватность: эмбеддинги не покидают узел (исключение: `reference_embedding` при назначении имени).
- Устойчивость: падение воркера не влияет на API анализатора и тем более на s\_media\_service.
- Идемпотентность: повторный запуск обработки того же файла даёт тот же результат и не плодит дубли.
- Производительность: воркер не должен мешать s\_media\_service (низкий приоритет, ограничение параллелизма, опциональное окно работы).
- Логирование структурированное; в логах нет эмбеддингов.

## 11. Тесты и критерии готовности

- Юнит-тесты: перевод bbox в нормализованные координаты (с EXIF-ориентациями 1–8), порог матчинга, обновление центроида, слияние кластеров, парсинг GPS из exiftool JSON, отбрасывание (0,0).
- Интеграционные (pytest + Postgres с pgvector в контейнере): очередь (`SKIP LOCKED`, зависшие задачи), повторный анализ с сохранением `confirmed`/`rejected`, каскадное удаление при удалении файла из таблицы файлов, `assign` и `sync`.
- Набор тестовых изображений: фото с несколькими лицами, повёрнутое по EXIF, без лиц, с GPS, без GPS, HEIC, видео с GPS.
- Готово, когда: миграции применяются на чистой БД; воркер обрабатывает тестовый каталог; все эндпоинты из раздела 7 покрыты тестами; `docs/INTEGRATION.md` заполнен; приложение запускается в docker-compose рядом с s\_media\_service.

## 12. Допущения и открытые вопросы

1. **Допущение:** у каждого узла своя PostgreSQL; справочник людей (`persons`) живёт в БД s\_media\_api. Если БД окажется общей для всех узлов, `person_refs` и `PUT /persons/sync` упрощаются или уходят.
2. Если s\_media\_api не имеет своей БД, справочник людей нужно где-то хранить; решение вынести в отдельную задачу в s\_media\_api.
3. Изменения в s\_media\_api и s\_media\_front (проксирование эндпоинтов анализатора, реестр узлов, экран «неопознанные люди», подсветка рамок, карта) **не входят** в это ТЗ и описываются отдельно.
4. Видео: лица не обрабатываются; в будущем сэмплирование кадров.
5. Пороги T\_PERSON и T\_CLUSTER подбираются на реальных данных.

## 13. Порядок реализации

1. Изучение репозиториев, `docs/INTEGRATION.md`, скелет проекта, конфиг, подключение к БД.
2. Миграции, ORM-модели, роль БД.
3. Обработка геотегов (самая простая сквозная цепочка: очередь, discovery, процессор, эндпоинты geo).
4. Обработка лиц: детекция, эмбеддинги, запись, эндпоинты faces и thumbnail.
5. Кластеризация, `assign`, `merge`, `people/{id}/files`.
6. `PUT /persons/sync` и перематчинг.
7. Docker, compose, документация, тесты.
