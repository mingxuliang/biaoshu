"""E0 招标文件解析引擎（P1：招标文件解析与评标尺子锁定）。

调用 DeepSeek，将招标文件正文抽取为结构化「评标尺子」：评分规则、必响应/否决条款、
资格要求、格式与暗标要求，以及归一化后可直接驱动 E1/E2 引擎的数值参数（vetoParams）。
调用失败或未配置 API Key 时返回空清单，不阻塞人工在解析页手动补录/校对。
"""

import json
import uuid

import httpx

from ..config import get_settings

SYSTEM_PROMPT = """你是"青天大模型"口径的招标文件解析专家。请从提供的招标文件正文中抽取评标要素，只返回严格的 JSON，不要包含任何其他文字说明，格式如下：
{
  "scoreRules": [
    {"dimension": "评分维度名称", "weight": 数字(0-100，代表该维度分值), "detail": "评分细则说明", "subject": true/false（是否为主观评审项）, "sectionPath": "原文章节定位", "isEssential": true/false（是否为必响应项）}
  ],
  "mustRespond": [
    {"clause": "条款内容摘要", "original": "原文章节定位", "type": "星号条款|废标条款|实质性条款"}
  ],
  "qualification": [
    {"title": "资格项标题", "desc": "具体要求描述", "source": "原文章节定位", "level": "星号|废标|建议"}
  ],
  "formatRequirements": [
    {"title": "格式项标题", "desc": "具体要求描述", "source": "原文章节定位", "level": "废标|建议|强制"}
  ],
  "vetoParams": {
    "validity_days_required": 数字或null（投标有效期要求的日历天数）,
    "budget_cap_wan": 数字或null（预算上限，单位：万元）,
    "asset_liability_ratio_max": 数字或null（资产负债率上限百分数，如 85 表示 85%）,
    "qualification_keywords": ["资质/证书类关键词，如营业执照、安全生产许可证等"],
    "anonymity_required": true/false（是否为暗标评审，投标文件不得出现可识别身份的标记）
  }
}
要求：
1. scoreRules 的 weight 合计应接近 100；
2. 尽量标注原文章节定位（如"第二章 投标人须知 1.4.1"），找不到明确定位则填写"未标注"；
3. 若招标文件未提及某类信息，对应数组返回空数组、数值字段返回 null，不要编造内容；
4. 每个数组最多返回 20 条，优先保留最重要的条款。
"""

MAX_CHARS = 16000


def run(full_text: str) -> dict:
    settings = get_settings()

    if not settings.deepseek_api_key:
        return _fallback_result("未配置 DeepSeek API Key，解析结果为空，请人工补录评标尺子")

    truncated = full_text[:MAX_CHARS]
    payload = {
        "model": settings.deepseek_model,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": f"以下是招标文件正文（可能因篇幅截断）：\n\n{truncated}"},
        ],
        "temperature": 0.1,
        "response_format": {"type": "json_object"},
    }
    headers = {"Authorization": f"Bearer {settings.deepseek_api_key}"}

    try:
        with httpx.Client(base_url=settings.deepseek_base_url, timeout=120) as client:
            resp = client.post("/chat/completions", json=payload, headers=headers)
            resp.raise_for_status()
            content = resp.json()["choices"][0]["message"]["content"]
            data = json.loads(content)
            return _normalize(data)
    except Exception as exc:  # noqa: BLE001 —— 任何网络/解析异常都应降级而不是让解析任务失败
        return _fallback_result(f"调用 DeepSeek 失败（{exc.__class__.__name__}），解析结果为空，请人工补录评标尺子")


def _as_str(value, default: str = "") -> str:
    return value if isinstance(value, str) and value.strip() else default


def _as_bool(value, default: bool = False) -> bool:
    return value if isinstance(value, bool) else default


def _as_float_or_none(value):
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _as_int_or_none(value):
    f = _as_float_or_none(value)
    return int(f) if f is not None else None


def _normalize(data: dict) -> dict:
    score_rules = []
    for item in (data.get("scoreRules") or [])[:20]:
        if not isinstance(item, dict):
            continue
        score_rules.append(
            {
                "id": f"sr-{uuid.uuid4().hex[:8]}",
                "dimension": _as_str(item.get("dimension"), "未命名维度"),
                "weight": _as_float_or_none(item.get("weight")) or 0,
                "detail": _as_str(item.get("detail")),
                "subject": _as_bool(item.get("subject")),
                "sectionPath": _as_str(item.get("sectionPath"), "未标注"),
                "responseStatus": "未覆盖",
                "isEssential": _as_bool(item.get("isEssential")),
            }
        )

    must_respond = []
    for item in (data.get("mustRespond") or [])[:20]:
        if not isinstance(item, dict):
            continue
        clause_type = item.get("type") if item.get("type") in ("星号条款", "废标条款", "实质性条款") else "实质性条款"
        must_respond.append(
            {
                "id": f"mr-{uuid.uuid4().hex[:8]}",
                "clause": _as_str(item.get("clause"), "未提取到条款内容"),
                "original": _as_str(item.get("original"), "未标注"),
                "type": clause_type,
                "status": "待响应",
            }
        )

    qualification = []
    for item in (data.get("qualification") or [])[:20]:
        if not isinstance(item, dict):
            continue
        level = item.get("level") if item.get("level") in ("星号", "废标", "建议") else "建议"
        qualification.append(
            {
                "title": _as_str(item.get("title"), "未命名资格项"),
                "desc": _as_str(item.get("desc")),
                "source": _as_str(item.get("source"), "未标注"),
                "level": level,
            }
        )

    format_requirements = []
    for item in (data.get("formatRequirements") or [])[:20]:
        if not isinstance(item, dict):
            continue
        level = item.get("level") if item.get("level") in ("废标", "建议", "强制") else "建议"
        format_requirements.append(
            {
                "title": _as_str(item.get("title"), "未命名格式项"),
                "desc": _as_str(item.get("desc")),
                "source": _as_str(item.get("source"), "未标注"),
                "level": level,
            }
        )

    veto = data.get("vetoParams") or {}
    veto_params = {
        "validity_days_required": _as_int_or_none(veto.get("validity_days_required")),
        "budget_cap_wan": _as_float_or_none(veto.get("budget_cap_wan")),
        "asset_liability_ratio_max": _as_float_or_none(veto.get("asset_liability_ratio_max")),
        "qualification_keywords": [k for k in (veto.get("qualification_keywords") or []) if isinstance(k, str)][:20],
        "anonymity_required": _as_bool(veto.get("anonymity_required")),
    }

    return {
        "scoreRules": score_rules,
        "mustRespond": must_respond,
        "qualification": qualification,
        "formatRequirements": format_requirements,
        "vetoParams": veto_params,
        "error": None,
    }


def _fallback_result(reason: str) -> dict:
    return {
        "scoreRules": [],
        "mustRespond": [],
        "qualification": [],
        "formatRequirements": [],
        "vetoParams": {
            "validity_days_required": None,
            "budget_cap_wan": None,
            "asset_liability_ratio_max": None,
            "qualification_keywords": [],
            "anonymity_required": False,
        },
        "error": reason,
    }
