"""E3 技术评分模块确定性核验（对应青天第三层「技术标核心 AI 评分点」8 个模块）。

与 e3_semantic.py 的大模型五维打分互补：这里只做关键词/正则可判定的完整性核验，
命中缺项时产生 L3 级别 Finding，供编排层与大模型 issues 合并后一起扣 L3 分。
tech_keys 为 None 表示不做开关过滤（全部启用）；管理员在规则页「技术评分」tab
关闭某模块后，对应 key 不在集合内，直接跳过该模块的确定性核验（同时也退出 Prompt，见 e3_semantic.py）。

只使用投标文件正文关键词与项目名称，不联网核验规范条文真实性、设备/图纸内容。
"""

import re

CODE_PATTERN = re.compile(r"GB\s?/?\s?\d|JGJ\s?\d|JTG\s?\d")
QUANT_PATTERN = re.compile(r"\d+(?:\.\d+)?\s*(?:%|dB|吨|db)")
HOUR_RESPONSE_PATTERN = re.compile(r"\d+\s*小时")


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


def run(
    full_text: str,
    paragraphs: list[dict] | None = None,
    project_name: str = "",
    tech_keys: set[str] | None = None,
) -> list[dict]:
    findings: list[dict] = []
    text = full_text or ""
    if not text.strip():
        return findings

    if _enabled("org_outline", tech_keys) and project_name and len(project_name.strip()) >= 4:
        opening = ""
        if paragraphs:
            opening = "\n".join(p["text"] for p in paragraphs[:5])
        else:
            opening = text[:400]
        if len(text) > 200 and project_name.strip() not in opening:
            findings.append(
                _finding(
                    rule="T01 施工组织总纲-开篇绑定本项目",
                    excerpt=opening[:150] or "（技术标开篇为空）",
                    suggestion=f"技术标开篇未检出本项目全称「{project_name.strip()}」，请在总纲开篇写明项目全称与独有特征，避免使用通用模板开篇",
                )
            )

    if _enabled("special_plan", tech_keys) and "危大工程" in text and not CODE_PATTERN.search(text):
        findings.append(
            _finding(
                rule="T02 专项施工方案-引用规范条文号",
                excerpt="正文提及危大工程",
                suggestion="危大工程专项方案未检出规范条文号（如 GB/JGJ/JTG 编号），请引用具体条文号，不使用泛泛表述",
                severity="扣分",
            )
        )

    if _enabled("schedule", tech_keys) and any(k in text for k in ("工期", "进度计划")) and not any(
        k in text for k in ("网络图", "横道图")
    ):
        findings.append(
            _finding(
                rule="T03 工期管控-须附网络图或横道图",
                excerpt="正文提及工期/进度计划",
                suggestion="未检出「双代号网络图」或「横道图」字样，纯文字描述进度计划不予认可，请补充图示并标注关键线路",
                severity="扣分",
            )
        )

    if _enabled("quality", tech_keys) and any(k in text for k in ("质量管理", "质保体系")):
        missing = [k for k in ("三级交底", "样板引路", "验收流程") if k not in text]
        if len(missing) >= 2:
            findings.append(
                _finding(
                    rule="T04 质量管理-要素完整性",
                    excerpt="正文提及质量管理/质保体系",
                    suggestion=f"质量管理部分缺少：{'、'.join(missing)}，请补齐并引用具体验收规范条文号",
                    severity="扣分",
                )
            )

    if _enabled("safety", tech_keys) and any(k in text for k in ("安全管理", "安全生产")):
        if "危险源" not in text and "专项防护" not in text:
            findings.append(
                _finding(
                    rule="T05 安全文明-危险源与专项防护",
                    excerpt="正文提及安全管理/安全生产",
                    suggestion="未检出「危险源」清单或「专项防护」方案，请补充危险源辨识清单与对应专项防护措施",
                    severity="扣分",
                )
            )

    if _enabled("environment", tech_keys) and any(k in text for k in ("环保", "噪声", "污水")):
        if not QUANT_PATTERN.search(text):
            findings.append(
                _finding(
                    rule="T06 环保水保-量化指标",
                    excerpt="正文提及环保/噪声/污水治理",
                    suggestion="环保水保措施缺少量化指标（如噪声分贝、污水处理率、固废回收率），请补充具体数值",
                )
            )

    if _enabled("resources", tech_keys) and any(k in text for k in ("资源配置", "劳动力")):
        if "动态曲线" not in text:
            findings.append(
                _finding(
                    rule="T07 资源配置-劳动力动态曲线",
                    excerpt="正文提及资源配置/劳动力",
                    suggestion="未检出「劳动力动态曲线」，请补充分阶段人力/机械资源配置曲线，便于与工期数据交叉验证",
                )
            )

    if _enabled("after_sales", tech_keys) and "售后" in text:
        if not HOUR_RESPONSE_PATTERN.search(text):
            findings.append(
                _finding(
                    rule="T08 售后质保-响应时限量化",
                    excerpt="正文提及售后服务",
                    suggestion="未检出量化的响应时限（如“2小时到场、24小时修复”），请补充具体小时数与巡检计划、备品备件清单",
                    severity="扣分",
                )
            )

    return findings
