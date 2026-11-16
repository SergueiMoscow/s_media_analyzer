"""ORM-модели s_media_analyzer (схема analysis).

Анализатор ведёт собственный реестр файлов ``scanned_files`` (по диску) и не
имеет внешних ключей на таблицы s_media_service: связь с каталогом — колонка
``catalog_file_id`` (uuid, без FK). Все индексы создаются в миграции.
"""
from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    Column,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    Uuid,
    text,
)
from sqlalchemy.dialects.postgresql import DOUBLE_PRECISION, REAL
from sqlalchemy.orm import relationship

from db.db import Base

GUID = Uuid
EMBEDDING_DIM = 512


class ScannedFile(Base):
    """Реестр файлов, найденных сканированием (не зависит от каталога)."""

    __tablename__ = 'scanned_files'
    __table_args__ = (
        UniqueConstraint('storage_id', 'folder_path', 'filename', name='uq_scanned_files_path'),
        CheckConstraint("kind IN ('image', 'video', 'other')", name='ck_scanned_files_kind'),
        CheckConstraint("status IN ('present', 'missing')", name='ck_scanned_files_status'),
    )

    id = Column(BigInteger, primary_key=True)
    storage_id = Column(GUID, nullable=False)
    folder_path = Column(String, nullable=False, server_default='')
    filename = Column(String, nullable=False)
    size = Column(BigInteger, nullable=True)
    mtime_ns = Column(BigInteger, nullable=True)
    kind = Column(String, nullable=False)
    status = Column(String, nullable=False, server_default='present')
    catalog_file_id = Column(GUID, nullable=True)
    first_seen_at = Column(DateTime(timezone=True), nullable=False, server_default=text('now()'))
    last_seen_at = Column(DateTime(timezone=True), nullable=False, server_default=text('now()'))


class MediaAnalysis(Base):
    """Учёт обработки: идемпотентность, очередь, повторный запуск по версии."""

    __tablename__ = 'media_analysis'
    __table_args__ = (
        UniqueConstraint('file_id', 'kind', name='uq_media_analysis_file_kind'),
        CheckConstraint("kind IN ('faces', 'geo')", name='ck_media_analysis_kind'),
        CheckConstraint(
            "status IN ('pending', 'processing', 'done', 'failed', 'skipped')",
            name='ck_media_analysis_status',
        ),
    )

    id = Column(BigInteger, primary_key=True)
    file_id = Column(
        BigInteger, ForeignKey('scanned_files.id', ondelete='CASCADE'), nullable=False
    )
    kind = Column(String, nullable=False)
    status = Column(String, nullable=False, server_default='pending')
    analyzer_version = Column(Integer, nullable=False, server_default=text('0'))
    attempts = Column(Integer, nullable=False, server_default=text('0'))
    error = Column(Text, nullable=True)
    locked_at = Column(DateTime(timezone=True), nullable=True)
    processed_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=text('now()'))

    scanned_file = relationship('ScannedFile', lazy='selectin')

    @property
    def scanned_file_id(self) -> int:
        return self.file_id


class FaceCluster(Base):
    """Кластеры похожих лиц (локальные для узла)."""

    __tablename__ = 'face_clusters'

    id = Column(BigInteger, primary_key=True)
    centroid = Column(Vector(EMBEDDING_DIM), nullable=False)
    size = Column(Integer, nullable=False, server_default=text('1'))
    person_id = Column(GUID, nullable=True)  # без FK: справочник в БД s_media_api
    ignored = Column(Boolean, nullable=False, server_default=text('false'))
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=text('now()'))
    updated_at = Column(DateTime(timezone=True), nullable=False, server_default=text('now()'))


