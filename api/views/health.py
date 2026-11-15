"""Health check: БД, модель, SCAN_ROOTS, FACES_DIR."""
from fastapi import APIRouter
from fastapi.responses import JSONResponse
from sqlalchemy import text

from common.settings import settings
from db.connector import AsyncSession
from services.model import model_available

router = APIRouter()


async def _check_db() -> bool:
    try:
        async with AsyncSession() as session:
            await session.execute(text('SELECT 1'))
        return True
    except Exception:  # pylint: disable=broad-exception-caught
        return False


@router.get('/health')
async def health() -> JSONResponse:
    db_ok = await _check_db()
    model_ok = model_available()
    try:
        settings.validate_paths()
        paths_ok = True
    except RuntimeError:
        paths_ok = False

    payload = {
        'status': 'ok' if (db_ok and model_ok and paths_ok) else 'degraded',
        'db': db_ok,
        'model': model_ok,
        'scan_roots': settings.scan_roots,
        'faces_dir': settings.FACES_DIR,
    }
    return JSONResponse(status_code=200 if db_ok else 503, content=payload)
