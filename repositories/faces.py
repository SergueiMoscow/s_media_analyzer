"""Доступ к лицам, кластерам и эталонным эмбеддингам людей."""
from uuid import UUID

from sqlalchemy import delete, func, select, text, update
from sqlalchemy.ext.asyncio import AsyncSession

from common.settings import settings
from db.models import Face, FaceCluster
from services.faces_service import l2_normalize


def _vector_literal(embedding) -> str:
    return '[' + ','.join(str(float(x)) for x in embedding) + ']'


def _parse_vector(value) -> list[float]:
    if value is None:
        return []
    if isinstance(value, str):
        text_value = value.strip('[] ')
        if not text_value:
            return []
        return [float(x) for x in text_value.split(',')]
    # список, tuple или numpy-массив (pgvector)
    return [float(x) for x in value]


async def get_faces_for_file(
    session: AsyncSession, file_id: int, include_rejected: bool = False
) -> list[Face]:
    stmt = select(Face).where(Face.file_id == file_id).order_by(Face.id)
    if not include_rejected:
        stmt = stmt.where(Face.status != 'rejected')
    result = await session.execute(stmt)
    return list(result.scalars().all())


async def get_face_by_id(session: AsyncSession, face_id: int) -> Face | None:
    return await session.get(Face, face_id)


async def delete_auto_faces(session: AsyncSession, file_id: int) -> int:
    result = await session.execute(
        delete(Face).where(Face.file_id == file_id, Face.status == 'auto')
    )
    return result.rowcount


async def insert_face(
    session: AsyncSession,
    file_id: int,
    bbox: dict,
    embedding: list[float],
    det_score: float,
    cluster_id: int | None,
    person_id: UUID | None,
    match_score: float | None,
    status: str = 'auto',
    crop_path: str | None = None,
) -> Face:
    face = Face(
        file_id=file_id,
        bbox_x=bbox['x'],
        bbox_y=bbox['y'],
        bbox_w=bbox['w'],
        bbox_h=bbox['h'],
        embedding=embedding,
        det_score=det_score,
        model_name=settings.MODEL_NAME,
        analyzer_version=settings.ANALYZER_VERSION,
        cluster_id=cluster_id,
        person_id=person_id,
        match_score=match_score,
        status=status,
        crop_path=crop_path,
    )
    session.add(face)
    await session.flush()
    return face


async def set_face_crop_path(session: AsyncSession, face_id: int, crop_path: str) -> None:
    await session.execute(
        update(Face).where(Face.id == face_id).values(crop_path=crop_path)
    )


async def find_nearest_person_ref(session: AsyncSession, embedding: list[float]) -> dict | None:
    emb = _vector_literal(embedding)
    stmt = text(
        f"""
        SELECT person_id, 1 - (embedding <=> CAST(:emb AS vector)) AS similarity
        FROM {settings.ANALYSIS_SCHEMA}.person_ref_embeddings
        ORDER BY embedding <=> CAST(:emb AS vector)
        LIMIT 1
        """
    )
    row = (await session.execute(stmt, {'emb': emb})).mappings().first()
    if row is None:
        return None
    return {'person_id': row['person_id'], 'similarity': float(row['similarity'])}


async def find_nearest_cluster(session: AsyncSession, embedding: list[float]) -> dict | None:
    emb = _vector_literal(embedding)
    stmt = text(
        f"""
        SELECT id, person_id, size, centroid,
               1 - (centroid <=> CAST(:emb AS vector)) AS similarity
        FROM {settings.ANALYSIS_SCHEMA}.face_clusters
        ORDER BY centroid <=> CAST(:emb AS vector)
        LIMIT 1
        """
    )
    row = (await session.execute(stmt, {'emb': emb})).mappings().first()
    if row is None:
        return None
    return {
        'id': row['id'],
        'person_id': row['person_id'],
        'size': int(row['size']),
        'centroid': _parse_vector(row['centroid']),
        'similarity': float(row['similarity']),
    }


async def create_cluster(session: AsyncSession, embedding: list[float]) -> int:
    cluster = FaceCluster(centroid=l2_normalize(embedding), size=1)
    session.add(cluster)
    await session.flush()
    return cluster.id


async def update_cluster(
    session: AsyncSession, cluster_id: int, centroid: list[float], size: int
) -> None:
    await session.execute(
        update(FaceCluster)
        .where(FaceCluster.id == cluster_id)
        .values(centroid=centroid, size=size)
    )


async def get_cluster(session: AsyncSession, cluster_id: int) -> FaceCluster | None:
    return await session.get(FaceCluster, cluster_id)


async def get_cluster_centroid(session: AsyncSession, cluster_id: int) -> list[float]:
    centroid = await session.scalar(
        select(FaceCluster.centroid).where(FaceCluster.id == cluster_id)
    )
    return _parse_vector(centroid)


async def list_clusters(
    session: AsyncSession,
    *,
    unassigned: bool | None = None,
    ignored: bool | None = None,
    min_size: int | None = None,
    limit: int = 100,
    offset: int = 0,
) -> tuple[list[FaceCluster], int]:
    stmt = select(FaceCluster)
    if unassigned is True:
        stmt = stmt.where(FaceCluster.person_id.is_(None))
    elif unassigned is False:
        stmt = stmt.where(FaceCluster.person_id.is_not(None))
    if ignored is not None:
        stmt = stmt.where(FaceCluster.ignored == ignored)
    if min_size is not None:
        stmt = stmt.where(FaceCluster.size >= min_size)

    total = await session.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    result = await session.execute(
        stmt.order_by(FaceCluster.size.desc()).limit(limit).offset(offset)
    )
    return list(result.scalars().all()), total


