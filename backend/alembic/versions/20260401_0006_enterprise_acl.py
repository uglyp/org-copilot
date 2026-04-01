"""企业权限：用户/文档/知识库 ACL 字段

Revision ID: 20260401_0006
Revises: 20260331_0005
Create Date: 2026-04-01

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "20260401_0006"
down_revision: Union[str, None] = "20260331_0005"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        bool_false = sa.false()
    else:
        bool_false = sa.text("0")

    op.add_column(
        "users",
        sa.Column("branch", sa.String(128), nullable=False, server_default=sa.text("'公共'")),
    )
    op.add_column(
        "users",
        sa.Column("role", sa.String(64), nullable=False, server_default=sa.text("'user'")),
    )
    op.add_column(
        "users",
        sa.Column("security_level", sa.Integer(), nullable=False, server_default="4"),
    )
    op.add_column("users", sa.Column("departments_json", sa.JSON(), nullable=True))
    op.add_column("users", sa.Column("org_id", sa.String(64), nullable=True))
    op.create_index("ix_users_org_id", "users", ["org_id"])

    op.add_column(
        "knowledge_bases",
        sa.Column("org_id", sa.String(64), nullable=True),
    )
    op.add_column(
        "knowledge_bases",
        sa.Column("is_org_shared", sa.Boolean(), nullable=False, server_default=bool_false),
    )
    op.create_index("ix_knowledge_bases_org_id", "knowledge_bases", ["org_id"])

    op.add_column(
        "documents",
        sa.Column("branch", sa.String(128), nullable=False, server_default=sa.text("'公共'")),
    )
    op.add_column("documents", sa.Column("department", sa.String(128), nullable=True))
    op.add_column(
        "documents",
        sa.Column("security_level", sa.Integer(), nullable=False, server_default="1"),
    )
    op.add_column("documents", sa.Column("creator_user_id", sa.Integer(), nullable=True))
    op.create_foreign_key(
        "fk_documents_creator_user_id_users",
        "documents",
        "users",
        ["creator_user_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index("ix_documents_creator_user_id", "documents", ["creator_user_id"])

    # 去掉 server_default，后续 ORM default 接管新行
    op.alter_column("users", "branch", server_default=None)
    op.alter_column("users", "role", server_default=None)
    op.alter_column("users", "security_level", server_default=None)
    op.alter_column("knowledge_bases", "is_org_shared", server_default=None)
    op.alter_column("documents", "branch", server_default=None)
    op.alter_column("documents", "security_level", server_default=None)


def downgrade() -> None:
    op.drop_index("ix_documents_creator_user_id", table_name="documents")
    op.drop_constraint("fk_documents_creator_user_id_users", "documents", type_="foreignkey")
    op.drop_column("documents", "creator_user_id")
    op.drop_column("documents", "security_level")
    op.drop_column("documents", "department")
    op.drop_column("documents", "branch")

    op.drop_index("ix_knowledge_bases_org_id", table_name="knowledge_bases")
    op.drop_column("knowledge_bases", "is_org_shared")
    op.drop_column("knowledge_bases", "org_id")

    op.drop_index("ix_users_org_id", table_name="users")
    op.drop_column("users", "org_id")
    op.drop_column("users", "departments_json")
    op.drop_column("users", "security_level")
    op.drop_column("users", "role")
    op.drop_column("users", "branch")
