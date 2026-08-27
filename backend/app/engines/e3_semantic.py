"""E3 技术标五维语义引擎（对应青天第三层「技术标核心 AI 评分点」，前端 L3）。

调用 DeepSeek Chat Completions API，按五维评分标准输出结构化分数与问题清单。
"""

import json

import httpx

from ..config import get_settings
from .rules_data import (
    DEFAULT_WEIGHTS,
    DIMENSION_LABELS,
    DIMENSION_RUBRIC,
    FILLER_SELF_CHECK_RULES,
    HIGH_SCORE_STRATEGIES,
    TECH_SCORE_MODULES,
)

MAX_CHARS = 12000


def _build_system_prompt(weights: dict) -> str:
    dim_lines = []
    for key, weight in weights.items():
        label = DIMENSION_LABELS.get(key, key)
        rubric = DIMENSION_RUBRIC.get(key, {})
        dim_lines.append(
            f"- {label}({weight}%)：校验重点：{rubric.get('focus', '')}；扣分/否决：{rubric.get('penalty', '')}"
        )
    check_lines = "\n".join(f"{i}. {rule}" for i, rule in enumerate(FILLER_SELF_CHECK_RULES, 1))
    strategy_lines = "\n".join(f"- {s['category']}：{s['point']}" for s in HIGH_SCORE_STRATEGIES[:6])
    module_lines = "\n".join(f"- {m['module']}：{m['logic']}" for m in TECH_SCORE_MODULES)
    return f"""你是"青天大模型"口径的招投标技术标评审专家。请严格按照以下五维评分标准对投标文件技术标内容打分：
{chr(10).join(dim_lines)}

技术标评分模块：
{module_lines}

评分时请遵循"虚词自查五规则"：
{check_lines}

属地合规细节（合肥/安徽常见）：临边防护高度 1.2m、扫地杆距地 ≤20cm、扬尘六个 100%。若正文涉及对应主题但缺少量化，在合规性或可落地性中扣分。

高分策略参考（用于给改写建议，不作为虚构加分）：
{strategy_lines}

请仅返回严格的 JSON，不要包含任何其他文字说明，格式如下：
{{
  "dimensions": {{
    "completeness": {{"score": 0-100, "reason": "..."}},
    "relevance": {{"score": 0-100, "reason": "..."}},
    "compliance": {{"score": 0-100, "reason": "..."}},
    "feasibility": {{"score": 0-100, "reason": "..."}},
    "standardization": {{"score": 0-100, "reason": "..."}}
  }},
  "issues": [
    {{"severity": "扣分|降档|建议", "location": "章节/位置描述", "excerpt": "原文片段", "suggestion": "改写建议"}}
  ]
}}
"""


def run(full_text: str, weights: dict | None = None) -> dict:
    settings = get_settings()
    weights = weights or DEFAULT_WEIGHTS

    if not settings.deepseek_api_key:
        return _fallback_result("未配置 DeepSeek API Key，已使用保守默认分，请人工复核技术标内容", weights)

    truncated = full_text[:MAX_CHARS]
    payload = {
        "model": settings.deepseek_model,
        "messages": [
            {"role": "system", "content": _build_system_prompt(weights)},
            {"role": "user", "content": f"以下是投标文件技术标正文（可能因篇幅截断）：\n\n{truncated}"},
        ],
        "temperature": 0.2,
        "response_format": {"type": "json_object"},
    }
    headers = {"Authorization": f"Bearer {settings.deepseek_api_key}"}

    try:
        with httpx.Client(base_url=settings.deepseek_base_url, timeout=90) as client:
            resp = client.post("/chat/completions", json=payload, headers=headers)
            resp.raise_for_status()
            content = resp.json()["choices"][0]["message"]["content"]
            data = json.loads(content)
            return _normalize(data, weights)
    except Exception as exc:  # noqa: BLE001 —— 任何网络/解析异常都应降级而不是让整轮预审失败
        return _fallback_result(f"调用 DeepSeek 失败（{exc.__class__.__name__}），已使用保守默认分，请人工复核", weights)


def _normalize(data: dict, weights: dict) -> dict:
    dims: dict[str, dict] = {}
    for key in weights:
        d = (data.get("dimensions") or {}).get(key, {}) or {}
        score = d.get("score", 70)
        try:
            score = max(0.0, min(100.0, float(score)))
        except (TypeError, ValueError):
            score = 70.0
        dims[key] = {"score": score, "reason": d.get("reason", "")}

    issues = []
    for item in (data.get("issues") or [])[:20]:
        severity = item.get("severity") if item.get("severity") in ("扣分", "降档", "建议") else "建议"
        issues.append(
            {
                "engine": "e3_semantic",
                "level": "L3",
                "severity": severity,
                "location": item.get("location", "技术标"),
                "excerpt": (item.get("excerpt") or "")[:200],
                "rule": "五维语义评审（AI 生成，供参考）",
                "tenderQuote": "",
                "suggestion": item.get("suggestion", ""),
                "confidence": 0.6,
            }
        )

    return {"dimensions": dims, "issues": issues}


def _fallback_result(reason: str, weights: dict | None = None) -> dict:
    weights = weights or DEFAULT_WEIGHTS
    dims = {key: {"score": 70.0, "reason": reason} for key in weights}
    issues = [
        {
            "engine": "e3_semantic",
            "level": "L3",
            "severity": "建议",
            "location": "技术标 / 五维评审",
            "excerpt": reason,
            "rule": "五维语义评审降级提示",
            "tenderQuote": "",
            "suggestion": "请检查 DeepSeek API Key 配置或网络连通性后重试",
            "confidence": 0.3,
        }
    ]
    return {"dimensions": dims, "issues": issues}
