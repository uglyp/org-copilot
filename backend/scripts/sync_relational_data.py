#!/usr/bin/env python3
"""
将关系型数据从 MySQL 同步到 PostgreSQL（保留主键与外键顺序）。

前置条件：
- 目标库已执行 `alembic upgrade head`（schema 与 MySQL 一致）。
- 同步连接串须使用 **同步** 驱动：`mysql+pymysql://`、`postgresql+psycopg://`
  （与 `DATABASE_URL` 的 aiomysql/asyncpg 不同）。

限制：**仅支持 MySQL → PostgreSQL**；反向或其它组合请自行处理。连接串中的密码若含 `@`、`:` 等须按 URL 编码。

用法（在 backend 目录下）::

    uv run python scripts/sync_relational_data.py \\
      --source-url 'mysql+pymysql://root:pass@127.0.0.1:3306/org_copilot' \\
      --target-url 'postgresql+psycopg://kbuser:pass@127.0.0.1:5432/org_copilot' \\
      --truncate-target

也可通过环境变量（便于与 CI/脚本集成）::

    export SYNC_SOURCE_DATABASE_URL='mysql+pymysql://...'
    export SYNC_TARGET_DATABASE_URL='postgresql+psycopg://...'
    uv run python scripts/sync_relational_data.py --truncate-target

`--truncate-target`：清空目标库中本应用相关表并 `RESTART IDENTITY` 后再写入；
若不加该参数，目标表必须为空，否则可能因主键冲突失败。
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from typing import Any

from sqlalchemy import MetaData, Table, create_engine, insert, text
from sqlalchemy.engine import Connection, Engine
from sqlalchemy.types import Boolean, JSON

# 外键顺序：先父后子
TABLE_NAMES: tuple[str, ...] = (
    "users",
    "llm_providers",
    "llm_models",
    "knowledge_bases",
    "documents",
    "chunks",
    "conversations",
    "messages",
    "password_reset_tokens",
    "audit_logs",
    "llm_usage_records",
)


def _parse_json_if_needed(val: Any) -> Any:
    if val is None:
        return None
    if isinstance(val, (dict, list)):
        return val
    if isinstance(val, (bytes, bytearray)):
        val = val.decode("utf-8")
    if isinstance(val, str):
        s = val.strip()
        if not s:
            return None
        try:
            return json.loads(s)
        except json.JSONDecodeError:
            return val
    return val


def _normalize_cell(col_type: Any, val: Any) -> Any:
    if val is None:
        return None
    if isinstance(col_type, JSON):
        return _parse_json_if_needed(val)
    if isinstance(col_type, Boolean):
        if isinstance(val, bool):
            return val
        if isinstance(val, (int, float)):
            return bool(int(val))
        if isinstance(val, str):
            return val.lower() in ("1", "true", "t", "yes")
    return val


def _normalize_row(table: Table, row: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for col in table.columns:
        key = col.name
        if key not in row:
            continue
        out[key] = _normalize_cell(col.type, row[key])
    return out


def _truncate_postgres(conn: Connection) -> None:
    names = ", ".join(TABLE_NAMES)
    conn.execute(
        text(f"TRUNCATE TABLE {names} RESTART IDENTITY CASCADE")
    )


def _reset_sequences(conn: Connection) -> None:
    for name in TABLE_NAMES:
        max_id = conn.execute(text(f"SELECT MAX(id) FROM {name}")).scalar()
        if max_id is None:
            continue
        conn.execute(
            text("SELECT setval(pg_get_serial_sequence(:t, 'id'), :m)"),
            {"t": name, "m": max_id},
        )


def _copy_tables(
    source: Engine, target: Engine, *, truncate: bool, dry_run: bool
) -> None:
    if dry_run:
        with source.connect() as sconn:
            for name in TABLE_NAMES:
                n = sconn.execute(text(f"SELECT COUNT(*) FROM {name}")).scalar()
                print(f"  {name}: {n} 行（dry-run，未写目标库）")
        return

    metadata = MetaData()
    reflected: dict[str, Table] = {
        n: Table(n, metadata, autoload_with=target) for n in TABLE_NAMES
    }

    with target.connect() as tconn:
        if truncate:
            _truncate_postgres(tconn)
            tconn.commit()

    with source.connect() as sconn, target.connect() as tconn:
        trans = tconn.begin()
        try:
            for name in TABLE_NAMES:
                tbl = reflected[name]
                cols = [c.name for c in tbl.columns]
                col_list = ", ".join(cols)
                rows = (
                    sconn.execute(
                        text(f"SELECT {col_list} FROM {name} ORDER BY id")
                    )
                    .mappings()
                    .all()
                )
                if not rows:
                    print(f"  {name}: 0 行")
                    continue
                for row in rows:
                    payload = _normalize_row(tbl, dict(row))
                    tconn.execute(insert(tbl), payload)
                print(f"  {name}: 已写入 {len(rows)} 行")
            _reset_sequences(tconn)
            trans.commit()
        except Exception:
            trans.rollback()
            raise


def _require_urls(
    source: str | None, target: str | None
) -> tuple[str, str]:
    src = source or os.environ.get("SYNC_SOURCE_DATABASE_URL", "").strip()
    dst = target or os.environ.get("SYNC_TARGET_DATABASE_URL", "").strip()
    if not src or not dst:
        print(
            "请提供 --source-url / --target-url，"
            "或设置 SYNC_SOURCE_DATABASE_URL 与 SYNC_TARGET_DATABASE_URL",
            file=sys.stderr,
        )
        sys.exit(2)
    if not src.startswith("mysql+pymysql://"):
        print("源库 URL 须以 mysql+pymysql:// 开头", file=sys.stderr)
        sys.exit(2)
    if not dst.startswith("postgresql+psycopg://"):
        print("目标库 URL 须以 postgresql+psycopg:// 开头", file=sys.stderr)
        sys.exit(2)
    return src, dst


def main() -> None:
    parser = argparse.ArgumentParser(description="MySQL → PostgreSQL 关系数据同步")
    parser.add_argument("--source-url", default=None, help="mysql+pymysql://...")
    parser.add_argument("--target-url", default=None, help="postgresql+psycopg://...")
    parser.add_argument(
        "--truncate-target",
        action="store_true",
        help="清空目标库相关表（PostgreSQL TRUNCATE ... CASCADE）后写入",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="仅统计行数，不写库",
    )
    args = parser.parse_args()
    src, dst = _require_urls(args.source_url, args.target_url)

    print("连接源库 (MySQL)...")
    source_eng = create_engine(src, pool_pre_ping=True)
    print("连接目标库 (PostgreSQL)...")
    target_eng = create_engine(dst, pool_pre_ping=True)

    if args.truncate_target and not args.dry_run:
        print("清空目标表（TRUNCATE ... RESTART IDENTITY CASCADE）...")
    print("按外键顺序复制...")
    _copy_tables(
        source_eng,
        target_eng,
        truncate=args.truncate_target,
        dry_run=args.dry_run,
    )
    print("完成。")


if __name__ == "__main__":
    main()
