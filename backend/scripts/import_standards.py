"""把规范 PDF 目录按条导入规范库。已入库的同名文件会跳过。

在 backend 目录执行：

python scripts/import_standards.py "C:\\Users\\92109\\Desktop\\建筑行业标准\\JG标准原文PDF"
python scripts/import_standards.py "D:\\standards" --limit 5
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.db import SessionLocal
from app.engines.standard_ingest import import_folder


def main() -> None:
    parser = argparse.ArgumentParser(description="按条导入规范 PDF")
    parser.add_argument("folder", help="存放规范 PDF 的目录")
    parser.add_argument("--limit", type=int, default=0, help="只导入前 N 个文件，0 表示全部")
    args = parser.parse_args()
    with SessionLocal() as db:
        result = import_folder(db, args.folder, limit=args.limit)
    print(
        f"入库 {result['imported']} 本，跳过 {result['skipped']} 本，"
        f"未能抽出条文 {result['empty']} 本"
    )
    for reason in result["reasons"]:
        print(reason)


if __name__ == "__main__":
    main()
