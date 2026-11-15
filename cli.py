# flake8: noqa: T201
"""CLI для проверки: analyze, reconcile, cleanup-crops."""
import argparse
import asyncio
import logging
import os
from uuid import UUID

from common.settings import settings
from db.connector import AsyncSession
from repositories.analysis import claim_tasks
from repositories.faces import get_faces_for_file
from repositories.scanned_files import list_files
from services.crops import cleanup_orphan_crops
from services.reconcile import reconcile_catalog
from services.scanner import file_kind, scan_folder
from worker.processors import faces as faces_proc
from worker.processors.faces import process_faces_task
from worker.processors.geo import process_geo_task

PROCESSORS = {'geo': process_geo_task, 'faces': process_faces_task}


async def _drain_queue(kinds: list[str]) -> int:
    processed = 0
    while True:
        claimed = 0
        for kind in kinds:
            async with AsyncSession() as session:
                tasks = await claim_tasks(
                    session, kind, settings.WORKER_CONCURRENCY, settings.LOCK_TIMEOUT_SEC
                )
            for task in tasks:
                await PROCESSORS[kind](task)
                processed += 1
                claimed += 1
        if claimed == 0:
            break
    return processed


async def _analyze(args) -> None:
    settings.validate_paths()
    root = settings.scan_roots.get(str(args.storage))
    base = os.path.join(root, args.path)

    if args.dry_run:
        count = 0
        for _, _, filenames in os.walk(base):
            count += sum(1 for f in filenames if file_kind(f) != 'other')
        print(f'dry-run: файлов для анализа: {count}')
        return

    async with AsyncSession() as session:
        result = await scan_folder(
            session,
            args.storage,
            args.path,
            recursive=True,
            kinds=args.kinds,
            limit=args.limit,
        )
    print(
        f'зарегистрировано={result.registered} обновлено={result.updated} '
        f'отсутствуют={result.marked_missing} задач={result.queued}'
    )

    processed = await _drain_queue(args.kinds)
    print(f'обработано задач: {processed}')

    if 'faces' in args.kinds:
        async with AsyncSession() as session:
            files, _ = await list_files(session, has_faces=True, limit=100000)
            total_faces = 0
            for scanned in files:
                total_faces += len(await get_faces_for_file(session, scanned.id))
        print(f'лиц найдено: {total_faces}')


async def _reconcile(args) -> None:
    async with AsyncSession() as session:
        linked = await reconcile_catalog(session)
    print(f'связано с каталогом: {linked}')


async def _cleanup_crops(args) -> None:
    from sqlalchemy import select

    from db.models import Face

    async with AsyncSession() as session:
        result = await session.execute(
            select(Face.crop_path).where(Face.crop_path.is_not(None))
        )
        valid = {row[0] for row in result.all()}
    removed = cleanup_orphan_crops(valid)
    print(f'удалено осиротевших вырезок: {removed}')


def main() -> None:
    parser = argparse.ArgumentParser(prog='s_media_analyzer')
    sub = parser.add_subparsers(dest='cmd', required=True)

    p = sub.add_parser('analyze')
    p.add_argument('--storage', required=True)
    p.add_argument('--path', default='')
    p.add_argument('--no-save-crops', action='store_true')
    p.add_argument('--limit', type=int, default=None)
    p.add_argument('--kinds', default='faces,geo')
    p.add_argument('--dry-run', action='store_true')
    p.set_defaults(func=_analyze)

    p = sub.add_parser('reconcile')
    p.set_defaults(func=_reconcile)

    p = sub.add_parser('cleanup-crops')
    p.set_defaults(func=_cleanup_crops)

    args = parser.parse_args()
    if args.cmd == 'analyze':
        args.storage = UUID(args.storage)
        args.path = args.path.strip('/')
        args.kinds = [k.strip() for k in args.kinds.split(',')]
        faces_proc.SAVE_CROPS = not args.no_save_crops

    logging.basicConfig(level=logging.INFO)
    asyncio.run(args.func(args))


if __name__ == '__main__':
    main()
