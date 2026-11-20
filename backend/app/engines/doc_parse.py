"""三库共用的 PDF 解析路由。

有文字层的页直接用 PyMuPDF；无文字层（扫描、拍照）的页交给硅基流动的 Qwen3-VL-8B，
未配置或调用失败时回退 Tesseract。docx 不经过这里，仍走 python-docx。
"""

from __future__ import annotations

import logging
from typing import Any

import httpx

from ..config import get_settings

log = logging.getLogger(__name__)

SOURCE_TEXT = "text"
SOURCE_MINERU = "mineru"
SOURCE_VL = "vl"
SOURCE_OCR = "ocr"
SCAN_VL_API = "Qwen/Qwen3-VL-8B-Instruct"
_SCAN_PROMPT = "把这页扫描件里的文字逐字转写出来。保留条号、标题和表格中的文字。不要解释，不要补写图上没有的内容。"

# 少于这么多字符视为无文字层
MIN_TEXT_CHARS = 20
MAX_SCAN_PAGES = 60


def mineru_enabled() -> bool:
    return bool((get_settings().mineru_url or "").strip())


def _find_markdown(payload: Any) -> str:
    """取出 Markdown 正文。新版结果把正文放在 files[].content.markdown，旁边还有任务号等字符串，不能把任意字符串当成正文。"""
    if isinstance(payload, dict):
        for key in ("md_content", "markdown", "md"):
            value = payload.get(key)
            if isinstance(value, str) and value.strip():
                return value
            if isinstance(value, (dict, list)):
                found = _find_markdown(value)
                if found:
                    return found
        chunks: list[str] = []
        for key, value in payload.items():
            if key in {"md_content", "markdown", "md"} or not isinstance(value, (dict, list)):
                continue
            found = _find_markdown(value)
            if found:
                chunks.append(found)
        return "\n".join(chunks)
    if isinstance(payload, list):
        chunks = []
        for value in payload:
            found = _find_markdown(value)
            if found:
                chunks.append(found)
        return "\n".join(chunks)
    return ""


# 整本扫描件一次提交。内联 base64 只有约 1MB，不能用来传规范 PDF。
_MINERU_WAIT = 3600
_MINERU_FAIL = {"failed", "error", "canceled", "cancelled"}
_MINERU_DONE = {"succeeded", "success", "completed", "done", "finished"}


def mineru_markdown(
    pdf_bytes: bytes,
    filename: str = "page.pdf",
    *,
    request_id: str = "",
    on_ticket: Any = None,
) -> str:
    """把整份 PDF 用 multipart 交给 MinerU。失败返回空串，不使用 base64 内联。"""
    settings = get_settings()
    base = (settings.mineru_url or "").strip().rstrip("/")
    if not base or not pdf_bytes:
        return ""
    timeout = httpx.Timeout(_MINERU_WAIT + 60, connect=10.0)
    text, task, outcome = _mineru_submit(
        base, pdf_bytes, filename or "standard.pdf", request_id, timeout, settings
    )
    if task and on_ticket is not None and outcome in {"ok", "pending"}:
        try:
            on_ticket(task)
        except Exception:
            log.warning("MinerU 任务号未写入进度", exc_info=True)
    if text:
        return text
    if outcome == "pending" and task:
        return mineru_fetch(task, base=base)
    return ""


def mineru_fetch(request_id: str, *, base: str = "", timeout: float | None = None) -> str:
    """按任务号取回已提交的整本结果。任务不存在时尽快返回空串，方便重新提交。"""
    import time

    ticket = (request_id or "").strip()
    root = (base or (get_settings().mineru_url or "")).strip().rstrip("/")
    if not ticket or not root:
        return ""
    wait = _MINERU_WAIT if timeout is None else max(0.0, float(timeout))
    deadline = time.time() + wait
    misses = 0
    finished_without_text = 0
    while time.time() < deadline:
        saw = False
        failed = False
        finished = False
        for path in (
            f"/v1/file_parse/{ticket}/result",
            f"/v1/file_parse/{ticket}",
            f"/v1/tasks/{ticket}/result",
            f"/v1/tasks/{ticket}",
            f"/v1/parse/jobs/{ticket}",
        ):
            try:
                got = httpx.get(root + path, timeout=60)
            except httpx.HTTPError:
                continue
            if got.status_code == 404:
                continue
            saw = True
            if got.status_code >= 400:
                continue
            text, state = _mineru_body(got)
            if text:
                return text
            if state in _MINERU_FAIL:
                failed = True
            elif state in _MINERU_DONE:
                finished = True
        if failed:
            return ""
        if finished:
            finished_without_text += 1
            if finished_without_text >= 3:
                return ""
        else:
            finished_without_text = 0
        if not saw:
            misses += 1
            if misses >= 6:
                return ""
        else:
            misses = 0
        time.sleep(5)
    return ""


