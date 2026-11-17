"""Справочник людей: person_refs, имена (алиасы), эталонные эмбеддинги."""
from uuid import UUID

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from db.models import Face, PersonName, PersonRef, PersonRefEmbedding, ScannedFile


async def get_names(session: AsyncSession, person_id: UUID) -> list[str]:
    result = await session.execute(
        select(PersonName.name).where(PersonName.person_id == person_id).order_by(PersonName.id)
    )
    return list(result.scalars().all())


async def get_primary_name(session: AsyncSession, person_id: UUID) -> str | None:
    names = await get_names(session, person_id)
    return names[0] if names else None


async def get_names_map(session: AsyncSession, person_ids: set[UUID]) -> dict[UUID, str]:
    """person_id -> первое (основное) имя."""
    if not person_ids:
        return {}
    result = await session.execute(
        select(PersonName.person_id, PersonName.name)
        .where(PersonName.person_id.in_(list(person_ids)))
        .order_by(PersonName.person_id, PersonName.id)
    )
    mapping: dict[UUID, str] = {}
    for person_id, name in result.all():
        mapping.setdefault(person_id, name)
    return mapping


async def add_person_name(session: AsyncSession, person_id: UUID, name: str) -> bool:
    """Добавляет имя-алиас; возвращает True, если добавлено (False — уже есть)."""
    existing = await session.execute(
        select(PersonName.id).where(
            PersonName.person_id == person_id, PersonName.name == name
        )
    )
    if existing.scalar() is not None:
        return False
    session.add(PersonName(person_id=person_id, name=name))
    await session.flush()
    return True


async def remove_person_name(session: AsyncSession, person_id: UUID, name: str) -> int:
    result = await session.execute(
        delete(PersonName).where(PersonName.person_id == person_id, PersonName.name == name)
    )
    return result.rowcount


async def upsert_person_ref(session: AsyncSession, person_id: UUID) -> bool:
    """Создаёт person_ref, если нет; возвращает True, если создан."""
    if await session.get(PersonRef, person_id) is not None:
        return False
    session.add(PersonRef(person_id=person_id))
    await session.flush()
    return True


async def upsert_person_name(session: AsyncSession, person_id: UUID, name: str) -> bool:
    await upsert_person_ref(session, person_id)
    return await add_person_name(session, person_id, name)


async def add_person_embedding(session: AsyncSession, person_id: UUID, embedding) -> None:
    session.add(PersonRefEmbedding(person_id=person_id, embedding=embedding))
    await session.flush()


async def clear_person_embeddings(session: AsyncSession, person_id: UUID) -> None:
    await session.execute(
        delete(PersonRefEmbedding).where(PersonRefEmbedding.person_id == person_id)
    )


async def delete_person_refs(session: AsyncSession, person_ids: list[UUID]) -> int:
    if not person_ids:
        return 0
    result = await session.execute(
        delete(PersonRef).where(PersonRef.person_id.in_(person_ids))
    )
    return result.rowcount


async def list_person_ids(session: AsyncSession) -> list[UUID]:
    result = await session.execute(select(PersonRef.person_id))
    return list(result.scalars().all())


async def list_people(
    session: AsyncSession,
    limit: int = 100,
    offset: int = 0,
    search: str | None = None,
) -> tuple[list[dict], int]:
    """Список людей (person_id -> имена) с пагинацией и поиском по имени.

    Сортировка — по первому (основному) имени без учёта регистра; ``search``
    фильтрует по любому имени (ILIKE ``%search%``).
    """
    primary_name = (
        select(PersonName.name)
        .where(PersonName.person_id == PersonRef.person_id)
        .order_by(PersonName.id)
        .limit(1)
        .correlate(PersonRef)
        .scalar_subquery()
    )

    conditions = []
    if search:
        conditions.append(
            select(PersonName.id)
            .where(PersonName.person_id == PersonRef.person_id)
            .where(PersonName.name.ilike(f'%{search}%'))
            .exists()
        )

    count_stmt = select(func.count()).select_from(PersonRef)
    if conditions:
        count_stmt = count_stmt.where(*conditions)
    total = await session.scalar(count_stmt) or 0

    stmt = select(PersonRef.person_id, primary_name.label('primary_name'))
    if conditions:
        stmt = stmt.where(*conditions)
    stmt = stmt.order_by(func.lower(primary_name), PersonRef.person_id)
    stmt = stmt.limit(limit).offset(offset)
    rows = (await session.execute(stmt)).all()

    person_ids = [row.person_id for row in rows]
    names_map: dict[UUID, list[str]] = {pid: [] for pid in person_ids}
    if person_ids:
        names_rows = await session.execute(
            select(PersonName.person_id, PersonName.name)
            .where(PersonName.person_id.in_(person_ids))
            .order_by(PersonName.person_id, PersonName.id)
        )
        for person_id, name in names_rows.all():
            names_map[person_id].append(name)

    return [{'person_id': pid, 'names': names_map[pid]} for pid in person_ids], total


