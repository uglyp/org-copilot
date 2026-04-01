"""
企业级文档 ACL（应用层，MySQL / PostgreSQL 通用）。

- Milvus：检索期按 `branch`、`security_level` 过滤（与 docs/RAG权限管理方案.md 一致）。
- 部门：多值逻辑仅在第三层用 DB 校验（`departments_json`）。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from sqlalchemy import and_, false, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql import ColumnElement

from app.models.entities import Document, KnowledgeBase, User


def default_public_branch_label() -> str:
    """与配置 `public_branch_label` 默认值保持一致；避免循环 import 时供迁移/测试使用。"""
    return "公共"


def escape_milvus_string(value: str) -> str:
    """Milvus 布尔表达式中双引号字符串的转义：反斜杠与双引号。"""
    return value.replace("\\", "\\\\").replace('"', '\\"')


@dataclass(frozen=True)
class PermissionContext:
    """从已加载的 `User` 派生，供检索与序列化 JWT 载荷对照。"""

    user_id: int
    branch: str
    role: str
    security_level: int
    departments: tuple[str, ...]
    org_id: str | None

    @classmethod
    def from_user(cls, user: User) -> PermissionContext:
        raw = user.departments_json
        if raw is None:
            depts: tuple[str, ...] = ()
        elif isinstance(raw, list):
            depts = tuple(str(x) for x in raw)
        else:
            depts = ()
        return cls(
            user_id=user.id,
            branch=(user.branch or default_public_branch_label()).strip()
            or default_public_branch_label(),
            role=user.role or "user",
            security_level=int(user.security_level),
            departments=depts,
            org_id=(user.org_id.strip() if isinstance(user.org_id, str) and user.org_id.strip() else None),
        )


def jwt_extra_from_user(user: User) -> dict[str, Any]:
    """写入 JWT 的权限声明（`departments` 用 JSON 数组字符串便于 jose 序列化）。"""
    import json

    ctx = PermissionContext.from_user(user)
    return {
        "branch": ctx.branch,
        "role": ctx.role,
        "security_level": ctx.security_level,
        "departments": json.dumps(list(ctx.departments), ensure_ascii=False),
        "org_id": ctx.org_id or "",
    }


def parse_departments_jwt_claim(raw: str | None) -> tuple[str, ...]:
    if not raw:
        return ()
    import json

    try:
        data = json.loads(raw)
        if isinstance(data, list):
            return tuple(str(x) for x in data)
    except (json.JSONDecodeError, TypeError):
        pass
    return ()


def knowledge_base_accessible(kb: KnowledgeBase, user: User) -> bool:
    if kb.user_id == user.id:
        return True
    if kb.is_org_shared and kb.org_id and user.org_id:
        return kb.org_id.strip() == user.org_id.strip()
    return False


def kb_access_filter(user: User) -> ColumnElement[bool]:
    """当前用户可见的知识库：`owner` 或组织共享。"""
    conds: list[ColumnElement[bool]] = [KnowledgeBase.user_id == user.id]
    uid_org = user.org_id.strip() if isinstance(user.org_id, str) and user.org_id.strip() else None
    if uid_org:
        conds.append(
            and_(
                KnowledgeBase.is_org_shared.is_(True),
                KnowledgeBase.org_id == uid_org,
            )
        )
    return or_(*conds)


def document_visible_to(
    doc: Document,
    user: User,
    *,
    public_branch_label: str,
) -> bool:
    pub = public_branch_label.strip() or default_public_branch_label()
    ubranch = (user.branch or pub).strip() or pub
    dbranch = (doc.branch or pub).strip() or pub
    if dbranch != ubranch and dbranch != pub:
        return False
    if int(doc.security_level) > int(user.security_level):
        return False
    return _department_allowed(user, doc.department)


def _department_allowed(user: User, doc_department: str | None) -> bool:
    if doc_department is None or not str(doc_department).strip():
        return True
    need = str(doc_department).strip()
    depts = user.departments_json
    if not depts or not isinstance(depts, list):
        return False
    return need in {str(x).strip() for x in depts if str(x).strip()}


def document_acl_filter(
    user: User,
    *,
    public_branch_label: str,
) -> ColumnElement[bool]:
    """与 `document_visible_to` 等价的 SQL 条件（用于 list/download/delete）。"""
    pub = public_branch_label.strip() or default_public_branch_label()
    ubranch = (user.branch or pub).strip() or pub

    branch_ok = or_(Document.branch == ubranch, Document.branch == pub)

    level_ok = Document.security_level <= user.security_level

    depts = user.departments_json or []
    dept_list: list[str] = []
    if isinstance(depts, list):
        dept_list = [str(x).strip() for x in depts if str(x).strip()]

    trim_dep = func.trim(Document.department)
    if dept_list:
        dept_ok = or_(
            Document.department.is_(None),
            trim_dep == "",
            Document.department.in_(dept_list),
        )
    else:
        dept_ok = or_(
            Document.department.is_(None),
            trim_dep == "",
            false(),
        )

    return and_(branch_ok, level_ok, dept_ok)


def build_milvus_acl_filter(
    kb_id: int,
    user: User,
    *,
    public_branch_label: str,
) -> str:
    """拼接 Milvus 标量过滤表达式（不含部门）。"""
    pub = public_branch_label.strip() or default_public_branch_label()
    ubranch = escape_milvus_string(
        ((user.branch or pub).strip() or pub),
    )
    pub_e = escape_milvus_string(pub)
    lvl = int(user.security_level)
    return (
        f"kb_id == {int(kb_id)} and "
        f'(branch == "{ubranch}" or branch == "{pub_e}") and '
        f"security_level <= {lvl}"
    )


async def load_documents_for_acl_check(
    session: AsyncSession,
    doc_ids: list[int],
) -> dict[int, Document]:
    if not doc_ids:
        return {}
    r = await session.execute(select(Document).where(Document.id.in_(doc_ids)))
    return {d.id: d for d in r.scalars().all()}
