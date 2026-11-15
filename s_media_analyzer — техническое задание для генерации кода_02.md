# s\_media\_analyzer — полное техническое задание

Версия 2. **Заменяет** документы «s\_media\_analyzer — техническое задание» и «Задание агенту: переход на scanned\_files».

## 0. Как пользоваться документом (для агента)

Шаг 4 (обработка лиц) уже реализован по предыдущей версии ТЗ: FK на таблицу файлов каталога, bigint-идентификаторы, без вырезок лиц на диске. Не переписывай всё заново:

1. Изучи текущий код и сравни его с чеклистом из раздела 13.
2. Исправь расхождения: схему БД, конфигурацию, discovery, вырезки, эндпоинты.
3. То, что уже соответствует ТЗ, не трогай.

Данные, созданные шагом 4, считаются тестовыми: их можно очистить и пересканировать. **Изменения в s\_media\_service, s\_media\_api и s\_media\_front не требуются.** Раздел 11 только описывает интерфейс, которым будет пользоваться s\_media\_api.

## 1. Контекст

Каталогизатор фото и видео из трёх приложений (GitHub-пользователь SergueiMoscow):

| Приложение | Репозиторий | Роль |
| --- | --- | --- |
| s\_media\_front | https://github.com/SergueiMoscow/s\_media\_front | Веб-интерфейс |
| s\_media\_api | https://github.com/SergueiMoscow/s\_media\_api | Прослойка между фронтом и одним или несколькими сервисами (узлами) |
| s\_media\_service | https://github.com/SergueiMoscow/s\_media\_service | Работает на компьютере с файлами, хранит каталог в PostgreSQL |

Новое приложение **s\_media\_analyzer** работает на каждом узле рядом с s\_media\_service, читает те же файлы (только чтение) и ту же PostgreSQL, ищет лица на фото и извлекает геометки из фото и видео. Сейчас 2 узла, планируется 5–10. Предполагается **своя PostgreSQL на каждом узле**. На узле работают два процесса анализатора: `api` и `worker`. Фронт обращается только к s\_media\_api, тот проксирует запросы на нужный узел.

**Принцип каталога.** В каталог s\_media\_service попадают только файлы, у которых есть описание или тег. Остальные файлы остаются на диске и в каталоге не видны. Поэтому анализатор работает **раньше каталога**: сканирует директории, находит лица и ведёт собственный реестр файлов. В каталог попадают только файлы с интересными людьми, остальное остаётся только в анализаторе.

## 2. Факты о s\_media\_service (из его кода, не менять)

- `files.id` — uuid. `File.name` хранит **абсолютный путь** на машине сервиса: `os.path.join(storage.path, folder_path, filename)`. Существующий файл ищется по этому полю.
- `Storage`: `id` (uuid), `path`, `user_id` (владелец). Менять `note`, `is_public`, `tags` может только владелец хранилища.
- Файл попадает в каталог через `POST /fileinfo` (тело `CatalogFileRequest`, пользователь из заголовка). Файл задаётся либо `id`, либо тройкой `storage_id` + `folder_path` + `filename` (`folder_path` без ведущего `/`). Если записи нет, она создаётся.
- Параметр `tags` передаётся **полным списком**: сервис сам вычисляет, что добавить и что удалить. Тот, кто вызывает `/fileinfo`, обязан передать текущие тэги плюс новые, иначе остальные тэги файла будут удалены (это обязанность s\_media\_api, раздел 11).
- `storages.path` задан с точки зрения сервиса. В контейнере анализатора тот же каталог может быть смонтирован по другому пути, поэтому анализатор хранит `storage_id` и относительный путь, а полный путь строит только для сверки с `files.name`.

## 3. Цели и не-цели

**Цели**

- Обнаружение лиц на фото, нормализованные рамки (bbox) для подсветки на фронте, вырезки лиц на диске в директории анализатора.
- Эмбеддинги лиц, автоматическая группировка в кластеры, присвоение кластеру имени человека.
- Опознавание уже названных людей на новых фото, в том числе названных на других узлах (по эталонным эмбеддингам).
- Извлечение геометок (lat/lon/alt, дата съёмки) из EXIF фото и метаданных видео.
- Идемпотентная фоновая обработка с учётом версий модели, повторный запуск после обновления.
- Запуск по заданной директории (CLI и HTTP).

