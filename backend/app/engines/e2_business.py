"""E2 商务客观核验引擎（对应青天第二层「商务标 AI 打分自查项」，前端 L2）。

阈值优先级：项目已锁定评标尺子（checklist_params 携带 asset_liability_ratio_max）＞
调用方传入的 thresholds（规则页真实配置）＞ rules_data.THRESHOLDS 兜底默认值。

属地细则：仅在正文已写到对应主题（临边/扫地杆/扬尘）却缺少启用包中的量化要求时扣分，
不因未写该主题而凭空否决。

biz_keys/veto_keys/strategy_keys/dup_keys：管理员在规则页关闭对应条目时，这里跳过相应检查块；
传 None 表示不做开关过滤（全部启用，兼容旧调用方）。
资产负债率上限由专项检查「资产负债率」开关控制，商务自查「财务指标」只核验资料完整性。
"""

import re

from .excerpt_guard import hit_sentence
from .rules_data import THRESHOLDS

PERFORMANCE_KEYWORDS = ["业绩", "类似项目", "施工业绩"]
FOUR_PIECES = ["中标通知书", "合同", "竣工验收", "官网"]
PERFORMANCE_QUANTIFIER_PATTERN = re.compile(r"\d+(?:\.\d+)?\s*(?:项|个|万元|㎡|平方米|年|月|km|公里)")

ASSET_LIABILITY_PATTERN = re.compile(r"资产负债率\D{0,10}(\d{1,3}(?:\.\d+)?)\s*%")
PRICE_WAN_PATTERN = re.compile(r"(?:投标报价|总报价|投标总价)\D{0,12}(-?\d{1,3}(?:,\d{3})*(?:\.\d+)?)\s*万元")
BASE_PRICE_PATTERN = re.compile(r"(?:评标基准价|基准价|拦标价)\D{0,12}(\d{1,3}(?:,\d{3})*(?:\.\d+)?)\s*万元")
FINANCE_TOPIC_KEYWORDS = ("财务指标", "资产负债率", "财务状况")
FINANCE_COMPLETENESS_KEYWORDS = (("营业收入", "营收"), ("现金流",), ("审计报告",))

SENTENCE_SPLIT = re.compile(r"[。！？；\n]")

HONOR_KEYS = ("ISO", "iso", "荣誉", "奖项", "体系认证")
HONOR_PROOF = ("证书", "证书编号", "有效期", "认证证书", "扫描件")
STAFF_KEYS = ("拟派项目经理", "人员表", "持证上岗", "拟派人员")
STAFF_PROOF = ("证书编号", "注册证书", "执业资格", "身份证", "职称证", "建造师证")
EQUIP_KEYS = ("机械", "盾构", "塔吊", "挖掘机", "泵车")
EQUIP_PROOF = ("设备清单", "型号", "台账", "购置发票", "租赁协议", "租赁合同")
LOCAL_KEYS = ("本地分支", "分支机构", "售后网点", "售后服务网点")
CREDIT_KEYS = ("信用中国", "政府采购网", "失信")
CREDIT_PROOF = ("查询截图", "无违法", "无失信", "信用报告", "截图")

LOCAL_ITEM_CHECKS = [
    {
        "hint": "临边防护高度 1.2m",
        "topic": ("临边",),
        "required": ("1.2m", "1.2米", "1.2 m"),
        "rule": "属地细则-临边防护高度 1.2m",
        "suggestion": "正文已写临边防护，但未写明高度 1.2m，请按启用的属地细则补全",
    },
    {
        "hint": "扫地杆距地 ≤20cm",
        "topic": ("扫地杆",),
        "required": ("20cm", "20厘米", "≤20", "不大于20", "不超过20"),
        "rule": "属地细则-扫地杆距地 ≤20cm",
        "suggestion": "正文已写扫地杆，但未写明距地 ≤20cm，请按启用的属地细则补全",
    },
    {
        "hint": "扬尘",
        "topic": ("扬尘",),
        "required": ("100%", "六个100", "6个100", "6 个 100"),
        "rule": "属地细则-扬尘六个 100%",
        "suggestion": "正文已写扬尘防治，但未写明六个 100% 等量化要求，请按启用的属地细则补全",
    },
]


def _finding(severity: str, location: str, excerpt: str, rule: str, suggestion: str, tender_quote: str = "") -> dict:
    return {
        "engine": "e2_business",
        "level": "L2",
        "severity": severity,
        "location": location,
        "excerpt": excerpt,
        "rule": rule,
        "tenderQuote": tender_quote,
        "suggestion": suggestion,
        "confidence": 0.75,
    }


def _enabled(key: str, enabled_keys: set[str] | None) -> bool:
    return enabled_keys is None or key in enabled_keys


