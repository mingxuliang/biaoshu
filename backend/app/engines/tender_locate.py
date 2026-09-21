"""把解析页抽出的字段贴回招标原文：条款行 + 原文高亮框。"""

from __future__ import annotations

import re

_HANZI = re.compile(r"[\u4e00-\u9fff0-9A-Za-z]")
_SKIP = (
    "未从招标文件中抽取到该项内容",
    "招标文件未明确",
    "未抽取",
    "答疑补遗为准",
)
_CLAUSE = re.compile(r"^(\d+\.)+\d+")
_CHAPTER = re.compile(r"^第[0-9一二三四五六七八九十百零]+[章节篇]")
_PAREN = re.compile(r"[（(][^）)]{0,80}[）)]")


def compact(text: str) -> str:
    return "".join(_HANZI.findall(text or ""))


def _plain_value(text: str) -> str:
    raw = (text or "").strip()
    if raw.startswith("【答疑补遗为准】"):
        raw = raw[len("【答疑补遗为准】") :].strip()
    head = _PAREN.sub("", raw).strip()
    if not head:
        head = re.split(r"[（(]", raw, 1)[0].strip()
    return head or raw


def needles(text: str, label: str = "") -> list[str]:
    raw = (text or "").strip()
    if raw.startswith("【答疑补遗为准】"):
        raw = raw[len("【答疑补遗为准】") :].strip()
    if any(s in raw and len(raw) < 40 for s in _SKIP):
        return []
    label = (label or "").strip()
    cleaned = _plain_value(raw)
    lines = [ln.strip() for ln in re.split(r"[\n；;]+", raw) if ln.strip()]
    out: list[str] = []
    if label and cleaned:
        out.append(f"{label}：{cleaned[:48]}")
        out.append(f"{label}{cleaned[:48]}")
    if cleaned and cleaned != raw:
        out.append(cleaned[:48])
    if label and 2 <= len(label) <= 40:
        out.append(label)
    for line in lines[:12]:
        if any(s == line for s in _SKIP):
            continue
        piece = _plain_value(line) or line
        cjk = compact(piece)
        if len(cjk) >= 6:
            out.append(cjk[:18])
        if 4 <= len(piece) <= 80:
            out.append(piece[:80])
        quoted = re.findall(r"[「『“\"]([^」』”\"]{4,40})", line)
        out.extend(quoted)
    seen: set[str] = set()
    uniq: list[str] = []
    for item in sorted(out, key=lambda s: len(compact(s)), reverse=True):
        key = compact(item) or item
        if key in seen or len(key) < 2:
            continue
        seen.add(key)
        uniq.append(item)
        if len(uniq) >= 12:
            break
    return uniq


def _norm_rect(bbox: tuple[float, float, float, float], pw: float, ph: float) -> dict:
    x0, y0, x1, y1 = bbox
    return {
        "x": max(0.0, x0 / pw),
        "y": max(0.0, y0 / ph),
        "w": max(0.004, (x1 - x0) / pw),
        "h": max(0.008, (y1 - y0) / ph),
    }


def _union(boxes: list[tuple[float, float, float, float]]) -> tuple[float, float, float, float]:
    return (
        min(b[0] for b in boxes),
        min(b[1] for b in boxes),
        max(b[2] for b in boxes),
        max(b[3] for b in boxes),
    )


def _page_lines(page) -> list[dict]:
    data = page.get_text("dict") or {}
    lines: list[dict] = []
    for block in data.get("blocks") or []:
        for line in block.get("lines") or []:
            spans = [s for s in (line.get("spans") or []) if str(s.get("text") or "").strip()]
            if not spans:
                continue
            text = "".join(str(s.get("text") or "") for s in spans).strip()
            if not text:
                continue
            boxes = []
            for span in spans:
                bbox = span.get("bbox") or (0, 0, 0, 0)
                boxes.append((float(bbox[0]), float(bbox[1]), float(bbox[2]), float(bbox[3])))
            lines.append({"text": text, "compact": compact(text), "bbox": _union(boxes)})
    return lines


