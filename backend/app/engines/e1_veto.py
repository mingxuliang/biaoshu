"""E1 一票否决引擎（对应青天第一层「一票否决项」，前端 L1）。

P1 落地后：若项目已完成招标解析（锁定优先，否则用最新一轮 done），
则按该项目的真实招标文件参数（有效期天数、预算上限、资质关键词等）判定；
若项目尚未解析（checklist_params 为空），完全回退到通用正则/关键词。

must_respond 来自锁定尺子中的星号/废标条款：条款核心表述未在投标文件出现则废标。

enabled_keys：管理员在「规则页 / 一票否决」tab 关闭某条时，对应 key 不在集合内，
该条检查整体跳过，不产生 Finding；传 None 表示不做开关过滤（全部启用，兼容旧调用方）。
"""

import re
from datetime import datetime

VALIDITY_KEYWORDS = ["投标有效期"]
VALIDITY_NUMBER_PATTERN = re.compile(r"(\d{1,3})\s*(日历天|天)")

SIGNATURE_KEYWORDS = ["法定代表人", "授权代表", "单位盖章", "公章", "骑缝章", "法人授权书", "授权委托书"]
PLACEHOLDER_PATTERN = re.compile(r"[＿_]{3,}|（\s*）|\(\s*\)")

QUALIFICATION_KEYWORDS = ["资质证书", "安全生产许可证", "营业执照"]
DATE_VALID_UNTIL_PATTERN = re.compile(
    r"有效期(?:至|到)?\s*[:：]?\s*(\d{4})[年\-./](\d{1,2})[月\-./](\d{1,2})"
)

PRICE_KEYWORDS = ["投标报价", "总报价", "投标总价"]
PRICE_WAN_PATTERN = re.compile(r"(?:投标报价|总报价|投标总价)\D{0,12}(-?\d{1,3}(?:,\d{3})*(?:\.\d+)?)\s*万元")
NEGATIVE_PRICE_PATTERN = re.compile(r"(?:投标报价|总报价|投标总价)\D{0,12}-\s*\d")
BASE_PRICE_PATTERN = re.compile(r"(?:评标基准价|基准价|拦标价)\D{0,12}(\d{1,3}(?:,\d{3})*(?:\.\d+)?)\s*万元")
PROVISIONAL_AMOUNT_PATTERN = re.compile(r"暂列金额\D{0,10}(\d+(?:\.\d+)?)\s*万")
LOW_PRICE_EXPLANATION_KEYWORDS = ("说明", "分析", "承诺", "让利", "薄利")

_CJK_RUN = re.compile(r"[\u4e00-\u9fff]{4,}")
_GENERIC_PREFIXES = ("必须", "应当", "须", "应", "提交", "提供", "出具", "附上")
_VETO_TYPE_HINTS = ("星号", "废标")


def _now() -> datetime:
    return datetime.utcnow()


def _finding(severity: str, location: str, excerpt: str, rule: str, suggestion: str, tender_quote: str = "") -> dict:
    return {
        "engine": "e1_veto",
        "level": "L1",
        "severity": severity,
        "location": location,
        "excerpt": excerpt,
        "rule": rule,
        "tenderQuote": tender_quote,
        "suggestion": suggestion,
        "confidence": 0.8,
    }


def _enabled(key: str, enabled_keys: set[str] | None) -> bool:
    return enabled_keys is None or key in enabled_keys


def _clause_keys(clause: str) -> list[str]:
    """从星号条款抽出可检索的中文核心短语。"""
    cjk = "".join(re.findall(r"[\u4e00-\u9fff]", clause or ""))
    for prefix in _GENERIC_PREFIXES:
        cjk = cjk.replace(prefix, "")
    if len(cjk) < 4:
        return _CJK_RUN.findall(clause or "")
    n = 6 if len(cjk) >= 6 else 4
    windows = [cjk[i : i + n] for i in range(0, max(1, len(cjk) - n + 1))]
    if cjk not in windows:
        windows.insert(0, cjk if len(cjk) <= 16 else cjk[:12])
    return windows


def _clause_unanswered(clause: str, full_text: str) -> bool:
    keys = _clause_keys(clause)
    if not keys:
        return False
    return not any(k and k in full_text for k in keys)


def _is_veto_clause(item: dict) -> bool:
    kind = str(item.get("type") or "")
    return any(hint in kind for hint in _VETO_TYPE_HINTS)


