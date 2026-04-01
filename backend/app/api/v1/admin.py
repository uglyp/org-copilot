"""
系统管理 API：管理员（`User.role == "admin"` 且账号启用）维护用户与权限字典表。

字典表（分行/组织/部门/角色/密级）供界面维护展示名与启用状态；业务侧 `User`/`Document` 仍使用字符串或整数，
与现有 ACL 逻辑兼容。
"""

from __future__ import annotations

from typing import Annotated

from pydantic import BaseModel, Field, field_validator
from sqlalchemy import delete, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from fastapi import APIRouter, Depends, HTTPException, Path, status

from app.api.deps import get_db, require_admin
from app.core.security import hash_password
from app.models.entities import (
    Conversation,
    KnowledgeBase,
    LLMProvider,
    Message,
    SysBranch,
    SysDepartment,
    SysOrganization,
    SysRole,
    SysSecurityLevel,
    User,
)
from app.services.default_llm_seed import (
    ensure_deepseek_auto_seed,
    ensure_embedding_api_auto_seed,
    ensure_ollama_chat_seed,
)
from app.services.kb_purge import purge_knowledge_base

router = APIRouter(prefix="/admin", tags=["admin"])


# --- 用户 ---


class AdminUserOut(BaseModel):
    id: int
    username: str
    branch: str
    role: str
    security_level: int
    departments: list[str]
    org_id: str | None
    is_active: bool

    class Config:
        from_attributes = True

    @classmethod
    def from_user(cls, u: User) -> AdminUserOut:
        raw = u.departments_json
        depts = list(raw) if isinstance(raw, list) else []
        return cls(
            id=u.id,
            username=u.username,
            branch=u.branch or "公共",
            role=u.role or "user",
            security_level=int(u.security_level),
            departments=[str(x) for x in depts],
            org_id=u.org_id.strip() if isinstance(u.org_id, str) and u.org_id.strip() else None,
            is_active=bool(getattr(u, "is_active", True)),
        )


class AdminUserCreate(BaseModel):
    username: str = Field(min_length=2, max_length=64)
    password: str = Field(min_length=6, max_length=128)
    branch: str | None = Field(None, max_length=128)
    role: str | None = Field(None, max_length=64)
    security_level: int | None = Field(None, ge=1, le=4)
    departments: list[str] | None = None
    org_id: str | None = Field(None, max_length=64)
    is_active: bool = True

    @field_validator("departments", mode="before")
    @classmethod
    def _strip_departments(cls, v: object) -> object:
        if v is None:
            return None
        if isinstance(v, list):
            return [str(x).strip() for x in v if str(x).strip()]
        return v


class AdminUserPatch(BaseModel):
    branch: str | None = Field(None, max_length=128)
    role: str | None = Field(None, max_length=64)
    security_level: int | None = Field(None, ge=1, le=4)
    departments: list[str] | None = None
    org_id: str | None = Field(None, max_length=64)
    is_active: bool | None = None
    new_password: str | None = Field(None, min_length=6, max_length=128)

    @field_validator("departments", mode="before")
    @classmethod
    def _strip_departments(cls, v: object) -> object:
        if v is None:
            return None
        if isinstance(v, list):
            return [str(x).strip() for x in v if str(x).strip()]
        return v


