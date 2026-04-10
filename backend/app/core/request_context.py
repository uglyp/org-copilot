"""
请求上下文：统一管理 request_id（中间件写入，业务层读取）。
"""

from contextvars import ContextVar

_request_id_var: ContextVar[str] = ContextVar("request_id", default="")


def set_request_id(request_id: str) -> None:
    _request_id_var.set(request_id)


def get_request_id() -> str:
    return _request_id_var.get("")