**Не-цели (первая версия)**

- Лица в видео (только геотеги видео).
- Обязательный GPU (всё должно работать на CPU).
- Кластеризация лиц между узлами (только локально + эталоны человека).
- Обратное геокодирование (название места).
- Любая запись в таблицы и файлы s\_media\_service, в каталоги с фото.

## 4. Стек

- Python 3.12, FastAPI, Pydantic v2, Uvicorn.
- SQLAlchemy 2.x + Alembic (sync/async выбрать как в s\_media\_service), PostgreSQL 15+ с расширением **pgvector**.
- InsightFace, модель `buffalo_l` (детекция SCRFD + эмбеддинг ArcFace, 512-мерный), onnxruntime на CPU.
- Pillow + pillow-heif (`ImageOps.exif_transpose`), exiftool (subprocess, `-n -j`) для EXIF и метаданных видео, ffprobe как запасной вариант.
- numpy, pytest, Docker.

## 5. Архитектура и конфигурация

Один пакет, две точки входа: `api` (FastAPI) и `worker` (фоновая обработка).

```
s_media_analyzer/
  app/
    main.py, config.py
    db/ (session.py, models.py)
    schemas/ (faces.py, geo.py, clusters.py, persons.py, files.py, common.py)
    api/ (deps.py, routes_*.py)
    services/ (faces_service.py, clustering.py, matching.py, geo_service.py, crops.py, reconcile.py)
    worker/ (main.py, discovery.py, queue.py, processors/faces.py, processors/geo.py)
    imaging.py, cli.py
  migrations/   # alembic, version_table=alembic_version_analysis, schema analysis
  tests/
  docs/INTEGRATION.md
  Dockerfile, docker-compose.example.yml
```

Перед началом работы изучи s\_media\_service и s\_media\_api (стиль конфигурации, ORM, префикс URL, формат ошибок, схема аутентификации между API и сервисом) и зафиксируй в `docs/INTEGRATION.md`. Где ТЗ расходится со стилем комплекса, следуй стилю комплекса и отметь расхождение.

| Переменная | Назначение | По умолчанию |
| --- | --- | --- |
| DATABASE\_URL | Подключение к БД (роль analyzer) | — |
| SCAN\_ROOTS | JSON-объект: storage\_id (uuid) → путь каталога в контейнере (read-only) | — |
| FACES\_DIR | Каталог для вырезок лиц, вне всех SCAN\_ROOTS, доступен на запись | — |
| API\_KEY | Ключ для заголовка X-API-Key (или схема из s\_media\_service) | — |
| ANALYZER\_VERSION | Целое, растёт при смене логики или модели | 1 |
| MODEL\_NAME | Модель InsightFace | buffalo\_l |
| DET\_SCORE\_MIN | Минимальная уверенность детектора | 0.6 |
| MIN\_FACE\_PX | Минимальная сторона лица в пикселях исходника | 40 |
| MAX\_IMAGE\_SIDE | Масштаб изображения перед детекцией | 1600 |
| CROP\_MARGIN | Поля вокруг лица | 0.2 |
| CROP\_MAX\_SIDE | Длинная сторона вырезки, px | 256 |
| CROP\_JPEG\_QUALITY | Качество JPEG | 90 |
| T\_PERSON | Порог cosine similarity для опознавания по эталону человека | 0.45 |
| T\_CLUSTER | Порог cosine similarity для присоединения к кластеру | 0.5 |
| WORKER\_CONCURRENCY | Параллельных задач | 1 |
| WORKER\_NICE | Приоритет процесса | 10 |
| WORKER\_ACTIVE\_HOURS | Окно работы, например 22-07 (пусто = всегда) | пусто |
| LOCK\_TIMEOUT\_SEC | Через сколько задача считается зависшей | 900 |

Пороги T\_PERSON и T\_CLUSTER стартовые, их нужно подбирать на реальных фото. При старте приложение проверяет: `FACES_DIR` существует или создаётся, не лежит внутри ни одного SCAN\_ROOT и не содержит ни одного из них, все SCAN\_ROOTS доступны на чтение. При нарушении завершается с понятной ошибкой.

