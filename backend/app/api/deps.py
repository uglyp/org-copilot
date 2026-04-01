"""
FastAPI 依赖（Dependency Injection）。

`Depends(函数)` 会在进入路由前执行函数，返回值注入到参数里。
`Annotated[T, Depends(...)]` 是推荐写法，类型检查器能认出 `T`。

- `get_current_user`：从 Bearer Token 解析用户 id，再查库得到 `User`。
- `require_*_ready`：在已登录基础上，再检查是否配置了默认 chat/embedding 模型（业务前置条件）。
"""

from typing import Annotated

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.security import decode_token
from app.db.session import get_db
from app.models.entities import User
from app.services.permissions import PermissionContext, is_user_admin
from app.services.model_readiness import (
    is_chat_ready,
    is_embedding_ready,
    is_model_ready,
)

# auto_error=False：无 Authorization 头时不自动 403，便于自行返回 401
security = HTTPBearer(auto_error=False)


async def get_current_user(
    cred: Annotated[HTTPAuthorizationCredentials | None, Depends(security)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> User:
    if not cred:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, detail="Not authenticated")
    payload = decode_token(cred.credentials)
    if not payload or "sub" not in payload:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, detail="Invalid token")
    uid = int(payload["sub"])
    r = await db.execute(select(User).where(User.id == uid))
    user = r.scalar_one_or_none()
    if not user:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, detail="User not found")
    if not getattr(user, "is_active", True):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, detail="账户已停用")
    return user


async def require_admin(user: Annotated[User, Depends(get_current_user)]) -> User:
    if not is_user_admin(user):
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            detail="需要管理员权限（用户角色为 admin）",
        )
    return user


async def get_permission_context(
    user: Annotated[User, Depends(get_current_user)],
) -> PermissionContext:
    """从数据库中的 `User` 行派生权限上下文（权威源，与 JWT 声明对齐）。"""
    return PermissionContext.from_user(user)


async def require_chat_ready(
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> User:
    settings = get_settings()
    if settings.allow_chat_without_model_setup:
        return user
    if not await is_chat_ready(db, user.id):
        raise HTTPException(
            status.HTTP_412_PRECONDITION_FAILED,
            detail={
                "code": "CHAT_MODEL_NOT_READY",
                "message": "请先配置默认对话模型（或设置 DEEPSEEK_API_KEY 以自动创建）",
            },
        )
    return user


async def require_embedding_ready(
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> User:
    settings = get_settings()
    if settings.allow_chat_without_model_setup:
        return user
    if not await is_embedding_ready(db, user.id):
        raise HTTPException(
            status.HTTP_412_PRECONDITION_FAILED,
            detail={
                "code": "EMBEDDING_MODEL_NOT_READY",
                "message": "请先配置默认向量模型后，再上传文档或入库",
            },
        )
    return user


async def require_model_ready(
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> User:
    """对话 + 向量均就绪（兼容旧逻辑）。"""
    settings = get_settings()
    if settings.allow_chat_without_model_setup:
        return user
    ok, _ = await is_model_ready(db, user.id)
    if not ok:
        raise HTTPException(
            status.HTTP_412_PRECONDITION_FAILED,
            detail={"code": "MODEL_NOT_READY", "message": "请先完成模型配置"},
        )
    return user