def _item_enabled(local_items: list[str], hint: str) -> bool:
    return any(hint in (item or "") for item in local_items)


def run(
    paragraphs: list[dict],
    checklist_params: dict | None = None,
    thresholds: dict | None = None,
    local_items: list[str] | None = None,
    context=None,
    biz_keys: set[str] | None = None,
    veto_keys: set[str] | None = None,
    strategy_keys: set[str] | None = None,
    dup_keys: set[str] | None = None,
) -> list[dict]:
    findings: list[dict] = []
    text_blocks = [p["text"] for p in paragraphs]
    full_text = "\n".join(text_blocks)

    checklist_params = checklist_params or {}
    thresholds = thresholds or THRESHOLDS
    local_items = local_items if local_items is not None else []
    ratio_max = checklist_params.get("asset_liability_ratio_max")
    if ratio_max is None:
        ratio_max = thresholds.get("asset_liability_ratio_max", THRESHOLDS["asset_liability_ratio_max"])
    ok_dev = thresholds.get("price_deviation_ok", THRESHOLDS.get("price_deviation_ok", 5))
    warn_dev = thresholds.get("price_deviation_warn", THRESHOLDS.get("price_deviation_warn", 10))

    performance_enabled = _enabled("performance", biz_keys)
    finance_enabled = _enabled("finance", biz_keys)
    asset_liability_enabled = _enabled("asset_liability", dup_keys)
    price_deviation_enabled = _enabled("price_deviation", dup_keys)

    flagged_windows: set[int] = set()
    if performance_enabled:
        for idx, p in enumerate(paragraphs):
            text = p["text"]
            if not any(k in text for k in PERFORMANCE_KEYWORDS):
                continue
            window_key = idx // 6
            if window_key in flagged_windows:
                continue
            window = "\n".join(text_blocks[idx : idx + 6])
            missing = [kw for kw in FOUR_PIECES if kw not in window]
            if missing:
                flagged_windows.add(window_key)
                findings.append(
                    _finding(
                        severity="降档",
                        location=f"商务标 / 业绩证明 / 段落 {p['index']}",
                        excerpt=_hit_excerpt(text, [{"text": text}], PERFORMANCE_KEYWORDS),
                        rule="F03.05 业绩四件套齐全才计分",
                        suggestion=f"该业绩缺少：{'、'.join(missing)}，请补充佐证材料，否则该项业绩不予计分",
                    )
                )
            elif not PERFORMANCE_QUANTIFIER_PATTERN.search(window):
                flagged_windows.add(window_key)
                findings.append(
                    _finding(
                        severity="建议",
                        location=f"商务标 / 业绩证明 / 段落 {p['index']}",
                        excerpt=_hit_excerpt(text, [{"text": text}], PERFORMANCE_KEYWORDS),
                        rule="F03.05 业绩数量/规模/时间须量化",
                        suggestion="该业绩缺少可核验的数量、规模或时间数据（如合同金额、建筑面积、完工年月），请补充具体数字",
                    )
                )

    if asset_liability_enabled:
        m = ASSET_LIABILITY_PATTERN.search(full_text)
        if m:
            ratio = float(m.group(1))
            if ratio > ratio_max:
                findings.append(
                    _finding(
                        severity="扣分",
                        location="资格文件 / 财务指标",
                        excerpt=m.group(0),
                        rule="F02.04 财务要求核对",
                        suggestion=(
                            f"资产负债率 {ratio}% 超过 {ratio_max}% 上限，"
                            "请核对最新年度报表或附说明函"
                        ),
                        tender_quote=f"资产负债率不高于 {ratio_max}%" if checklist_params.get("asset_liability_ratio_max") is not None else "",
                    )
                )
    if finance_enabled:
        if any(k in full_text for k in FINANCE_TOPIC_KEYWORDS):
            missing_finance = [
                labels[0]
                for labels in FINANCE_COMPLETENESS_KEYWORDS
                if not any(kw in full_text for kw in labels)
            ]
            if len(missing_finance) >= 2:
                findings.append(
                    _finding(
                        severity="扣分",
                        location="资格文件 / 财务指标",
                        excerpt=_hit_excerpt(full_text, paragraphs, FINANCE_TOPIC_KEYWORDS),
                        rule="F02.04 财务资料完整性",
                        suggestion=f"财务部分缺少：{'、'.join(missing_finance)}，近三年营收、现金流、审计报告须完整清晰、数据前后一致",
                    )
                )

    if price_deviation_enabled:
        m_price = PRICE_WAN_PATTERN.search(full_text)
        m_base = BASE_PRICE_PATTERN.search(full_text)
        if m_price and m_base:
            try:
                price = float(m_price.group(1).replace(",", ""))
                base = float(m_base.group(1).replace(",", ""))
            except ValueError:
                price, base = None, None
            if price is not None and base and base > 0 and price >= 0:
                deviation = abs(price - base) / base * 100
                if deviation > warn_dev:
                    findings.append(
                        _finding(
                            severity="降档",
                            location="商务标 / 投标报价",
                            excerpt=f"{m_price.group(0)}；{m_base.group(0)}",
                            rule="F02.01 报价偏离预警",
                            suggestion=f"相对评标基准价偏离 {deviation:.1f}%，超过 {warn_dev}%。请附成本分析或合理说明，避免被认定为异常价",
                        )
                    )
                elif deviation > ok_dev:
                    findings.append(
                        _finding(
                            severity="扣分",
                            location="商务标 / 投标报价",
                            excerpt=f"{m_price.group(0)}；{m_base.group(0)}",
                            rule="F02.01 报价偏离扣分",
                            suggestion=f"相对评标基准价偏离 {deviation:.1f}%，超过 {ok_dev}%。请复核报价组成",
                        )
                    )

    for spec in LOCAL_ITEM_CHECKS:
        if not _item_enabled(local_items, spec["hint"]):
            continue
        if not any(topic in full_text for topic in spec["topic"]):
            continue
        if any(req in full_text for req in spec["required"]):
            continue
        findings.append(
            _finding(
                severity="扣分",
                location="技术标 / 属地细则",
                excerpt=_hit_excerpt(full_text, paragraphs, spec["topic"]),
                rule=spec["rule"],
                suggestion=spec["suggestion"],
            )
        )

    findings.extend(_bid_material_findings(full_text, paragraphs, checklist_params, biz_keys, strategy_keys))
    return findings


