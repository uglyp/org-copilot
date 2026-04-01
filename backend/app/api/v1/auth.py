"""
注册 / 登录：返回 JWT；注册成功后尝试根据环境变量自动种子化 DeepSeek / Embedding 提供商（见 `default_llm_seed`）。
"""

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.core.config import get_settings
from app.db.session import get_db
from app.core.security import create_access_token, hash_password, verify_password
from app.services.permissions import PermissionContext, jwt_extra_from_user
from app.models.entities import User
from app.services.default_llm_seed import (
    ensure_deepseek_auto_seed,
    ensure_embedding_api_auto_seed,
    ensure_ollama_chat_seed,
)
from app.services.password_reset import (
    create_password_reset_token,
    reset_password_with_token,
)

router = APIRouter(prefix="/auth", tags=["auth"])


class RegisterBody(BaseModel):
    username: str = Field(min_length=2, max_length=64)
    password: str = Field(min_length=6, max_length=128)
    branch: str | None = Field(None, max_length=128)
    security_level: int | None = Field(None, ge=1, le=4)
    departments: list[str] | None = None
    org_id: str | None = Field(None, max_length=64)

    @field_validator("departments", mode="before")
    @classmethod
    def _strip_departments(cls, v: object) -> object:
        if v is None:
            return None
        if isinstance(v, list):
            return [str(x).strip() for x in v if str(x).strip()]
        return v


class LoginBody(BaseModel):
    username: str
    password: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"


class MePatchBody(BaseModel):
    """更新当前用户权限相关字段；仅提交需要修改的键。角色仅可由管理员在系统管理中修改。"""

    branch: str | None = Field(None, max_length=128)
    security_level: int | None = Field(None, ge=1, le=4)
    departments: list[str] | None = None
    org_id: str | None = Field(None, max_length=64)

    @field_validator("departments", mode="before")
    @classmethod
    def _strip_departments(cls, v: object) -> object:
        if v is None:
            return None
        if isinstance(v, list):
            return [str(x).strip() for x in v if str(x).strip()]
        return v


class MePatchResponse(BaseModel):
    """保存后签发新 JWT，使载荷与库内权限一致。"""

    access_token: str
    token_type: str = "bearer"
    id: int
    username: str
    branch: str
    role: str
    security_level: int
    departments: list[str]
    org_id: str | None


class ForgotPasswordBody(BaseModel):
    username: str = Field(min_length=1, max_length=64)


class ForgotPasswordResponse(BaseModel):
    """统一文案，避免枚举用户名是否存在。开发环境可额外返回 reset_token / reset_url。"""

    message: str
    reset_token: str | None = None
    reset_url: str | None = None


class ResetPasswordBody(BaseModel):
    token: str = Field(min_length=10, max_length=512)
    new_password: str = Field(min_length=6, max_length=128)


@router.post("/register", response_model=TokenResponse)
async def register(body: RegisterBody, db: AsyncSession = Depends(get_db)) -> TokenResponse:
    r = await db.execute(select(User).where(User.username == body.username))
    if r.scalar_one_or_none():
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail="Username taken")
    user = User(username=body.username, hashed_password=hash_password(body.password))
    user.role = "user"
    if body.branch is not None:
        user.branch = body.branch.strip() or "公共"
    if body.security_level is not None:
        user.security_level = body.security_level
    if body.departments is not None:
        user.departments_json = body.departments
    if body.org_id is not None:
        user.org_id = body.org_id.strip() or None
    db.add(user)
    await db.flush()
    await ensure_deepseek_auto_seed(db, user.id)
    await ensure_embedding_api_auto_seed(db, user.id)
    await ensure_ollama_chat_seed(db, user.id)
    token = create_access_token(user.id, extra=jwt_extra_from_user(user))
    return TokenResponse(access_token=token)


@router.post("/login", response_model=TokenResponse)
async def login(body: LoginBody, db: AsyncSession = Depends(get_db)) -> TokenResponse:
    r = await db.execute(select(User).where(User.username == body.username))
    user = r.scalar_one_or_none()
    if not user or not verify_password(body.password, user.hashed_password):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, detail="Invalid credentials")
    if not getattr(user, "is_active", True):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, detail="账户已停用")
    await ensure_deepseek_auto_seed(db, user.id)
    await ensure_embedding_api_auto_seed(db, user.id)
    await ensure_ollama_chat_seed(db, user.id)
    token = create_access_token(user.id, extra=jwt_extra_from_user(user))
    return TokenResponse(access_token=token)


@router.get("/me")
async def me(user: User = Depends(get_current_user)) -> dict:
    ctx = PermissionContext.from_user(user)
    return {
        "id": user.id,
        "username": user.username,
        "branch": ctx.branch,
        "role": ctx.role,
        "security_level": ctx.security_level,
        "departments": list(ctx.departments),
        "org_id": ctx.org_id,
        "is_active": bool(getattr(user, "is_active", True)),
    }


@router.patch("/me", response_model=MePatchResponse)
async def patch_me(
    body: MePatchBody,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> MePatchResponse:
    data = body.model_dump(exclude_unset=True)
    if "branch" in data:
        user.branch = (data["branch"] or "").strip() or "公共"
    if "security_level" in data:
        user.security_level = int(data["security_level"])
    if "departments" in data:
        depts = data["departments"]
        user.departments_json = depts if depts else None
    if "org_id" in data:
        raw = data["org_id"]
        if raw is None:
            user.org_id = None
        elif isinstance(raw, str):
            user.org_id = raw.strip() or None
        else:
            user.org_id = None
    await db.flush()
    token = create_access_token(user.id, extra=jwt_extra_from_user(user))
    ctx = PermissionContext.from_user(user)
    return MePatchResponse(
        access_token=token,
        token_type="bearer",
        id=user.id,
        username=user.username,
        branch=ctx.branch,
        role=ctx.role,
        security_level=ctx.security_level,
        departments=list(ctx.departments),
        org_id=ctx.org_id,
    )


@router.post("/forgot-password", response_model=ForgotPasswordResponse)
async def forgot_password(
    body: ForgotPasswordBody, db: AsyncSession = Depends(get_db)
) -> ForgotPasswordResponse:
    """申请重置：不泄露用户是否存在。若配置了在响应中返回 token（仅开发），可用于无邮件场景。"""
    settings = get_settings()
    generic = ForgotPasswordResponse(
        message="若该用户名存在，我们已受理重置请求。请按页面或邮件说明完成新密码设置。"
    )
    r = await db.execute(select(User).where(User.username == body.username))
    user = r.scalar_one_or_none()
    if not user:
        return generic

    raw = await create_password_reset_token(db, user.id)
    if settings.password_reset_token_in_response:
        base = settings.password_reset_frontend_base.rstrip("/")
        return ForgotPasswordResponse(
            message=generic.message,
            reset_token=raw,
            reset_url=f"{base}/reset-password?token={raw}",
        )
    return generic


@router.post("/reset-password")
async def reset_password_ep(
    body: ResetPasswordBody, db: AsyncSession = Depends(get_db)
) -> dict[str, str]:
    try:
        await reset_password_with_token(db, body.token, body.new_password)
    except ValueError as e:
        if str(e) == "INVALID_OR_EXPIRED_TOKEN":
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST,
                detail="重置链接无效或已过期，请重新申请忘记密码。",
            ) from e
        raise
    return {"status": "ok"}
