"""
知识库与文档：上传后 **同步** 调用入库流水线（解析 → 分块 → 向量 → Milvus），便于接口直接返回最终 `status`。

删除文档时需同时删 MySQL 分块、Milvus 实体与磁盘文件，避免孤儿数据。
"""

import mimetypes
import os
import uuid
from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from sqlalchemy import and_, delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, require_embedding_ready
from app.core.config import get_settings
from app.db.session import get_db

from app.models.entities import Chunk, Document, KnowledgeBase, User
from app.services.image_ingest import is_image_extension, verify_image_file
from app.services.milvus_store import delete_by_doc_id, update_milvus_entities_acl_for_document
from app.services.permissions import document_acl_filter, kb_access_filter
from app.workers.tasks import ingest_document_task

router = APIRouter(prefix="/knowledge-bases", tags=["knowledge"])

TEXT_UPLOAD_EXT = frozenset({".pdf", ".txt", ".md", ".markdown"})


class KBCreate(BaseModel):
    name: str = Field(max_length=256)
    description: str | None = None
    org_id: str | None = Field(None, max_length=64)
    is_org_shared: bool = False


class KBOut(BaseModel):
    id: int
    user_id: int
    name: str
    description: str | None
    org_id: str | None = None
    is_org_shared: bool = False

    class Config:
        from_attributes = True


class DocOut(BaseModel):
    id: int
    filename: str
    modality: str = "text"
    status: str
    error_message: str | None
    branch: str = "公共"
    security_level: int = 1
    department: str | None = None
    creator_user_id: int | None = None

    class Config:
        from_attributes = True


class DocumentMetadataPatch(BaseModel):
    """部分更新文档权限元数据；未传字段保持不变。"""

    branch: str | None = None
    security_level: int | None = None
    department: str | None = None


@router.get("", response_model=list[KBOut])
async def list_kb(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[KnowledgeBase]:
    r = await db.execute(select(KnowledgeBase).where(kb_access_filter(user)))
    return list(r.scalars().all())


@router.post("", response_model=KBOut)
async def create_kb(
    body: KBCreate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> KnowledgeBase:
    oid = body.org_id.strip() if body.org_id and body.org_id.strip() else None
    kb = KnowledgeBase(
        user_id=user.id,
        name=body.name,
        description=body.description,
        org_id=oid,
        is_org_shared=body.is_org_shared,
    )
    db.add(kb)
    await db.flush()
    return kb


async def _get_kb(db: AsyncSession, kb_id: int, user: User) -> KnowledgeBase:
    r = await db.execute(
        select(KnowledgeBase).where(
            KnowledgeBase.id == kb_id,
            kb_access_filter(user),
        )
    )
    kb = r.scalar_one_or_none()
    if not kb:
        raise HTTPException(status.HTTP_404_NOT_FOUND)
    return kb


def _can_edit_document_metadata(kb: KnowledgeBase, doc: Document, user: User) -> bool:
    """知识库属主或文档上传者可改密级/分行/部门。"""
    if kb.user_id == user.id:
        return True
    if doc.creator_user_id is not None and doc.creator_user_id == user.id:
        return True
    return False


@router.get("/{kb_id}/documents", response_model=list[DocOut])
async def list_docs(
    kb_id: int,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[Document]:
    await _get_kb(db, kb_id, user)
    settings = get_settings()
    acl = document_acl_filter(user, public_branch_label=settings.public_branch_label)
    r = await db.execute(
        select(Document).where(and_(Document.kb_id == kb_id, acl))
    )
    return list(r.scalars().all())


@router.post("/{kb_id}/documents", response_model=DocOut)
async def upload_doc(
    kb_id: int,
    user: User = Depends(require_embedding_ready),
    db: AsyncSession = Depends(get_db),
    file: UploadFile = File(...),
    branch: str | None = Form(None),
    security_level: int | None = Form(None),
    department: str | None = Form(None),
) -> Document:
    kb = await _get_kb(db, kb_id, user)
    settings = get_settings()
    ext = Path(file.filename or "bin").suffix.lower()
    if ext in TEXT_UPLOAD_EXT:
        modality = "text"
    elif is_image_extension(ext):
        modality = "image"
    else:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            detail="不支持的文件类型（支持 PDF/TXT/Markdown 与常见图片：png/jpg/webp/gif/bmp）",
        )
    sub = os.path.join(settings.upload_dir, str(kb_id))
    os.makedirs(sub, exist_ok=True)
    safe_name = f"{uuid.uuid4().hex}{ext}"
    path = os.path.join(sub, safe_name)
    content = await file.read()
    with open(path, "wb") as f:
        f.write(content)
    if modality == "image":
        try:
            verify_image_file(path)
        except ValueError as e:
            try:
                os.remove(path)
            except OSError:
                pass
            raise HTTPException(status.HTTP_400_BAD_REQUEST, detail=str(e)) from e
    pub = (settings.public_branch_label or "公共").strip() or "公共"
    br = (branch.strip() if branch and branch.strip() else None) or pub
    sl = int(security_level) if security_level is not None else 1
    if sl < 1 or sl > 4:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            detail="security_level 须在 1～4 之间",
        )
    dept = department.strip() if department and department.strip() else None
    doc = Document(
        kb_id=kb.id,
        filename=file.filename or safe_name,
        storage_path=path,
        modality=modality,
        status="queued",
        branch=br,
        security_level=sl,
        department=dept,
        creator_user_id=user.id,
    )
    db.add(doc)
    await db.flush()
    # 先提交，保证入库任务能读到该行；在同一次请求内 await 完成解析/向量/Milvus，避免 BackgroundTasks 未执行或失败被吞导致永远 queued
    await db.commit()
    try:
        await ingest_document_task(doc.id)
    except Exception:
        # 失败原因已写入 Document；此处不抛，避免前端只看到 500
        pass
    r = await db.execute(select(Document).where(Document.id == doc.id))
    doc = r.scalar_one()
    return doc


@router.get("/{kb_id}/documents/{doc_id}/file")
async def get_doc_file(
    kb_id: int,
    doc_id: int,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> FileResponse:
    """返回原始文件流，供列表预览（图像与 PDF/TXT/Markdown 等文本文档）。"""
    await _get_kb(db, kb_id, user)
    settings = get_settings()
    acl = document_acl_filter(user, public_branch_label=settings.public_branch_label)
    r = await db.execute(
        select(Document).where(
            and_(Document.id == doc_id, Document.kb_id == kb_id, acl)
        )
    )
    doc = r.scalar_one_or_none()
    if not doc:
        raise HTTPException(status.HTTP_404_NOT_FOUND)
    if doc.modality not in ("image", "text"):
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, detail="该文档类型不支持预览"
        )
    upload_root = Path(settings.upload_dir).resolve()
    try:
        file_path = Path(doc.storage_path).resolve()
        file_path.relative_to(upload_root)
    except ValueError:
        raise HTTPException(status.HTTP_403_FORBIDDEN) from None
    if not file_path.is_file():
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="文件不存在")

    ext = file_path.suffix.lower()
    guessed, _ = mimetypes.guess_type(doc.filename or str(file_path))

    if doc.modality == "image":
        media_type: str | None = (
            guessed if guessed and guessed.startswith("image/") else None
        )
        if not media_type:
            if ext == ".png":
                media_type = "image/png"
            elif ext in {".jpg", ".jpeg"}:
                media_type = "image/jpeg"
            elif ext == ".webp":
                media_type = "image/webp"
            elif ext == ".gif":
                media_type = "image/gif"
            elif ext == ".bmp":
                media_type = "image/bmp"
            else:
                media_type = "application/octet-stream"
    else:
        if ext == ".pdf":
            media_type = "application/pdf"
        elif ext in {".md", ".markdown"}:
            media_type = "text/markdown; charset=utf-8"
        elif ext == ".txt":
            media_type = "text/plain; charset=utf-8"
        elif guessed:
            media_type = guessed
        else:
            media_type = "application/octet-stream"

    return FileResponse(
        path=file_path,
        media_type=media_type,
        filename=doc.filename or file_path.name,
    )


