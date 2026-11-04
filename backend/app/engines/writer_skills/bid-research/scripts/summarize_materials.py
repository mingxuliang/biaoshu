"""汇总工作区 materials/ 已保存的取材，不访问网络。"""

from __future__ import annotations

from pathlib import Path


def main() -> int:
    folder = Path("materials")
    if not folder.is_dir():
        print("暂无取材")
        return 0
    files = sorted(folder.glob("*.txt"))
    if not files:
        print("暂无取材")
        return 0
    chunks: list[str] = []
    for path in files[:20]:
        text = path.read_text(encoding="utf-8", errors="ignore")[:800]
        chunks.append(f"## {path.name}\n{text}")
    print("\n\n".join(chunks))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
