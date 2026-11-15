"""Административные эндпоинты: scan, reconcile-catalog, stats."""

from fastapi import APIRouter, Depends

from api.deps import get_session, require_api_key
from repositories.analysis import get_stats
from schemas.files import ScanRequest, ScanResult
from schemas.geo import StatsOut
from services.reconcile import reconcile_catalog
from services.scanner import scan_folder

router = APIRouter(dependencies=[Depends(require_api_key)])


@router.post('/admin/scan', response_model=ScanResult, status_code=202)
async def admin_scan(body: ScanRequest, session=Depends(get_session)):
    result = await scan_folder(
        session,
        storage_id=body.storage_id,
        folder_path=body.folder_path,
        recursive=body.recursive,
        kinds=list(body.kinds),
        limit=body.limit,
    )
    return result


@router.post('/admin/reconcile-catalog')
async def admin_reconcile(session=Depends(get_session)):
    linked = await reconcile_catalog(session)
    return {'linked': linked}


@router.get('/stats', response_model=StatsOut)
async def stats(session=Depends(get_session)):
    return await get_stats(session)