@router.patch("/{kb_id}/documents/{doc_id}", response_model=DocOut)
async def patch_document_metadata(
    kb_id: int,
    doc_id: int,
    body: DocumentMetadataPatch,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> Document:
    kb = await _get_kb(db, kb_id, user)
    r = await db.execute(
        select(Document).where(
            and_(Document.id == doc_id, Document.kb_id == kb_id),
        )
    )
    doc = r.scalar_one_or_none()
    if not doc:
        raise HTTPException(status.HTTP_404_NOT_FOUND)
    if not _can_edit_document_metadata(kb, doc, user):
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            detail="无权编辑该文档的权限元数据",
        )
    data = body.model_dump(exclude_unset=True)
    if not data:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            detail="请至少提供 branch、security_level、department 之一",
        )
    settings = get_settings()
    pub = (settings.public_branch_label or "公共").strip() or "公共"
    old_branch, old_security_level = doc.branch, doc.security_level
    if "branch" in data:
        br = data["branch"]
        doc.branch = (
            (br.strip() if isinstance(br, str) and br.strip() else None) or pub
        )
    if "security_level" in data:
        sl = int(data["security_level"])
        if sl < 1 or sl > 4:
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST,
                detail="security_level 须在 1～4 之间",
            )
        doc.security_level = sl
    if "department" in data:
        dept = data["department"]
        if dept is None:
            doc.department = None
        elif isinstance(dept, str):
            doc.department = dept.strip() or None
        else:
            doc.department = None
    branch_or_sec_changed = (
        doc.branch != old_branch or doc.security_level != old_security_level
    )
    await db.commit()
    await db.refresh(doc)
    if (
        doc.status == "ready"
        and settings.enterprise_acl_enabled
        and branch_or_sec_changed
    ):
        update_milvus_entities_acl_for_document(
            doc.id,
            branch=doc.branch,
            security_level=doc.security_level,
        )
    return doc


@router.delete("/{kb_id}/documents/{doc_id}")
async def delete_doc(
    kb_id: int,
    doc_id: int,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, str]:
    await _get_kb(db, kb_id, user)
    settings = get_settings()
    acl = document_acl_filter(user, public_branch_label=settings.public_branch_label)
    r = await db.execute(
        select(Document).where(
            and_(Document.id == doc_id, Document.kb_id == kb_id, acl)
        )
    )
    doc = r.scalar_one_or_none()
    if not doc:
        raise HTTPException(status.HTTP_404_NOT_FOUND)
    delete_by_doc_id(doc.id)
    await db.execute(delete(Chunk).where(Chunk.doc_id == doc.id))
    await db.execute(delete(Document).where(Document.id == doc.id))
    try:
        if os.path.isfile(doc.storage_path):
            os.remove(doc.storage_path)
    except OSError:
        pass
    return {"status": "ok"}
