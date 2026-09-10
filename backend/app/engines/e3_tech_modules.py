"""E3 技术评分模块确定性核验（对应青天第三层「技术标核心 AI 评分点」8 个模块）。

与 e3_semantic.py 的大模型五维打分互补：这里只做关键词/正则可判定的完整性核验，
命中缺项时产生 L3 级别 Finding，供编排层与大模型 issues 合并后一起扣 L3 分。
tech_keys 为 None 表示不做开关过滤（全部启用）；管理员在规则页「技术评分」tab
关闭某模块后，对应 key 不在集合内，直接跳过该模块的确定性核验（同时也退出 Prompt，见 e3_semantic.py）。

只使用投标文件正文关键词、附图占位与项目名称，不联网核验规范条文真实性。
声称有「网络图/横道图/动态曲线」但附近没有抽出的原图，按未附图扣分。

run() 除了返回给 L3 合并用的 Finding 列表，还会返回一份「8 模块打分明细」
（module_score()），直接对应 rules_data.TECH_SCORE_MODULES 里配置的满分权重，
供 AI 预审报告逐模块展示"模块名 N 分，缺项说明"，不再只把结果揉进笼统的 issue 列表。
"""

from __future__ import annotations

import re

from . import rules_data
from .bid_media import seqs_in_text
from .excerpt_guard import hit_sentence

CODE_PATTERN = re.compile(r"GB\s?/?\s?\d|JGJ\s?\d|JTG\s?\d")
QUANT_PATTERN = re.compile(r"\d+(?:\.\d+)?\s*(?:%|dB|吨|db)")
HOUR_RESPONSE_PATTERN = re.compile(r"\d+\s*小时")
SENTENCE_SPLIT = re.compile(r"[。！？；\n]")

# finding.severity → 该模块满分的扣减比例；无 finding 时视为满分达标。
_SEVERITY_DEDUCT_RATIO = {"废标": 1.0, "降档": 0.6, "扣分": 0.4, "建议": 0.15}
_MODULE_META = {m["key"]: m for m in rules_data.TECH_SCORE_MODULES}


def _finding(rule: str, excerpt: str, suggestion: str, severity: str = "建议") -> dict:
    return {
        "engine": "e3_tech_modules",
        "level": "L3",
        "severity": severity,
        "location": "技术标 / 技术评分模块",
        "excerpt": excerpt,
        "rule": rule,
        "tenderQuote": "",
        "suggestion": suggestion,
        "confidence": 0.65,
    }


def _enabled(key: str, tech_keys: set[str] | None) -> bool:
    return tech_keys is None or key in tech_keys


def _hit(text: str, paragraphs: list[dict] | None, keywords: tuple[str, ...]) -> str:
    return hit_sentence(text, paragraphs, keywords, skip_score_voice=True)


_CHAPTER_HEAD = re.compile(r"^第[0-9一二三四五六七八九十百零]+[章节篇]")
_DOTTED_HEAD = re.compile(r"^(\d{1,2}(?:\.\d{1,2})+)")
_TOC_DOTS = re.compile(r"[.．·…]{3,}")
_TOC_PAGE = re.compile(r"\s+\d+\s*$")
_EMPTY_BODY_CHARS = 80
_NEAR_RADIUS = 12
_SKIP_SHELL = ("目录", "封面", "投标函", "分目录")


def _is_outline_heading(title: str) -> bool:
    raw = (title or "").strip()
    return bool(_CHAPTER_HEAD.match(raw) or _DOTTED_HEAD.match(raw))


def _decoded_seqs(images: list[dict] | None) -> set[int]:
    out: set[int] = set()
    for img in images or []:
        if not (img.get("decoded") or img.get("jpeg")):
            continue
        seq = int(img.get("seq") or 0)
        if seq:
            out.add(seq)
    return out


