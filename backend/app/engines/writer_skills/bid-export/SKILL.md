---
name: bid-export
description: 把当前撰写草稿导出为 Word 投标书。必须调用 export_draft_docx，禁止手写 OOXML 或让脚本生成 .docx。
---

# 导出 Word

1. 用 `read_chapter` 确认目录和正文已在草稿中。
2. 执行 `run_skill_script` skill=`bid-export` script=`check_export_ready.py` 查看工作区目录快照。
3. 用户要求导出 Word 时必须调用 `export_draft_docx`。不要编写 docx、不要调用 Shell、不要把 Markdown 当成 Word 文件写入磁盘。
4. 导出成功后把文档名称转告用户，请其在撰写工作台下载。