@router.get("/users", response_model=list[AdminUserOut])
async def admin_list_users(
    _: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> list[AdminUserOut]:
    r = await db.execute(select(User).order_by(User.id))
    return [AdminUserOut.from_user(u) for u in r.scalars().all()]


@router.post("/users", response_model=AdminUserOut)
async def admin_create_user(
    body: AdminUserCreate,
    _: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> AdminUserOut:
    r = await db.execute(select(User).where(User.username == body.username))
    if r.scalar_one_or_none():
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail="用户名已存在")
    u = User(
        username=body.username,
        hashed_password=hash_password(body.password),
        is_active=body.is_active,
    )
    if body.branch is not None:
        u.branch = body.branch.strip() or "公共"
    if body.role is not None:
        u.role = body.role.strip() or "user"
    if body.security_level is not None:
        u.security_level = body.security_level
    if body.departments is not None:
        u.departments_json = body.departments
    if body.org_id is not None:
        u.org_id = body.org_id.strip() or None
    db.add(u)
    await db.flush()
    await ensure_deepseek_auto_seed(db, u.id)
    await ensure_embedding_api_auto_seed(db, u.id)
    await ensure_ollama_chat_seed(db, u.id)
    await db.commit()
    await db.refresh(u)
    return AdminUserOut.from_user(u)


@router.patch("/users/{user_id}", response_model=AdminUserOut)
async def admin_patch_user(
    user_id: int,
    body: AdminUserPatch,
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> AdminUserOut:
    r = await db.execute(select(User).where(User.id == user_id))
    u = r.scalar_one_or_none()
    if not u:
        raise HTTPException(status.HTTP_404_NOT_FOUND)
    data = body.model_dump(exclude_unset=True)
    if not data:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail="无更新字段")
    if "branch" in data:
        u.branch = (data["branch"] or "").strip() or "公共"
    if "role" in data:
        u.role = (data["role"] or "").strip() or "user"
    if "security_level" in data:
        u.security_level = int(data["security_level"])
    if "departments" in data:
        depts = data["departments"]
        u.departments_json = depts if depts else None
    if "org_id" in data:
        raw = data["org_id"]
        u.org_id = raw.strip() if isinstance(raw, str) and raw.strip() else None
    if "is_active" in data:
        u.is_active = bool(data["is_active"])
    if "new_password" in data and data["new_password"]:
        u.hashed_password = hash_password(data["new_password"])
    await db.commit()
    await db.refresh(u)
    return AdminUserOut.from_user(u)


@router.delete("/users/{user_id}")
async def admin_delete_user(
    user_id: int,
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> dict[str, str]:
    if user_id == admin.id:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            detail="不能删除当前登录账号",
        )
    r = await db.execute(select(User).where(User.id == user_id))
    u = r.scalar_one_or_none()
    if not u:
        raise HTTPException(status.HTTP_404_NOT_FOUND)
    r = await db.execute(select(KnowledgeBase.id).where(KnowledgeBase.user_id == user_id))
    for (kid,) in r.all():
        await purge_knowledge_base(db, kid)
    r = await db.execute(select(Conversation.id).where(Conversation.user_id == user_id))
    cids = [row[0] for row in r.all()]
    if cids:
        await db.execute(delete(Message).where(Message.conversation_id.in_(cids)))
        await db.execute(delete(Conversation).where(Conversation.user_id == user_id))
    await db.execute(
        update(LLMProvider)
        .where(LLMProvider.user_id == user_id)
        .values(user_id=None)
    )
    await db.execute(delete(User).where(User.id == user_id))
    await db.commit()
    return {"status": "ok"}


# --- 组织 ---


class OrgOut(BaseModel):
    id: int
    org_code: str
    name: str
    description: str | None
    enabled: bool

    class Config:
        from_attributes = True


class OrgCreate(BaseModel):
    org_code: str = Field(max_length=64)
    name: str = Field(max_length=256)
    description: str | None = None
    enabled: bool = True


class OrgPatch(BaseModel):
    org_code: str | None = Field(None, max_length=64)
    name: str | None = Field(None, max_length=256)
    description: str | None = None
    enabled: bool | None = None


@router.get("/organizations", response_model=list[OrgOut])
async def list_orgs(
    _: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> list[SysOrganization]:
    r = await db.execute(select(SysOrganization).order_by(SysOrganization.id))
    return list(r.scalars().all())


@router.post("/organizations", response_model=OrgOut)
async def create_org(
    body: OrgCreate,
    _: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> SysOrganization:
    code = body.org_code.strip()
    if not code:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail="组织编码不能为空")
    o = SysOrganization(
        org_code=code,
        name=body.name.strip(),
        description=body.description.strip() if body.description else None,
        enabled=body.enabled,
    )
    db.add(o)
    try:
        await db.commit()
    except Exception:
        await db.rollback()
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            detail="组织编码可能已存在",
        ) from None
    await db.refresh(o)
    return o


@router.patch("/organizations/{org_pk}", response_model=OrgOut)
async def patch_org(
    org_pk: int,
    body: OrgPatch,
    _: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> SysOrganization:
    o = await db.get(SysOrganization, org_pk)
    if not o:
        raise HTTPException(status.HTTP_404_NOT_FOUND)
    data = body.model_dump(exclude_unset=True)
    if "org_code" in data and data["org_code"] is not None:
        c = data["org_code"].strip()
        if not c:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, detail="组织编码不能为空")
        o.org_code = c
    if "name" in data and data["name"] is not None:
        o.name = data["name"].strip()
    if "description" in data:
        d = data["description"]
        o.description = d.strip() if isinstance(d, str) and d.strip() else None
    if "enabled" in data:
        o.enabled = bool(data["enabled"])
    try:
        await db.commit()
    except Exception:
        await db.rollback()
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            detail="更新失败（编码冲突等）",
        ) from None
    await db.refresh(o)
    return o


