"""按扩展名选择解析器：PDF 用 PyMuPDF 文字层 + 可选整页 OCR，其余按 UTF-8 读文本（非法字节忽略）。"""

from pathlib import Path

from app.services.pdf_extract import extract_pdf_text_hybrid


def extract_text_from_file(path: str) -> str:
    p = Path(path)
    suf = p.suffix.lower()
    if suf == ".pdf":
        return extract_pdf_text_hybrid(path)
    return p.read_text(encoding="utf-8", errors="ignore")
