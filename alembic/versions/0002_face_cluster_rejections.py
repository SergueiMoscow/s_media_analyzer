"""face_cluster_rejections: отказы «этот кластер — не этот человек»

Revision ID: 0002_face_cluster_rejections
Revises: 0001_analysis
Create Date: 2026-11-16

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = '0002_face_cluster_rejections'
down_revision: Union[str, None] = '0001_analysis'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'face_cluster_rejections',
        sa.Column('id', sa.BigInteger(), nullable=False),
        sa.Column('person_id', sa.Uuid(), nullable=False),
        sa.Column('cluster_id', sa.BigInteger(), nullable=False),
        sa.Column(
            'created_at',
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text('now()'),
        ),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('person_id', 'cluster_id', name='uq_face_cluster_rejections'),
    )
    op.create_index(
        'ix_face_cluster_rejections_person',
        'face_cluster_rejections',
        ['person_id'],
    )


def downgrade() -> None:
    op.drop_index('ix_face_cluster_rejections_person', table_name='face_cluster_rejections')
    op.drop_table('face_cluster_rejections')
