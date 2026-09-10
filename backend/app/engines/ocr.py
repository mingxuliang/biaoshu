"""扫描件 OCR：识别真实像素文字，不编造证号或证书内容。

Tesseract 未安装或识别失败时返回空文本并标明原因，调用方不得用占位证号填补。
"""

from __future__ import annotations

import io
import os
from typing import Any

STATUS_OK = "ok"
STATUS_EMPTY = "empty"
STATUS_UNAVAILABLE = "unavailable"

# 施工图图签通常在右下角。
TITLE_BLOCK_BOX = (0.70, 0.72, 1.0, 1.0)


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


def _ocr_pil(img: Any, *, lang: str = "chi_sim+eng") -> tuple[str, str]:
    ready, reason = tesseract_ready()
    if not ready:
        return "", STATUS_UNAVAILABLE if reason else STATUS_EMPTY
    try:
        import pytesseract

        text = pytesseract.image_to_string(img, lang=lang)
    except Exception:
        return "", STATUS_EMPTY
    cleaned = (text or "").strip()
    return cleaned, STATUS_OK if cleaned else STATUS_EMPTY


def fit_image(img: Any, max_side: int = 1600) -> Any:
    w, h = img.size
    longest = max(w, h)
    if longest <= max_side or max_side <= 0:
        return img
    scale = max_side / float(longest)
    nw = max(1, int(w * scale))
    nh = max(1, int(h * scale))
    return img.resize((nw, nh))


def image_to_jpeg_bytes(img: Any, *, quality: int = 85, max_side: int = 1600) -> bytes:
    fitted = fit_image(img, max_side=max_side)
    if fitted.mode not in ("RGB", "L"):
        fitted = fitted.convert("RGB")
    elif fitted.mode == "L":
        fitted = fitted.convert("RGB")
    buf = io.BytesIO()
    fitted.save(buf, format="JPEG", quality=quality, optimize=True)
    return buf.getvalue()


def crop_box(img: Any, box: tuple[float, float, float, float] = TITLE_BLOCK_BOX) -> Any:
    w, h = img.size
    left, top, right, bottom = box
    x0 = int(max(0.0, min(1.0, left)) * w)
    y0 = int(max(0.0, min(1.0, top)) * h)
    x1 = int(max(0.0, min(1.0, right)) * w)
    y1 = int(max(0.0, min(1.0, bottom)) * h)
    if x1 <= x0 or y1 <= y0:
        return img
    return img.crop((x0, y0, x1, y1))


def pixmap_to_image(pix: Any):
    from PIL import Image

    return Image.frombytes("RGB", (pix.width, pix.height), pix.samples)


def raster_pdf_page(path: str, page_index: int, *, zoom: float = 1.6) -> Any | None:
    try:
        import pymupdf as fitz
    except ImportError:
        return None
    try:
        with fitz.open(path) as doc:
            if page_index < 0 or page_index >= len(doc):
                return None
            pix = doc[page_index].get_pixmap(matrix=fitz.Matrix(zoom, zoom), alpha=False)
            return pixmap_to_image(pix)
    except Exception:
        return None


def pdf_page_count(path: str) -> int:
    try:
        import pymupdf as fitz

        with fitz.open(path) as doc:
            return len(doc)
    except Exception:
        return 0


def pdf_page_native_text(path: str, page_index: int) -> str:
    try:
        import pymupdf as fitz

        with fitz.open(path) as doc:
            if page_index < 0 or page_index >= len(doc):
                return ""
            return (doc[page_index].get_text("text") or "").strip()
    except Exception:
        return ""


def load_image_file(path: str) -> Any | None:
    try:
        from PIL import Image

        img = Image.open(path)
        img.load()
        if img.mode not in ("RGB", "L"):
            img = img.convert("RGB")
        return img
    except Exception:
        return None


def ocr_pil_image(img: Any) -> tuple[str, str]:
    return _ocr_pil(img)


def ocr_region(img: Any, box: tuple[float, float, float, float] = TITLE_BLOCK_BOX) -> tuple[str, str]:
    if img is None:
        return "", STATUS_EMPTY
    return _ocr_pil(crop_box(img, box))


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