class Face(Base):
    """Лицо, обнаруженное на фото."""

    __tablename__ = 'faces'
    __table_args__ = (
        CheckConstraint('bbox_x >= 0 AND bbox_x <= 1', name='ck_faces_bbox_x'),
        CheckConstraint('bbox_y >= 0 AND bbox_y <= 1', name='ck_faces_bbox_y'),
        CheckConstraint('bbox_w > 0 AND bbox_w <= 1', name='ck_faces_bbox_w'),
        CheckConstraint('bbox_h > 0 AND bbox_h <= 1', name='ck_faces_bbox_h'),
        CheckConstraint("status IN ('auto', 'confirmed', 'rejected')", name='ck_faces_status'),
    )

    id = Column(BigInteger, primary_key=True)
    file_id = Column(
        BigInteger, ForeignKey('scanned_files.id', ondelete='CASCADE'), nullable=False
    )
    bbox_x = Column(REAL, nullable=False)
    bbox_y = Column(REAL, nullable=False)
    bbox_w = Column(REAL, nullable=False)
    bbox_h = Column(REAL, nullable=False)
    embedding = Column(Vector(EMBEDDING_DIM), nullable=False)
    det_score = Column(REAL, nullable=False)
    model_name = Column(String, nullable=False)
    analyzer_version = Column(Integer, nullable=False)
    cluster_id = Column(
        BigInteger, ForeignKey('face_clusters.id', ondelete='SET NULL'), nullable=True
    )
    person_id = Column(GUID, nullable=True)  # без FK: справочник в БД s_media_api
    match_score = Column(REAL, nullable=True)
    status = Column(String, nullable=False, server_default='auto')
    crop_path = Column(String, nullable=True)  # относительно FACES_DIR
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=text('now()'))
    updated_at = Column(DateTime(timezone=True), nullable=False, server_default=text('now()'))

    scanned_file = relationship('ScannedFile', lazy='selectin')

    @property
    def bbox(self) -> dict:
        """Нормализованный bbox (для сериализации в schemas.FaceOut)."""
        return {'x': self.bbox_x, 'y': self.bbox_y, 'w': self.bbox_w, 'h': self.bbox_h}

    @property
    def scanned_file_id(self) -> int:
        return self.file_id

    @property
    def catalog_file_id(self):
        return self.scanned_file.catalog_file_id if self.scanned_file else None

    @property
    def has_crop(self) -> bool:
        return self.crop_path is not None


class PersonRef(Base):
    """Локальный кэш глобальных людей (синхронизируется из s_media_api)."""

    __tablename__ = 'person_refs'

    person_id = Column(GUID, primary_key=True)
    synced_at = Column(DateTime(timezone=True), nullable=False, server_default=text('now()'))


class PersonName(Base):
    """Имена (алиасы) человека: одному человеку можно дать несколько имён."""

    __tablename__ = 'person_names'
    __table_args__ = (
        UniqueConstraint('person_id', 'name', name='uq_person_names_person_name'),
    )

    id = Column(BigInteger, primary_key=True)
    person_id = Column(
        GUID, ForeignKey('person_refs.person_id', ondelete='CASCADE'), nullable=False
    )
    name = Column(String, nullable=False)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=text('now()'))


class PersonRefEmbedding(Base):
    """Эталонные эмбеддинги людей из глобального справочника."""

    __tablename__ = 'person_ref_embeddings'

    id = Column(BigInteger, primary_key=True)
    person_id = Column(
        GUID, ForeignKey('person_refs.person_id', ondelete='CASCADE'), nullable=False
    )
    embedding = Column(Vector(EMBEDDING_DIM), nullable=False)


class FaceClusterRejection(Base):
    """Отказ «этот кластер — не этот человек» (логическая связь, без FK)."""

    __tablename__ = 'face_cluster_rejections'
    __table_args__ = (
        UniqueConstraint('person_id', 'cluster_id', name='uq_face_cluster_rejections'),
    )

    id = Column(BigInteger, primary_key=True)
    person_id = Column(GUID, nullable=False)
    cluster_id = Column(BigInteger, nullable=False)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=text('now()'))


class MediaGeo(Base):
    """Геоданные (одна запись на файл)."""

    __tablename__ = 'media_geo'
    __table_args__ = (
        CheckConstraint('lat BETWEEN -90 AND 90', name='ck_media_geo_lat'),
        CheckConstraint('lon BETWEEN -180 AND 180', name='ck_media_geo_lon'),
        CheckConstraint("source IN ('exif', 'video', 'manual')", name='ck_media_geo_source'),
    )

    file_id = Column(
        BigInteger, ForeignKey('scanned_files.id', ondelete='CASCADE'), primary_key=True
    )
    lat = Column(DOUBLE_PRECISION, nullable=False)
    lon = Column(DOUBLE_PRECISION, nullable=False)
    alt = Column(REAL, nullable=True)
    taken_at = Column(DateTime(timezone=True), nullable=True)
    source = Column(String, nullable=False)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=text('now()'))

    scanned_file = relationship('ScannedFile', lazy='selectin')

    @property
    def scanned_file_id(self) -> int:
        return self.file_id

    @property
    def catalog_file_id(self):
        return self.scanned_file.catalog_file_id if self.scanned_file else None
