"""E3 技术标五维语义引擎（对应青天第三层「技术标核心 AI 评分点」，前端 L3）。

调用 DeepSeek Chat Completions API，按五维评分标准输出结构化分数与问题清单。
"""

import json

import httpx

from ..config import get_settings
from .rules_data import DEFAULT_WEIGHTS

SYSTEM_PROMPT = """你是"青天大模型"口径的招投标技术标评审专家。请严格按照以下五维评分标准对投标文件技术标内容打分：
- 完整性(30%)：是否覆盖招标文件要求的章节、附表、承诺内容
- 针对性(25%)：是否结合本项目实际（地点/规模/工期/地质等），而非通用模板空话
- 合规性(20%)：是否符合现行工程规范、安全标准
- 可落地性(15%)：是否有具体数字、流程、人员设备配置，而非空洞形容词
- 规范性(10%)：格式、编号、术语是否规范统一

评分时请遵循"虚词自查五规则"：
1. 数字规则：段落应至少包含一个可验证数字
2. 动作规则：动词应为可执行动作，而非空洞态度词（如"加强""确保"）
3. 对象规则：措施应有明确责任对象
4. 验证规则：承诺应有验证方式
5. 密度规则：全文虚词密度不应超过 5%

请仅返回严格的 JSON，不要包含任何其他文字说明，格式如下：
{
  "dimensions": {
    "completeness": {"score": 0-100, "reason": "..."},
    "relevance": {"score": 0-100, "reason": "..."},
    "compliance": {"score": 0-100, "reason": "..."},
    "feasibility": {"score": 0-100, "reason": "..."},
    "standardization": {"score": 0-100, "reason": "..."}
  },
  "issues": [
    {"severity": "扣分|降档|建议", "location": "章节/位置描述", "excerpt": "原文片段", "suggestion": "改写建议"}
  ]
}
"""

MAX_CHARS = 12000


def run(full_text: str) -> dict:
    settings = get_settings()

    if not settings.deepseek_api_key:
        return _fallback_result("未配置 DeepSeek API Key，已使用保守默认分，请人工复核技术标内容")

    truncated = full_text[:MAX_CHARS]
    payload = {
        "model": settings.deepseek_model,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
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
            return _normalize(data)
    except Exception as exc:  # noqa: BLE001 —— 任何网络/解析异常都应降级而不是让整轮预审失败
        return _fallback_result(f"调用 DeepSeek 失败（{exc.__class__.__name__}），已使用保守默认分，请人工复核")


def _normalize(data: dict) -> dict:
    dims: dict[str, dict] = {}
    for key in DEFAULT_WEIGHTS:
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


def _fallback_result(reason: str) -> dict:
    dims = {key: {"score": 70.0, "reason": reason} for key in DEFAULT_WEIGHTS}
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
