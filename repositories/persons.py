"""Справочник людей: person_refs, имена (алиасы), эталонные эмбеддинги."""
from uuid import UUID

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from db.models import PersonName, PersonRef, PersonRefEmbedding


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