SAMPLE_FACES = 6


async def list_people_summaries(
    session: AsyncSession,
    limit: int = 100,
    offset: int = 0,
    search: str | None = None,
) -> tuple[list[dict], int]:
    """Сводка по людям: имена + агрегаты лиц (face_count, sample, счётчики файлов)."""
    people, total = await list_people(session, limit, offset, search)
    person_ids = [p['person_id'] for p in people]
    if not person_ids:
        return [], total

    # face_count и счётчики файлов — одним GROUP BY (не N+1).
    agg_stmt = (
        select(
            Face.person_id,
            func.count().label('face_count'),
            func.count(func.distinct(ScannedFile.id)).label('total_files_count'),
            func.count(func.distinct(ScannedFile.id))
            .filter(ScannedFile.catalog_file_id.is_not(None))
            .label('catalog_files_count'),
        )
        .join(ScannedFile, ScannedFile.id == Face.file_id)
        .where(Face.person_id.in_(person_ids))
        .where(Face.status != 'rejected')
        .group_by(Face.person_id)
    )
    agg_rows = (await session.execute(agg_stmt)).all()
    counts = {row.person_id: row for row in agg_rows}

    # sample-лица (топ-N по det_score) — одним запросом через оконную функцию.
    rn = func.row_number().over(
        partition_by=Face.person_id,
        order_by=(Face.det_score.desc(), Face.id),
    ).label('rn')
    sample_subq = (
        select(Face.person_id, Face.id, rn)
        .where(Face.person_id.in_(person_ids))
        .where(Face.status != 'rejected')
        .subquery()
    )
    sample_stmt = (
        select(sample_subq.c.person_id, sample_subq.c.id)
        .where(sample_subq.c.rn <= SAMPLE_FACES)
        .order_by(sample_subq.c.person_id, sample_subq.c.rn)
    )
    samples: dict[UUID, list[int]] = {pid: [] for pid in person_ids}
    for person_id, face_id in (await session.execute(sample_stmt)).all():
        samples[person_id].append(int(face_id))

    items = []
    for person in people:
        pid = person['person_id']
        row = counts.get(pid)
        items.append(
            {
                'person_id': pid,
                'names': person['names'],
                'face_count': int(row.face_count) if row else 0,
                'sample_face_ids': samples[pid],
                'catalog_files_count': int(row.catalog_files_count) if row else 0,
                'total_files_count': int(row.total_files_count) if row else 0,
            }
        )
    return items, total


async def get_person_catalog_file_ids(
    session: AsyncSession, person_id: UUID, limit: int = 100, cursor: int | None = None
) -> tuple[list[UUID], int | None]:
    """catalog_file_id файлов с этим человеком (без rejected), курсорная пагинация."""
    from db.models import Face, ScannedFile

    stmt = (
        select(Face.id, ScannedFile.catalog_file_id)
        .join(ScannedFile, ScannedFile.id == Face.file_id)
        .where(Face.person_id == person_id)
        .where(Face.status != 'rejected')
        .where(ScannedFile.catalog_file_id.is_not(None))
        .order_by(Face.id)
        .limit(limit + 1)
    )
    if cursor is not None:
        stmt = stmt.where(Face.id > cursor)

    result = await session.execute(stmt)
    rows = list(result.all())
    next_cursor = None
    if len(rows) > limit:
        rows = rows[:limit]
        next_cursor = rows[-1][0]
    return [row[1] for row in rows], next_cursor
