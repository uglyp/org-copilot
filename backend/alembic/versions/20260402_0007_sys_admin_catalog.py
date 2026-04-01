"""系统管理：用户启用开关 + 分行/组织/部门/角色/密级字典表

Revision ID: 20260402_0007
Revises: 20260401_0006
Create Date: 2026-04-02

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "20260402_0007"
down_revision: Union[str, None] = "20260401_0006"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        bool_true = sa.true()
    else:
        bool_true = sa.text("1")

    op.add_column(
        "users",
        sa.Column(
            "is_active",
            sa.Boolean(),
            nullable=False,
            server_default=bool_true,
        ),
    )

    op.create_table(
        "sys_organizations",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("org_code", sa.String(64), nullable=False),
        sa.Column("name", sa.String(256), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=bool_true),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_sys_organizations_org_code", "sys_organizations", ["org_code"], unique=True
    )

    op.create_table(
        "sys_branches",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("code", sa.String(128), nullable=False),
        sa.Column("name", sa.String(256), nullable=False),
        sa.Column("sort_order", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=bool_true),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_sys_branches_code", "sys_branches", ["code"], unique=True)

    op.create_table(
        "sys_departments",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("code", sa.String(128), nullable=False),
        sa.Column("name", sa.String(256), nullable=False),
        sa.Column("org_code", sa.String(64), nullable=True),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=bool_true),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_sys_departments_code", "sys_departments", ["code"], unique=True)

    op.create_table(
        "sys_roles",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("code", sa.String(64), nullable=False),
        sa.Column("display_name", sa.String(128), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=bool_true),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_sys_roles_code", "sys_roles", ["code"], unique=True)

    op.create_table(
        "sys_security_levels",
        sa.Column("level", sa.Integer(), nullable=False),
        sa.Column("label", sa.String(64), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("sort_order", sa.Integer(), nullable=False, server_default="0"),
        sa.PrimaryKeyConstraint("level"),
    )

    if bind.dialect.name == "postgresql":
        op.execute(
            sa.text(
                "INSERT INTO sys_branches (code, name, sort_order, enabled) "
                "VALUES ('公共', '公共', 0, true)"
            )
        )
        op.execute(
            sa.text(
                "INSERT INTO sys_roles (code, display_name, description, enabled) VALUES "
                "('user', '普通用户', '默认角色', true), "
                "('admin', '系统管理员', '可访问系统管理', true)"
            )
        )
        op.execute(
            sa.text(
                "INSERT INTO sys_security_levels (level, label, description, sort_order) VALUES "
                "(1, '公开', '最低密级', 1), "
                "(2, '内部', NULL, 2), "
                "(3, '敏感', NULL, 3), "
                "(4, '机密', '最高密级', 4)"
            )
        )
    else:
        op.execute(
            sa.text(
                "INSERT INTO sys_branches (code, name, sort_order, enabled) "
                "VALUES ('公共', '公共', 0, 1)"
            )
        )
        op.execute(
            sa.text(
                "INSERT INTO sys_roles (code, display_name, description, enabled) VALUES "
                "('user', '普通用户', '默认角色', 1), "
                "('admin', '系统管理员', '可访问系统管理', 1)"
            )
        )
        op.execute(
            sa.text(
                "INSERT INTO sys_security_levels (level, label, description, sort_order) VALUES "
                "(1, '公开', '最低密级', 1), "
                "(2, '内部', NULL, 2), "
                "(3, '敏感', NULL, 3), "
                "(4, '机密', '最高密级', 4)"
            )
        )


def downgrade() -> None:
    op.drop_table("sys_security_levels")
    op.drop_index("ix_sys_roles_code", table_name="sys_roles")
    op.drop_table("sys_roles")
    op.drop_index("ix_sys_departments_code", table_name="sys_departments")
    op.drop_table("sys_departments")
    op.drop_index("ix_sys_branches_code", table_name="sys_branches")
    op.drop_table("sys_branches")
    op.drop_index("ix_sys_organizations_org_code", table_name="sys_organizations")
    op.drop_table("sys_organizations")
    op.drop_column("users", "is_active")
