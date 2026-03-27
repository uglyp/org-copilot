"""documents/chunks modality and chunks.extra_json

Revision ID: 20260326_0003
Revises: 20260324_0002
Create Date: 2026-03-26

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "20260326_0003"
down_revision: Union[str, None] = "20260324_0002"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "documents",
        sa.Column(
            "modality",
            sa.String(16),
            nullable=False,
            server_default="text",
        ),
    )
    op.add_column(
        "chunks",
        sa.Column(
            "modality",
            sa.String(16),
            nullable=False,
            server_default="text",
        ),
    )
    op.add_column("chunks", sa.Column("extra_json", sa.JSON(), nullable=True))


def downgrade() -> None:
    op.drop_column("chunks", "extra_json")
    op.drop_column("chunks", "modality")
    op.drop_column("documents", "modality")