def _nearby_has_figure(
    text: str,
    paragraphs: list[dict] | None,
    keywords: tuple[str, ...],
    images: list[dict] | None,
) -> bool:
    """关键词附近是否有抽出的真图（含 JPEG）；仅「网络图」字样不算。"""
    decoded = _decoded_seqs(images)
    paras = [p for p in (paragraphs or []) if isinstance(p, dict)]
    if paras:
        hit_idxs = [
            i
            for i, p in enumerate(paras)
            if any(k in (p.get("text") or "") for k in keywords)
        ]
        for i in hit_idxs:
            start = i
            while start > 0 and not paras[start].get("isHeading"):
                start -= 1
            end = i + 1
            while end < len(paras) and not paras[end].get("isHeading"):
                end += 1
            window = paras[max(0, start) : max(end, i + _NEAR_RADIUS + 1)]
            for p in window:
                if p.get("isImage") and int(p.get("imageSeq") or 0) in decoded:
                    return True
                if p.get("isImage") and decoded and "【附图" in (p.get("text") or ""):
                    return True
            blob = "\n".join((p.get("text") or "") for p in window)
            if decoded & seqs_in_text(blob):
                return True
        if hit_idxs:
            return False
    for key in keywords:
        pos = (text or "").find(key)
        if pos < 0:
            continue
        window = (text or "")[max(0, pos - 800) : pos + 800]
        if decoded & seqs_in_text(window):
            return True
        if "【附图" in window and decoded:
            return True
    return False


def _heading_level(title: str) -> int:
    raw = (title or "").strip()
    if _CHAPTER_HEAD.match(raw):
        return 1
    m = _DOTTED_HEAD.match(raw)
    if m:
        return m.group(1).count(".") + 1
    return 9


def _empty_shell_findings(paragraphs: list[dict] | None) -> list[dict]:
    """标题后直至同级下一节均无实质正文/表/图 → L3 未实质性响应。"""
    if not paragraphs:
        return []
    sections: list[dict] = []
    heading = ""
    level = 9
    body_chars = 0
    has_image = False
    has_table = False

    def flush() -> None:
        if heading:
            sections.append(
                {
                    "title": heading,
                    "level": level,
                    "chars": body_chars,
                    "image": has_image,
                    "table": has_table,
                }
            )

    for p in paragraphs:
        if not isinstance(p, dict):
            continue
        t = (p.get("text") or "").strip()
        if p.get("isHeading") and t and _is_outline_heading(t):
            flush()
            heading = t[:40]
            level = _heading_level(heading)
            body_chars = 0
            has_image = False
            has_table = False
            continue
        if p.get("isImage"):
            has_image = True
            continue
        if p.get("fromTable"):
            has_table = True
            body_chars += len(t)
            continue
        body_chars += len(t)
    flush()

    names: list[str] = []
    excerpt = ""
    first_substance = next(
        (i for i, s in enumerate(sections) if s["chars"] >= 40 or s["image"] or s["table"]),
        None,
    )
    start = 0 if first_substance is None else first_substance
    for i, sec in enumerate(sections):
        if i < start:
            continue
        title = sec["title"]
        if any(skip in title for skip in _SKIP_SHELL):
            continue
        if _TOC_DOTS.search(title) or _TOC_PAGE.search(title):
            continue
        if not _is_outline_heading(title):
            continue
        if len(title) < 4:
            continue
        chars = sec["chars"]
        img = sec["image"]
        table = sec["table"]
        for nxt in sections[i + 1 :]:
            if nxt["level"] <= sec["level"]:
                break
            chars += nxt["chars"]
            img = img or nxt["image"]
            table = table or nxt["table"]
        if img or table or chars >= _EMPTY_BODY_CHARS:
            continue
        names.append(title)
        if not excerpt:
            excerpt = title
        if len(names) >= 8:
            break
    if not names:
        return []
    listed = "、".join(names[:8])
    return [
        _finding(
            rule="空壳章节-标题不等于覆盖",
            excerpt=excerpt,
            suggestion=f"以下章节仅有标题、缺少实质正文/表格/原图：{listed}。请补写内容并附对应图表，不得以目录标题视为已响应",
            severity="扣分",
        )
    ]


