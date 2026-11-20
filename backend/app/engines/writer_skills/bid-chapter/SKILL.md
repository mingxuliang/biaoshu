---
name: bid-chapter
description: 撰写或改写技术标章节。必须覆盖义务短标题和招标条款里的数字指标，引用已绑定产品；报价、承诺书、授权委托、偏差表等固定格式件禁止改写成技术方案。
---

# 写技术章

1. 用 `read_chapter` 看当前目录和正文。本章对应的招标条款在工作区 `requirement.txt`，需要核对更多上下文时用 `read_tender`：`section="original"` 读招标书原文，`section="tech"` 读技术标应答需求（每条带 T 编号），都可以加 `query`。
2. 把义务清单写成工作区 `obligations.json`：`{"obligations":[{"title":"短标题","text":"对应招标要求"}],"product_names":[],"require_gap":false}`。
3. 条款里的数字、期限、数量、版本（工作区 `facts.txt` 每行一项）必须在正文里逐项写出，并说明本方案如何满足；不能只复述标题。
4. 工作区 `response_rule.txt` 是本份招标书的应答规定原句。有内容时，解决方案照这句写，不要改成另一套格式。`response_checks.txt` 里的词必须出现在正文里。投标函、授权委托、证照和纯报价金额行不套这套写法；报价金额写「待填」。
5. 把待验收正文写成 `chapter.md`，然后执行：

`run_skill_script` skill=`bid-chapter` script=`check_coverage.py`

6. 脚本报缺标题、缺指标、缺应答写法或字数不足时只改正文，补齐后重新执行。报价和固定格式件若 `replace_chapter` 拒绝，不要强行改写。
7. 写之前先用 `match_standard_product` 查产品库有没有对应功能。有对应功能时，实现方式、参数和截图以库内应标原文为准，不要另编；没有对应功能才自己撰写，并如实写明依据，不编造认证、证书、专利和案例数量（正文里出现这些断言而资料里没有，验收会退回）。
   正文提到公司资质、同类项目业绩或人员时，先用 `match_qualification` 查资质证照库（只含已入库条目）。库里命中的才可以写，名称、证号、金额照抄库内字段；库里没有的不得编造，要空出并说明需用户补充资质信息。
8. 每写完一条台账要求，用 `record_response` 记下它的结论（满足、部分满足、不满足）、实现方式和偏离说明；需要看要求原文用 `read_ledger`。
9. 不要打开浏览器，不要手写 Word。
