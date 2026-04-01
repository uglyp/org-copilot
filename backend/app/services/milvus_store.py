"""
Milvus 向量库封装。

- **Milvus Lite（默认）**：未配置 `MILVUS_URI` 时使用本地 `.db` 文件（`MILVUS_DB_PATH`）；与嵌入式 Qdrant 类似，注意单进程/文件锁与资源占用。
- **服务模式**：配置 `MILVUS_URI`（如 `http://127.0.0.1:19530`）连接独立 Milvus；可多 worker 共连；可选 `MILVUS_TOKEN`（如 Zilliz Cloud）。
- **集合 / 检索**：`ensure_collection` 按维度建表；标量字段与旧 Qdrant payload 对齐，便于 RAG 层复用 `payload` 结构。
- **企业 ACL**：`enterprise_acl_enabled` 为 true 时集合含 `branch`、`security_level`，检索在 Milvus 层过滤。
"""

from __future__ import annotations

import logging
import os
import threading
import uuid
from typing import TYPE_CHECKING, Any

from pymilvus import DataType, MilvusClient

from app.core.config import get_settings

logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    from app.models.entities import User

_client: MilvusClient | None = None
_client_key: str | None = None
_client_lock = threading.Lock()

# 与 ingestion 中 text 截断长度一致
_TEXT_MAX_LEN = 2048
_FILENAME_MAX_LEN = 512
_MODALITY_MAX_LEN = 32
_PK_MAX_LEN = 64
_BRANCH_MAX_LEN = 128


def _vector_dim_from_describe(info: dict[str, Any]) -> int:
    for f in info.get("fields") or []:
        if f.get("name") == "vector":
            return int((f.get("params") or {}).get("dim", 0))
    raise ValueError("Milvus collection 缺少 vector 字段")


def _collection_field_names(info: dict[str, Any]) -> set[str]:
    return {str(f.get("name")) for f in (info.get("fields") or []) if f.get("name")}


def _build_schema(dim: int, *, include_acl: bool) -> Any:
    schema = MilvusClient.create_schema(auto_id=False, enable_dynamic_field=False)
    schema.add_field(
        field_name="pk",
        datatype=DataType.VARCHAR,
        is_primary=True,
        max_length=_PK_MAX_LEN,
    )
    schema.add_field(field_name="vector", datatype=DataType.FLOAT_VECTOR, dim=dim)
    schema.add_field(field_name="kb_id", datatype=DataType.INT64)
    schema.add_field(field_name="doc_id", datatype=DataType.INT64)
    schema.add_field(field_name="chunk_id", datatype=DataType.INT64)
    schema.add_field(field_name="chunk_index", datatype=DataType.INT32)
    schema.add_field(field_name="chunk_db_id", datatype=DataType.INT64)
    schema.add_field(field_name="text", datatype=DataType.VARCHAR, max_length=_TEXT_MAX_LEN)
    schema.add_field(field_name="filename", datatype=DataType.VARCHAR, max_length=_FILENAME_MAX_LEN)
    schema.add_field(field_name="modality", datatype=DataType.VARCHAR, max_length=_MODALITY_MAX_LEN)
    if include_acl:
        schema.add_field(
            field_name="branch",
            datatype=DataType.VARCHAR,
            max_length=_BRANCH_MAX_LEN,
        )
        schema.add_field(field_name="security_level", datatype=DataType.INT32)
    return schema


def _build_index_params(client: MilvusClient, *, include_acl: bool) -> Any:
    idx = client.prepare_index_params()
    idx.add_index(field_name="vector", index_type="AUTOINDEX", metric_type="COSINE")
    idx.add_index(field_name="kb_id", index_type="INVERTED")
    idx.add_index(field_name="doc_id", index_type="INVERTED")
    if include_acl:
        idx.add_index(field_name="branch", index_type="INVERTED")
        idx.add_index(field_name="security_level", index_type="INVERTED")
    return idx