def _mineru_submit(
    base: str,
    pdf_bytes: bytes,
    filename: str,
    ticket: str,
    timeout: httpx.Timeout,
    settings: Any,
) -> tuple[str, str, str]:
    """先试旧的 /file_parse，404 再把整本文件上传到 /v1/file_parse。返回 (正文, 任务号, 状态)。"""
    legacy = _mineru_post(
        f"{base}/file_parse",
        pdf_bytes,
        filename,
        ticket,
        timeout,
        field="files",
        data={
            "backend": settings.mineru_backend or "pipeline",
            "lang_list": "ch",
            "return_md": "true",
            "formula_enable": "false",
            "request_id": ticket,
        },
    )
    if legacy[2] != "missing":
        return legacy
    uploaded = _mineru_post(
        f"{base}/v1/file_parse",
        pdf_bytes,
        filename,
        ticket,
        timeout,
        field="files",
        params=_mineru_v1_params(),
    )
    if uploaded[2] == "retry-file":
        return _mineru_post(
            f"{base}/v1/file_parse",
            pdf_bytes,
            filename,
            ticket,
            timeout,
            field="file",
            params=_mineru_v1_params(),
        )
    return uploaded


def _mineru_v1_params() -> list[tuple[str, str]]:
    # 这台 MinerU 4.0.12 不接受 request_id，任务号在 202 响应里返回。
    return [
        ("ocr_mode", "ocr"),
        ("tier", "basic"),
        ("output_formats", "markdown"),
        ("wait_timeout", str(_MINERU_WAIT)),
    ]


def _mineru_post(
    url: str,
    pdf_bytes: bytes,
    filename: str,
    ticket: str,
    timeout: httpx.Timeout,
    *,
    field: str,
    data: dict | None = None,
    params: list[tuple[str, str]] | None = None,
) -> tuple[str, str, str]:
    try:
        resp = httpx.post(
            url,
            params=params,
            data=data,
            files={field: (filename, pdf_bytes, "application/pdf")},
            timeout=timeout,
        )
    except httpx.TimeoutException:
        log.warning("MinerU 等待超时：%s", url)
        return "", "", "timeout"
    except httpx.HTTPError as exc:
        log.warning("MinerU 调用失败：%s", exc)
        return "", ticket, "error"
    if resp.status_code == 404:
        return "", ticket, "missing"
    if (
        field == "files"
        and resp.status_code in {400, 422}
        and "missing" in (resp.text or "")
        and '"files"' in (resp.text or "")
    ):
        log.warning("MinerU 不接受 files 字段：%s %s", resp.status_code, (resp.text or "")[:180])
        return "", "", "retry-file"
    if resp.status_code >= 400:
        log.warning("MinerU 返回 %s %s", resp.status_code, (resp.text or "")[:300])
        return "", ticket, "error"
    text, state = _mineru_body(resp)
    task = _mineru_task_id(resp, ticket)
    if text:
        return text, task, "ok"
    if state in _MINERU_FAIL:
        return "", task, "error"
    if resp.status_code == 202 or state not in _MINERU_DONE:
        return "", task, "pending"
    return "", task, "error"


def _mineru_task_id(resp: httpx.Response, fallback: str) -> str:
    try:
        payload = resp.json()
    except ValueError:
        return fallback
    return _task_id_from(payload, fallback)


def _task_id_from(payload: Any, fallback: str) -> str:
    if not isinstance(payload, dict):
        return fallback
    for key in ("request_id", "task_id", "job_id", "id"):
        value = payload.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    data = payload.get("data")
    if isinstance(data, dict):
        found = _task_id_from(data, "")
        if found:
            return found
    return fallback


def _mineru_body(resp: httpx.Response) -> tuple[str, str]:
    """返回 (markdown, 任务状态)。zip 里只取正文文件。"""
    ctype = (resp.headers.get("content-type") or "").lower()
    raw = resp.content or b""
    if "zip" in ctype or raw[:2] == b"PK":
        return _zip_markdown(raw), ""
    payload: Any = None
    if "json" in ctype or raw[:1] in {b"{", b"["}:
        try:
            payload = resp.json()
        except ValueError:
            payload = None
    if payload is not None:
        state = ""
        if isinstance(payload, dict):
            state = str(payload.get("status") or payload.get("state") or "").lower()
            data = payload.get("data")
            if not state and isinstance(data, dict):
                state = str(data.get("status") or data.get("state") or "").lower()
        return _find_markdown(payload).strip(), state
    if "markdown" in ctype or ctype.startswith("text/"):
        return (resp.text or "").strip(), ""
    return "", ""


def _zip_markdown(raw: bytes) -> str:
    import io
    import zipfile

    try:
        with zipfile.ZipFile(io.BytesIO(raw)) as archive:
            names = [name for name in archive.namelist() if name.lower().endswith(".md")]
            if not names:
                return ""
            names.sort(key=lambda name: archive.getinfo(name).file_size, reverse=True)
            return archive.read(names[0]).decode("utf-8", errors="ignore").strip()
    except (zipfile.BadZipFile, OSError, KeyError):
        return ""