def _hit_excerpt(full_text: str, paragraphs: list[dict] | None, keywords: tuple[str, ...] | list[str]) -> str:
    return hit_sentence(full_text, paragraphs, keywords, skip_score_voice=True)


def _has_any(text: str, keys: tuple[str, ...]) -> bool:
    return any(k in (text or "") for k in keys)


def _bid_material_findings(
    full_text: str,
    paragraphs: list[dict],
    checklist_params: dict,
    biz_keys: set[str] | None,
    strategy_keys: set[str] | None,
) -> list[dict]:
    """商务材料核验只读投标书原文，不查询资质证照库。"""
    extra: list[dict] = []
    honor_enabled = _enabled("honor", biz_keys)
    localization_enabled = _enabled("localization", biz_keys)
    staffing_enabled = _enabled("staffing", biz_keys)
    equipment_enabled = _enabled("equipment", biz_keys)
    credit_enabled = _enabled("credit", biz_keys)
    data_loop_enabled = _enabled("data_loop", strategy_keys)
    code_cite_enabled = _enabled("code_cite", strategy_keys)

    if honor_enabled and _has_any(full_text, HONOR_KEYS) and not _has_any(full_text, HONOR_PROOF):
        extra.append(
            _finding(
                severity="扣分",
                location="商务标 / 荣誉认证",
                excerpt=_hit_excerpt(full_text, paragraphs, HONOR_KEYS),
                rule="F03.06 荣誉认证须附有效期内证书",
                suggestion="投标书写到荣誉或体系认证，但未检出证书编号/有效期。请在商务标中附有效期内证书扫描件及编号，勿只写套话",
            )
        )

    if localization_enabled:
        if _hit_excerpt(full_text, paragraphs, LOCAL_KEYS):
            missing = [k for k in ("分支", "网点", "备品") if k not in full_text]
            if len(missing) >= 2:
                extra.append(
                    _finding(
                        severity="扣分",
                        location="商务标 / 本地化服务",
                        excerpt=_hit_excerpt(full_text, paragraphs, LOCAL_KEYS),
                        rule="F03.07 本地化服务要素",
                        suggestion="请在投标书中补齐本地分支机构、售后网点、备品备件库与应急响应方案的具体地址或时限",
                    )
                )

    if staffing_enabled:
        personnel_required: dict = checklist_params.get("personnel_required") or {}
        if personnel_required:
            for role, required_count in personnel_required.items():
                if not role:
                    continue
                if role not in full_text:
                    extra.append(
                        _finding(
                            severity="扣分",
                            location="商务标 / 人员配置",
                            excerpt="",
                            rule="F03.08 岗位持证人数达标",
                            suggestion=f"招标要求「{role}」不少于 {required_count} 人，投标书未检出该岗位。请在人员表中列明姓名、证书专业与编号",
                            tender_quote=f"{role}不少于 {required_count} 人",
                        )
                    )
                elif not _has_any(full_text, STAFF_PROOF):
                    extra.append(
                        _finding(
                            severity="扣分",
                            location="商务标 / 人员配置",
                            excerpt=_hit_excerpt(full_text, paragraphs, (role,)),
                            rule="F03.08 岗位证书人数",
                            suggestion=f"投标书写到「{role}」，但未检出证书编号或注册信息。请在商务标人员表中附证书",
                            tender_quote=f"{role}不少于 {required_count} 人",
                        )
                    )
        elif _hit_excerpt(full_text, paragraphs, STAFF_KEYS) and not _has_any(full_text, STAFF_PROOF):
            extra.append(
                _finding(
                    severity="扣分",
                    location="商务标 / 人员配置",
                    excerpt=_hit_excerpt(full_text, paragraphs, STAFF_KEYS),
                    rule="F03.08 岗位证书人数",
                    suggestion="投标书写到人员配置，但未检出证书编号/注册证书。请在商务标中附岗位人员证书，勿只写岗位名称",
                )
            )

    if equipment_enabled:
        equip_hit = _hit_excerpt(full_text, paragraphs, EQUIP_KEYS)
        if equip_hit and any(bad in equip_hit for bad in ("网络关键", "网络安全", "关键信息")):
            equip_hit = ""
        if not equip_hit:
            for eq_name in (checklist_params.get("equipment_required") or {}):
                if eq_name and eq_name in full_text:
                    equip_hit = _hit_excerpt(full_text, paragraphs, (eq_name,))
                    break
        equipment_required: dict = checklist_params.get("equipment_required") or {}
        if equipment_required:
            for eq_name, required_count in equipment_required.items():
                if not eq_name:
                    continue
                if eq_name not in full_text:
                    extra.append(
                        _finding(
                            severity="扣分",
                            location="商务标 / 设备机械",
                            excerpt="",
                            rule="F03.09 设备型号数量达标",
                            suggestion=f"招标要求「{eq_name}」不少于 {required_count} 台/套，投标书未检出该设备。请在设备表中列明型号与数量",
                            tender_quote=f"{eq_name}不少于 {required_count} 台/套",
                        )
                    )
        if equip_hit and not _has_any(full_text, EQUIP_PROOF):
            extra.append(
                _finding(
                    severity="扣分",
                    location="商务标 / 设备机械",
                    excerpt=equip_hit,
                    rule="F03.09 设备清单与权属",
                    suggestion="投标书写到设备或机械，但未检出设备清单、型号或购置发票/租赁协议。请在商务标中附设备表及权属证明",
                )
            )
        elif equip_hit and not _has_any(full_text, ("发票", "租赁")):
            extra.append(
                _finding(
                    severity="建议",
                    location="商务标 / 设备机械",
                    excerpt=equip_hit,
                    rule="F03.09 设备权属证明",
                    suggestion="设备清单已写，但未写明购置发票或租赁协议。请在投标书中补充权属证明附件说明",
                )
            )

    if credit_enabled and _has_any(full_text, CREDIT_KEYS) and not _has_any(full_text, CREDIT_PROOF):
        extra.append(
            _finding(
                severity="扣分",
                location="商务标 / 信用记录",
                excerpt=_hit_excerpt(full_text, paragraphs, CREDIT_KEYS),
                rule="F03.10 信用记录须附查询截图",
                suggestion="投标书提及信用查询，但未检出查询截图或无失信结论。请在商务标中附信用中国/政府采购网查询截图",
            )
        )

    if data_loop_enabled:
        people_n = re.search(r"(?:高峰人数|劳动力|施工人数)\D{0,8}(\d{2,4})\s*人", full_text)
        area_n = re.search(r"(?:宿舍|临建)\D{0,12}(\d{2,5})\s*(?:㎡|平方米|平米)", full_text)
        if people_n and area_n:
            headcount = int(people_n.group(1))
            area = int(area_n.group(1))
            if headcount > 0 and area / headcount < 4:
                extra.append(
                    _finding(
                        severity="扣分",
                        location="技术标 / 数据链闭环",
                        excerpt=f"{people_n.group(0)}；{area_n.group(0)}",
                        rule="F06.07 高峰人数与宿舍面积交叉验算",
                        suggestion="高峰人数与宿舍/临建面积交叉验算人均不足 4㎡。请按人均不少于 4㎡ 调整临建面积或劳动力峰值",
                    )
                )

    if code_cite_enabled and "废止" in full_text and re.search(r"GB[/\s]?\d|JGJ|JTG", full_text):
        extra.append(
            _finding(
                severity="建议",
                location="技术标 / 规范引用",
                excerpt=_hit_excerpt(full_text, paragraphs, ("废止",)),
                rule="F06.08 不使用废止规范",
                suggestion="请对照官方废止公告核对条文号，避免引用已废止规范",
            )
        )

    return extra
