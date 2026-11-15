"""Эндпоинты scanned-files и связи с каталогом."""
from uuid import UUID

from fastapi import APIRouter, Depends, Query

from api.deps import get_scanned_file_or_404, get_session, require_api_key
from repositories.analysis import get_analysis_rows, rescan_file
from repositories.scanned_files import list_files, set_catalog_file_id
from schemas.common import Page
from schemas.files import (
    CatalogLinksRequest,
    CatalogLinksResult,
    RescanRequest,
    ScannedFileOut,
)
from schemas.geo import AnalysisStatusOut

router = APIRouter(dependencies=[Depends(require_api_key)])


@router.get('/scanned-files', response_model=Page[ScannedFileOut])
async def scanned_files_list(
    session=Depends(get_session),
    storage_id: UUID | None = None,
    folder_path: str | None = None,
    status: str | None = None,
    has_faces: bool | None = None,
    limit: int = Query(default=100, ge=1, le=1000),
    offset: int = Query(default=0, ge=0),
):
    files, total = await list_files(
        session,
        storage_id=storage_id,
        folder_path=folder_path,
        status=status,
        has_faces=has_faces,
        limit=limit,
        offset=offset,
    )
    return Page(items=files, total=total, limit=limit, offset=offset)


@router.get('/scanned-files/{file_id}/analysis', response_model=list[AnalysisStatusOut])
async def scanned_file_analysis(file_id: int, session=Depends(get_session)):
    await get_scanned_file_or_404(session, file_id)
    return await get_analysis_rows(session, file_id)


@router.post('/scanned-files/{file_id}/rescan', status_code=202)
async def scanned_file_rescan(file_id: int, body: RescanRequest, session=Depends(get_session)):
    await get_scanned_file_or_404(session, file_id)
    await rescan_file(session, file_id, list(body.kinds))
    return {'status': 'accepted'}


@router.put('/scanned-files/catalog-links', response_model=CatalogLinksResult)
async def catalog_links(body: CatalogLinksRequest, session=Depends(get_session)):
    linked = 0
    for link in body.links:
        if await get_scanned_file_or_404(session, link.scanned_file_id):
            await set_catalog_file_id(session, link.scanned_file_id, link.catalog_file_id)
            linked += 1
    await session.commit()
    return CatalogLinksResult(linked=linked)