async def get_cluster_faces(
    session: AsyncSession, cluster_id: int, limit: int = 100, offset: int = 0
) -> tuple[list[Face], int]:
    stmt = select(Face).where(Face.cluster_id == cluster_id)
    total = await session.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    result = await session.execute(
        stmt.order_by(Face.det_score.desc(), Face.id).limit(limit).offset(offset)
    )
    return list(result.scalars().all()), total


async def get_sample_face_ids(session: AsyncSession, cluster_id: int, limit: int = 6) -> list[int]:
    result = await session.execute(
        select(Face.id)
        .where(Face.cluster_id == cluster_id, Face.status != 'rejected')
        .order_by(Face.det_score.desc())
        .limit(limit)
    )
    return list(result.scalars().all())


async def set_cluster_ignored(session: AsyncSession, cluster_id: int, ignored: bool) -> None:
    await session.execute(
        update(FaceCluster).where(FaceCluster.id == cluster_id).values(ignored=ignored)
    )


async def assign_cluster(
    session: AsyncSession, cluster_id: int, person_id: UUID, reference_embedding: list[float]
) -> int:
    """Назначает кластеру человека; возвращает число обновлённых лиц."""
    await session.execute(
        update(FaceCluster).where(FaceCluster.id == cluster_id).values(person_id=person_id)
    )
    result = await session.execute(
        update(Face)
        .where(Face.cluster_id == cluster_id)
        .where(Face.status != 'rejected')
        .values(person_id=person_id)
    )
    # центроид кластера как эталон
    centroid = await get_cluster_centroid(session, cluster_id)
    await session.execute(
        text(
            f'INSERT INTO {settings.ANALYSIS_SCHEMA}.person_ref_embeddings '
            f'(person_id, embedding) VALUES (:pid, CAST(:emb AS vector))'
        ),
        {'pid': person_id, 'emb': _vector_literal(centroid)},
    )
    return result.rowcount


async def rematch_faces(session: AsyncSession) -> int:
    """Перематчивает авто-лица без person_id по эталонам (раздел 9.6 ТЗ)."""
    result = await session.execute(
        select(Face).where(Face.person_id.is_(None), Face.status == 'auto')
    )
    faces = list(result.scalars().all())
    matched = 0
    for face in faces:
        match = await find_nearest_person_ref(session, _parse_vector(face.embedding))
        if match and match['similarity'] >= settings.T_PERSON:
            face.person_id = match['person_id']
            face.match_score = match['similarity']
            matched += 1
    await session.commit()
    return matched


async def merge_clusters(session: AsyncSession, source_id: int, target_id: int) -> None:
    """Сливает source в target: пересчитывает центроид и size, переносит лица."""
    source = await get_cluster(session, source_id)
    target = await get_cluster(session, target_id)
    if source is None or target is None:
        return
    src_centroid = await get_cluster_centroid(session, source_id)
    tgt_centroid = await get_cluster_centroid(session, target_id)

    merged_raw = [a * source.size + b * target.size for a, b in zip(src_centroid, tgt_centroid)]
    new_centroid = l2_normalize(merged_raw)
    new_size = source.size + target.size

    await session.execute(
        update(Face).where(Face.cluster_id == source_id).values(cluster_id=target_id)
    )
    await session.execute(
        update(FaceCluster).where(FaceCluster.id == target_id).values(
            centroid=new_centroid, size=new_size
        )
    )
    await session.execute(delete(FaceCluster).where(FaceCluster.id == source_id))


async def add_cluster_rejection(session: AsyncSession, person_id: UUID, cluster_id: int) -> bool:
    """Запоминает отказ «кластер — не этот человек» (идемпотентно)."""
    result = await session.execute(
        text(
            f'INSERT INTO {settings.ANALYSIS_SCHEMA}.face_cluster_rejections '
            f'(person_id, cluster_id) VALUES (:pid, :cid) '
            f'ON CONFLICT (person_id, cluster_id) DO NOTHING'
        ),
        {'pid': person_id, 'cid': cluster_id},
    )
    return result.rowcount > 0


async def get_person_candidates(
    session: AsyncSession,
    person_id: UUID,
    limit: int = 20,
    min_similarity: float | None = None,
) -> tuple[list[dict], int]:
    """Кластеры, похожие на человека (косинусно близкие к любому эталону).

    Исключает назначенные (`person_id IS NULL`), `ignored` и отклонённые для этого
    человека кластеры; сортировка по similarity desc.
    """
    if min_similarity is None:
        min_similarity = settings.T_CLUSTER

    stmt = text(
        f"""
        SELECT fc.id AS cluster_id,
               fc.size AS size,
               MAX(1 - (fc.centroid <=> pre.embedding)) AS similarity
        FROM {settings.ANALYSIS_SCHEMA}.face_clusters fc
        JOIN {settings.ANALYSIS_SCHEMA}.person_ref_embeddings pre
          ON pre.person_id = :pid
        WHERE fc.person_id IS NULL
          AND fc.ignored = false
          AND NOT EXISTS (
              SELECT 1 FROM {settings.ANALYSIS_SCHEMA}.face_cluster_rejections r
              WHERE r.person_id = :pid AND r.cluster_id = fc.id
          )
        GROUP BY fc.id, fc.size
        HAVING MAX(1 - (fc.centroid <=> pre.embedding)) >= :min_sim
        ORDER BY similarity DESC
        """
    )
    rows = (await session.execute(stmt, {'pid': person_id, 'min_sim': min_similarity})).all()

    total = len(rows)
    items = []
    for row in rows[:limit]:
        cluster_id = int(row.cluster_id)
        items.append(
            {
                'cluster_id': cluster_id,
                'size': int(row.size),
                'sample_face_ids': await get_sample_face_ids(session, cluster_id),
                'similarity': float(row.similarity),
            }
        )
    return items, total
