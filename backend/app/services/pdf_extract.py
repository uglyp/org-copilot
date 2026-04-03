"""
PDF 文本抽取：优先 PyMuPDF 文字层；单页文字过少时视为扫描页，渲染为位图后走 PaddleOCR。

依赖：`pymupdf` 为必选；扫描页 OCR 需 `uv sync --extra image`（与图片入库相同）。
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Any

import fitz  # type: ignore[import-untyped]  # PyMuPDF

logger = logging.getLogger(__name__)

# 少于此字数的页面尝试 OCR（含空白/仅页眉页脚的正文层）
MIN_PAGE_TEXT_CHARS = 48
# 渲染倍率，过小影响小字识别
PAGE_RENDER_SCALE = 2.0


def _lines_from_paddle_result(result: Any) -> list[str]:
    lines: list[str] = []
    if not result or not result[0]:
        return lines
    for line in result[0]:
        if line and len(line) >= 2 and line[1]:
            text_part = line[1][0]
            if text_part:
                lines.append(str(text_part))
    return lines


def _ocr_bgr_numpy(ocr: Any, bgr: Any) -> str:
    """bgr: numpy HxWx3 uint8。"""
    result = ocr.ocr(bgr, cls=True)
    return "\n".join(_lines_from_paddle_result(result)).strip()


def _page_text_or_ocr(page: Any, get_ocr: Callable[[], Any | None]) -> str:
    text = (page.get_text("text") or "").strip()
    if len(text) >= MIN_PAGE_TEXT_CHARS:
        return text

    ocr = get_ocr()
    if ocr is None:
        if text:
            logger.debug(
                "pdf 第 %s 页文字层较短且 OCR 不可用，仅使用文字层",
                page.number + 1,
            )
        return text

    try:
        import numpy as np  # type: ignore[import-untyped]
    except ImportError as e:
        logger.warning("pdf OCR 需要 numpy：%s", e)
        return text

    m = fitz.Matrix(PAGE_RENDER_SCALE, PAGE_RENDER_SCALE)
    pix = page.get_pixmap(matrix=m, alpha=False)
    n = pix.n
    if n not in (3, 4):
        logger.warning("pdf 第 %s 页 pixmap 通道数异常 n=%s", page.number + 1, n)
        return text

    arr = np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.height, pix.width, n)
    if n == 4:
        arr = arr[:, :, :3]
    bgr = arr[..., ::-1].copy()

    ocr_text = _ocr_bgr_numpy(ocr, bgr).strip()
    if ocr_text:
        return ocr_text
    return text


def extract_pdf_text_hybrid(path: str) -> str:
    """打开 PDF，逐页合并文本（文字层 + 必要时整页 OCR）。"""
    doc = fitz.open(path)
    ocr: Any | None = None
    ocr_tried = False

    def get_ocr() -> Any | None:
        nonlocal ocr, ocr_tried
        if ocr_tried:
            return ocr
        ocr_tried = True
        try:
            from app.services.image_ingest import _get_paddle_ocr

            ocr = _get_paddle_ocr()
        except RuntimeError:
            logger.info(
                "未安装 PaddleOCR 可选依赖，PDF 仅使用文字层（扫描件可能几乎无字）。"
                "安装：uv sync --extra image"
            )
            ocr = None
        except Exception as e:  # noqa: BLE001
            logger.warning("初始化 PaddleOCR 失败，PDF 将仅使用文字层：%s", e)
            ocr = None
        return ocr

    try:
        parts: list[str] = []
        for page in doc:
            chunk = _page_text_or_ocr(page, get_ocr).strip()
            if chunk:
                parts.append(chunk)
        return "\n\n".join(parts).strip()
    finally:
        doc.close()
