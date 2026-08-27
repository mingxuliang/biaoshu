"""扫描件 OCR：识别真实像素文字，不编造证号或证书内容。

Tesseract 未安装或识别失败时返回空文本并标明原因，调用方不得用占位证号填补。
"""

from __future__ import annotations

import os

STATUS_OK = "ok"
STATUS_EMPTY = "empty"
STATUS_UNAVAILABLE = "unavailable"


def tesseract_ready() -> tuple[bool, str]:
    try:
        import pytesseract
        from PIL import Image  # noqa: F401
    except ImportError:
        return False, "未安装 OCR 依赖（pytesseract / Pillow）"
    try:
        pytesseract.get_tesseract_version()
    except Exception:
        return False, "容器内未安装 Tesseract OCR 引擎"
    return True, ""


def ocr_image_path(path: str) -> tuple[str, str]:
    ready, reason = tesseract_ready()
    if not ready:
        return "", STATUS_UNAVAILABLE if reason else STATUS_EMPTY
    try:
        import pytesseract
        from PIL import Image

        with Image.open(path) as img:
            text = pytesseract.image_to_string(img, lang="chi_sim+eng")
    except Exception:
        return "", STATUS_EMPTY
    cleaned = (text or "").strip()
    return cleaned, STATUS_OK if cleaned else STATUS_EMPTY


def ocr_image_bytes(data: bytes) -> tuple[str, str]:
    ready, _reason = tesseract_ready()
    if not ready:
        return "", STATUS_UNAVAILABLE
    try:
        import io

        import pytesseract
        from PIL import Image

        with Image.open(io.BytesIO(data)) as img:
            text = pytesseract.image_to_string(img, lang="chi_sim+eng")
    except Exception:
        return "", STATUS_EMPTY
    cleaned = (text or "").strip()
    return cleaned, STATUS_OK if cleaned else STATUS_EMPTY


def ocr_pdf_pages(path: str, max_pages: int = 8) -> tuple[str, str]:
    ready, _reason = tesseract_ready()
    if not ready:
        return "", STATUS_UNAVAILABLE
    try:
        import pytesseract
        import pymupdf as fitz
        from PIL import Image
    except ImportError:
        return "", STATUS_UNAVAILABLE

    texts: list[str] = []
    try:
        with fitz.open(path) as doc:
            for i, page in enumerate(doc):
                if i >= max_pages:
                    break
                pix = page.get_pixmap(matrix=fitz.Matrix(2, 2), alpha=False)
                img = Image.frombytes("RGB", (pix.width, pix.height), pix.samples)
                piece = pytesseract.image_to_string(img, lang="chi_sim+eng")
                if piece.strip():
                    texts.append(piece.strip())
    except Exception:
        return "", STATUS_EMPTY
    cleaned = "\n".join(texts).strip()
    return cleaned, STATUS_OK if cleaned else STATUS_EMPTY


def ocr_file(path: str) -> tuple[str, str]:
    if not path or not os.path.exists(path):
        return "", STATUS_EMPTY
    ext = os.path.splitext(path)[1].lower()
    if ext == ".pdf":
        native = ""
        try:
            import pymupdf as fitz

            with fitz.open(path) as doc:
                native = "\n".join(page.get_text("text") for page in doc).strip()
        except Exception:
            native = ""
        if len(native) >= 80:
            return native, STATUS_OK
        ocr_text, status = ocr_pdf_pages(path)
        if ocr_text:
            return ocr_text, status
        return native, STATUS_OK if native else status
    if ext in {".jpg", ".jpeg", ".png", ".webp", ".tif", ".tiff", ".bmp"}:
        return ocr_image_path(path)
    return "", STATUS_EMPTY
