"""Схемы лиц."""
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from schemas.common import FaceStatus
from schemas.files import PromoteItem


class BBox(BaseModel):
    """Нормализованные координаты 0..1 относительно изображения после EXIF-ориентации."""

    x: float = Field(ge=0, le=1)
    y: float = Field(ge=0, le=1)
    w: float = Field(gt=0, le=1)
    h: float = Field(gt=0, le=1)


class FaceOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    scanned_file_id: int
    catalog_file_id: UUID | None
    storage_id: UUID | None
    folder_path: str | None
    filename: str | None
    bbox: BBox
    det_score: float
    cluster_id: int | None
    person_id: UUID | None
    person_name: str | None = None
    match_score: float | None
    status: FaceStatus
    has_crop: bool


class FaceUpdate(BaseModel):
    """PATCH /faces/{id}: хотя бы одно поле."""

    person_id: UUID | None = None
    name: str | None = None
    status: FaceStatus | None = None
    unassign: bool = False
    promote: bool = False


class FaceUpdateResult(BaseModel):
    face: FaceOut
    files_to_promote: list[PromoteItem] = Field(default_factory=list)
