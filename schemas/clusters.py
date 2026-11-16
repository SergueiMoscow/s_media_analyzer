"""Схемы кластеров лиц."""
from uuid import UUID

from pydantic import BaseModel, Field

from schemas.files import PromoteItem


class ClusterOut(BaseModel):
    id: int
    size: int
    person_id: UUID | None
    person_name: str | None = None
    ignored: bool
    sample_face_ids: list[int]


class CandidateClusterOut(BaseModel):
    cluster_id: int
    size: int
    sample_face_ids: list[int]
    similarity: float


class ClusterAssignRequest(BaseModel):
    person_id: UUID
    name: str = Field(min_length=1, max_length=200)
    promote: bool = False


class ClusterAssignResult(BaseModel):
    cluster_id: int
    person_id: UUID
    faces_updated: int
    reference_embedding: list[float] = Field(min_length=512, max_length=512)
    files_to_promote: list[PromoteItem] = Field(default_factory=list)


class ClusterMergeRequest(BaseModel):
    target_cluster_id: int