def _check_org_outline(text: str, paragraphs: list[dict] | None, project_name: str, _images=None) -> dict | None:
    if not (project_name and len(project_name.strip()) >= 4):
        return None
    opening_blob = "\n".join((p.get("text") or "") for p in (paragraphs or [])[:5]) if paragraphs else (text or "")[:2000]
    if len(text) > 200 and project_name.strip() not in opening_blob:
        first = (paragraphs[0].get("text") or "").strip() if paragraphs else (text.splitlines()[0] if text.splitlines() else "")
        first_sent = SENTENCE_SPLIT.split(first, 1)[0].strip()[:180] if first else ""
        return _finding(
            rule="T01 施工组织总纲-开篇绑定本项目",
            excerpt=first_sent,
            suggestion=f"技术标开篇未检出本项目全称「{project_name.strip()}」，请在总纲开篇写明项目全称与独有特征，避免使用通用模板开篇",
        )
    return None


def _check_special_plan(text: str, paragraphs=None, _name="", _images=None) -> dict | None:
    if "危大工程" in text and not CODE_PATTERN.search(text):
        return _finding(
            rule="T02 专项施工方案-引用规范条文号",
            excerpt=_hit(text, paragraphs, ("危大工程",)),
            suggestion="危大工程专项方案未检出规范条文号（如 GB/JGJ/JTG 编号），请引用具体条文号，不使用泛泛表述",
            severity="扣分",
        )
    return None


def _check_schedule(text: str, paragraphs=None, _name="", images=None) -> dict | None:
    if not any(k in text for k in ("工期", "进度计划")):
        return None
    claimed = any(k in text for k in ("网络图", "横道图", "甘特图"))
    has_fig = _nearby_has_figure(text, paragraphs, ("工期", "进度计划", "网络图", "横道图", "甘特图"), images)
    if has_fig:
        return None
    if claimed:
        return _finding(
            rule="T03 工期管控-声称有图须有原图",
            excerpt=_hit(text, paragraphs, ("网络图", "横道图", "甘特图", "工期", "进度计划")),
            suggestion="正文出现「网络图/横道图」字样，但该章附近未抽出可阅读的原图。不得凭字样认定已附图，请插入双代号网络图或横道图原图并标注关键线路",
            severity="扣分",
        )
    return _finding(
        rule="T03 工期管控-须附网络图或横道图",
        excerpt=_hit(text, paragraphs, ("工期", "进度计划")),
        suggestion="未检出工期网络图/横道图原图，纯文字或仅有章节标题不予认可，请补充图示并标注关键线路",
        severity="扣分",
    )


def _check_quality(text: str, paragraphs=None, _name="", _images=None) -> dict | None:
    if any(k in text for k in ("质量管理", "质保体系")):
        missing = [k for k in ("三级交底", "样板引路", "验收流程") if k not in text]
        if len(missing) >= 2:
            return _finding(
                rule="T04 质量管理-要素完整性",
                excerpt=_hit(text, paragraphs, ("质量管理", "质保体系")),
                suggestion=f"质量管理部分缺少：{'、'.join(missing)}，请补齐并引用具体验收规范条文号",
                severity="扣分",
            )
    return None


def _check_safety(text: str, paragraphs=None, _name="", _images=None) -> dict | None:
    if any(k in text for k in ("安全管理", "安全生产")) and "危险源" not in text and "专项防护" not in text:
        return _finding(
            rule="T05 安全文明-危险源与专项防护",
            excerpt=_hit(text, paragraphs, ("安全管理", "安全生产")),
            suggestion="未检出「危险源」清单或「专项防护」方案，请补充危险源辨识清单与对应专项防护措施",
            severity="扣分",
        )
    return None


def _check_environment(text: str, paragraphs=None, _name="", _images=None) -> dict | None:
    if any(k in text for k in ("环保", "噪声", "污水")) and not QUANT_PATTERN.search(text):
        return _finding(
            rule="T06 环保水保-量化指标",
            excerpt=_hit(text, paragraphs, ("环保", "噪声", "污水")),
            suggestion="环保水保措施缺少量化指标（如噪声分贝、污水处理率、固废回收率），请补充具体数值",
        )
    return None


