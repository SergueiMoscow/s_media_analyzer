"""Очередь обработки (media_analysis) и геоданные (media_geo)."""
from datetime import datetime, timedelta, timezone

from sqlalchemy import and_, case, func, or_, select, text, update
from sqlalchemy.ext.asyncio import AsyncSession

from common.settings import settings
from db.models import Face, FaceCluster, MediaAnalysis, MediaGeo, ScannedFile


def _now() -> datetime:
    return datetime.now(timezone.utc)


async def queue_tasks(session: AsyncSession, file_id: int, kinds: list[str]) -> None:
    """Создаёт (если нет) и переоткрывает задачи анализа для файла."""
    for kind in kinds:
        await session.execute(
            text(
                f'INSERT INTO {settings.ANALYSIS_SCHEMA}.media_analysis (file_id, kind) '
                f'VALUES (:file_id, :kind) ON CONFLICT (file_id, kind) DO NOTHING'
            ),
            {'file_id': file_id, 'kind': kind},
        )
    await session.execute(
        update(MediaAnalysis)
        .where(MediaAnalysis.file_id == file_id)
        .where(MediaAnalysis.kind.in_(kinds))
        .values(status='pending', error=None)
    )


async def requeue_by_version(session: AsyncSession) -> int:
    """Переоткрывает задачи со старой версией анализатора."""
    result = await session.execute(
        text(
            f"UPDATE {settings.ANALYSIS_SCHEMA}.media_analysis SET status = 'pending' "
            f"WHERE status IN ('done', 'failed', 'skipped') AND analyzer_version < :current"
        ),
        {'current': settings.ANALYZER_VERSION},
    )
    return result.rowcount


async def claim_tasks(
    session: AsyncSession, kind: str, limit: int, lock_timeout_sec: int
) -> list[MediaAnalysis]:
    """Захватывает пачку задач (FOR UPDATE SKIP LOCKED) и ставит их в processing."""
    cutoff = _now() - timedelta(seconds=lock_timeout_sec)
    stmt = (
        select(MediaAnalysis)
        .where(MediaAnalysis.kind == kind)
        .where(
            or_(
                MediaAnalysis.status == 'pending',
                and_(MediaAnalysis.status == 'processing', MediaAnalysis.locked_at < cutoff),
            )
        )
        .order_by(MediaAnalysis.id)
        .limit(limit)
        .with_for_update(skip_locked=True)
    )
    result = await session.execute(stmt)
    tasks = list(result.scalars().all())
    for task in tasks:
        task.status = 'processing'
        task.locked_at = _now()
        task.attempts = (task.attempts or 0) + 1
        task.error = None
    await session.commit()
    return tasks


async def complete_task(
    session: AsyncSession, task_id: int, status: str, error: str | None = None
) -> None:
    await session.execute(
        update(MediaAnalysis)
        .where(MediaAnalysis.id == task_id)
        .values(
            status=status,
            analyzer_version=settings.ANALYZER_VERSION,
            error=error,
            processed_at=_now(),
            locked_at=None,
        )
    )
    await session.commit()


async def record_error(session: AsyncSession, task_id: int, error: str) -> None:
    await session.execute(
        update(MediaAnalysis).where(MediaAnalysis.id == task_id).values(error=error)
    )
    await session.commit()


async def get_analysis_rows(session: AsyncSession, file_id: int) -> list[MediaAnalysis]:
    result = await session.execute(
        select(MediaAnalysis).where(MediaAnalysis.file_id == file_id).order_by(MediaAnalysis.kind)
    )
    return list(result.scalars().all())


async def rescan_file(session: AsyncSession, file_id: int, kinds: list[str]) -> None:
    await queue_tasks(session, file_id, kinds)
    await session.commit()


async def get_media_geo(session: AsyncSession, file_id: int) -> MediaGeo | None:
    return await session.get(MediaGeo, file_id)


async def upsert_media_geo(
    session: AsyncSession,
    file_id: int,
    lat: float,
    lon: float,
    alt: float | None,
    taken_at: datetime | None,
    source: str,
) -> None:
    """UPSERT геоданных; записи с source='manual' не перезаписываются."""
    await session.execute(
        text(
            f"""
            INSERT INTO {settings.ANALYSIS_SCHEMA}.media_geo
            (file_id, lat, lon, alt, taken_at, source)
            VALUES (:file_id, :lat, :lon, :alt, :taken_at, :source)
            ON CONFLICT (file_id) DO UPDATE SET
                lat = EXCLUDED.lat,
                lon = EXCLUDED.lon,
                alt = EXCLUDED.alt,
                taken_at = EXCLUDED.taken_at,
                source = EXCLUDED.source
            WHERE {settings.ANALYSIS_SCHEMA}.media_geo.source <> 'manual'
            """
        ),
        {
            'file_id': file_id,
            'lat': lat,
            'lon': lon,
            'alt': alt,
            'taken_at': taken_at,
            'source': source,
        },
    )
    await session.commit()


