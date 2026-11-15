"""Общие Pydantic-схемы и литералы."""
from typing import Literal

from pydantic import BaseModel

AnalysisKind = Literal['faces', 'geo']
AnalysisStatus = Literal['pending', 'processing', 'done', 'failed', 'skipped']
FaceStatus = Literal['auto', 'confirmed', 'rejected']


class Page[T](BaseModel):
    """Страница результатов с пагинацией offset/limit."""

    items: list[T]
    total: int
    limit: int
    offset: int