def get_milvus() -> MilvusClient:
    """进程内单例。Lite 本地文件模式勿多进程争用同一 `.db`；HTTP 模式可多 worker。"""
    global _client, _client_key
    settings = get_settings()
    with _client_lock:
        uri = (settings.milvus_uri or "").strip()
        if uri:
            key = f"uri:{uri}"
            if settings.milvus_token:
                key += f"|t:{settings.milvus_token[:8]}"
            if _client is None or _client_key != key:
                kwargs: dict[str, Any] = {"uri": uri}
                if (settings.milvus_token or "").strip():
                    kwargs["token"] = settings.milvus_token.strip()
                _client = MilvusClient(**kwargs)
                _client_key = key
        else:
            path = os.path.abspath(settings.milvus_db_path)
            parent = os.path.dirname(path)
            if parent:
                os.makedirs(parent, exist_ok=True)
            key = f"file:{path}"
            if _client is None or _client_key != key:
                _client = MilvusClient(uri=path)
                _client_key = key
        return _client


def ensure_collection(dim: int) -> None:
    """若集合不存在则创建；已存在则校验向量维度与 `dim` 一致；企业 ACL 模式下校验标量字段齐全。"""
    if dim < 1:
        raise ValueError("向量维度必须 >= 1")
    settings = get_settings()
    name = settings.milvus_collection
    client = get_milvus()
    acl = settings.enterprise_acl_enabled
    if not client.has_collection(name):
        schema = _build_schema(dim, include_acl=acl)
        idx = _build_index_params(client, include_acl=acl)
        client.create_collection(collection_name=name, schema=schema, index_params=idx)
        return
    info = client.describe_collection(name)
    existing = _vector_dim_from_describe(info)
    if existing != dim:
        raise ValueError(
            f"Milvus 集合「{name}」向量维度为 {existing}，与当前 embedding 输出维度 {dim} 不一致。"
            "请删除该集合、更换 MILVUS_COLLECTION 或清空本地 .db 后重新入库。"
        )
    if acl:
        names = _collection_field_names(info)
        if "branch" not in names or "security_level" not in names:
            raise ValueError(
                f"已启用企业 ACL，但集合「{name}」缺少 branch/security_level 字段。"
                "请设置新的 MILVUS_COLLECTION 或删除旧集合并重建后全量重新入库。"
            )


def upsert_chunks(
    kb_id: int,
    doc_id: int,
    vectors: list[list[float]],
    payloads: list[dict[str, Any]],
    chunk_ids: list[int],
) -> list[str]:
    """写入向量实体，返回主键 pk 列表（UUID 字符串，与 MySQL `milvus_point_id` 对齐）。"""
    settings = get_settings()
    client = get_milvus()
    ensure_collection(len(vectors[0]))
    name = settings.milvus_collection
    acl = settings.enterprise_acl_enabled
    pks: list[str] = []
    rows: list[dict[str, Any]] = []
    pub = (settings.public_branch_label or "公共").strip() or "公共"
    for vec, pl, cid in zip(vectors, payloads, chunk_ids, strict=True):
        pk = str(uuid.uuid4())
        pks.append(pk)
        text = str(pl.get("text", ""))[:_TEXT_MAX_LEN]
        chunk_index = int(pl.get("chunk_index", 0))
        chunk_db_id = int(pl.get("chunk_db_id", cid))
        filename = str(pl.get("filename", ""))[:_FILENAME_MAX_LEN]
        modality = str(pl.get("modality", "text"))[:_MODALITY_MAX_LEN]
        row: dict[str, Any] = {
            "pk": pk,
            "vector": vec,
            "kb_id": kb_id,
            "doc_id": doc_id,
            "chunk_id": cid,
            "chunk_index": chunk_index,
            "chunk_db_id": chunk_db_id,
            "text": text,
            "filename": filename,
            "modality": modality,
        }
        if acl:
            br = str(pl.get("branch", pub))[:_BRANCH_MAX_LEN]
            row["branch"] = br
            row["security_level"] = int(pl.get("security_level", 1))
        rows.append(row)
    client.upsert(collection_name=name, data=rows)
    return pks


