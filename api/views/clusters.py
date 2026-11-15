"""Эндпоинты кластеров."""
from fastapi import APIRouter, Depends, Query

from api.deps import get_session, require_api_key
from common.exceptions import NotFound
from repositories.faces import get_cluster, get_cluster_faces, list_clusters
from schemas.clusters import (
    ClusterAssignRequest,
    ClusterAssignResult,
    ClusterMergeRequest,
    ClusterOut,
)
from schemas.common import Page
from schemas.faces import FaceOut
from services.clustering import (
    assign_cluster_service,
    build_cluster_out,
    build_faces_out,
    merge_clusters_service,
    set_ignored_service,
)

router = APIRouter(dependencies=[Depends(require_api_key)])


@router.get('/clusters', response_model=Page[ClusterOut])
async def clusters_list(
    session=Depends(get_session),
    unassigned: bool | None = None,
    ignored: bool | None = None,
    min_size: int | None = None,
    limit: int = Query(default=100, ge=1, le=1000),
    offset: int = Query(default=0, ge=0),
):
    clusters, total = await list_clusters(
        session,
        unassigned=unassigned,
        ignored=ignored,
        min_size=min_size,
        limit=limit,
        offset=offset,
    )
    items = [await build_cluster_out(session, c) for c in clusters]
    return Page(items=items, total=total, limit=limit, offset=offset)


@router.get('/clusters/{cluster_id}/faces', response_model=Page[FaceOut])
async def cluster_faces(
    cluster_id: int,
    session=Depends(get_session),
    limit: int = Query(default=100, ge=1, le=1000),
    offset: int = Query(default=0, ge=0),
):
    if await get_cluster(session, cluster_id) is None:
        raise NotFound(error_code='not_found', error_message='Cluster not found')
    faces, total = await get_cluster_faces(session, cluster_id, limit=limit, offset=offset)
    return Page(
        items=await build_faces_out(session, faces), total=total, limit=limit, offset=offset
    )


@router.post('/clusters/{cluster_id}/assign', response_model=ClusterAssignResult)
async def cluster_assign(cluster_id: int, body: ClusterAssignRequest, session=Depends(get_session)):
    return await assign_cluster_service(
        session, cluster_id, body.person_id, body.name, body.promote
    )


@router.post('/clusters/{cluster_id}/merge', response_model=ClusterOut)
async def cluster_merge(cluster_id: int, body: ClusterMergeRequest, session=Depends(get_session)):
    return await merge_clusters_service(session, cluster_id, body.target_cluster_id)


@router.post('/clusters/{cluster_id}/ignore', response_model=ClusterOut)
async def cluster_ignore(cluster_id: int, session=Depends(get_session)):
    return await set_ignored_service(session, cluster_id, True)


@router.delete('/clusters/{cluster_id}/ignore', response_model=ClusterOut)
async def cluster_unignore(cluster_id: int, session=Depends(get_session)):
    return await set_ignored_service(session, cluster_id, False)
