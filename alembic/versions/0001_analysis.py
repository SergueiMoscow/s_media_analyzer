"""analysis schema: scanned_files + лица + кластеры + гео (ТЗ v2)

Revision ID: 0001_analysis
Revises:
Create Date: 2026-11-13

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from pgvector.sqlalchemy import Vector
from sqlalchemy.dialects.postgresql import DOUBLE_PRECISION, REAL

from common.settings import settings

# revision identifiers, used by Alembic.
revision: str = '0001_analysis'
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

EMBEDDING_DIM = 512


def _create_extension() -> None:
    """CREATE EXTENSION нельзя выполнять внутри транзакции — отдельное autocommit-подключение."""
    bind = op.get_bind()
    engine = getattr(bind, 'engine', None)
    if engine is None:
        op.execute('CREATE EXTENSION IF NOT EXISTS vector')
        return
    with engine.connect().execution_options(isolation_level='AUTOCOMMIT') as conn:
        conn.execute(sa.text('CREATE EXTENSION IF NOT EXISTS vector'))


def upgrade() -> None:
    _create_extension()

    op.create_table(
        'scanned_files',
        sa.Column('id', sa.BigInteger(), nullable=False),
        sa.Column('storage_id', sa.Uuid(), nullable=False),
        sa.Column('folder_path', sa.String(), nullable=False, server_default=''),
        sa.Column('filename', sa.String(), nullable=False),
        sa.Column('size', sa.BigInteger(), nullable=True),
        sa.Column('mtime_ns', sa.BigInteger(), nullable=True),
        sa.Column('kind', sa.String(), nullable=False),
        sa.Column('status', sa.String(), nullable=False, server_default='present'),
        sa.Column('catalog_file_id', sa.Uuid(), nullable=True),
        sa.Column(
            'first_seen_at',
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text('now()'),
        ),
        sa.Column(
            'last_seen_at',
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text('now()'),
        ),
        sa.CheckConstraint("kind IN ('image', 'video', 'other')", name='ck_scanned_files_kind'),
        sa.CheckConstraint("status IN ('present', 'missing')", name='ck_scanned_files_status'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('storage_id', 'folder_path', 'filename', name='uq_scanned_files_path'),
    )
    op.create_index(
        'ix_scanned_files_catalog',
        'scanned_files',
        ['catalog_file_id'],
        postgresql_where=sa.text('catalog_file_id IS NOT NULL'),
    )
    op.create_index('ix_scanned_files_folder', 'scanned_files', ['storage_id', 'folder_path'])

    op.create_table(
        'media_analysis',
        sa.Column('id', sa.BigInteger(), nullable=False),
        sa.Column(
            'file_id',
            sa.BigInteger(),
            sa.ForeignKey('scanned_files.id', ondelete='CASCADE'),
            nullable=False,
        ),
        sa.Column('kind', sa.String(), nullable=False),
        sa.Column('status', sa.String(), nullable=False, server_default='pending'),
        sa.Column('analyzer_version', sa.Integer(), nullable=False, server_default=sa.text('0')),
        sa.Column('attempts', sa.Integer(), nullable=False, server_default=sa.text('0')),
        sa.Column('error', sa.Text(), nullable=True),
        sa.Column('locked_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('processed_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            'created_at',
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text('now()'),
        ),
        sa.CheckConstraint("kind IN ('faces', 'geo')", name='ck_media_analysis_kind'),
        sa.CheckConstraint(
            "status IN ('pending', 'processing', 'done', 'failed', 'skipped')",
            name='ck_media_analysis_status',
        ),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('file_id', 'kind', name='uq_media_analysis_file_kind'),
    )
    op.create_index('ix_media_analysis_queue', 'media_analysis', ['kind', 'status', 'locked_at'])

    op.create_table(
        'face_clusters',
        sa.Column('id', sa.BigInteger(), nullable=False),
        sa.Column('centroid', Vector(EMBEDDING_DIM), nullable=False),
        sa.Column('size', sa.Integer(), nullable=False, server_default=sa.text('1')),
        sa.Column('person_id', sa.Uuid(), nullable=True),
        sa.Column('ignored', sa.Boolean(), nullable=False, server_default=sa.text('false')),
        sa.Column(
            'created_at',
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text('now()'),
        ),
        sa.Column(
            'updated_at',
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text('now()'),
        ),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_face_clusters_person', 'face_clusters', ['person_id'])

    op.create_table(
        'faces',
        sa.Column('id', sa.BigInteger(), nullable=False),
        sa.Column(
            'file_id',
            sa.BigInteger(),
            sa.ForeignKey('scanned_files.id', ondelete='CASCADE'),
            nullable=False,
        ),
        sa.Column('bbox_x', REAL, nullable=False),
        sa.Column('bbox_y', REAL, nullable=False),
        sa.Column('bbox_w', REAL, nullable=False),
        sa.Column('bbox_h', REAL, nullable=False),
        sa.Column('embedding', Vector(EMBEDDING_DIM), nullable=False),
        sa.Column('det_score', REAL, nullable=False),
        sa.Column('model_name', sa.String(), nullable=False),
        sa.Column('analyzer_version', sa.Integer(), nullable=False),
        sa.Column(
            'cluster_id',
            sa.BigInteger(),
            sa.ForeignKey('face_clusters.id', ondelete='SET NULL'),
            nullable=True,
        ),
        sa.Column('person_id', sa.Uuid(), nullable=True),
        sa.Column('match_score', REAL, nullable=True),
        sa.Column('status', sa.String(), nullable=False, server_default='auto'),
        sa.Column('crop_path', sa.String(), nullable=True),
        sa.Column(
            'created_at',
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text('now()'),
        ),
        sa.Column(
            'updated_at',
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text('now()'),
        ),
        sa.CheckConstraint('bbox_x >= 0 AND bbox_x <= 1', name='ck_faces_bbox_x'),
        sa.CheckConstraint('bbox_y >= 0 AND bbox_y <= 1', name='ck_faces_bbox_y'),
        sa.CheckConstraint('bbox_w > 0 AND bbox_w <= 1', name='ck_faces_bbox_w'),
        sa.CheckConstraint('bbox_h > 0 AND bbox_h <= 1', name='ck_faces_bbox_h'),
        sa.CheckConstraint("status IN ('auto', 'confirmed', 'rejected')", name='ck_faces_status'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_faces_file', 'faces', ['file_id'])
    op.create_index(
        'ix_faces_person',
        'faces',
        ['person_id'],
        postgresql_where=sa.text('person_id IS NOT NULL'),
    )
    op.create_index('ix_faces_cluster', 'faces', ['cluster_id'])

    op.create_table(
        'person_refs',
        sa.Column('person_id', sa.Uuid(), nullable=False),
        sa.Column(
            'synced_at',
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text('now()'),
        ),
        sa.PrimaryKeyConstraint('person_id'),
    )

    op.create_table(
        'person_names',
        sa.Column('id', sa.BigInteger(), nullable=False),
        sa.Column(
            'person_id',
            sa.Uuid(),
            sa.ForeignKey('person_refs.person_id', ondelete='CASCADE'),
            nullable=False,
        ),
        sa.Column('name', sa.String(), nullable=False),
        sa.Column(
            'created_at',
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text('now()'),
        ),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('person_id', 'name', name='uq_person_names_person_name'),
    )

    op.create_table(
        'person_ref_embeddings',
        sa.Column('id', sa.BigInteger(), nullable=False),
        sa.Column(
            'person_id',
            sa.Uuid(),
            sa.ForeignKey('person_refs.person_id', ondelete='CASCADE'),
            nullable=False,
        ),
        sa.Column('embedding', Vector(EMBEDDING_DIM), nullable=False),
        sa.PrimaryKeyConstraint('id'),
    )

    op.create_table(
        'media_geo',
        sa.Column(
            'file_id',
            sa.BigInteger(),
            sa.ForeignKey('scanned_files.id', ondelete='CASCADE'),
            nullable=False,
        ),
        sa.Column('lat', DOUBLE_PRECISION, nullable=False),
        sa.Column('lon', DOUBLE_PRECISION, nullable=False),
        sa.Column('alt', REAL, nullable=True),
        sa.Column('taken_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('source', sa.String(), nullable=False),
        sa.Column(
            'created_at',
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text('now()'),
        ),
        sa.CheckConstraint('lat BETWEEN -90 AND 90', name='ck_media_geo_lat'),
        sa.CheckConstraint('lon BETWEEN -180 AND 180', name='ck_media_geo_lon'),
        sa.CheckConstraint("source IN ('exif', 'video', 'manual')", name='ck_media_geo_source'),
        sa.PrimaryKeyConstraint('file_id'),
    )
    op.create_index('ix_media_geo_latlon', 'media_geo', ['lat', 'lon'])

    # HNSW-индексы для векторного поиска (pgvector).
    op.execute(
        f'CREATE INDEX ix_faces_embedding ON {settings.ANALYSIS_SCHEMA}.faces '
        f'USING hnsw (embedding vector_cosine_ops)'
    )
    op.execute(
        f'CREATE INDEX ix_person_ref_emb ON {settings.ANALYSIS_SCHEMA}.person_ref_embeddings '
        f'USING hnsw (embedding vector_cosine_ops)'
    )


def downgrade() -> None:
    op.execute(f'DROP INDEX IF EXISTS {settings.ANALYSIS_SCHEMA}.ix_person_ref_emb')
    op.execute(f'DROP INDEX IF EXISTS {settings.ANALYSIS_SCHEMA}.ix_faces_embedding')
    op.drop_table('media_geo')
    op.drop_table('person_ref_embeddings')
    op.drop_table('person_names')
    op.drop_table('person_refs')
    op.drop_table('faces')
    op.drop_table('face_clusters')
    op.drop_table('media_analysis')
    op.drop_table('scanned_files')
