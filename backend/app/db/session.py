"""
异步数据库会话（SQLAlchemy 2.x）。

概念速览：
- `Engine`：连接池与方言（由 `DATABASE_URL` 决定：MySQL 用 aiomysql，PostgreSQL 用 asyncpg）的入口；应用进程内通常只有一个全局 `engine`。
- `async_sessionmaker`：工厂函数，每次请求 `()` 得到一个 `AsyncSession`。
- `expire_on_commit=False`：提交后 ORM 对象仍可读取已加载属性，避免懒加载在异步里踩坑。

`get_db` 是 FastAPI 依赖注入用例：`Depends(get_db)` 的路由会在一次请求内共用一个 session，
在请求正常结束时 `commit`，异常时 `rollback`（与路由里手动 `flush` 配合时注意事务边界）。
"""

from collections.abc import AsyncGenerator

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.config import get_settings, mysql_url_and_connect_args


settings = get_settings()
_db_url, _mysql_connect = mysql_url_and_connect_args(settings.database_url)
_engine_kw: dict = {
    "echo": settings.debug,
    "pool_pre_ping": True,
}
if _mysql_connect:
    _engine_kw["connect_args"] = _mysql_connect
engine = create_async_engine(_db_url, **_engine_kw)
async_session_factory = async_sessionmaker(
    engine, class_=AsyncSession, expire_on_commit=False
)


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """yield session → 路由执行 → 成功则 commit；任一步异常则 rollback 并向上抛出。"""
    async with async_session_factory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()
