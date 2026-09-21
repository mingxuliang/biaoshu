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

from .clause_cover import CAPS, cap_overflow_finding, check_clause

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
SENTENCE_SPLIT = re.compile(r"[。！？；\n]")

CERT_NAMES = ("营业执照", "安全生产许可证", "资质证书")
CERT_PROOF = {
    "营业执照": ("统一社会信用代码", "信用代码", "营业执照副本", "登记机关", "经营范围"),
    "安全生产许可证": ("安全生产许可证号", "许可范围", "安许证"),
    "资质证书": ("资质证书编号", "资质等级", "施工总承包", "专业承包", "证书编号"),
}
STAFF_PROOF = ("证书编号", "注册证书", "执业资格", "建造师", "职称证")
SOCIAL_PROOF = ("社保证明", "社保缴纳", "参保", "养老保险", "缴纳单位")


def _now() -> datetime:
    return datetime.utcnow()


def _finding(
    severity: str,
    location: str,
    excerpt: str,
    rule: str,
    suggestion: str,
    tender_quote: str = "",
    *,
    unanswered_confirmed: bool = False,
    evidence_ok: bool = False,
    issue_class: str = "",
) -> dict:
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
        "unansweredConfirmed": unanswered_confirmed,
        "evidenceOk": evidence_ok,
        "issueClass": issue_class,
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


def _hit_excerpt(full_text: str, paragraphs: list[dict] | None, keywords: tuple[str, ...] | list[str]) -> str:
    return hit_sentence(full_text, paragraphs, keywords, skip_score_voice=True)


def _hit_tender(combined_req: str, keywords: tuple[str, ...] | list[str]) -> str:
    hit = hit_sentence(combined_req, None, keywords, skip_reject=True)
    return hit or hit_sentence(combined_req, None, keywords)


def _has_any(text: str, keys: tuple[str, ...]) -> bool:
    return any(k in (text or "") for k in keys)


def run(
    paragraphs: list[dict],
    checklist_params: dict | None = None,
    must_respond: list | None = None,
    thresholds: dict | None = None,  # 恶意低价线 price_deviation_malicious，由专项检查「报价偏离」开关控制
    context=None,
    enabled_keys: set[str] | None = None,
    dup_keys: set[str] | None = None,
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
    price_deviation_enabled = _enabled("price_deviation", dup_keys)
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
                    excerpt=_hit_excerpt(text, [{"text": text}], PRICE_KEYWORDS),
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
                            excerpt=_hit_excerpt(text, [{"text": text}], PRICE_KEYWORDS),
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
                            excerpt=_hit_excerpt(text, [{"text": text}], (kw,)),
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
                            excerpt=_hit_excerpt(text, [{"text": text}], (kw,)),
                            rule="F02.05 签字盖章须实质性完成",
                            suggestion=f"检测到「{kw}」附近存在占位符（下划线/空括号），请确认已实际签字盖章",
                        )
                    )

        if price_enabled and any(k in text for k in PRICE_KEYWORDS) and PLACEHOLDER_PATTERN.search(text):
            findings.append(
                _finding(
                    severity="废标",
                    location=f"投标文件 / 段落 {p['index']}",
                    excerpt=_hit_excerpt(text, [{"text": text}], PRICE_KEYWORDS),
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
                            excerpt=_hit_excerpt(text, [{"text": text}], ("暂列金额",)),
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
                    excerpt=_hit_excerpt(full_text, paragraphs, VALIDITY_KEYWORDS),
                    rule="F02.03 实质性条款须明确响应",
                    suggestion="投标有效期条款未填写明确天数。请补填具体天数（如 90 日历天）并加盖公章",
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
                    excerpt=_hit_excerpt(full_text, paragraphs, VALIDITY_KEYWORDS),
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
                    excerpt="",
                    rule="F02.03 实质性条款须明确响应",
                    suggestion="投标书全文未检出「投标有效期」条款。请人工确认投标函是否包含投标有效期并写明天数",
                    issue_class="human_check",
                    evidence_ok=True,
                )
            )

    if price_deviation_enabled:
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
                            excerpt=f"{m_price.group(0)}；{m_base.group(0)}",
                            rule="F02.01 恶意低价须提供说明",
                            suggestion=(
                                f"投标报价低于评标基准价 {malicious_threshold}% 以上且未见成本说明/分析/承诺等解释性文字，"
                                "存在恶意低价嫌疑，须提供书面说明"
                            ),
                            tender_quote=f"报价偏离基准价超过 {malicious_threshold}% 须说明",
                        )
                    )

    if star_clause_enabled:
        pending = []
        for item in must_respond or []:
            if not isinstance(item, dict):
                continue
            if not _is_veto_clause(item):
                continue
            clause = str(item.get("clause") or item.get("text") or "").strip()
            if not clause:
                continue
            pending.append((item, check_clause(clause, bid=full_text, paragraphs=paragraphs)))
        kept = 0
        omitted = 0
        for item, result in pending:
            if result.answered:
                continue
            if kept >= CAPS["star"]:
                omitted += 1
                continue
            kept += 1
            findings.append(
                _finding(
                    severity="废标",
                    location=f"投标文件 / 星号条款响应 / {item.get('original') or '未标注'}",
                    excerpt=result.excerpt,
                    rule="F02.06 星号条款必须全部响应",
                    suggestion=result.reason or "招标文件标记的实质性条款未确认对应响应，请按原文补写",
                    tender_quote=str(item.get("clause") or item.get("text") or "")[:500],
                    unanswered_confirmed=result.unanswered_confirmed,
                )
            )
        if omitted:
            findings.append(cap_overflow_finding("star", omitted, "L1", "废标"))

    findings.extend(
        _context_findings(full_text, paragraphs, must_respond or [], context, checklist_params, enabled_keys)
    )
    return findings


