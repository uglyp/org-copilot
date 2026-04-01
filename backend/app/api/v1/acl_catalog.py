"""
ACL 字典只读接口：供前端下拉选择分行/组织/部门/密级（与系统管理中的 sys_* 表同步）。

无需登录，便于注册页拉取选项；未执行迁移或表为空时返回空列表，由前端允许自定义输入。
"""

from __future__ import annotations

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.models.entities import SysBranch, SysDepartment, SysOrganization, SysSecurityLevel

router = APIRouter(prefix="/acl-catalog", tags=["acl-catalog"])


class BranchOption(BaseModel):
    code: str
    name: str


class OrganizationOption(BaseModel):
    org_code: str
    name: str


class DepartmentOption(BaseModel):
    code: str
    name: str
    org_code: str | None = None


class SecurityLevelOption(BaseModel):
    level: int
    label: str


class AclCatalogOut(BaseModel):
    branches: list[BranchOption]
    organizations: list[OrganizationOption]
    departments: list[DepartmentOption]
    security_levels: list[SecurityLevelOption]


@router.get("", response_model=AclCatalogOut)
async def get_acl_catalog(db: AsyncSession = Depends(get_db)) -> AclCatalogOut:
    """返回已启用的字典项；表不存在时返回空列表（例如尚未迁移）。"""
    try:
        rb = await db.execute(
            select(SysBranch)
            .where(SysBranch.enabled.is_(True))
            .order_by(SysBranch.sort_order, SysBranch.id)
        )
        branches = [
            BranchOption(code=b.code, name=b.name) for b in rb.scalars().all()
        ]

        ro = await db.execute(
            select(SysOrganization)
            .where(SysOrganization.enabled.is_(True))
            .order_by(SysOrganization.id)
        )
        organizations = [
            OrganizationOption(org_code=o.org_code, name=o.name)
            for o in ro.scalars().all()
        ]

        rd = await db.execute(
            select(SysDepartment)
            .where(SysDepartment.enabled.is_(True))
            .order_by(SysDepartment.id)
        )
        departments = [
            DepartmentOption(code=d.code, name=d.name, org_code=d.org_code)
            for d in rd.scalars().all()
        ]

        rs = await db.execute(
            select(SysSecurityLevel).order_by(
                SysSecurityLevel.sort_order, SysSecurityLevel.level
            )
        )
        security_levels = [
            SecurityLevelOption(level=s.level, label=s.label)
            for s in rs.scalars().all()
        ]

        return AclCatalogOut(
            branches=branches,
            organizations=organizations,
            departments=departments,
            security_levels=security_levels,
        )
    except SQLAlchemyError:
        return AclCatalogOut(
            branches=[],
            organizations=[],
            departments=[],
            security_levels=[],
        )
