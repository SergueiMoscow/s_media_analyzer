"""Эндпоинты лиц."""
import asyncio
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from fastapi.responses import Response

from api.deps import (
    get_scanned_by_catalog_or_404,
    get_scanned_file_or_404,
    get_session,
    require_api_key,
)
from common.exceptions import NotFound
from common.settings import settings
from repositories.faces import get_face_by_id, get_faces_for_file
from repositories.persons import upsert_person_name
from repositories.scanned_files import full_path
from schemas.faces import FaceOut, FaceUpdate, FaceUpdateResult
from schemas.files import PromoteItem
from services.clustering import build_face_out, build_faces_out
from services.crops import resize_jpeg, thumbnail_from_original

router = APIRouter(dependencies=[Depends(require_api_key)])


@router.get('/scanned-files/{file_id}/faces', response_model=list[FaceOut])
async def scanned_file_faces(
    file_id: int, include_rejected: bool = False, session=Depends(get_session)
):
    await get_scanned_file_or_404(session, file_id)
    faces = await get_faces_for_file(session, file_id, include_rejected=include_rejected)
    return await build_faces_out(session, faces)


@router.get('/catalog-files/{catalog_file_id}/faces', response_model=list[FaceOut])
async def catalog_file_faces(
    catalog_file_id: UUID, include_rejected: bool = False, session=Depends(get_session)
):
    scanned = await get_scanned_by_catalog_or_404(session, catalog_file_id)
    faces = await get_faces_for_file(session, scanned.id, include_rejected=include_rejected)
    return await build_faces_out(session, faces)


@router.get('/faces/{face_id}', response_model=FaceOut)
async def face_info(face_id: int, session=Depends(get_session)):
    face = await get_face_by_id(session, face_id)
    if face is None:
        raise NotFound(error_code='not_found', error_message='Face not found')
    return await build_face_out(session, face)


@router.patch('/faces/{face_id}', response_model=FaceUpdateResult)
async def patch_face(face_id: int, body: FaceUpdate, session=Depends(get_session)):
    face = await get_face_by_id(session, face_id)
    if face is None:
        raise NotFound(error_code='not_found', error_message='Face not found')

    if body.unassign:
        face.person_id = None
    elif body.person_id is not None:
        if body.name is not None:
            await upsert_person_name(session, body.person_id, body.name)
        face.person_id = body.person_id
    if body.status is not None:
        face.status = body.status

    files_to_promote: list[PromoteItem] = []
    if body.promote and face.scanned_file.catalog_file_id is None:
        scanned = face.scanned_file
        files_to_promote = [
            PromoteItem(
                scanned_file_id=scanned.id,
                storage_id=scanned.storage_id,
                folder_path=scanned.folder_path,
                filename=scanned.filename,
            )
        ]

    await session.commit()
    return FaceUpdateResult(
        face=await build_face_out(session, face), files_to_promote=files_to_promote
    )


@router.get('/faces/{face_id}/thumbnail')
async def face_thumbnail(
    face_id: int,
    size: int = Query(default=160, ge=16, le=1024),
    session=Depends(get_session),
):
    face = await get_face_by_id(session, face_id)
    if face is None:
        raise NotFound(error_code='not_found', error_message='Face not found')

    scanned = await get_scanned_file_or_404(session, face.file_id)
    try:
        path = full_path(scanned.storage_id, scanned.folder_path, scanned.filename)
    except KeyError:
        raise NotFound(
            error_code='storage_not_configured', error_message='Storage not configured'
        ) from None

    headers = {'Cache-Control': 'public, max-age=86400'}

    if face.crop_path and settings.faces_dir_path is not None:
        abs_path = settings.faces_dir_path / face.crop_path
        try:
            if abs_path.exists():
                data = abs_path.read_bytes()
                if size != settings.CROP_MAX_SIDE:
                    data = resize_jpeg(data, size)
                return Response(content=data, media_type='image/jpeg', headers=headers)
        except Exception:  # pylint: disable=broad-exception-caught
            pass  # вырезка недоступна/битая — генерируем из оригинала

    try:
        data = await asyncio.to_thread(thumbnail_from_original, path, face.bbox, size)
    except Exception:  # pylint: disable=broad-exception-caught
        raise NotFound(
            error_code='thumbnail_unavailable', error_message='Thumbnail unavailable'
        ) from None
    return Response(content=data, media_type='image/jpeg', headers=headers)
