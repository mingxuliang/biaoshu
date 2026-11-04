---
name: bid-outline
description: 按本项目已抽出的技术标应答需求、商务标应答和投标文件格式要求编制或验收投标目录。目录标题必须是不超过12字的短名称，禁止把招标说明句当标题。
---

# 编目录

1. 先调用 `read_tender`，`section` 用 `format`、`tech`、`business` 分段阅读。需要定位条款时带上 `query`。
2. 目录骨架只来自格式要求；技术章下级只来自技术标应答需求；商务章和签字件只来自商务标应答，保持叶子。
3. 把目录 Markdown 写到工作区 `outline.md`，然后执行：

`run_skill_script` skill=`bid-outline` script=`lint_outline.py` args=`["outline.md"]`

4. 脚本报不合格标题时只重写目录，不要解释。不要调用浏览器，不要导出 Word。
