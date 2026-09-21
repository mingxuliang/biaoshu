"""抽取是否够用：抽不到字就不能当已解析。"""

from __future__ import annotations

import re

_HANZI = re.compile(r"[\u4e00-\u9fff]")
_PLACEHOLDER = (
    "未能抽取",
    "仅存档",
    "请另存为",
    "未识别到文字",
    "未启用 OCR",
    "未能抽出文字",
    "该格式仅存档",
    "请先解压",
)

MIN_MAIN_HANZI = 800
DRAWING_SKIP = {"drawing"}


def hanzi_count(text: str) -> int:
    return len(_HANZI.findall(text or ""))


def is_placeholder(text: str) -> bool:
    raw = (text or "").strip()
    if not raw:
        return True
    if hanzi_count(raw) >= 80:
        return False
    return any(hint in raw for hint in _PLACEHOLDER)


def usable_hanzi(text: str) -> int:
    if is_placeholder(text):
        return 0
    return hanzi_count(text)


def merge_stats(parts: list[dict]) -> dict:
    ocr_pages = 0
    unpacked = 0
    pages = 0
    errors: list[str] = []
    slots: dict[str, int] = {}
    for part in parts:
        stats = part.get("stats") if isinstance(part.get("stats"), dict) else {}
        ocr_pages += int(stats.get("ocrPages") or 0)
        unpacked += int(stats.get("unpackedFiles") or 0)
        pages += int(stats.get("pages") or 0)
        kind = str(part.get("kind") or "main")
        slots[kind] = slots.get(kind, 0) + usable_hanzi(str(part.get("text") or ""))
        err = str(stats.get("error") or part.get("error") or "").strip()
        if err:
            errors.append(err)
    body = sum(n for k, n in slots.items() if k not in DRAWING_SKIP)
    return {
        "ocrPages": ocr_pages,
        "unpackedFiles": unpacked,
        "pages": pages,
        "usableHanzi": body,
        "slotHanzi": slots,
        "errors": errors,
    }


def parse_fail_reason(stats: dict, *, filled: int = 0, llm_error: str | None = None) -> str | None:
    """返回失败原因；None 表示可以标 done。"""
    usable = int(stats.get("usableHanzi") or 0)
    errors = [str(x) for x in (stats.get("errors") or []) if x]
    if usable < MIN_MAIN_HANZI:
        extra = "；".join(errors[:3])
        if extra:
            return f"招标正文抽取不足（有效汉字 {usable}，至少 {MIN_MAIN_HANZI}）。{extra}"
        return f"招标正文抽取不足（有效汉字 {usable}，至少 {MIN_MAIN_HANZI}）。扫描件请确认可复制文字或等待 OCR；压缩包请解压后按槽位上传"
    if llm_error and filled <= 0:
        return llm_error
    return None
