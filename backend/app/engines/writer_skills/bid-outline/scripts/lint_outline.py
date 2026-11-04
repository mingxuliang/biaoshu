"""验收目录 Markdown 标题，不访问数据库。"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from app.engines.writer_harness import _bad_outline_headings


def _read_markdown(argv: list[str]) -> str:
    if argv:
        path = Path(argv[0])
        if not path.is_file():
            return ""
        return path.read_text(encoding="utf-8", errors="ignore")
    return sys.stdin.read()


def main() -> int:
    markdown = _read_markdown(sys.argv[1:])
    if not markdown.strip():
        print(json.dumps({"ok": False, "problems": ["没有目录 Markdown"]}, ensure_ascii=False))
        return 1
    problems = _bad_outline_headings(markdown)
    print(json.dumps({"ok": not problems, "problems": problems[:20]}, ensure_ascii=False))
    return 1 if problems else 0


if __name__ == "__main__":
    raise SystemExit(main())
