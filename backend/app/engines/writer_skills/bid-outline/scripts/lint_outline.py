"""验收目录 Markdown：标题是否合格、当前分册的条目是否都有节点引用。不访问数据库。"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

from app.engines.e_writer import _business_volume_items
from app.engines.writer_harness import _bad_outline_headings
from app.engines.writer_tool_runtime import numbered_requirement_items, outline_cited_ids


def _read_markdown(argv: list[str]) -> str:
    if argv:
        path = Path(argv[0])
        if not path.is_file():
            return ""
        return path.read_text(encoding="utf-8", errors="ignore")
    return sys.stdin.read()


def _doc_kind(root: Path) -> str:
    marker = root / "doc_kind.txt"
    if not marker.is_file():
        return "tech"
    kind = marker.read_text(encoding="utf-8", errors="ignore").strip().lower()
    return kind if kind in ("tech", "business") else "tech"


def _uncited_items(markdown: str) -> list[str]:
    root = Path(os.environ.get("WRITER_WORKSPACE") or ".")
    cited = outline_cited_ids(markdown)
    missing = []
    if _doc_kind(root) == "business":
        business = root / "tender" / "business.txt"
        if not business.is_file():
            return []
        text = business.read_text(encoding="utf-8", errors="ignore")
        for item_id, _title, body in _business_volume_items(text):
            if item_id not in cited:
                missing.append(f"{item_id} 没有被任何标题引用：{body.strip()[:30]}")
        return missing
    tech = root / "tender" / "tech.txt"
    if not tech.is_file():
        return []
    text = tech.read_text(encoding="utf-8", errors="ignore")
    for item_id, item in numbered_requirement_items(text, "tech"):
        if item_id not in cited:
            missing.append(f"{item_id} 没有被任何标题引用：{item.strip()[:30]}")
    return missing


def _missing_composition(markdown: str) -> list[str]:
    """本份招标书规定的大章，在目录一级标题里找不到的列出来。"""
    from app.engines.e_writer import _is_same_large_chapter

    root = Path(os.environ.get("WRITER_WORKSPACE") or ".")
    path = root / "composition.txt"
    if not path.is_file():
        return []
    wanted = [line.strip() for line in path.read_text(encoding="utf-8", errors="ignore").splitlines() if line.strip()]
    tops = [line.lstrip("#").strip() for line in markdown.splitlines() if line.startswith("# ")]
    return [
        f"招标书规定的大章「{title}」没有对应的一级标题"
        for title in wanted
        if not any(_is_same_large_chapter(title, top) for top in tops)
    ]


def _duplicate_titles(markdown: str) -> list[str]:
    seen: dict[str, int] = {}
    for line in markdown.splitlines():
        stripped = line.strip()
        if stripped.startswith("#"):
            title = stripped.lstrip("#").strip()
            seen[title] = seen.get(title, 0) + 1
    return [f"标题「{title}」重复出现 {n} 次，同一条款只留一个章节" for title, n in seen.items() if n > 1][:10]


def main() -> int:
    markdown = _read_markdown(sys.argv[1:])
    if not markdown.strip():
        print(json.dumps({"ok": False, "problems": ["没有目录 Markdown"]}, ensure_ascii=False))
        return 1
    problems = _bad_outline_headings(markdown)
    problems.extend(_missing_composition(markdown))
    problems.extend(_duplicate_titles(markdown))
    problems.extend(_uncited_items(markdown))
    print(json.dumps({"ok": not problems, "problems": problems[:30]}, ensure_ascii=False))
    return 1 if problems else 0


if __name__ == "__main__":
    raise SystemExit(main())