def _context_findings(
    full_text: str,
    paragraphs: list[dict],
    must_respond: list,
    context,
    checklist_params: dict,
    enabled_keys: set[str] | None,
) -> list[dict]:
    extra: list[dict] = []
    tender = getattr(context, "tender_text", "") or "" if context is not None else ""
    combined_req = tender + "\n" + " ".join(
        str(item.get("clause") or item.get("text") or "") for item in must_respond if isinstance(item, dict)
    )

    bid_elements_enabled = _enabled("bid_elements", enabled_keys)
    personnel_enabled = _enabled("personnel", enabled_keys)
    qualification_enabled = _enabled("qualification", enabled_keys)
    content_match_enabled = _enabled("content_match", enabled_keys)

    if bid_elements_enabled and ("保证金" in combined_req or "投标保证金" in combined_req):
        cover = check_clause("投标保证金", bid=full_text, paragraphs=paragraphs, title="保证金")
        if not cover.answered:
            extra.append(
                _finding(
                    severity="降档",
                    location="投标文件 / 投标保证金",
                    excerpt=cover.excerpt,
                    rule="F02.05 投标保证金须按招标要求提交",
                    suggestion=cover.reason or "招标要求提交投标保证金，投标书未确认对应表述。请写明金额、形式与递交凭证",
                    tender_quote=_hit_tender(combined_req, ("投标保证金", "保证金")),
                    unanswered_confirmed=cover.unanswered_confirmed,
                    issue_class="human_check",
                )
            )

    if bid_elements_enabled and checklist_params.get("anonymity_required") and context is not None:
        bidder_name = ""
        for q in getattr(context, "quals", []) or []:
            if getattr(q, "kind", "") == "cert" and "营业执照" in (getattr(q, "name", "") or "") and (getattr(q, "owner", "") or "").strip():
                bidder_name = q.owner.strip()
                break
        if bidder_name and len(bidder_name) >= 4 and bidder_name in full_text:
            extra.append(
                _finding(
                    severity="降档",
                    location="投标文件 / 暗标残留",
                    excerpt=_hit_excerpt(full_text, paragraphs, (bidder_name,)),
                    rule="F02.05 暗标文件不得出现单位名称",
                    suggestion=f"招标要求暗标评审，投标书正文出现本企业名称「{bidder_name}」。请删除单位名称、徽标等可识别身份信息",
                )
            )

    if personnel_enabled:
        if "社保" in full_text:
            if not _has_any(full_text, SOCIAL_PROOF):
                extra.append(
                    _finding(
                        severity="降档",
                        location="资格文件 / 人员社保",
                        excerpt=_hit_excerpt(full_text, paragraphs, ("社保",)),
                        rule="F02.02 人员核查-社保证明",
                        suggestion="投标书写到社保，但未检出缴纳证明、参保或养老保险等可核验表述。请在资格文件中附社保证明",
                        issue_class="human_check",
                    )
                )
        elif "社保" in combined_req:
            extra.append(
                _finding(
                    severity="降档",
                    location="资格文件 / 人员社保",
                    excerpt="",
                    rule="F02.02 人员核查-社保证明",
                    suggestion="招标要求提供社保证明，投标书未检出相关表述。请在资格文件中附人员社保证明",
                    tender_quote=_hit_tender(combined_req, ("社保",)),
                    issue_class="human_check",
                    unanswered_confirmed=True,
                )
            )
        if "项目经理" in full_text:
            if not _has_any(full_text, STAFF_PROOF):
                extra.append(
                    _finding(
                        severity="降档",
                        location="资格文件 / 项目经理",
                        excerpt=_hit_excerpt(full_text, paragraphs, ("项目经理",)),
                        rule="F02.02 人员核查-项目经理证书",
                        suggestion="投标书写到项目经理，但未检出建造师/证书编号或注册信息。请在资格文件中附项目经理证书",
                    )
                )
        elif "项目经理" in combined_req:
            extra.append(
                _finding(
                    severity="降档",
                    location="资格文件 / 项目经理",
                    excerpt="",
                    rule="F02.02 人员核查-项目经理证书",
                    suggestion="招标要求配备项目经理，投标书未检出该岗位。请在资格文件中列明项目经理及证书",
                    tender_quote=_hit_tender(combined_req, ("项目经理",)),
                )
            )

    if qualification_enabled:
        for cert_name in CERT_NAMES:
            in_bid = cert_name in full_text
            in_tender = cert_name in combined_req
            if not in_bid and not in_tender:
                continue
            if in_bid and not _has_any(full_text, CERT_PROOF.get(cert_name, ())):
                extra.append(
                    _finding(
                        severity="降档",
                        location=f"资格文件 / {cert_name}",
                        excerpt=_hit_excerpt(full_text, paragraphs, (cert_name,)),
                        rule="F02.02 资质证书须在投标书中可核验",
                        suggestion=f"投标书写到「{cert_name}」，但未检出证号、有效期或副本等可核验信息。请在资格文件中附扫描件并写明证号与有效期",
                        tender_quote=_hit_tender(combined_req, (cert_name,)) if in_tender else "",
                    )
                )
            elif in_tender and not in_bid:
                extra.append(
                    _finding(
                        severity="降档",
                        location=f"资格文件 / {cert_name}",
                        excerpt="",
                        rule="F02.02 资质证书须在投标书中可核验",
                        suggestion=f"招标要求提供「{cert_name}」，投标书未检出。请在资格文件中附有效扫描件并写明证号与有效期",
                        tender_quote=_hit_tender(combined_req, (cert_name,)),
                    )
                )

    if content_match_enabled and context is not None:
        current_name = (getattr(context, "project_name", "") or "").strip()
        for other in getattr(context, "other_project_names", []) or []:
            if not other or other == current_name:
                continue
            if other in full_text:
                extra.append(
                    _finding(
                        severity="废标",
                        location="投标文件 / 内容错配",
                        excerpt=_hit_excerpt(full_text, paragraphs, (other,)),
                        rule="F02.07 不得出现其他项目名称",
                        suggestion=f"投标书检出本企业其他项目名称「{other}」，请替换为本项目全称，避免串稿",
                    )
                )
                break

    if _enabled("collusion", enabled_keys) and context is not None:
        current_hash = getattr(context, "current_hash", "") or ""
        for label, digest in getattr(context, "other_file_hashes", []) or []:
            if current_hash and digest and digest == current_hash:
                extra.append(
                    _finding(
                        severity="废标",
                        location="投标文件 / 串标痕迹",
                        excerpt="",
                        rule="F02.08 本企业历史标书文件哈希相同",
                        suggestion=f"当前投标文件与本企业项目「{label}」的文件 MD5 完全相同，请确认是否误用历史标书。不比对其他投标人未公开文件。",
                        evidence_ok=True,
                    )
                )
                break
        hits = 0
        for label, sent in getattr(context, "other_sentences", []) or []:
            if hits >= 3:
                break
            if len(sent) < 40 or sent not in full_text:
                continue
            extra.append(
                _finding(
                    severity="降档",
                    location="投标文件 / 历史标书雷同",
                    excerpt=_hit_excerpt(full_text, paragraphs, (sent[:12],)) or sent[:180],
                    rule="F02.08 与本企业历史标书长句完全相同",
                    suggestion=f"检出与本企业项目「{label}」相同的长句，请改写为本项目针对性表述。",
                )
            )
            hits += 1

    return extra
