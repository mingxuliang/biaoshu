"""E3 技术评分模块确定性核验（对应青天第三层「技术标核心 AI 评分点」8 个模块）。

与 e3_semantic.py 的大模型五维打分互补：这里只做关键词/正则可判定的完整性核验，
命中缺项时产生 L3 级别 Finding，供编排层与大模型 issues 合并后一起扣 L3 分。
tech_keys 为 None 表示不做开关过滤（全部启用）；管理员在规则页「技术评分」tab
关闭某模块后，对应 key 不在集合内，直接跳过该模块的确定性核验（同时也退出 Prompt，见 e3_semantic.py）。

只使用投标文件正文关键词与项目名称，不联网核验规范条文真实性、设备/图纸内容。

run() 除了返回给 L3 合并用的 Finding 列表，还会返回一份「8 模块打分明细」
（module_score()），直接对应 rules_data.TECH_SCORE_MODULES 里配置的满分权重，
供 AI 预审报告逐模块展示"模块名 N 分，缺项说明"，不再只把结果揉进笼统的 issue 列表。
"""

from __future__ import annotations

import re

from . import rules_data

CODE_PATTERN = re.compile(r"GB\s?/?\s?\d|JGJ\s?\d|JTG\s?\d")
QUANT_PATTERN = re.compile(r"\d+(?:\.\d+)?\s*(?:%|dB|吨|db)")
HOUR_RESPONSE_PATTERN = re.compile(r"\d+\s*小时")

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


def _check_org_outline(text: str, paragraphs: list[dict] | None, project_name: str) -> dict | None:
    if not (project_name and len(project_name.strip()) >= 4):
        return None
    opening = "\n".join(p["text"] for p in paragraphs[:5]) if paragraphs else text[:400]
    if len(text) > 200 and project_name.strip() not in opening:
        return _finding(
            rule="T01 施工组织总纲-开篇绑定本项目",
            excerpt=opening[:150] or "（技术标开篇为空）",
            suggestion=f"技术标开篇未检出本项目全称「{project_name.strip()}」，请在总纲开篇写明项目全称与独有特征，避免使用通用模板开篇",
        )
    return None


def _check_special_plan(text: str) -> dict | None:
    if "危大工程" in text and not CODE_PATTERN.search(text):
        return _finding(
            rule="T02 专项施工方案-引用规范条文号",
            excerpt="正文提及危大工程",
            suggestion="危大工程专项方案未检出规范条文号（如 GB/JGJ/JTG 编号），请引用具体条文号，不使用泛泛表述",
            severity="扣分",
        )
    return None


def _check_schedule(text: str) -> dict | None:
    if any(k in text for k in ("工期", "进度计划")) and not any(k in text for k in ("网络图", "横道图")):
        return _finding(
            rule="T03 工期管控-须附网络图或横道图",
            excerpt="正文提及工期/进度计划",
            suggestion="未检出「双代号网络图」或「横道图」字样，纯文字描述进度计划不予认可，请补充图示并标注关键线路",
            severity="扣分",
        )
    return None


def _check_quality(text: str) -> dict | None:
    if any(k in text for k in ("质量管理", "质保体系")):
        missing = [k for k in ("三级交底", "样板引路", "验收流程") if k not in text]
        if len(missing) >= 2:
            return _finding(
                rule="T04 质量管理-要素完整性",
                excerpt="正文提及质量管理/质保体系",
                suggestion=f"质量管理部分缺少：{'、'.join(missing)}，请补齐并引用具体验收规范条文号",
                severity="扣分",
            )
    return None


def _check_safety(text: str) -> dict | None:
    if any(k in text for k in ("安全管理", "安全生产")) and "危险源" not in text and "专项防护" not in text:
        return _finding(
            rule="T05 安全文明-危险源与专项防护",
            excerpt="正文提及安全管理/安全生产",
            suggestion="未检出「危险源」清单或「专项防护」方案，请补充危险源辨识清单与对应专项防护措施",
            severity="扣分",
        )
    return None


def _check_environment(text: str) -> dict | None:
    if any(k in text for k in ("环保", "噪声", "污水")) and not QUANT_PATTERN.search(text):
        return _finding(
            rule="T06 环保水保-量化指标",
            excerpt="正文提及环保/噪声/污水治理",
            suggestion="环保水保措施缺少量化指标（如噪声分贝、污水处理率、固废回收率），请补充具体数值",
        )
    return None


def _check_resources(text: str) -> dict | None:
    if any(k in text for k in ("资源配置", "劳动力")) and "动态曲线" not in text:
        return _finding(
            rule="T07 资源配置-劳动力动态曲线",
            excerpt="正文提及资源配置/劳动力",
            suggestion="未检出「劳动力动态曲线」，请补充分阶段人力/机械资源配置曲线，便于与工期数据交叉验证",
        )
    return None


def _check_after_sales(text: str) -> dict | None:
    if "售后" in text and not HOUR_RESPONSE_PATTERN.search(text):
        return _finding(
            rule="T08 售后质保-响应时限量化",
            excerpt="正文提及售后服务",
            suggestion="未检出量化的响应时限（如“2小时到场、24小时修复”），请补充具体小时数与巡检计划、备品备件清单",
            severity="扣分",
        )
    return None


_CHECKS = {
    "org_outline": lambda text, paras, name: _check_org_outline(text, paras, name),
    "special_plan": lambda text, paras, name: _check_special_plan(text),
    "schedule": lambda text, paras, name: _check_schedule(text),
    "quality": lambda text, paras, name: _check_quality(text),
    "safety": lambda text, paras, name: _check_safety(text),
    "environment": lambda text, paras, name: _check_environment(text),
    "resources": lambda text, paras, name: _check_resources(text),
    "after_sales": lambda text, paras, name: _check_after_sales(text),
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
        finding = _CHECKS[key](text, paragraphs, project_name)
        if finding is not None:
            findings.append(finding)
        modules.append(_module_entry(key, finding))

    return findings, modules


def run(
    full_text: str,
    paragraphs: list[dict] | None = None,
    project_name: str = "",
    tech_keys: set[str] | None = None,
) -> list[dict]:
    """兼容旧调用：只要 Finding 列表。新调用请使用 evaluate() 同时取模块打分明细。"""
    findings, _modules = evaluate(full_text, paragraphs, project_name, tech_keys)
    return findings