## 6. Схема БД

Всё в схеме `analysis`. Роль БД `analyzer`: полные права на схему `analysis` и `SELECT` на `public.files` и `public.storages` (только для сверки с каталогом). Миграции Alembic с `version_table='alembic_version_analysis'`, `version_table_schema='analysis'`. Первая миграция: `CREATE EXTENSION IF NOT EXISTS vector;`. **Ссылок на таблицы s\_media\_service (FK) нет.**

```sql
CREATE SCHEMA IF NOT EXISTS analysis;

-- Реестр файлов, найденных сканированием (не зависит от каталога)
CREATE TABLE analysis.scanned_files (
    id              bigserial PRIMARY KEY,
    storage_id      uuid NOT NULL,
    folder_path     text NOT NULL DEFAULT '',   -- без ведущего и завершающего '/'
    filename        text NOT NULL,
    size            bigint,
    mtime_ns        bigint,
    kind            text NOT NULL CHECK (kind IN ('image','video','other')),
    status          text NOT NULL DEFAULT 'present' CHECK (status IN ('present','missing')),
    catalog_file_id uuid,                       -- files.id сервиса; заполняется при связывании
    first_seen_at   timestamptz NOT NULL DEFAULT now(),
    last_seen_at    timestamptz NOT NULL DEFAULT now(),
    UNIQUE (storage_id, folder_path, filename)
);
CREATE INDEX ix_scanned_files_catalog ON analysis.scanned_files (catalog_file_id) WHERE catalog_file_id IS NOT NULL;
CREATE INDEX ix_scanned_files_folder ON analysis.scanned_files (storage_id, folder_path);

-- Учёт обработки: идемпотентность, очередь, повторный запуск по версии
CREATE TABLE analysis.media_analysis (
    id            bigserial PRIMARY KEY,
    file_id       bigint NOT NULL REFERENCES analysis.scanned_files(id) ON DELETE CASCADE,
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
    ignored     boolean NOT NULL DEFAULT false,
    created_at  timestamptz NOT NULL DEFAULT now(),
    updated_at  timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX ix_face_clusters_person ON analysis.face_clusters (person_id);

-- Лица
CREATE TABLE analysis.faces (
    id            bigserial PRIMARY KEY,
    file_id       bigint NOT NULL REFERENCES analysis.scanned_files(id) ON DELETE CASCADE,
    bbox_x        real NOT NULL CHECK (bbox_x >= 0 AND bbox_x <= 1),
    bbox_y        real NOT NULL CHECK (bbox_y >= 0 AND bbox_y <= 1),
    bbox_w        real NOT NULL CHECK (bbox_w > 0 AND bbox_w <= 1),
    bbox_h        real NOT NULL CHECK (bbox_h > 0 AND bbox_h <= 1),
    embedding     vector(512) NOT NULL,
    det_score     real NOT NULL,
    model_name    text NOT NULL,
    analyzer_version integer NOT NULL,
    cluster_id    bigint REFERENCES analysis.face_clusters(id) ON DELETE SET NULL,
    person_id     uuid,                     -- глобальный человек (справочник в БД s_media_api), без FK
    match_score   real,
    status        text NOT NULL DEFAULT 'auto' CHECK (status IN ('auto','confirmed','rejected')),
    crop_path     text,                     -- относительно FACES_DIR
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
    file_id     bigint PRIMARY KEY REFERENCES analysis.scanned_files(id) ON DELETE CASCADE,
    lat         double precision NOT NULL CHECK (lat BETWEEN -90 AND 90),
    lon         double precision NOT NULL CHECK (lon BETWEEN -180 AND 180),
    alt         real,
    taken_at    timestamptz,
    source      text NOT NULL CHECK (source IN ('exif','video','manual')),
    created_at  timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX ix_media_geo_latlon ON analysis.media_geo (lat, lon);
```