@router.delete("/organizations/{org_pk}")
async def delete_org(
    org_pk: int,
    _: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> dict[str, str]:
    o = await db.get(SysOrganization, org_pk)
    if not o:
        raise HTTPException(status.HTTP_404_NOT_FOUND)
    await db.delete(o)
    await db.commit()
    return {"status": "ok"}


# --- 分行 ---


class BranchOut(BaseModel):
    id: int
    code: str
    name: str
    sort_order: int
    enabled: bool

    class Config:
        from_attributes = True


class BranchCreate(BaseModel):
    code: str = Field(max_length=128)
    name: str = Field(max_length=256)
    sort_order: int = 0
    enabled: bool = True


class BranchPatch(BaseModel):
    code: str | None = Field(None, max_length=128)
    name: str | None = Field(None, max_length=256)
    sort_order: int | None = None
    enabled: bool | None = None


@router.get("/branches", response_model=list[BranchOut])
async def list_branches(
    _: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> list[SysBranch]:
    r = await db.execute(
        select(SysBranch).order_by(SysBranch.sort_order, SysBranch.id)
    )
    return list(r.scalars().all())


@router.post("/branches", response_model=BranchOut)
async def create_branch(
    body: BranchCreate,
    _: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> SysBranch:
    c = body.code.strip()
    if not c:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail="分行编码不能为空")
    b = SysBranch(
        code=c,
        name=body.name.strip(),
        sort_order=int(body.sort_order),
        enabled=body.enabled,
    )
    db.add(b)
    try:
        await db.commit()
    except Exception:
        await db.rollback()
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            detail="分行编码可能已存在",
        ) from None
    await db.refresh(b)
    return b


@router.patch("/branches/{branch_pk}", response_model=BranchOut)
async def patch_branch(
    branch_pk: int,
    body: BranchPatch,
    _: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> SysBranch:
    b = await db.get(SysBranch, branch_pk)
    if not b:
        raise HTTPException(status.HTTP_404_NOT_FOUND)
    data = body.model_dump(exclude_unset=True)
    if "code" in data and data["code"] is not None:
        c = data["code"].strip()
        if not c:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, detail="分行编码不能为空")
        b.code = c
    if "name" in data and data["name"] is not None:
        b.name = data["name"].strip()
    if "sort_order" in data:
        b.sort_order = int(data["sort_order"])
    if "enabled" in data:
        b.enabled = bool(data["enabled"])
    try:
        await db.commit()
    except Exception:
        await db.rollback()
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            detail="更新失败",
        ) from None
    await db.refresh(b)
    return b


@router.delete("/branches/{branch_pk}")
async def delete_branch(
    branch_pk: int,
    _: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> dict[str, str]:
    b = await db.get(SysBranch, branch_pk)
    if not b:
        raise HTTPException(status.HTTP_404_NOT_FOUND)
    await db.delete(b)
    await db.commit()
    return {"status": "ok"}


# --- 部门 ---


class DeptOut(BaseModel):
    id: int
    code: str
    name: str
    org_code: str | None
    enabled: bool

    class Config:
        from_attributes = True


class DeptCreate(BaseModel):
    code: str = Field(max_length=128)
    name: str = Field(max_length=256)
    org_code: str | None = Field(None, max_length=64)
    enabled: bool = True


class DeptPatch(BaseModel):
    code: str | None = Field(None, max_length=128)
    name: str | None = Field(None, max_length=256)
    org_code: str | None = Field(None, max_length=64)
    enabled: bool | None = None


@router.get("/departments", response_model=list[DeptOut])
async def list_depts(
    _: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> list[SysDepartment]:
    r = await db.execute(select(SysDepartment).order_by(SysDepartment.id))
    return list(r.scalars().all())


@router.post("/departments", response_model=DeptOut)
async def create_dept(
    body: DeptCreate,
    _: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> SysDepartment:
    c = body.code.strip()
    if not c:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail="部门编码不能为空")
    oc = body.org_code.strip() if body.org_code and body.org_code.strip() else None
    d = SysDepartment(code=c, name=body.name.strip(), org_code=oc, enabled=body.enabled)
    db.add(d)
    try:
        await db.commit()
    except Exception:
        await db.rollback()
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            detail="部门编码可能已存在",
        ) from None
    await db.refresh(d)
    return d


@router.patch("/departments/{dept_pk}", response_model=DeptOut)
async def patch_dept(
    dept_pk: int,
    body: DeptPatch,
    _: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> SysDepartment:
    d = await db.get(SysDepartment, dept_pk)
    if not d:
        raise HTTPException(status.HTTP_404_NOT_FOUND)
    data = body.model_dump(exclude_unset=True)
    if "code" in data and data["code"] is not None:
        c = data["code"].strip()
        if not c:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, detail="部门编码不能为空")
        d.code = c
    if "name" in data and data["name"] is not None:
        d.name = data["name"].strip()
    if "org_code" in data:
        raw = data["org_code"]
        d.org_code = raw.strip() if isinstance(raw, str) and raw.strip() else None
    if "enabled" in data:
        d.enabled = bool(data["enabled"])
    try:
        await db.commit()
    except Exception:
        await db.rollback()
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail="更新失败") from None
    await db.refresh(d)
    return d


