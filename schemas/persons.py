"""Схемы справочника людей."""
from uuid import UUID

from pydantic import BaseModel, Field


class PersonRefIn(BaseModel):
    person_id: UUID
    name: str
    embeddings: list[list[float]] = Field(default_factory=list)


class PersonSyncRequest(BaseModel):
    persons: list[PersonRefIn]
    full: bool = False


class PersonSyncResult(BaseModel):
    upserted: int
    removed: int
    faces_matched: int


class PersonOut(BaseModel):
    person_id: UUID
    names: list[str]


class PersonNameAdd(BaseModel):
    name: str = Field(min_length=1, max_length=200)


class PersonFilesOut(BaseModel):
    person_id: UUID
    catalog_file_ids: list[UUID]
    next_cursor: int | None