Замечания: PostGIS не нужен (поиск по радиусу: сначала bounding box по индексу, затем haversine). `person_id` без FK, потому что справочник людей живёт в БД s\_media\_api. `catalog_file_id` без FK, потому что каталогом владеет s\_media\_service; согласованность обеспечивает сверка (раздел 8). Старые таблицы шага 4 пересоздаются отдельной миграцией (данные тестовые, их можно очистить).

## 7. Pydantic-схемы (v2)

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


class ScannedFileOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    storage_id: UUID
    folder_path: str
    filename: str
    kind: Literal['image', 'video', 'other']
    status: Literal['present', 'missing']
    catalog_file_id: UUID | None


class FaceOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    scanned_file_id: int
    catalog_file_id: UUID | None
    bbox: BBox
    det_score: float
    cluster_id: int | None
    person_id: UUID | None
    person_name: str | None = None
    match_score: float | None
    status: FaceStatus
    has_crop: bool


class PromoteItem(BaseModel):
    scanned_file_id: int
    storage_id: UUID
    folder_path: str
    filename: str


class FaceUpdate(BaseModel):
    """PATCH /faces/{id}. Хотя бы одно поле."""
    person_id: UUID | None = None
    status: FaceStatus | None = None
    unassign: bool = False
    promote: bool = False


class FaceUpdateResult(BaseModel):
    face: FaceOut
    files_to_promote: list[PromoteItem]


class ClusterOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    size: int
    person_id: UUID | None
    person_name: str | None = None
    ignored: bool
    sample_face_ids: list[int]          # до 6 лиц с лучшим det_score


class ClusterAssignRequest(BaseModel):
    person_id: UUID
    name: str = Field(min_length=1, max_length=200)
    promote: bool = False


class ClusterAssignResult(BaseModel):
    cluster_id: int
    person_id: UUID
    faces_updated: int
    reference_embedding: list[float] = Field(min_length=512, max_length=512)
    files_to_promote: list[PromoteItem]  # только при promote=True и только файлы без catalog_file_id


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
    faces_matched: int


class GeoOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    scanned_file_id: int
    catalog_file_id: UUID | None
    lat: float
    lon: float
    alt: float | None
    taken_at: datetime | None
    source: Literal['exif', 'video', 'manual']


class GeoPoint(BaseModel):
    scanned_file_id: int
    catalog_file_id: UUID | None
    lat: float
    lon: float


class ScanRequest(BaseModel):
    storage_id: UUID
    folder_path: str = ''               # папка внутри хранилища
    recursive: bool = True
    kinds: list[AnalysisKind] = Field(default_factory=lambda: ['faces', 'geo'])
    limit: int | None = None            # максимум файлов за запуск (для проверки)


class ScanResult(BaseModel):
    registered: int
    updated: int
    marked_missing: int
    queued: int


class AnalysisStatusOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    scanned_file_id: int
    kind: AnalysisKind
    status: AnalysisStatus
    analyzer_version: int
    attempts: int
    error: str | None
    processed_at: datetime | None


class RescanRequest(BaseModel):
    kinds: list[AnalysisKind] = Field(default_factory=lambda: ['faces', 'geo'])


class CatalogLink(BaseModel):
    scanned_file_id: int
    catalog_file_id: UUID


class CatalogLinksRequest(BaseModel):
    links: list[CatalogLink]


class CatalogLinksResult(BaseModel):
    linked: int


class PersonFilesOut(BaseModel):
    person_id: UUID
    catalog_file_ids: list[UUID]        # только файлы, связанные с каталогом
    next_cursor: int | None


class StatsOut(BaseModel):
    queue: dict[str, dict[str, int]]    # kind -> status -> count
    scanned_files: int
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

Эмбеддинги лиц **никогда** не возвращаются в ответах API, кроме `reference_embedding` при назначении имени кластеру (нужен глобальному справочнику людей).

## 8. Эндпоинты

Префикс (например `/api/v1`) и формат ошибок взять из s\_media\_service. Аутентификация: заголовок `X-API-Key` (или схема из s\_media\_service). Анализатор доверяет s\_media\_api; права проверяет API (см. конец раздела).