def search_kb(
    kb_id: int,
    vector: list[float],
    top_k: int,
    *,
    acl_user: User | None = None,
) -> list[dict[str, Any]]:
    """向量近邻检索，返回结构与旧 Qdrant 层一致：`score`、`payload`、`id`。"""
    if not vector:
        return []
    dim = len(vector)
    ensure_collection(dim)
    settings = get_settings()
    client = get_milvus()
    name = settings.milvus_collection
    if settings.enterprise_acl_enabled:
        if acl_user is None:
            raise ValueError("enterprise_acl_enabled 为 true 时，search_kb 必须传入 acl_user")
        from app.services.permissions import build_milvus_acl_filter

        flt = build_milvus_acl_filter(
            kb_id,
            acl_user,
            public_branch_label=settings.public_branch_label,
        )
    else:
        flt = f"kb_id == {int(kb_id)}"

    out_fields = [
        "kb_id",
        "doc_id",
        "chunk_id",
        "chunk_index",
        "chunk_db_id",
        "text",
        "filename",
        "modality",
    ]
    if settings.enterprise_acl_enabled:
        out_fields.extend(["branch", "security_level"])

    raw = client.search(
        collection_name=name,
        data=[vector],
        limit=top_k,
        filter=flt,
        output_fields=out_fields,
    )
    hits = raw[0] if raw else []
    result: list[dict[str, Any]] = []
    for hit in hits:
        ent = hit.get("entity") or {}
        payload = {k: ent.get(k) for k in out_fields}
        dist = float(hit.get("distance", 0.0))
        # Milvus 返回的 distance 依 metric 而定；用负值近似「越大越相似」，仅用于调试/对齐 Qdrant 习惯
        result.append(
            {
                "score": -dist,
                "payload": payload,
                "id": str(hit.get("id", "")),
            }
        )
    return result


def delete_by_doc_id(doc_id: int) -> None:
    settings = get_settings()
    client = get_milvus()
    if not client.has_collection(settings.milvus_collection):
        return
    try:
        client.delete(collection_name=settings.milvus_collection, filter=f"doc_id == {int(doc_id)}")
    except Exception:
        pass


def update_milvus_entities_acl_for_document(
    doc_id: int,
    *,
    branch: str,
    security_level: int,
) -> None:
    """已入库文档修改分行/密级后，批量更新 Milvus 中该文档全部 chunk 的标量字段（向量与其它字段不变）。"""
    settings = get_settings()
    if not settings.enterprise_acl_enabled:
        return
    client = get_milvus()
    name = settings.milvus_collection
    if not client.has_collection(name):
        return
    info = client.describe_collection(name)
    names = _collection_field_names(info)
    if "branch" not in names or "security_level" not in names:
        return
    pub = (settings.public_branch_label or "公共").strip() or "公共"
    branch_s = (branch or "").strip()[:_BRANCH_MAX_LEN] or pub[:_BRANCH_MAX_LEN]
    sec = int(security_level)
    out_fields = [
        "pk",
        "vector",
        "kb_id",
        "doc_id",
        "chunk_id",
        "chunk_index",
        "chunk_db_id",
        "text",
        "filename",
        "modality",
        "branch",
        "security_level",
    ]
    # 单文档 chunk 数量通常远小于上限；若超限可再加分页
    try:
        rows = client.query(
            collection_name=name,
            filter=f"doc_id == {int(doc_id)}",
            output_fields=out_fields,
            limit=100_000,
        )
    except Exception:
        logger.exception(
            "Milvus query 失败，无法同步文档 ACL：doc_id=%s", doc_id
        )
        return
    if not rows:
        return
    if len(rows) >= 100_000:
        logger.warning(
            "文档 chunk 数达到 query 上限 100000，可能未全部更新 ACL：doc_id=%s",
            doc_id,
        )
    batch: list[dict[str, Any]] = []
    for row in rows:
        d = dict(row)
        d["branch"] = branch_s
        d["security_level"] = sec
        batch.append(d)
    # MilvusClient.upsert 单次体量过大可能失败，分批写入
    step = 256
    for i in range(0, len(batch), step):
        try:
            client.upsert(collection_name=name, data=batch[i : i + step])
        except Exception:
            logger.exception(
                "Milvus upsert 失败，向量库 ACL 与数据库可能不一致：doc_id=%s batch=%s:%s",
                doc_id,
                i,
                i + step,
            )
