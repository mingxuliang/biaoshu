---
name: bid-chapter
description: 撰写或改写技术标章节。必须覆盖义务短标题，引用已绑定产品；报价、承诺书、授权委托、偏差表等固定格式件禁止改写成技术方案。
---

# 写技术章

1. 用 `read_chapter` 看当前目录和正文。需要招标原文时用 `read_tender`，`section=tech`，必要时加 `query`。
2. 把义务清单写成工作区 `obligations.json`：`{"obligations":[{"title":"短标题","text":"对应招标要求"}],"product_names":[],"require_gap":false}`。
3. 把待验收正文写成 `chapter.md`，然后执行：

`run_skill_script` skill=`bid-chapter` script=`check_coverage.py`

4. 脚本报缺标题时只改技术章正文。报价和固定格式件若 `replace_chapter` 拒绝，不要强行改写。
5. 不要打开浏览器，不要手写 Word。
