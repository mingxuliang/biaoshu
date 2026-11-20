"""验收技术章是否覆盖义务标题，不访问数据库。"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from app.engines.writer_harness import _coverage_problems


def main() -> int:
    payload_path = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("obligations.json")
    chapter_path = Path(sys.argv[2]) if len(sys.argv) > 2 else Path("chapter.md")
    if not payload_path.is_file():
        print(json.dumps({"ok": False, "problems": ["没有 obligations.json"]}, ensure_ascii=False))
        return 1
    try:
        data = json.loads(payload_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        print(json.dumps({"ok": False, "problems": ["obligations.json 无法解析"]}, ensure_ascii=False))
        return 1
    if not isinstance(data, dict):
        print(json.dumps({"ok": False, "problems": ["obligations.json 不是对象"]}, ensure_ascii=False))
        return 1
    obligations = [item for item in (data.get("obligations") or []) if isinstance(item, dict)]
    names = [str(name) for name in (data.get("product_names") or []) if str(name).strip()]
    require_gap = bool(data.get("require_gap"))
    solution = chapter_path.read_text(encoding="utf-8", errors="ignore") if chapter_path.is_file() else ""
    facts_path = Path("facts.txt")
    facts = [line.strip() for line in facts_path.read_text(encoding="utf-8").splitlines() if line.strip()] if facts_path.is_file() else []
    min_path = Path("min_chars.txt")
    try:
        min_chars = int(min_path.read_text(encoding="utf-8").strip() or 0) if min_path.is_file() else 0
    except ValueError:
        min_chars = 0
    checks_path = Path("response_checks.txt")
    marks = (
        [line.strip() for line in checks_path.read_text(encoding="utf-8").splitlines() if line.strip()]
        if checks_path.is_file()
        else []
    )
    problems = _coverage_problems(obligations, solution, names, require_gap, facts, min_chars, marks)
    print(json.dumps({"ok": not problems, "problems": problems[:20]}, ensure_ascii=False))
    return 1 if problems else 0


if __name__ == "__main__":
    raise SystemExit(main())
