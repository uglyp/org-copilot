"""聚合 v1 子路由；`main.py` 里再统一加 `/api/v1` 前缀。"""

from fastapi import APIRouter

from app.api.v1 import acl_catalog, admin, auth, conversations, knowledge, usage, user_models

api_router = APIRouter()
api_router.include_router(acl_catalog.router)
api_router.include_router(auth.router)
api_router.include_router(admin.router)
api_router.include_router(user_models.router)
api_router.include_router(knowledge.router)
api_router.include_router(conversations.router)
api_router.include_router(usage.router)