def _heading_near(lines: list[dict], idx: int) -> str:
    for j in range(idx, max(-1, idx - 12), -1):
        t = (lines[j].get("text") or "").strip()
        if _CHAPTER.match(t) and len(t) <= 48:
            return t
        if _CLAUSE.match(t) and len(t) <= 60:
            return t.split("：")[0].split(":")[0].strip()
    return ""


def _score_line(line: dict, keys: list[str], label_c: str, value_c: str) -> int:
    text = line["text"]
    blob = line["compact"]
    if not blob:
        return 0
    score = 0
    for key in keys:
        kc = compact(key)
        if len(kc) < 2:
            continue
        if blob == kc:
            score = max(score, 90)
        elif kc in blob:
            score = max(score, 40 + min(len(kc), 28))
        elif blob in kc and len(blob) >= 6:
            score = max(score, 18 + min(len(blob), 16))
    if value_c and len(value_c) >= 4:
        if value_c == blob:
            score += 36
        elif value_c in blob:
            score += 28
        elif blob in value_c and len(blob) >= 8:
            score += 10
    if label_c and label_c in blob:
        score += 26
        if "：" in text or ":" in text:
            score += 12
    if _CLAUSE.match(text):
        score += 20
    if _CHAPTER.match(text):
        score += 6
    if len(text) <= 72:
        score += 8
    elif len(text) > 180:
        score -= 12
    return score


def _merge_neighbor(lines: list[dict], idx: int, label_c: str, value_c: str) -> tuple[str, list[tuple[float, float, float, float]]]:
    chosen = [lines[idx]]
    cur = lines[idx]
    if label_c and label_c in cur["compact"] and value_c and value_c not in cur["compact"]:
        for nxt in lines[idx + 1 : idx + 3]:
            if value_c[:12] in nxt["compact"] or compact(nxt["text"][:20]) in value_c:
                chosen.append(nxt)
                break
    elif value_c and value_c in cur["compact"] and label_c and label_c not in cur["compact"]:
        for prev in reversed(lines[max(0, idx - 2) : idx]):
            if label_c in prev["compact"] or _CLAUSE.match(prev["text"]):
                chosen.insert(0, prev)
                break
    snippet = "".join(item["text"] for item in chosen)
    boxes = [item["bbox"] for item in chosen]
    return snippet[:80], boxes


def locate_in_pdf(path: str, query: str, label: str = "") -> dict:
    keys = needles(query, label)
    empty = {"found": False, "page": 0, "pageCount": 0, "snippet": "", "heading": "", "rects": []}
    if not keys:
        return empty
    import pymupdf as fitz

    label_c = compact(label)
    value_c = compact(_plain_value(query))
    best: dict | None = None
    with fitz.open(path) as pdf:
        total = int(pdf.page_count or 0)
        for i, page in enumerate(pdf, start=1):
            lines = _page_lines(page)
            pw = float(page.rect.width or 1)
            ph = float(page.rect.height or 1)
            for idx, line in enumerate(lines):
                score = _score_line(line, keys, label_c, value_c)
                if score < 28:
                    continue
                if best and score < int(best["score"]):
                    continue
                snippet, boxes = _merge_neighbor(lines, idx, label_c, value_c)
                heading = _heading_near(lines, idx)
                best = {
                    "score": score,
                    "page": i,
                    "pageCount": total,
                    "snippet": snippet or line["text"][:80],
                    "heading": heading,
                    "rects": [_norm_rect(b, pw, ph) for b in boxes[:8]],
                }
        if best and best["rects"]:
            return {
                "found": True,
                "page": best["page"],
                "pageCount": best["pageCount"],
                "snippet": best["snippet"],
                "heading": best["heading"],
                "rects": best["rects"],
            }
        return {**empty, "pageCount": total}


def pdf_paragraphs(path: str) -> list[dict]:
    import pymupdf as fitz

    out: list[dict] = []
    idx = 0
    with fitz.open(path) as pdf:
        for page_i, page in enumerate(pdf, start=1):
            for line in (page.get_text("text") or "").splitlines():
                line = line.strip()
                if not line:
                    continue
                out.append(
                    {
                        "index": idx,
                        "text": line,
                        "style": "",
                        "outline_level": None,
                        "page": page_i,
                    }
                )
                idx += 1
                if idx >= 8000:
                    return out
    return out
