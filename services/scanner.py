"""Сканирование директорий: регистрация файлов в scanned_files и постановка задач."""
import os
from dataclasses import dataclass
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from common.settings import settings
from repositories.analysis import queue_tasks
from repositories.scanned_files import mark_missing, present_in_prefix, upsert_file

IMAGE_EXTENSIONS = {'jpg', 'jpeg', 'png', 'webp', 'heic', 'heif', 'tiff', 'tif', 'bmp', 'gif'}
VIDEO_EXTENSIONS = {'mp4', 'mov', 'm4v', 'avi', 'mkv', 'webm', '3gp'}


def file_kind(filename: str) -> str:
    ext = filename.rsplit('.', 1)[-1].lower() if '.' in filename else ''
    if ext in IMAGE_EXTENSIONS:
        return 'image'
    if ext in VIDEO_EXTENSIONS:
        return 'video'
    return 'other'


def normalize_folder_path(folder_path: str) -> str:
    """Убирает ведущие/завершающие '/' (как в s_media_service)."""
    return folder_path.strip('/')


def kinds_for(kind: str) -> list[str]:
    if kind == 'image':
        return ['faces', 'geo']
    if kind == 'video':
        return ['geo']
    return []


@dataclass
class ScanResult:
    registered: int = 0
    updated: int = 0
    marked_missing: int = 0
    queued: int = 0


async def scan_folder(  # noqa: C901
    session: AsyncSession,
    storage_id: UUID,
    folder_path: str = '',
    recursive: bool = True,
    kinds: list[str] | None = None,
    limit: int | None = None,
) -> ScanResult:
    """Обходит папку на диске, регистрирует файлы и ставит задачи анализа."""
    if kinds is None:
        kinds = ['faces', 'geo']
    root = settings.scan_roots.get(str(storage_id))
    if not root:
        raise KeyError(f'storage {storage_id} не найден в SCAN_ROOTS')

    folder_path = normalize_folder_path(folder_path)
    base = os.path.join(root, folder_path)
    if not os.path.isdir(base):
        raise FileNotFoundError(f'каталог не найден: {base}')

    result = ScanResult()
    seen: set[tuple[str, str]] = set()

    def walk():
        if recursive:
            for dirpath, _dirnames, filenames in os.walk(base):
                for fname in filenames:
                    yield dirpath, fname
        else:
            for fname in os.listdir(base):
                full = os.path.join(base, fname)
                if os.path.isfile(full):
                    yield base, fname

    for dirpath, fname in walk():
        if limit is not None and result.registered + result.updated >= limit:
            break
        kind = file_kind(fname)
        if kind == 'other':
            continue

        rel_dir = os.path.relpath(dirpath, root)
        if rel_dir == '.':
            rel_dir = ''
        else:
            rel_dir = rel_dir.replace(os.sep, '/')

        full = os.path.join(dirpath, fname)
        stat = os.stat(full)
        scanned, created, changed = await upsert_file(
            session, storage_id, rel_dir, fname, stat.st_size, stat.st_mtime_ns, kind
        )
        seen.add((rel_dir, fname))
        file_kinds = [k for k in kinds_for(kind) if k in kinds]

        if created:
            result.registered += 1
            await queue_tasks(session, scanned.id, file_kinds)
            result.queued += len(file_kinds)
        elif changed:
            result.updated += 1
            await queue_tasks(session, scanned.id, file_kinds)
            result.queued += len(file_kinds)

    # Пометить отсутствующие только при полном обходе (limit is None).
    if limit is None:
        present = await present_in_prefix(session, storage_id, folder_path)
        missing_ids = [fid for fid, d, f in present if (d, f) not in seen]
        result.marked_missing = await mark_missing(session, missing_ids)

    await session.commit()
    return result
