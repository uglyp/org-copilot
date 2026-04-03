"""
知识库图片：校验格式 → PaddleOCR 抽中文/英文 → canonical 文本 + extra_json。

扫描类 PDF 在 `pdf_extract` 中渲染页面后复用同一套 PaddleOCR（见 `extract_pdf_text_hybrid`）。

未安装 `image` 可选依赖时，`ocr_image_to_canonical` 会抛出带说明的 `RuntimeError`；
PDF 仍可抽文字层，但扫描页几乎无字时需安装 `uv sync --extra image`。
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

IMAGE_SUFFIXES = frozenset({".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp"})


def is_image_extension(suffix: str) -> bool:
    s = suffix.strip().lower()
    if not s.startswith("."):
        s = f".{s}"
    return s in IMAGE_SUFFIXES


def is_image_path(path: str) -> bool:
    return Path(path).suffix.lower() in IMAGE_SUFFIXES


def verify_image_file(path: str) -> None:
    """打开并解码，确保为有效光栅图。"""
    from PIL import Image, UnidentifiedImageError

    try:
        with Image.open(path) as im:
            im.load()
    except UnidentifiedImageError as e:
        raise ValueError("无法识别为图片格式") from e
    except OSError as e:
        raise ValueError(f"图片读取失败: {e}") from e


_ocr_singleton: Any = None


def _get_paddle_ocr() -> Any:
    global _ocr_singleton
    if _ocr_singleton is not None:
        return _ocr_singleton
    try:
        from paddleocr import PaddleOCR
    except ImportError as e:
        raise RuntimeError(
            "图像 OCR 需要安装可选依赖：在 backend 目录执行 uv sync --extra image "
            "（或 pip install paddlepaddle paddleocr；macOS/ARM 请参考 Paddle 官方安装说明）"
        ) from e
    _ocr_singleton = PaddleOCR(use_angle_cls=True, lang="ch", show_log=False)
    return _ocr_singleton


def ocr_image_to_canonical(storage_path: str, *, filename: str) -> tuple[str, dict[str, Any]]:
    """对本地图片做 OCR，返回 (canonical 文本, 写入 Chunk.extra_json 的元数据)。"""
    verify_image_file(storage_path)
    ocr = _get_paddle_ocr()
    result = ocr.ocr(storage_path, cls=True)
    lines: list[str] = []
    if result and result[0]:
        for line in result[0]:
            if line and len(line) >= 2 and line[1]:
                text_part = line[1][0]
                if text_part:
                    lines.append(str(text_part))
    text = "\n".join(lines).strip()
    if not text:
        raise ValueError("OCR 未识别到文字，请换清晰截图或含文字的图片重试")

    extra: dict[str, Any] = {
        "ocr_engine": "paddleocr",
        "line_count": len(lines),
        "source_filename": filename,
        "caption": None,
    }
    header = f"[图片: {filename}]\n"
    canonical = header + text
    return canonical, extra
