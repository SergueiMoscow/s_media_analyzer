"""Схемы файлов (scanned_files) и связи с каталогом."""
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from schemas.common import AnalysisKind


class ScannedFileOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    storage_id: UUID
    folder_path: str
    filename: str
    kind: str
    status: str
    catalog_file_id: UUID | None


class PromoteItem(BaseModel):
    scanned_file_id: int
    storage_id: UUID
    folder_path: str
    filename: str


class ScanRequest(BaseModel):
    storage_id: UUID
    folder_path: str = ''
    recursive: bool = True
    kinds: list[AnalysisKind] = Field(default_factory=lambda: ['faces', 'geo'])
    limit: int | None = None


class ScanResult(BaseModel):
    registered: int
    updated: int
    marked_missing: int
    queued: int


class RescanRequest(BaseModel):
    kinds: list[AnalysisKind] = Field(default_factory=lambda: ['faces', 'geo'])


class CatalogLink(BaseModel):
    scanned_file_id: int
    catalog_file_id: UUID | None  # None — очистить связь с каталогом


class CatalogLinksRequest(BaseModel):
    links: list[CatalogLink]


class CatalogLinksResult(BaseModel):
    linked: int