def run(
    paragraphs: list[dict],
    checklist_params: dict | None = None,
    must_respond: list | None = None,
    thresholds: dict | None = None,  # 目前仅消费 price_deviation_malicious，其余跨投标人阈值不适用于 E1
    context=None,
    enabled_keys: set[str] | None = None,
) -> list[dict]:
    findings: list[dict] = []
    today = _now()
    full_text = "\n".join(p["text"] for p in paragraphs)

    checklist_params = checklist_params or {}
    validity_days_required = checklist_params.get("validity_days_required")
    budget_cap_wan = checklist_params.get("budget_cap_wan")
    qualification_keywords = checklist_params.get("qualification_keywords") or QUALIFICATION_KEYWORDS
    provisional_amount_wan = checklist_params.get("provisional_amount_wan")
    anonymity_required = bool(checklist_params.get("anonymity_required"))

    price_enabled = _enabled("price", enabled_keys)
    qualification_enabled = _enabled("qualification", enabled_keys)
    bid_elements_enabled = _enabled("bid_elements", enabled_keys)
    star_clause_enabled = _enabled("star_clause", enabled_keys)

    seen_validity = False
    seen_validity_number = False
    seen_validity_days: int | None = None

    for p in paragraphs:
        text = p["text"]

        if bid_elements_enabled and any(k in text for k in VALIDITY_KEYWORDS):
            seen_validity = True
            m_days = VALIDITY_NUMBER_PATTERN.search(text)
            if m_days:
                seen_validity_number = True
                try:
                    seen_validity_days = int(m_days.group(1))
                except ValueError:
                    pass

        if price_enabled and NEGATIVE_PRICE_PATTERN.search(text):
            findings.append(
                _finding(
                    severity="废标",
                    location=f"投标文件 / 段落 {p['index']}",
                    excerpt=text[:150],
                    rule="F02.01 报价不得为负数",
                    suggestion="投标报价出现负数，属于报价废标情形，须重新核对并更正报价表",
                )
            )

        if price_enabled and budget_cap_wan is not None:
            m_price = PRICE_WAN_PATTERN.search(text)
            if m_price:
                try:
                    price_wan = float(m_price.group(1).replace(",", ""))
                except ValueError:
                    price_wan = None
                if price_wan is not None and price_wan > budget_cap_wan:
                    findings.append(
                        _finding(
                            severity="废标",
                            location=f"投标文件 / 段落 {p['index']}",
                            excerpt=text[:150],
                            rule="F02.01 投标报价不得超过预算上限（评标尺子）",
                            suggestion=f"投标报价 {price_wan} 万元超过招标文件预算上限 {budget_cap_wan} 万元，须重新核对报价",
                            tender_quote=f"预算上限 {budget_cap_wan} 万元",
                        )
                    )

        if qualification_enabled:
            for kw in qualification_keywords:
                if kw not in text:
                    continue
                m = DATE_VALID_UNTIL_PATTERN.search(text)
                if not m:
                    continue
                y, mo, d = map(int, m.groups())
                try:
                    expire = datetime(y, mo, d)
                except ValueError:
                    continue
                if expire < today:
                    findings.append(
                        _finding(
                            severity="废标",
                            location=f"投标文件 / 段落 {p['index']}",
                            excerpt=text[:150],
                            rule="F02.02 资质证书须在有效期内",
                            suggestion=f"「{kw}」已于 {y}-{mo:02d}-{d:02d} 过期，须更新为有效证书后重新提交",
                        )
                    )

        if bid_elements_enabled:
            for kw in SIGNATURE_KEYWORDS:
                if kw in text and PLACEHOLDER_PATTERN.search(text):
                    findings.append(
                        _finding(
                            severity="降档",
                            location=f"投标文件 / 段落 {p['index']}",
                            excerpt=text[:150],
                            rule="F02.05 签字盖章须实质性完成",
                            suggestion=f"检测到「{kw}」附近存在占位符（下划线/空括号），请确认已实际签字盖章",
                        )
                    )

        if price_enabled and any(k in text for k in PRICE_KEYWORDS) and PLACEHOLDER_PATTERN.search(text):
            findings.append(
                _finding(
                    severity="废标",
                    location=f"投标文件 / 段落 {p['index']}",
                    excerpt=text[:150],
                    rule="F02.01 报价不得漏项",
                    suggestion="报价栏仍为占位符，属于漏项废标情形，请填入完整投标总价",
                )
            )

        if price_enabled and provisional_amount_wan is not None and "暂列金额" in text:
            m_prov = PROVISIONAL_AMOUNT_PATTERN.search(text)
            if m_prov:
                try:
                    prov_wan = float(m_prov.group(1))
                except ValueError:
                    prov_wan = None
                if prov_wan is not None and abs(prov_wan - provisional_amount_wan) > 0.01:
                    findings.append(
                        _finding(
                            severity="扣分",
                            location=f"投标文件 / 段落 {p['index']}",
                            excerpt=text[:150],
                            rule="F02.01 暂列金额须按招标文件固定填写",
                            suggestion=f"招标文件固定暂列金额为 {provisional_amount_wan} 万元，投标文件填写为 {prov_wan} 万元，须核对一致",
                            tender_quote=f"暂列金额 {provisional_amount_wan} 万元",
                        )
                    )

    if bid_elements_enabled:
        if seen_validity and not seen_validity_number:
            findings.append(
                _finding(
                    severity="废标",
                    location="投标文件 / 投标函",
                    excerpt="投标有效期条款未填写明确天数",
                    rule="F02.03 实质性条款须明确响应",
                    suggestion="补填投标有效期的具体天数（如 90 日历天）并加盖公章",
                )
            )
        elif (
            seen_validity
            and seen_validity_number
            and validity_days_required is not None
            and seen_validity_days is not None
            and seen_validity_days < validity_days_required
        ):
            findings.append(
                _finding(
                    severity="废标",
                    location="投标文件 / 投标函",
                    excerpt=f"投标有效期填写为 {seen_validity_days} 日历天",
                    rule="F02.03 实质性条款须明确响应（评标尺子）",
                    suggestion=f"招标文件要求投标有效期不少于 {validity_days_required} 日历天，当前填写 {seen_validity_days} 天不满足要求",
                    tender_quote=f"投标有效期不少于 {validity_days_required} 日历天",
                )
            )
        elif not seen_validity:
            findings.append(
                _finding(
                    severity="建议",
                    location="投标文件 / 投标函",
                    excerpt="全文未检测到「投标有效期」条款",
                    rule="F02.03 实质性条款须明确响应",
                    suggestion="请人工确认投标函是否包含投标有效期条款",
                )
            )

    if price_enabled:
        m_price = PRICE_WAN_PATTERN.search(full_text)
        m_base = BASE_PRICE_PATTERN.search(full_text)
        if m_price and m_base:
            try:
                price_wan = float(m_price.group(1).replace(",", ""))
                base_wan = float(m_base.group(1).replace(",", ""))
            except ValueError:
                price_wan, base_wan = None, None
            malicious_threshold = (thresholds or {}).get("price_deviation_malicious", 20)
            if price_wan is not None and base_wan and base_wan > 0:
                deviation = (base_wan - price_wan) / base_wan * 100
                if deviation > malicious_threshold and not any(k in full_text for k in LOW_PRICE_EXPLANATION_KEYWORDS):
                    findings.append(
                        _finding(
                            severity="废标",
                            location="投标文件 / 投标报价",
                            excerpt=f"投标报价 {price_wan} 万元，基准价 {base_wan} 万元，低于基准价 {deviation:.1f}%",
                            rule="F02.01 恶意低价须提供说明",
                            suggestion=(
                                f"投标报价低于评标基准价 {malicious_threshold}% 以上且未见成本说明/分析/承诺等解释性文字，"
                                "存在恶意低价嫌疑，须提供书面说明"
                            ),
                            tender_quote=f"报价偏离基准价超过 {malicious_threshold}% 须说明",
                        )
                    )

    if star_clause_enabled:
        for item in must_respond or []:
            if not isinstance(item, dict):
                continue
            if not _is_veto_clause(item):
                continue
            clause = str(item.get("clause") or item.get("text") or "").strip()
            if not clause:
                continue
            if _clause_unanswered(clause, full_text):
                findings.append(
                    _finding(
                        severity="废标",
                        location="投标文件 / 星号条款响应",
                        excerpt=clause[:150],
                        rule="F02.06 星号条款必须全部响应",
                        suggestion="招标文件标记的实质性条款未在投标文件中检出对应响应，任何一条不响应即废标",
                        tender_quote=str(item.get("original") or ""),
                    )
                )

    findings.extend(
        _context_findings(full_text, must_respond or [], context, checklist_params, enabled_keys)
    )
    return findings


