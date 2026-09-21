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
    overall: float,
    light: str,
    waste: int,
    risk: int,
    suggest: int,
    levels: list[dict],
    dimensions: list[dict],
    issues: list[dict],
    tech_modules: list[dict] | None = None,
    custom_rules: list[dict] | None = None,
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
        "business": "商务标分册预审（L1 否决 + L2 商务客观核验，满分 100）",
        "tech": "技术标分册预审（L3 五维 + L4 查重 + L5 版式，满分 100）",
        "full": "请分别查看商务标与技术标报告，两册各自评分、互不加权",
    }.get(scope) or "分册预审"
    scope_label = {"business": "商务标", "tech": "技术标", "full": "分册"}.get(scope) or scope
    meta = document.add_paragraph()
    meta.add_run(f"项目：{project_name or '（未命名）'}\n")
    meta.add_run(f"招标编号：{project_code or '—'}\n")
    meta.add_run(f"预审分册：{scope_label}\n")
    meta.add_run(f"预审轮次：第 {round_no} 轮\n")
    meta.add_run(f"生成时间：{when}\n")
    meta.add_run(f"预审方法：{method}")

    document.add_heading("一、本册得分与分层指标", level=1)
    p = document.add_paragraph()
    score_label = {"business": "商务标得分", "tech": "技术标得分"}.get(scope) or "本册预审得分"
    p.add_run(f"{score_label}：{overall} 分（满分 100）").bold = True
    document.add_paragraph(
        f"风险灯：{light or '—'}　　废标 {waste} 项　　扣分 {risk} 项　　建议 {suggest} 项"
    )

    for level in levels or []:
        name = level.get("name") or level.get("key") or "—"
        score = level.get("score", "—")
        issues_n = level.get("issues", 0)
        status = level.get("status") or ""
        desc = level.get("desc") or ""
        key = level.get("key") or ""
        line = document.add_paragraph()
        line.add_run(f"{key} {name}：{score} 分，{issues_n} 项问题，结论 {status}").bold = True
        if desc:
            document.add_paragraph(f"审查内容：{desc}")

    heading_n = 2
    if scope != "business" and (dimensions or tech_modules):
        document.add_heading("二、技术标五维打分", level=1)
        heading_n = 3
        if not dimensions:
            document.add_paragraph("本册未计算五维得分。")
        for dim in dimensions or []:
            document.add_paragraph(
                f"{dim.get('name') or '—'}：{dim.get('score', '—')} 分 / 权重 {dim.get('weight', '—')}%"
            )

        if tech_modules:
            document.add_heading("三、技术评分模块核验", level=1)
            heading_n = 4
            for m in tech_modules:
                module = m.get("module") or m.get("key") or "—"
                max_score = m.get("maxScore", "—")
                score = m.get("score", "—")
                status = m.get("status") or "—"
                line = document.add_paragraph()
                line.add_run(f"{module}（满分 {max_score} 分）：得 {score} 分，{status}").bold = True
                summary = (m.get("summary") or "").strip()
                if summary:
                    document.add_paragraph(summary)

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
        f"本轮{score_label}为 {overall} 分，风险灯为「{light or '—'}」。"
        f"共发现废标 {waste} 项、扣分 {risk} 项、建议 {suggest} 项。"
        "本报告由系统基于本项目招标文件与投标文件原文自动生成，供投标前自查参考。"
    )

    buf = io.BytesIO()
    document.save(buf)
    return buf.getvalue()
