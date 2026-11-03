"""把已完成的 AI 预审运行导出为可读 Word 报告。"""

from __future__ import annotations

import io
from datetime import datetime

import docx
from docx.enum.text import WD_ALIGN_PARAGRAPH

from .excerpt_guard import chapter_from_location, display_rule, split_bid_and_tender


def review_run_to_docx(
    *,
    project_name: str,
    project_code: str,
    round_no: int,
    light: str,
    waste: int,
    risk: int,
    suggest: int,
    levels: list[dict],
    dimensions: list[dict],
    issues: list[dict],
    tech_modules: list[dict] | None = None,
    custom_rules: list[dict] | None = None,
    standard_review: dict | None = None,
    finished_at: datetime | None = None,
    scope: str = "full",
) -> bytes:
    document = docx.Document()
    titles = {
        "business": "商务标预审报告",
        "tech": "技术标预审报告",
        "full": "分册预审报告",
    }
    title_text = titles.get(scope) or "分册预审报告"
    title = document.add_heading(title_text, 0)
    title.alignment = WD_ALIGN_PARAGRAPH.CENTER

    when = finished_at.strftime("%Y-%m-%d %H:%M") if finished_at else "—"
    method = {
        "business": "商务标分册预审（L1 否决 + L2 商务客观核验，均为定性等级）",
        "tech": "技术标分册预审（L3 五维 + L4 查重 + L5 版式，均为定性等级）",
        "full": "请分别查看商务标与技术标报告，两册各自评审、互不混算",
    }.get(scope) or "分册预审"
    scope_label = {"business": "商务标", "tech": "技术标", "full": "分册"}.get(scope) or scope
    meta = document.add_paragraph()
    meta.add_run(f"项目：{project_name or '（未命名）'}\n")
    meta.add_run(f"招标编号：{project_code or '—'}\n")
    meta.add_run(f"预审分册：{scope_label}\n")
    meta.add_run(f"预审轮次：第 {round_no} 轮\n")
    meta.add_run(f"生成时间：{when}\n")
    meta.add_run(f"预审方法：{method}")

    document.add_heading("一、本册评审结论与分层等级", level=1)
    score_label = {"business": "商务标", "tech": "技术标"}.get(scope) or "本册"
    document.add_paragraph(
        f"风险灯：{light or '—'}　　废标 {waste} 项　　扣分/降档 {risk} 项　　建议 {suggest} 项"
    )

    for level in levels or []:
        name = level.get("name") or level.get("key") or "—"
        grade = level.get("grade", "—")
        issues_n = level.get("issues", 0)
        status = level.get("status") or ""
        desc = level.get("desc") or ""
        key = level.get("key") or ""
        line = document.add_paragraph()
        line.add_run(f"{key} {name}：等级 {grade}，{issues_n} 项问题，结论 {status}").bold = True
        if desc:
            document.add_paragraph(f"审查内容：{desc}")

    heading_n = 2
    if scope != "business" and (dimensions or tech_modules):
        document.add_heading("二、技术标五维评审", level=1)
        heading_n = 3
        if not dimensions:
            document.add_paragraph("本册未做五维评审。")
        for dim in dimensions or []:
            document.add_paragraph(
                f"{dim.get('name') or '—'}：等级 {dim.get('grade', '—')} / 权重 {dim.get('weight', '—')}%"
            )

        if tech_modules:
            document.add_heading("三、技术评分模块核验", level=1)
            heading_n = 4
            for m in tech_modules:
                module = m.get("module") or m.get("key") or "—"
                grade = m.get("grade", "—")
                status = m.get("status") or "—"
                line = document.add_paragraph()
                line.add_run(f"{module}：等级 {grade}，{status}").bold = True
                summary = (m.get("summary") or "").strip()
                if summary:
                    document.add_paragraph(summary)

    points = (standard_review or {}).get("points") if isinstance(standard_review, dict) else None
    if points:
        heading_n += 1
        document.add_heading("规范对标", level=1)
        note = str((standard_review or {}).get("note") or "")
        specialty = str((standard_review or {}).get("specialty") or "通用")
        document.add_paragraph(f"专业：{specialty}。{note}")
        grouped = {"招标书": [], "图纸": [], "清单": []}
        for point in points:
            if not isinstance(point, dict):
                continue
            source = str(point.get("source") or "")
            if source in {"招标书", "评分"}:
                grouped["招标书"].append(point)
            elif source == "图纸":
                grouped["图纸"].append(point)
            else:
                grouped["清单"].append(point)
        sections = (("招标书规则", grouped["招标书"]),)
        if scope != "business":
            sections = sections + (("图纸", grouped["图纸"]), ("清单", grouped["清单"]))
        for title, rows in sections:
            document.add_heading(title, level=2)
            if not rows:
                document.add_paragraph("这一类没有查核点。")
                continue
            chunks = [rows]
            labels = [""]
            if title == "招标书规则":
                def booklet_of(row: dict) -> str:
                    booklet = str(row.get("booklet") or "")
                    if booklet in {"技术标", "商务标"}:
                        return booklet
                    blob = f"{row.get('name') or ''}{row.get('detail') or ''}"
                    if any(word in blob for word in ("报价", "价格", "商务", "资信", "业绩", "信用", "资格", "投标函")):
                        return "商务标"
                    return "技术标"

                tech_rows = [row for row in rows if booklet_of(row) == "技术标"]
                biz_rows = [row for row in rows if booklet_of(row) == "商务标"]
                if scope == "tech":
                    chunks, labels = [tech_rows], ["技术标"]
                elif scope == "business":
                    chunks, labels = [biz_rows], ["商务标"]
                else:
                    chunks, labels = [tech_rows, biz_rows], ["技术标", "商务标"]
            for label, chunk in zip(labels, chunks):
                if label:
                    document.add_heading(label, level=3)
                if not chunk:
                    document.add_paragraph("这一类没有查核点。")
                    continue
                for point in chunk:
                    name = point.get("name") or "—"
                    verdict = point.get("verdict") or "—"
                    line = document.add_paragraph()
                    if point.get("score") is not None:
                        score_text = f"{point.get('grade') or ''} {point.get('score')} / {point.get('maxScore') or 100} 分".strip()
                        if point.get("weight"):
                            score_text += f"（权重 {point.get('weight')}"
                            if point.get("weightedScore") is not None:
                                score_text += f"，折合 {point.get('weightedScore')} 分"
                            score_text += "）"
                        line.add_run(f"{name}：{score_text}").bold = True
                    else:
                        line.add_run(f"{name}：{point.get('grade') or verdict}").bold = True
                    if point.get("scoreRule"):
                        document.add_paragraph(f"评分规则：{point.get('scoreRule')}")
                    for row in point.get("checks") or []:
                        if not isinstance(row, dict):
                            continue
                        document.add_paragraph(f"对标：{row.get('item') or ''}（{row.get('result') or ''}）")
                        if row.get("bid"):
                            document.add_paragraph(f"投标书原文：{row.get('bid')}")
                    if point.get("strengths"):
                        document.add_paragraph(f"好的地方：{point.get('strengths')}")
                    if point.get("revisions"):
                        document.add_paragraph(f"需要修改：{point.get('revisions')}")
                    elif point.get("problems"):
                        document.add_paragraph(f"存在问题：{point.get('problems')}")
                    if point.get("noncompliance"):
                        document.add_paragraph(f"不符合知识库规范：{point.get('noncompliance')}")
                    if point.get("strategy"):
                        document.add_paragraph(f"高分策略：{point.get('strategy')}")
                    if point.get("drawingNo"):
                        document.add_paragraph(f"图号：{point.get('drawingNo')}")
                    if point.get("axis"):
                        document.add_paragraph(f"判断轴：{point.get('axis')}")
                    note_label = "施工说明" if str(point.get("source") or "") == "图纸" else "必须写到"
                    param_label = "图面参数" if str(point.get("source") or "") == "图纸" else "参数"
                    if point.get("mustWrite"):
                        document.add_paragraph(f"{note_label}：{point.get('mustWrite')}")
                    if point.get("parameters"):
                        document.add_paragraph(f"{param_label}：{point.get('parameters')}")
                    standards = point.get("standards") or []
                    if isinstance(standards, list) and standards:
                        document.add_paragraph("标准号：" + "、".join(str(code) for code in standards if code))
                    if point.get("chapter"):
                        document.add_paragraph(f"应落章节：{point.get('chapter')}")
                    cited = "；".join(
                        f"{c.get('code') or ''} {c.get('clauseNo') or ''}".strip()
                        for c in (point.get("clauses") or [])
                        if isinstance(c, dict)
                    )
                    if cited:
                        document.add_paragraph(f"依据：{cited}")
                    knowledge = "；".join(
                        " ".join(
                            bit
                            for bit in (hit.get("title") or hit.get("code") or "", hit.get("heading") or hit.get("clauseNo") or "", hit.get("excerpt") or "")
                            if bit
                        ).strip()
                        for hit in (point.get("knowledge") or [])
                        if isinstance(hit, dict)
                    )
                    if knowledge:
                        document.add_paragraph(f"知识库：{knowledge[:800]}")
                    if point.get("excerpt"):
                        document.add_paragraph(f"标书原文：{point.get('excerpt')}")
                    if point.get("reason"):
                        document.add_paragraph(str(point.get("reason")))

    labels = {2: "二", 3: "三", 4: "四", 5: "五", 6: "六"}
    document.add_heading(f"{labels.get(heading_n, '四')}、预审问题清单", level=1)
    if not issues:
        document.add_paragraph("本轮无预审问题。")
    for i, issue in enumerate(issues, 1):
        rule = display_rule(
            issue.get("rule") or "",
            issue.get("suggestion") or "",
            issue.get("strategyKey") or "",
        )
        document.add_heading(
            f"{i}. [{issue.get('severity') or '—'}] {rule or '未标注规则'}",
            level=2,
        )
        document.add_paragraph(
            f"层级：{issue.get('level') or '—'}　　章节：{chapter_from_location(issue.get('location') or '') or '—'}"
        )
        excerpt, quote = split_bid_and_tender(
            issue.get("excerpt") or "",
            issue.get("tenderQuote") or issue.get("tender_quote") or "",
            issue.get("rule") or "",
        )
        excerpt = excerpt or "对照招标要求，投标书中未见相应的响应内容。"
        quote = quote or "此项不对照某一条招标条款，而是检查投标书自身写得是否清楚。"
        suggestion = (issue.get("suggestion") or "").strip() or "（无改写建议）"
        document.add_paragraph("投标书原文" + ("（对应内容）" if (issue.get("excerpt") or "").strip() else "（未见对应响应）") + f"：{excerpt}")
        document.add_paragraph(f"招标要求原文：{quote}")
        document.add_paragraph(f"修改建议：{suggestion}")

    custom_heading = heading_n + 1
    document.add_heading(f"{labels.get(custom_heading, '五')}、自定义规则对照", level=1)
    if not custom_rules:
        document.add_paragraph("本轮预审尚未纳入自定义规则对照。若解析页已添加规则，请再跑一轮预审。")
    else:
        unanswered_n = sum(1 for r in custom_rules if (r.get("status") or "") == "未响应")
        document.add_paragraph(f"共 {len(custom_rules)} 条，其中未响应 {unanswered_n} 条。")
        for i, rule in enumerate(custom_rules, 1):
            title = (rule.get("title") or "").strip() or f"规则 {i}"
            status = rule.get("status") or "未响应"
            severity = rule.get("severity") or "扣分"
            source = rule.get("sourceLabel") or rule.get("source") or "—"
            line = document.add_paragraph()
            line.add_run(f"{i}. [{status}] {title}（{severity} · {source}）").bold = True
            content = (rule.get("content") or "").strip()
            if content:
                document.add_paragraph(f"规则内容：{content}")
            reason = (rule.get("reason") or "").strip()
            if reason:
                document.add_paragraph(f"对照说明：{reason}")
            excerpt = (rule.get("excerpt") or "").strip()
            if excerpt:
                document.add_paragraph(f"投标书对应内容：{excerpt}")

    document.add_heading(f"{labels.get(custom_heading + 1, '六')}、预审结论", level=1)
    document.add_paragraph(
        f"本轮{score_label}评审风险灯为「{light or '—'}」。"
        f"共发现废标 {waste} 项、扣分/降档 {risk} 项、建议 {suggest} 项。"
        "本报告由系统基于本项目招标文件与投标文件原文自动生成，供投标前自查参考。"
    )

    buf = io.BytesIO()
    document.save(buf)
    return buf.getvalue()
