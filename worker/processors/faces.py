"""Процессор лиц (вид 'faces'): детекция, эмбеддинги, кластеризация, вырезки."""
import asyncio
import logging
import os

from common.settings import settings
from db.connector import AsyncSession
from imaging import open_oriented_rgb, resize_to_max_side, to_bgr_numpy
from repositories.analysis import complete_task, record_error
from repositories.faces import (
    create_cluster,
    delete_auto_faces,
    find_nearest_cluster,
    find_nearest_person_ref,
    get_faces_for_file,
    insert_face,
    set_face_crop_path,
    update_cluster,
)
from repositories.scanned_files import full_path, get_by_id
from services.crops import delete_crop, make_crop_bytes, write_crop
from services.faces_service import iou, normalize_bbox, update_centroid
from services.model import detect_and_embed

logger = logging.getLogger(__name__)

MAX_ATTEMPTS = 3
IOU_KEEP_THRESHOLD = 0.5
SAVE_CROPS = True  # CLI `analyze --no-save-crops` выставляет False


def _detect_candidates(path: str) -> list[dict]:
    """Открывает изображение, детектирует лица, фильтрует и нормализует bbox."""
    oriented = open_oriented_rgb(path)
    orig_w, orig_h = oriented.size
    det_img, scale = resize_to_max_side(oriented, settings.MAX_IMAGE_SIDE)
    bgr = to_bgr_numpy(det_img)
    detections = detect_and_embed(bgr, settings.DET_SCORE_MIN)

    candidates = []
    for det in detections:
        bbox_orig = [c / scale for c in det.bbox]
        width = bbox_orig[2] - bbox_orig[0]
        height = bbox_orig[3] - bbox_orig[1]
        if min(width, height) < settings.MIN_FACE_PX:
            continue
        candidates.append(
            {
                'bbox': normalize_bbox(bbox_orig, orig_w, orig_h),
                'det_score': det.det_score,
                'embedding': det.embedding,
            }
        )
    return candidates


async def _match(session, embedding: list[float]) -> tuple:
    """Возвращает (person_id, match_score, cluster_id)."""
    person_id = None
    match_score = None
    person_match = await find_nearest_person_ref(session, embedding)
    if person_match and person_match['similarity'] >= settings.T_PERSON:
        person_id = person_match['person_id']
        match_score = person_match['similarity']

    cluster_match = await find_nearest_cluster(session, embedding)
    if cluster_match and cluster_match['similarity'] >= settings.T_CLUSTER:
        centroid, size = update_centroid(
            cluster_match['centroid'], cluster_match['size'], embedding
        )
        await update_cluster(session, cluster_match['id'], centroid, size)
        cluster_id = cluster_match['id']
        if cluster_match['person_id'] and person_id is None:
            person_id = cluster_match['person_id']
            match_score = cluster_match['similarity']
    else:
        cluster_id = await create_cluster(session, embedding)

    return person_id, match_score, cluster_id


async def process_faces_task(task) -> None:  # noqa: C901
    """Обрабатывает одну задачу вида 'faces'."""
    file_id = task.file_id
    task_id = task.id
    attempts = task.attempts or 0
    created_crops: list[str] = []
    try:
        async with AsyncSession() as session:
            scanned = await get_by_id(session, file_id)
            if scanned is None:
                await complete_task(session, task_id, 'skipped', 'file not found in DB')
                return
            if scanned.kind != 'image':
                await complete_task(session, task_id, 'skipped', 'not an image')
                return

            try:
                path = full_path(scanned.storage_id, scanned.folder_path, scanned.filename)
            except KeyError as exc:
                await complete_task(session, task_id, 'failed', str(exc))
                return
            if not os.path.exists(path):
                await complete_task(session, task_id, 'skipped', 'file missing on disk')
                return

            candidates = await asyncio.to_thread(_detect_candidates, path)

            existing = await get_faces_for_file(session, file_id, include_rejected=True)
            kept = [f for f in existing if f.status in ('confirmed', 'rejected')]
            new_candidates = [
                c
                for c in candidates
                if not any(iou(c['bbox'], k.bbox) > IOU_KEEP_THRESHOLD for k in kept)
            ]

            auto_faces = [f for f in existing if f.status == 'auto']
            await delete_auto_faces(session, file_id)
            for face in auto_faces:
                delete_crop(face.crop_path)

            for candidate in new_candidates:
                person_id, match_score, cluster_id = await _match(
                    session, candidate['embedding']
                )
                face = await insert_face(
                    session,
                    file_id,
                    candidate['bbox'],
                    candidate['embedding'],
                    candidate['det_score'],
                    cluster_id=cluster_id,
                    person_id=person_id,
                    match_score=match_score,
                    status='auto',
                )
                if SAVE_CROPS:
                    crop_bytes = make_crop_bytes(path, candidate['bbox'])
                    rel_path = write_crop(face.id, crop_bytes)
                    created_crops.append(rel_path)
                    await set_face_crop_path(session, face.id, rel_path)

            await complete_task(session, task_id, 'done')
    except Exception as exc:  # pylint: disable=broad-exception-caught
        logger.exception('faces task %s failed', task_id)
        for rel_path in created_crops:
            delete_crop(rel_path)
        async with AsyncSession() as session:
            if attempts >= MAX_ATTEMPTS:
                await complete_task(session, task_id, 'failed', str(exc))
            else:
                await record_error(session, task_id, str(exc))
