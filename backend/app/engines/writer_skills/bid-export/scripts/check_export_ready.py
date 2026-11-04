"""检查工作区是否有目录快照，不生成 Word。"""

from __future__ import annotations

from pathlib import Path


def main() -> int:
    outline = Path("outline.txt")
    if not outline.is_file() or not outline.read_text(encoding="utf-8", errors="ignore").strip():
        print("未就绪：工作区没有目录快照。请先 read_chapter 确认目录，再调用 export_draft_docx。")
        return 1
    print("目录快照已在工作区。请调用 export_draft_docx 生成 Word，不要手写 docx。")
    print(outline.read_text(encoding="utf-8", errors="ignore")[:2000])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
