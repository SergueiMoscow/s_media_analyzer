"""Схемы геоданных и статусов обработки."""
from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict

from schemas.common import AnalysisKind, AnalysisStatus


class GeoOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    scanned_file_id: int
    catalog_file_id: UUID | None
    lat: float
    lon: float
    alt: float | None
    taken_at: datetime | None
    source: Literal['exif', 'video', 'manual']


class GeoPoint(BaseModel):
    scanned_file_id: int
    catalog_file_id: UUID | None
    lat: float
    lon: float


class AnalysisStatusOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    scanned_file_id: int
    kind: AnalysisKind
    status: AnalysisStatus
    analyzer_version: int
    attempts: int
    error: str | None
    processed_at: datetime | None


class ProcessingItemOut(BaseModel):
    """Задача, находящаяся в обработке прямо сейчас (``GET /stats`` -> ``processing``)."""

    scanned_file_id: int
    catalog_file_id: UUID | None
    folder_path: str
    filename: str
    kind: AnalysisKind
    attempts: int
    locked_at: datetime | None


class QueueItemOut(BaseModel):
    """Строка детальной очереди обработки (``GET /queue`` -> ``items``)."""

    scanned_file_id: int
    catalog_file_id: UUID | None
    folder_path: str
    filename: str
    kind: AnalysisKind
    status: AnalysisStatus
    attempts: int
    error: str | None
    locked_at: datetime | None
    processed_at: datetime | None
    analyzer_version: int


class StatsOut(BaseModel):
    queue: dict[str, dict[str, int]]  # kind -> status -> count
    processing: list[ProcessingItemOut]
    scanned_files: int
    faces_total: int
    faces_unassigned: int
    clusters_total: int
    geo_total: int
    analyzer_version: int