def _check_resources(text: str, paragraphs=None, _name="", images=None) -> dict | None:
    if not any(k in text for k in ("资源配置", "劳动力")):
        return None
    claimed = "动态曲线" in text
    has_fig = _nearby_has_figure(text, paragraphs, ("资源配置", "劳动力", "动态曲线"), images)
    if has_fig:
        return None
    if claimed:
        return _finding(
            rule="T07 资源配置-声称有图须有原图",
            excerpt=_hit(text, paragraphs, ("动态曲线", "劳动力", "资源配置")),
            suggestion="正文出现「劳动力动态曲线」字样，但该章附近未抽出可阅读的原图。不得凭字样认定已附图，请插入分阶段人力/机械配置曲线原图",
        )
    return _finding(
        rule="T07 资源配置-劳动力动态曲线",
        excerpt=_hit(text, paragraphs, ("资源配置", "劳动力")),
        suggestion="未检出「劳动力动态曲线」原图，请补充分阶段人力/机械资源配置曲线，便于与工期数据交叉验证",
    )


def _check_after_sales(text: str, paragraphs=None, _name="", _images=None) -> dict | None:
    if "售后" in text and not HOUR_RESPONSE_PATTERN.search(text):
        return _finding(
            rule="T08 售后质保-响应时限量化",
            excerpt=_hit(text, paragraphs, ("售后",)),
            suggestion="未检出量化的响应时限（如“2小时到场、24小时修复”），请补充具体小时数与巡检计划、备品备件清单",
            severity="扣分",
        )
    return None


_CHECKS = {
    "org_outline": _check_org_outline,
    "special_plan": _check_special_plan,
    "schedule": _check_schedule,
    "quality": _check_quality,
    "safety": _check_safety,
    "environment": _check_environment,
    "resources": _check_resources,
    "after_sales": _check_after_sales,
}

# 与 rules_data.TECH_SCORE_MODULES 顺序一致，保证报告里模块顺序稳定。
_ORDER = ["org_outline", "special_plan", "schedule", "quality", "safety", "environment", "resources", "after_sales"]


def _module_entry(key: str, finding: dict | None) -> dict:
    meta = _MODULE_META.get(key, {})
    max_score = meta.get("score", 0)
    if finding is None:
        return {
            "key": key,
            "module": meta.get("module", key),
            "maxScore": max_score,
            "score": max_score,
            "status": "达标",
            "summary": "正文核验通过，未检出缺项",
        }
    ratio = _SEVERITY_DEDUCT_RATIO.get(finding["severity"], 0.15)
    score = max(0.0, round(max_score - max_score * ratio, 1))
    return {
        "key": key,
        "module": meta.get("module", key),
        "maxScore": max_score,
        "score": score,
        "status": finding["severity"],
        "summary": finding["suggestion"],
    }


def evaluate(
    full_text: str,
    paragraphs: list[dict] | None = None,
    project_name: str = "",
    tech_keys: set[str] | None = None,
    images: list[dict] | None = None,
) -> tuple[list[dict], list[dict]]:
    """返回 (findings, module_scores)：findings 供 L3 合并扣分；module_scores 供报告逐模块展示。"""
    text = full_text or ""
    findings: list[dict] = []
    modules: list[dict] = []
    if not text.strip():
        return findings, modules

    for key in _ORDER:
        if not _enabled(key, tech_keys):
            continue
        finding = _CHECKS[key](text, paragraphs, project_name, images)
        if finding is not None:
            findings.append(finding)
        modules.append(_module_entry(key, finding))

    findings.extend(_empty_shell_findings(paragraphs))
    return findings, modules


def run(
    full_text: str,
    paragraphs: list[dict] | None = None,
    project_name: str = "",
    tech_keys: set[str] | None = None,
    images: list[dict] | None = None,
) -> list[dict]:
    """兼容旧调用：只要 Finding 列表。新调用请使用 evaluate() 同时取模块打分明细。"""
    findings, _modules = evaluate(full_text, paragraphs, project_name, tech_keys, images=images)
    return findings