| Метод и путь | Описание | Запрос / ответ |
| --- | --- | --- |
| GET /health | Проверка БД, модели, SCAN\_ROOTS, FACES\_DIR | `{status, db, model, scan_roots, faces_dir}`, 503 при сбое |
| POST /admin/scan | Обходит папку на диске (по SCAN\_ROOTS), регистрирует файлы в `scanned_files`, создаёт задачи в `media_analysis`. Сам анализ делает воркер | `ScanRequest` → `ScanResult`, 202 |
| POST /admin/reconcile-catalog | Связывает `scanned_files` с уже существующими записями каталога (раздел 9.7) | → `{linked: int}` |
| GET /scanned-files | Фильтры `storage_id`, `folder_path`, `status`, `has_faces`, `limit`, `offset` | `Page[ScannedFileOut]` |
| GET /scanned-files/{id}/faces | Лица файла (без `rejected`, если нет `include_rejected=true`) | `list[FaceOut]`, 404 |
| GET /scanned-files/{id}/geo | Геоданные файла | `GeoOut`, 404 |
| GET /scanned-files/{id}/analysis | Статус обработки по видам | `list[AnalysisStatusOut]` |
| POST /scanned-files/{id}/rescan | Поставить файл на повторный анализ | `RescanRequest`, 202 |
| PUT /scanned-files/catalog-links | Записать связь с каталогом после продвижения. Идемпотентно | `CatalogLinksRequest` → `CatalogLinksResult` |
| GET /catalog-files/{catalog\_file\_id}/faces и /geo | Для фронта: данные по файлу, уже связанному с каталогом | как выше, 404 если связи нет |
| PATCH /faces/{face\_id} | Подтвердить, отклонить, назначить или снять человека | `FaceUpdate` → `FaceUpdateResult` |
| GET /faces/{face\_id}/thumbnail | Отдаёт вырезку из `FACES_DIR`; если файла нет, вырезает из оригинала на лету (`size`, по умолчанию 160) | image/jpeg, кэш-заголовки |
| GET /clusters | Фильтры `unassigned`, `ignored`, `min_size`, `limit`, `offset`; сортировка по размеру по убыванию. По умолчанию игнорируемые кластеры не показываются | `Page[ClusterOut]` |
| GET /clusters/{id}/faces | Лица кластера, постранично | `Page[FaceOut]` |
| POST /clusters/{id}/assign | Назначить кластеру человека: `cluster.person_id`, `faces.person_id` (кроме `rejected`), запись в `person_refs` и эталон; статус лиц остаётся `auto` | `ClusterAssignRequest` → `ClusterAssignResult`, 404, 409 если кластер уже назван другим |
| POST /clusters/{id}/merge | Слить кластер в другой (пересчёт центроида и размера) | `ClusterMergeRequest` → `ClusterOut` |
| POST /clusters/{id}/ignore, DELETE /clusters/{id}/ignore | Пометить или снять пометку «неинтересный» | → `ClusterOut` |
| GET /people/{person\_id}/files | `catalog_file_id` файлов с этим человеком (без `rejected`); курсорная пагинация `limit`, `cursor` | `PersonFilesOut` |
| PUT /persons/sync | s\_media\_api передаёт справочник людей и эталонные эмбеддинги; после применения воркер перематчит неназначенные лица | `PersonSyncRequest` → `PersonSyncResult` |
| GET /geo/search | Либо `lat,lon,radius_m`, либо `min_lat,min_lon,max_lat,max_lon`; `limit` до 5000. По умолчанию только файлы с `catalog_file_id`; `include_unindexed=true` добавляет остальные | `list[GeoPoint]`, 422 |
| GET /stats | Состояние очереди и счётчики | `StatsOut` |

**Права.** Данные нескатализированных файлов и действия `assign` и `promote` доступны только владельцу хранилища (как в s\_media\_service: менять теги может только владелец). Для файлов, которые уже в каталоге, видимость лиц и геометок совпадает с видимостью самого файла (`is_public`). Проверку выполняет s\_media\_api, анализатор её не дублирует.

## 9. Воркер

### 9.1 Discovery (по диску, не по БД)