async def search_geo(
    session: AsyncSession,
    *,
    min_lat: float | None = None,
    max_lat: float | None = None,
    min_lon: float | None = None,
    max_lon: float | None = None,
    catalog_only: bool = True,
    limit: int = 100,
) -> list[MediaGeo]:
    stmt = select(MediaGeo).join(ScannedFile, ScannedFile.id == MediaGeo.file_id)
    if min_lat is not None:
        stmt = stmt.where(MediaGeo.lat >= min_lat)
    if max_lat is not None:
        stmt = stmt.where(MediaGeo.lat <= max_lat)
    if min_lon is not None:
        stmt = stmt.where(MediaGeo.lon >= min_lon)
    if max_lon is not None:
        stmt = stmt.where(MediaGeo.lon <= max_lon)
    if catalog_only:
        stmt = stmt.where(ScannedFile.catalog_file_id.is_not(None))
    stmt = stmt.order_by(MediaGeo.lat).limit(limit)
    result = await session.execute(stmt)
    return list(result.scalars().all())


async def get_processing(session: AsyncSession) -> list[dict]:
    """Задачи в обработке (status='processing') с путём файла из scanned_files."""
    stmt = (
        select(
            MediaAnalysis.file_id.label('scanned_file_id'),
            ScannedFile.catalog_file_id,
            ScannedFile.storage_id,
            ScannedFile.folder_path,
            ScannedFile.filename,
            MediaAnalysis.kind,
            MediaAnalysis.attempts,
            MediaAnalysis.locked_at,
        )
        .join(ScannedFile, ScannedFile.id == MediaAnalysis.file_id)
        .where(MediaAnalysis.status == 'processing')
        .order_by(MediaAnalysis.id)
    )
    result = await session.execute(stmt)
    return [dict(m) for m in result.mappings().all()]


async def list_queue(
    session: AsyncSession,
    *,
    kind: str | None = None,
    status: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> tuple[list[dict], int]:
    """Детальная очередь media_analysis с путём файла, фильтрами и пагинацией."""
    faces_count = case(
        (
            MediaAnalysis.kind == 'faces',
            select(func.count(Face.id))
            .where(Face.file_id == MediaAnalysis.file_id)
            .correlate(MediaAnalysis)
            .scalar_subquery(),
        ),
        else_=None,
    )
    stmt = (
        select(
            MediaAnalysis.file_id.label('scanned_file_id'),
            ScannedFile.catalog_file_id,
            ScannedFile.storage_id,
            ScannedFile.folder_path,
            ScannedFile.filename,
            MediaAnalysis.kind,
            MediaAnalysis.status,
            MediaAnalysis.attempts,
            MediaAnalysis.error,
            MediaAnalysis.locked_at,
            MediaAnalysis.processed_at,
            MediaAnalysis.analyzer_version,
            faces_count.label('faces_count'),
        )
        .join(ScannedFile, ScannedFile.id == MediaAnalysis.file_id)
    )
    conditions = []
    if kind is not None:
        conditions.append(MediaAnalysis.kind == kind)
    if status is not None:
        conditions.append(MediaAnalysis.status == status)
    if conditions:
        stmt = stmt.where(*conditions)

    count_stmt = (
        select(func.count())
        .select_from(MediaAnalysis)
        .join(ScannedFile, ScannedFile.id == MediaAnalysis.file_id)
    )
    if conditions:
        count_stmt = count_stmt.where(*conditions)
    total = await session.scalar(count_stmt) or 0

    result = await session.execute(stmt.order_by(MediaAnalysis.id).limit(limit).offset(offset))
    return [dict(m) for m in result.mappings().all()], total


async def get_stats(session: AsyncSession) -> dict:
    rows = await session.execute(
        select(MediaAnalysis.kind, MediaAnalysis.status, func.count())
        .group_by(MediaAnalysis.kind, MediaAnalysis.status)
    )
    queue: dict[str, dict[str, int]] = {}
    for kind, status, count in rows.all():
        queue.setdefault(kind, {})[status] = count

    scanned_files = await session.scalar(select(func.count()).select_from(ScannedFile)) or 0
    faces_total = await session.scalar(select(func.count()).select_from(Face)) or 0
    faces_unassigned = (
        await session.scalar(
            select(func.count()).select_from(Face).where(Face.person_id.is_(None))
        )
        or 0
    )
    clusters_total = await session.scalar(select(func.count()).select_from(FaceCluster)) or 0
    geo_total = await session.scalar(select(func.count()).select_from(MediaGeo)) or 0
    return {
        'queue': queue,
        'processing': await get_processing(session),
        'scanned_files': scanned_files,
        'faces_total': faces_total,
        'faces_unassigned': faces_unassigned,
        'clusters_total': clusters_total,
        'geo_total': geo_total,
        'analyzer_version': settings.ANALYZER_VERSION,
    }