def _single_page_pdf(doc: Any, index: int) -> bytes:
    import pymupdf as fitz

    out = fitz.open()
    try:
        out.insert_pdf(doc, from_page=index, to_page=index)
        return out.tobytes()
    finally:
        out.close()


def _tesseract_page(page: Any) -> str:
    import pymupdf as fitz

    from .ocr import ocr_pixmap

    try:
        pix = page.get_pixmap(matrix=fitz.Matrix(2, 2), alpha=False)
    except Exception:
        return ""
    text, _status = ocr_pixmap(pix)
    return text


def page_jpeg(page: Any) -> bytes:
    """把一页收成适合识图小模型的 JPEG，长边不超过 1600。"""
    import pymupdf as fitz

    zoom = 1.7
    rect = page.rect
    longest = max(float(rect.width), float(rect.height)) or 1.0
    if longest * zoom > 1600:
        zoom = 1600 / longest
    try:
        pix = page.get_pixmap(matrix=fitz.Matrix(zoom, zoom), alpha=False)
    except Exception:
        return b""
    return pix.tobytes("jpeg")


def _scan_model_id() -> str | None:
    """使用已配置的硅基密钥调用便宜的 8B 识图模型，不改撰写默认模型。"""
    from ..db import platform_session
    from ..llm_catalog import ensure_siliconflow_scan_model
    from ..models import LlmModel

    db = platform_session()
    try:
        ensure_siliconflow_scan_model(db)
        row = (
            db.query(LlmModel)
            .filter(LlmModel.api_model == SCAN_VL_API, LlmModel.enabled.is_(True))
            .order_by(LlmModel.sort_order.asc())
            .first()
        )
        return row.id if row is not None else None
    except Exception:
        log.warning("未找到硅基识图模型", exc_info=True)
        return None
    finally:
        db.close()


def read_scan_page(jpeg: bytes) -> str:
    """用硅基 Qwen3-VL-8B 读一页扫描图。未配置或调用失败时返回空串。"""
    if not jpeg:
        return ""
    model_id = _scan_model_id()
    if not model_id:
        return ""
    import base64

    from .llm import chat_complete

    url = "data:image/jpeg;base64," + base64.b64encode(jpeg).decode("ascii")
    try:
        return chat_complete(
            model_id=model_id,
            messages=[
                {
                    "role": "user",
                    "content": [
                        {"type": "image_url", "image_url": {"url": url}},
                        {"type": "text", "text": _SCAN_PROMPT},
                    ],
                }
            ],
            temperature=0,
            timeout=120,
            max_tokens=4096,
        ).strip()
    except Exception as exc:  # noqa: BLE001 —— 单页识图失败（超时、限流、返回格式异常）不能把整份文档的解析拖死，跳过这页继续
        log.warning("扫描页识图失败：%s", exc)
        return ""


def scan_page_text(doc: Any, index: int) -> tuple[str, str]:
    """无文字层页的识别：硅基 8B 识图优先，Tesseract 兜底。返回 (文本, 来源)。"""
    try:
        text = read_scan_page(page_jpeg(doc[index])).strip()
    except Exception:
        text = ""
    if len(text) >= MIN_TEXT_CHARS:
        return text, SOURCE_VL
    text = _tesseract_page(doc[index]).strip()
    return (text, SOURCE_OCR) if text else ("", "")


def extract_pdf_pages(path: str, *, max_scan_pages: int = MAX_SCAN_PAGES) -> list[dict]:
    """逐页返回 {page, text, source}。扫描页超过上限后不再识别，text 为空。"""
    import pymupdf as fitz

    pages: list[dict] = []
    scanned = 0
    with fitz.open(path) as doc:
        for index, page in enumerate(doc):
            text = (page.get_text("text") or "").strip()
            source = SOURCE_TEXT
            if len(text) < MIN_TEXT_CHARS:
                if scanned < max_scan_pages:
                    scanned += 1
                    text, source = scan_page_text(doc, index)
                else:
                    text, source = "", ""
            pages.append({"page": index + 1, "text": text, "source": source})
    return pages


def page_text(doc: Any, index: int) -> tuple[str, str]:
    """单页版本，给已经打开 PDF 自己遍历的调用方用。"""
    page = doc[index]
    text = (page.get_text("text") or "").strip()
    if len(text) >= MIN_TEXT_CHARS:
        return text, SOURCE_TEXT
    return scan_page_text(doc, index)


def extract_pdf_text(path: str) -> str:
    """整篇文本。有文字层的页直接读取，扫描页交给硅基 8B 识图。"""
    return "\n".join(p["text"] for p in extract_pdf_pages(path) if p["text"])