Обход папки из `ScanRequest` по `SCAN_ROOTS[storage_id]`. Для каждого файла выполнить `UPSERT` в `scanned_files` по тройке `storage_id, folder_path, filename`. Тип `kind` определить по расширению (изображения: jpg, jpeg, png, webp, heic, heif, tiff, bmp, gif; видео: mp4, mov, m4v, avi, mkv, webm, 3gp; остальное `other` и в анализ не попадает). Если `size` или `mtime_ns` изменились, поставить задачи `media_analysis` в `pending`; для новых файлов создать задачи (`faces` только для изображений, `geo` для изображений и видео). Файлы, которых нет на диске под обойдённым префиксом, пометить `status='missing'` (данные не удалять: переименование и перенос папки выглядят как исчезновение и появление). `folder_path` нормализовать как в сервисе (без ведущего `/`). Переименование как отдельное событие в первой версии не определяется: переименованный файл считается новым.

### 9.2 Очередь

Захват пачки: `SELECT ... FOR UPDATE SKIP LOCKED LIMIT n` по `status='pending'` или `status='processing' AND locked_at < now() - LOCK_TIMEOUT`; установить `processing`, `locked_at`, `attempts += 1`. После 3 неудач `failed` с текстом ошибки. Отсутствие файла на диске даёт `skipped`, а не `failed`.

### 9.3 Обработка лиц

1. Открыть файл, применить `ImageOps.exif_transpose`, привести к RGB, уменьшить длинную сторону до `MAX_IMAGE_SIDE`.
2. Детекция и эмбеддинги InsightFace. Отбросить лица с `det_score < DET_SCORE_MIN` и стороной меньше `MIN_FACE_PX` (в пикселях исходного изображения).
3. Перевести bbox в нормализованные координаты (0..1) относительно изображения после ориентации, обрезать по границам. Эмбеддинг нормализовать (L2).
4. При повторном анализе сохранить лица `confirmed` и `rejected`, а новые детекции с IoU > 0.5 относительно сохранённых отбросить. Лица `auto` удалить вместе с вырезками и записать заново (в одной транзакции).
5. Для каждого нового лица: найти ближайший эталон в `person_ref_embeddings`; если similarity `>= T_PERSON`, присвоить `person_id`, `match_score`, статус `auto`. Независимо от этого найти ближайший центроид в `face_clusters`; если `>= T_CLUSTER`, присоединить к кластеру и обновить центроид (скользящее среднее с нормировкой) и `size`, иначе создать новый кластер. Если кластер уже назван (`person_id`), лицо наследует `person_id`.
6. `rejected`-лица в матчинге не участвуют.
7. Записать `media_analysis`: `done`, `analyzer_version`, `processed_at`.

### 9.4 Вырезки лиц

Порядок для каждого нового лица: вставить строку в `faces` (получить `id` через `flush`), записать вырезку во временный файл в `FACES_DIR` и атомарно переименовать (`os.replace`) в `FACES_DIR/{id // 1000:06d}/{id}.jpg`, записать `crop_path`. Всё в одной транзакции: если запись файла или БД упала, откатить и удалить созданные файлы, чтобы не оставлять строку `faces` без файла. Вырезка: лицо с полями `CROP_MARGIN`, длинная сторона не больше `CROP_MAX_SIDE`, JPEG с качеством `CROP_JPEG_QUALITY`. Вырезки не пишутся в каталоги с фотографиями.

Каскадное удаление в БД не удаляет файлы с диска, поэтому нужна чистка осиротевших вырезок (`cleanup-crops`, раздел 10).

### 9.5 Геотеги

1. `exiftool -n -j -GPSLatitude -GPSLongitude -GPSAltitude -DateTimeOriginal -CreateDate <файл>`; для видео дополнительно QuickTime-теги (`-GPSCoordinates`, `-Keys:GPSCoordinates`); при неудаче ffprobe.
2. Если координат нет, статус `skipped`. Точка (0,0) и значения вне диапазона недействительны.
3. `UPSERT` в `media_geo` (`source='exif'` для фото, `'video'` для видео). Записи с `source='manual'` не перезаписывать.
4. Дату съёмки привести к `timestamptz` (если нет зоны, хранить как UTC и отметить это в документации).

