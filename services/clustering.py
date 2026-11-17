"""Кластеризация: assign, merge, ignore, продвижение, сериализация."""
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from common.exceptions import Conflict, NotFound
from db.models import Face, FaceCluster
from repositories import faces as faces_repo
from repositories.persons import get_names_map, upsert_person_name
from repositories.scanned_files import get_by_id
from schemas.clusters import ClusterAssignResult, ClusterOut
from schemas.faces import FaceOut
from schemas.files import PromoteItem


async def build_face_out(session: AsyncSession, face: Face, names: dict | None = None) -> FaceOut:
    out = FaceOut.model_validate(face)
    if face.person_id is not None:
        if names is None:
            names = await get_names_map(session, {face.person_id})
        out.person_name = names.get(face.person_id)
    return out


async def build_faces_out(session: AsyncSession, faces: list[Face]) -> list[FaceOut]:
    person_ids = {f.person_id for f in faces if f.person_id is not None}
    names = await get_names_map(session, person_ids)
    return [await build_face_out(session, face, names) for face in faces]


async def build_cluster_out(session: AsyncSession, cluster: FaceCluster) -> ClusterOut:
    names = await get_names_map(session, {cluster.person_id}) if cluster.person_id else {}
    sample = await faces_repo.get_sample_face_ids(session, cluster.id)
    catalog_count, total_count = await faces_repo.get_cluster_file_counts(
        session, cluster.id
    )
    return ClusterOut(
        id=cluster.id,
        size=cluster.size,
        person_id=cluster.person_id,
        person_name=names.get(cluster.person_id),
        ignored=cluster.ignored,
        sample_face_ids=sample,
        catalog_files_count=catalog_count,
        total_files_count=total_count,
    )


async def promotable_files_for_cluster(session: AsyncSession, cluster_id: int) -> list[PromoteItem]:
    """Файлы кластера без catalog_file_id (для продвижения в каталог)."""
    cluster_faces, _ = await faces_repo.get_cluster_faces(session, cluster_id, limit=100000)
    file_ids = {face.file_id for face in cluster_faces}
    items = []
    for file_id in file_ids:
        scanned = await get_by_id(session, file_id)
        if scanned is not None and scanned.catalog_file_id is None:
            items.append(
                PromoteItem(
                    scanned_file_id=scanned.id,
                    storage_id=scanned.storage_id,
                    folder_path=scanned.folder_path,
                    filename=scanned.filename,
                )
            )
    return items


async def assign_cluster_service(
    session: AsyncSession,
    cluster_id: int,
    person_id: UUID,
    name: str,
    promote: bool,
) -> ClusterAssignResult:
    cluster = await faces_repo.get_cluster(session, cluster_id)
    if cluster is None:
        raise NotFound(error_code='not_found', error_message='Cluster not found')
    if cluster.person_id is not None and cluster.person_id != person_id:
        raise Conflict(
            error_code='conflict', error_message='Cluster already assigned to another person'
        )

    # person_ref должен существовать до вставки эталонного эмбеддинга (FK).
    await upsert_person_name(session, person_id, name)
    faces_updated = await faces_repo.assign_cluster(session, cluster_id, person_id, [])

    files_to_promote = (
        await promotable_files_for_cluster(session, cluster_id) if promote else []
    )
    centroid = await faces_repo.get_cluster_centroid(session, cluster_id)
    await session.commit()
    return ClusterAssignResult(
        cluster_id=cluster_id,
        person_id=person_id,
        faces_updated=faces_updated,
        reference_embedding=centroid,
        files_to_promote=files_to_promote,
    )


async def merge_clusters_service(
    session: AsyncSession, source_id: int, target_id: int
) -> ClusterOut:
    if source_id == target_id:
        raise Conflict(error_code='conflict', error_message='Cannot merge cluster into itself')
    if await faces_repo.get_cluster(session, source_id) is None:
        raise NotFound(error_code='not_found', error_message='Cluster not found')
    if await faces_repo.get_cluster(session, target_id) is None:
        raise NotFound(error_code='not_found', error_message='Target cluster not found')

    await faces_repo.merge_clusters(session, source_id, target_id)
    await session.commit()
    target = await faces_repo.get_cluster(session, target_id)
    return await build_cluster_out(session, target)


async def set_ignored_service(session: AsyncSession, cluster_id: int, ignored: bool) -> ClusterOut:
    cluster = await faces_repo.get_cluster(session, cluster_id)
    if cluster is None:
        raise NotFound(error_code='not_found', error_message='Cluster not found')
    await faces_repo.set_cluster_ignored(session, cluster_id, ignored)
    await session.commit()
    await session.refresh(cluster)
    return await build_cluster_out(session, cluster)
