"""Эндпоинты справочника людей и имён (алиасов)."""
from uuid import UUID

from fastapi import APIRouter, Depends, Query

from api.deps import get_session, require_api_key
from common.exceptions import NotFound
from repositories import persons as persons_repo
from repositories.faces import rematch_faces
from schemas.common import Page
from schemas.persons import (
    PersonFilesOut,
    PersonNameAdd,
    PersonOut,
    PersonSyncRequest,
    PersonSyncResult,
)

router = APIRouter(dependencies=[Depends(require_api_key)])


@router.get('/people', response_model=Page[PersonOut])
async def people_list(
    session=Depends(get_session),
    search: str | None = None,
    limit: int = Query(default=100, ge=1, le=1000),
    offset: int = Query(default=0, ge=0),
):
    items, total = await persons_repo.list_people(
        session, limit=limit, offset=offset, search=search
    )
    return Page(items=items, total=total, limit=limit, offset=offset)


@router.get('/people/{person_id}', response_model=PersonOut)
async def person_info(person_id: UUID, session=Depends(get_session)):
    names = await persons_repo.get_names(session, person_id)
    if not names:
        raise NotFound(error_code='not_found', error_message='Person not found')
    return PersonOut(person_id=person_id, names=names)


@router.post('/people/{person_id}/names', response_model=PersonOut)
async def person_add_name(person_id: UUID, body: PersonNameAdd, session=Depends(get_session)):
    await persons_repo.upsert_person_name(session, person_id, body.name)
    await session.commit()
    names = await persons_repo.get_names(session, person_id)
    return PersonOut(person_id=person_id, names=names)


@router.delete('/people/{person_id}/names/{name}', response_model=PersonOut)
async def person_remove_name(person_id: UUID, name: str, session=Depends(get_session)):
    removed = await persons_repo.remove_person_name(session, person_id, name)
    if removed == 0:
        raise NotFound(error_code='not_found', error_message='Name not found')
    await session.commit()
    names = await persons_repo.get_names(session, person_id)
    return PersonOut(person_id=person_id, names=names)


@router.get('/people/{person_id}/files', response_model=PersonFilesOut)
async def person_files(
    person_id: UUID,
    session=Depends(get_session),
    limit: int = 100,
    cursor: int | None = None,
):
    catalog_ids, next_cursor = await persons_repo.get_person_catalog_file_ids(
        session, person_id, limit=limit, cursor=cursor
    )
    return PersonFilesOut(
        person_id=person_id, catalog_file_ids=catalog_ids, next_cursor=next_cursor
    )


@router.put('/persons/sync', response_model=PersonSyncResult)
async def persons_sync(body: PersonSyncRequest, session=Depends(get_session)):
    upserted = 0
    removed = 0

    if body.full:
        existing = await persons_repo.list_person_ids(session)
        incoming = {p.person_id for p in body.persons}
        to_remove = [pid for pid in existing if pid not in incoming]
        removed = await persons_repo.delete_person_refs(session, to_remove)

    for person in body.persons:
        created = await persons_repo.upsert_person_ref(session, person.person_id)
        if created:
            upserted += 1
        await persons_repo.upsert_person_name(session, person.person_id, person.name)
        await persons_repo.clear_person_embeddings(session, person.person_id)
        for embedding in person.embeddings:
            await persons_repo.add_person_embedding(session, person.person_id, embedding)

    await session.commit()
    # После применения справочника перематчиваем авто-лица без person_id (раздел 9.6).
    faces_matched = await rematch_faces(session)
    return PersonSyncResult(upserted=upserted, removed=removed, faces_matched=faces_matched)