def _context_findings(
    full_text: str,
    must_respond: list,
    context,
    checklist_params: dict,
    enabled_keys: set[str] | None,
) -> list[dict]:
    if context is None:
        return []
    extra: list[dict] = []
    tender = getattr(context, "tender_text", "") or ""
    combined_req = tender + "\n" + " ".join(
        str(item.get("clause") or item.get("text") or "") for item in must_respond if isinstance(item, dict)
    )

    bid_elements_enabled = _enabled("bid_elements", enabled_keys)
    personnel_enabled = _enabled("personnel", enabled_keys)
    qualification_enabled = _enabled("qualification", enabled_keys)
    content_match_enabled = _enabled("content_match", enabled_keys)

    quals = list(getattr(context, "quals", []) or [])

    if (
        bid_elements_enabled
        and ("保证金" in combined_req or "投标保证金" in combined_req)
        and "保证金" not in full_text
    ):
        extra.append(
            _finding(
                severity="废标",
                location="投标文件 / 投标保证金",
                excerpt="招标文件要求提交投标保证金，投标文件未检出「保证金」表述",
                rule="F02.05 投标保证金须按招标要求提交",
                suggestion="请在投标文件中写明保证金金额、形式与递交凭证，并附缴款证明",
                tender_quote="招标文件含保证金要求",
            )
        )

    if bid_elements_enabled and checklist_params.get("anonymity_required"):
        certs = [q for q in quals if q.kind == "cert"]
        bidder_name = ""
        for q in certs:
            if "营业执照" in (q.name or "") and (q.owner or "").strip():
                bidder_name = q.owner.strip()
                break
        if bidder_name and len(bidder_name) >= 4 and bidder_name in full_text:
            extra.append(
                _finding(
                    severity="降档",
                    location="投标文件 / 暗标残留",
                    excerpt=f"招标文件要求暗标评审，正文检出本企业名称「{bidder_name}」",
                    rule="F02.05 暗标文件不得出现单位名称",
                    suggestion="请删除正文中出现的本企业名称、徽标等可识别身份信息，避免暗标评审违规",
                )
            )

    personnel_topics = (("项目经理", "建造师"), ("安全员", "安全员"), ("八大员", "八大员"), ("社保", "社保"))
    if personnel_enabled and any(topic in full_text or topic in combined_req for topic, _hint in personnel_topics):
        people = [q for q in quals if q.kind == "people"]
        if "社保" in combined_req or "社保" in full_text:
            has_social = any("社保" in (q.blob or "") for q in people) or "社保" in full_text
            if not has_social:
                extra.append(
                    _finding(
                        severity="降档",
                        location="资格文件 / 人员社保",
                        excerpt="招标或正文涉及社保，但资质库人员条目与投标文件均未检出社保证明关键词",
                        rule="F02.02 人员核查-社保证明",
                        suggestion="请在资质证照库录入人员及社保证明，并在投标文件中附对应材料。本系统不联网社保局，只核验已入库材料与正文关键词",
                    )
                )
        if "项目经理" in full_text or "项目经理" in combined_req:
            if not any("项目经理" in (q.blob or "") or "建造师" in (q.blob or "") for q in people):
                extra.append(
                    _finding(
                        severity="降档",
                        location="资格文件 / 项目经理",
                        excerpt="正文或招标要求项目经理，但企业资质库未录入对应人员证书",
                        rule="F02.02 人员核查-项目经理证书",
                        suggestion="请在资质证照库录入项目经理/注册建造师证书后再提交",
                    )
                )

    if qualification_enabled:
        cert_names = ("营业执照", "安全生产许可证", "资质证书")
        certs = [q for q in quals if q.kind == "cert"]
        for cert_name in cert_names:
            if cert_name not in full_text and cert_name not in combined_req:
                continue
            matched = [q for q in certs if cert_name in (q.name or "") or cert_name in (q.blob or "")]
            if not matched and cert_name == "资质证书":
                matched = [q for q in certs if "施工" in (q.name or "") or "承包" in (q.name or "")]
            if not matched:
                extra.append(
                    _finding(
                        severity="降档",
                        location=f"资格文件 / {cert_name}",
                        excerpt=f"投标文件或招标要求涉及「{cert_name}」，企业资质库未找到对应条目",
                        rule="F02.02 资质证书须入库可核验",
                        suggestion=f"请在资质证照库录入有效的「{cert_name}」扫描件，预审按库内材料核验，不编造证号",
                    )
                )
            elif any(q.expired for q in matched):
                extra.append(
                    _finding(
                        severity="废标",
                        location=f"资格文件 / {cert_name}",
                        excerpt=f"资质库中「{matched[0].name}」已过有效期",
                        rule="F02.02 资质证书须在有效期内",
                        suggestion="请更新为仍在有效期内的证书后再提交",
                    )
                )

    if content_match_enabled:
        current_name = (getattr(context, "project_name", "") or "").strip()
        for other in getattr(context, "other_project_names", []) or []:
            if not other or other == current_name:
                continue
            if other in full_text:
                extra.append(
                    _finding(
                        severity="废标",
                        location="投标文件 / 内容错配",
                        excerpt=other[:80],
                        rule="F02.07 不得出现其他项目名称",
                        suggestion=f"检出本企业其他项目名称「{other}」，请替换为本项目全称，避免串稿",
                    )
                )
                break

    return extra