Геометки считаются для всех просканированных файлов и появляются в каталоге после связи файла с записью каталога.

### 9.6 Перематчинг после PUT /persons/sync

После применения справочника воркер находит лица без `person_id` и статусом `auto`, сравнивает с новыми эталонами и обновляет `person_id`, `match_score`. Лица `confirmed` и `rejected` не трогать. Игнорируемые кластеры продолжают принимать новые лица, но в списках неназначенных не показываются.

### 9.7 Сверка с каталогом (`reconcile-catalog`)

Для файлов без `catalog_file_id` по каждому хранилищу: прочитать `storages.path` (SELECT), построить полный путь так же, как сервис: `os.path.join(storage.path, folder_path, filename)`, и найти `files.id` по `files.name` (SELECT). Найденный uuid записать в `catalog_file_id`. Если хранилища нет в БД, пропустить с предупреждением. Запускается по `POST /admin/reconcile-catalog`, в конце сканирования и периодически; заодно сбрасывает `catalog_file_id` (в NULL), если записи уже нет в `files`. Так файлы, которые пользователь уже добавил в каталог, сразу получают лица без продвижения.

## 10. CLI для проверки

```
python -m app.cli analyze --storage <uuid> --path <folder_path> [--no-save-crops] [--limit N] [--kinds faces,geo] [--dry-run]
python -m app.cli reconcile
python -m app.cli cleanup-crops
```

`analyze` регистрирует файлы, прогоняет воркер в этом же процессе до опустошения очереди запуска и печатает итог: сколько файлов зарегистрировано и обработано, сколько лиц найдено, сколько вырезок записано (с путями), ошибки. `--dry-run` только считает файлы. `cleanup-crops` удаляет файлы в `FACES_DIR`, на которые не ссылается ни одна строка `faces`. Каталог и директории с фото при этом не меняются.

## 11. Продвижение файла в каталог (интерфейс для s\_media\_api, вне этого ТЗ)

Анализатор файлы в каталог не добавляет. Он только отдаёт список файлов для продвижения и принимает связь обратно. Рекомендуемый порядок для s\_media\_api:

1. Фронт назначает кластеру человека. API вызывает `POST /clusters/{id}/assign` с `promote=true` на узле и получает `files_to_promote` (только файлы без `catalog_file_id`).
2. Для каждого файла API вызывает `POST /fileinfo` сервиса: `storage_id`, `folder_path`, `filename`, `tags` = **текущие теги файла плюс имя человека** (список полный, потому что сервис сам удаляет всё, чего в списке нет), заголовок пользователя. Действие допустимо только если пользователь владелец хранилища. Если файла в каталоге ещё нет, текущих тегов нет и список состоит из одного имени. Повторный вызов для уже существующего файла дубль не создаёт: запись находится по полному пути.
3. API записывает связь через `PUT /scanned-files/catalog-links`.

Если у пользователя нет прав владельца, сервис молча ничего не меняет (а для нового файла вернёт пустой результат), поэтому API проверяет владельца до вызова.

## 12. Развёртывание и нефункциональные требования

- Образ с предзагруженной моделью InsightFace (не скачивать при старте). Нативные зависимости (exiftool, ffmpeg, libheif) ставить в Dockerfile.
- `docker-compose.example.yml`: сервисы `analyzer-api` и `analyzer-worker`, один образ, разные команды. Каталоги из `SCAN_ROOTS` монтируются `:ro`, `FACES_DIR` отдельным volume на запись. Для воркера лимиты CPU и памяти и `WORKER_NICE`.
- Подключение к той же PostgreSQL, что у s\_media\_service, под ролью `analyzer`. SQL создания роли и прав приложить в `docs/db-role.sql`.
- Приватность: эмбеддинги не покидают узел (исключение: `reference_embedding` при назначении имени). В логах эмбеддингов нет.
- Устойчивость: падение воркера не влияет на API анализатора, тем более на s\_media\_service.
- Идемпотентность: повторный запуск того же файла даёт тот же результат и не плодит дубли.
- Производительность: воркер не должен мешать s\_media\_service (низкий приоритет, ограничение параллелизма, опциональное окно работы).
- Логирование структурированное.