@router.delete("/departments/{dept_pk}")
async def delete_dept(
    dept_pk: int,
    _: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> dict[str, str]:
    d = await db.get(SysDepartment, dept_pk)
    if not d:
        raise HTTPException(status.HTTP_404_NOT_FOUND)
    await db.delete(d)
    await db.commit()
    return {"status": "ok"}


# --- 角色 ---


class RoleOut(BaseModel):
    id: int
    code: str
    display_name: str
    description: str | None
    enabled: bool

    class Config:
        from_attributes = True


class RoleCreate(BaseModel):
    code: str = Field(max_length=64)
    display_name: str = Field(max_length=128)
    description: str | None = None
    enabled: bool = True


class RolePatch(BaseModel):
    code: str | None = Field(None, max_length=64)
    display_name: str | None = Field(None, max_length=128)
    description: str | None = None
    enabled: bool | None = None


@router.get("/roles", response_model=list[RoleOut])
async def list_roles(
    _: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> list[SysRole]:
    r = await db.execute(select(SysRole).order_by(SysRole.id))
    return list(r.scalars().all())


@router.post("/roles", response_model=RoleOut)
async def create_role(
    body: RoleCreate,
    _: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> SysRole:
    c = body.code.strip()
    if not c:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail="角色编码不能为空")
    role = SysRole(
        code=c,
        display_name=body.display_name.strip(),
        description=body.description.strip() if body.description else None,
        enabled=body.enabled,
    )
    db.add(role)
    try:
        await db.commit()
    except Exception:
        await db.rollback()
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            detail="角色编码可能已存在",
        ) from None
    await db.refresh(role)
    return role


@router.patch("/roles/{role_pk}", response_model=RoleOut)
async def patch_role(
    role_pk: int,
    body: RolePatch,
    _: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> SysRole:
    role = await db.get(SysRole, role_pk)
    if not role:
        raise HTTPException(status.HTTP_404_NOT_FOUND)
    data = body.model_dump(exclude_unset=True)
    if "code" in data and data["code"] is not None:
        c = data["code"].strip()
        if not c:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, detail="角色编码不能为空")
        role.code = c
    if "display_name" in data and data["display_name"] is not None:
        role.display_name = data["display_name"].strip()
    if "description" in data:
        d = data["description"]
        role.description = d.strip() if isinstance(d, str) and d.strip() else None
    if "enabled" in data:
        role.enabled = bool(data["enabled"])
    try:
        await db.commit()
    except Exception:
        await db.rollback()
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail="更新失败") from None
    await db.refresh(role)
    return role


@router.delete("/roles/{role_pk}")
async def delete_role(
    role_pk: int,
    _: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> dict[str, str]:
    role = await db.get(SysRole, role_pk)
    if not role:
        raise HTTPException(status.HTTP_404_NOT_FOUND)
    if role.code in ("admin", "user"):
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            detail="内置角色 admin / user 不可删除",
        )
    await db.delete(role)
    await db.commit()
    return {"status": "ok"}


# --- 密级 ---


class SecLevelOut(BaseModel):
    level: int
    label: str
    description: str | None
    sort_order: int

    class Config:
        from_attributes = True


class SecLevelPatch(BaseModel):
    label: str | None = Field(None, max_length=64)
    description: str | None = None
    sort_order: int | None = None


@router.get("/security-levels", response_model=list[SecLevelOut])
async def list_sec_levels(
    _: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> list[SysSecurityLevel]:
    r = await db.execute(
        select(SysSecurityLevel).order_by(SysSecurityLevel.sort_order, SysSecurityLevel.level)
    )
    return list(r.scalars().all())


@router.patch(
    "/security-levels/{level}",
    response_model=SecLevelOut,
)
async def patch_sec_level(
    body: SecLevelPatch,
    level: Annotated[int, Path(ge=1, le=4)],
    _: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> SysSecurityLevel:
    row = await db.get(SysSecurityLevel, level)
    if not row:
        raise HTTPException(status.HTTP_404_NOT_FOUND)
    data = body.model_dump(exclude_unset=True)
    if "label" in data and data["label"] is not None:
        row.label = data["label"].strip() or row.label
    if "description" in data:
        d = data["description"]
        row.description = d.strip() if isinstance(d, str) and d.strip() else None
    if "sort_order" in data:
        row.sort_order = int(data["sort_order"])
    await db.commit()
    await db.refresh(row)
    return row
