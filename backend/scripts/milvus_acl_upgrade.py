#!/usr/bin/env python3
"""
企业 ACL / 新 Milvus schema 升级后的本地操作：

1. **Milvus Lite**（未配置 ``MILVUS_URI``）：删除 ``MILVUS_DB_PATH`` 及同前缀文件（如 ``.db-wal``）。
2. **独立 Milvus**（已配置 ``MILVUS_URI``）：可选 ``--drop-collection`` 删除当前 ``MILVUS_COLLECTION``。
3. 对数据库中 ``status == ready`` 的文档逐个重新执行入库流水线（删旧 Chunk 与向量点、重嵌入、写入含 ACL 标量的集合）。

在 ``backend/`` 目录执行（需已 ``alembic upgrade head`` 且 ``.env`` 可用）::

    uv run python scripts/milvus_acl_upgrade.py --yes
    uv run python scripts/milvus_acl_upgrade.py --yes --skip-delete      # 已手动清空向量库
    uv run python scripts/milvus_acl_upgrade.py --yes --drop-collection  # 仅用独立 Milvus 且需删集合时
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
from pathlib import Path

_BACKEND_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if _BACKEND_ROOT not in sys.path:
    sys.path.insert(0, _BACKEND_ROOT)


async def _reindex_all_ready() -> tuple[int, int]:
    from sqlalchemy import select

    from app.db.session import async_session_factory
    from app.models.entities import Document
    from app.workers.tasks import ingest_document_task

    async with async_session_factory() as session:
        r = await session.execute(
            select(Document.id).where(Document.status == "ready").order_by(Document.id.asc())
        )
        doc_ids = [row[0] for row in r.all()]

    ok, err = 0, 0
    for doc_id in doc_ids:
        try:
            await ingest_document_task(doc_id)
        except Exception as e:  # noqa: BLE001
            err += 1
            print(f"  异常 document id={doc_id}: {e!s}"[:500])
            continue
        async with async_session_factory() as session:
            r2 = await session.execute(
                select(Document.status, Document.error_message).where(Document.id == doc_id)
            )
            row = r2.one_or_none()
        if not row:
            err += 1
            print(f"  失败 document id={doc_id}: 记录不存在")
            continue
        st, msg = row[0], row[1]
        if st == "ready":
            ok += 1
            print(f"  已重入库 document id={doc_id}")
        else:
            err += 1
            hint = (msg or "")[:200]
            print(f"  未就绪 document id={doc_id} status={st} {hint}")
    return ok, err


def _remove_milvus_lite_files(settings) -> list[str]:
    """删除 Lite 本地文件，返回已删除路径列表。"""
    uri = (settings.milvus_uri or "").strip()
    if uri:
        return []
    raw = (settings.milvus_db_path or "./data/milvus_local.db").strip()
    p = Path(raw)
    if not p.is_absolute():
        p = (_BACKEND_ROOT / p).resolve()
    removed: list[str] = []
    parent = p.parent
    prefix = p.name
    if not parent.is_dir():
        return removed
    for f in sorted(parent.glob(f"{prefix}*"), key=lambda x: len(str(x)), reverse=True):
        if f.is_file():
            try:
                f.unlink()
                removed.append(str(f))
            except OSError as e:
                print(f"  警告：无法删除 {f}: {e}")
    return removed


def main() -> int:
    parser = argparse.ArgumentParser(description="Milvus ACL 升级：清本地库/删集合 + 全量重入库")
    parser.add_argument(
        "--yes",
        action="store_true",
        help="确认执行破坏性操作（删文件或删集合）",
    )
    parser.add_argument(
        "--skip-delete",
        action="store_true",
        help="跳过删本地 .db / 删集合（你已手动处理向量存储）",
    )
    parser.add_argument(
        "--drop-collection",
        action="store_true",
        help="使用 MILVUS_URI 时删除当前 MILVUS_COLLECTION（与 --yes 合用）",
    )
    parser.add_argument(
        "--reindex-only",
        action="store_true",
        help="仅重入库，不删向量存储",
    )
    args = parser.parse_args()

    from app.core.config import get_settings

    settings = get_settings()

    if args.reindex_only:
        print("仅重入库（未删除向量存储）…")
        ok, err = asyncio.run(_reindex_all_ready())
        print(f"完成：成功 {ok}，失败 {err}")
        return 1 if err else 0

    if not args.yes:
        print("未加 --yes，取消。确认后请执行：")
        print("  uv run python scripts/milvus_acl_upgrade.py --yes")
        return 2

    if not args.skip_delete:
        uri = (settings.milvus_uri or "").strip()
        if uri:
            if args.drop_collection:
                from app.services.milvus_store import get_milvus

                name = settings.milvus_collection
                client = get_milvus()
                if client.has_collection(name):
                    client.drop_collection(name)
                    print(f"已删除集合: {name}")
                else:
                    print(f"集合不存在，跳过: {name}")
            else:
                print(
                    "已配置 MILVUS_URI 但未指定 --drop-collection；未删除服务端集合。"
                    "若需重建 schema，请追加 --drop-collection，或在控制台手动删集合后重跑本脚本。"
                )
        else:
            removed = _remove_milvus_lite_files(settings)
            if removed:
                print("已删除 Milvus Lite 文件：")
                for p in removed:
                    print(f"  {p}")
            else:
                print("未找到需删除的 Milvus Lite 文件（可能路径不同或已清空）。")

    print("开始重入库 status=ready 的文档…")
    ok, err = asyncio.run(_reindex_all_ready())
    print(f"完成：成功 {ok}，失败 {err}")
    return 1 if err else 0


if __name__ == "__main__":
    raise SystemExit(main())