## 13. Чеклист проверки уже реализованного шага 4 (для агента)

Проверь каждый пункт в текущем коде и исправь расхождения. Подходящее оставь как есть.

| # | Что проверить | Как должно быть |
| --- | --- | --- |
| 1 | Ссылки на файлы | Все `file_id` ссылаются на `analysis.scanned_files(id)`; FK на таблицы s\_media\_service нет; `catalog_file_id` типа uuid |
| 2 | Конфиг | Вместо одного `MEDIA_ROOT` есть `SCAN_ROOTS` (storage\_id → путь); есть `FACES_DIR` и проверки при старте |
| 3 | Discovery | Идёт по диску и регистрирует файлы в `scanned_files`, а не читает таблицу файлов каталога |
| 4 | Вырезки | Лицо пишется в БД и в `FACES_DIR` в одной транзакции, есть `crop_path`; в каталоги с фото ничего не пишется |
| 5 | Кластеры | Есть `ignored` и эндпоинты `ignore` |
| 6 | Эндпоинты | Пути `/scanned-files/...` и `/catalog-files/...` вместо `/files/{id}/...`; добавлены `reconcile-catalog`, `catalog-links`; `assign` и `PATCH /faces` поддерживают `promote` |
| 7 | Схемы | Типы и поля соответствуют разделу 7 |
| 8 | CLI | Есть `analyze`, `reconcile`, `cleanup-crops` |
| 9 | Миграции | Новая миграция пересоздаёт таблицы `analysis.*` (данные шага 4 тестовые, можно очистить) |
| 10 | Тесты | Покрыты пункты из раздела 14 |

## 14. Порядок работ и критерии приёмки

Порядок: 1) миграции и модели; 2) discovery и CLI `analyze`; 3) вырезки и `cleanup-crops`; 4) эндпоинты раздела 8; 5) сверка с каталогом и `catalog-links`; 6) `persons/sync` и перематчинг; 7) тесты и документация.

**Готово, когда:**

- миграции применяются на чистой БД;
- `analyze --storage <uuid> --path <папка> --limit 20` регистрирует файлы, находит лица, записывает вырезки в `FACES_DIR` и строки в `analysis.faces`, ничего не пишет в каталог и в директории с фото;
- повторный запуск не плодит дубли;
- приложение не стартует, если `FACES_DIR` лежит внутри `SCAN_ROOTS`;
- сбой записи вырезки не оставляет строку `faces` без файла;
- `assign` с `promote=true` возвращает только файлы без `catalog_file_id`;
- `reconcile-catalog` связывает файл, уже существующий в каталоге, по полному пути;
- все эндпоинты раздела 8 покрыты тестами;
- юнит-тесты: перевод bbox в нормализованные координаты (EXIF-ориентации 1–8), пороги матчинга, обновление центроида, слияние кластеров, парсинг GPS из JSON exiftool, отбрасывание (0,0), нормализация `folder_path`;
- интеграционные тесты (pytest и Postgres с pgvector): очередь (`SKIP LOCKED`, зависшие задачи), повторный анализ с сохранением `confirmed` и `rejected`, `assign`, `sync`, `reconcile`;
- набор тестовых изображений: несколько лиц, повёрнутое по EXIF, без лиц, с GPS, без GPS, HEIC, видео с GPS.

## 15. Допущения и открытые вопросы

1. У каждого узла своя PostgreSQL; справочник людей (`persons`) живёт в БД s\_media\_api. Если БД окажется общей для всех узлов, `person_refs` и `PUT /persons/sync` упрощаются или уходят.
2. Если у s\_media\_api нет своей БД, справочник людей нужно где-то хранить; решение вынести в отдельную задачу s\_media\_api.
3. Изменения в s\_media\_api и s\_media\_front (проксирование эндпоинтов, реестр узлов, экран «неопознанные люди», подсветка рамок, карта, оркестрация продвижения) не входят в это ТЗ.
4. Лица в видео не обрабатываются; в будущем сэмплирование кадров.
5. Пороги T\_PERSON и T\_CLUSTER подбираются на реальных данных.
6. Определение переименования и переноса файлов отложено.
