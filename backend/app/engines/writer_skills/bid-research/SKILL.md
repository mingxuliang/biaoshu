---
name: bid-research
description: 用受限浏览器搜集标书素材（规范、公告、公开参数）。先取材保存，再决定是否写入技术章。不要把网上内容写进报价或固定格式件。
---

# 搜集素材

1. 只在用户明确要求查网上资料、规范或采购公告时使用。
2. `collect_material`：`action=search` 加 `query`，或 `action=fetch` 加白名单 `url`。`action=list` 查看已保存文件，`action=read` 加文件名阅读。
3. 取材完成后可执行：

`run_skill_script` skill=`bid-research` script=`summarize_materials.py`

4. 只有与当前技术章相关、且不编造资质参数的内容，才用 `replace_chapter` 写回。浏览器不可用时据实说明，不要假装查过网。
