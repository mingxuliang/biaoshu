"""E2 商务客观核验引擎（对应青天第二层「商务标 AI 打分自查项」，前端 L2）。

阈值优先级：项目已锁定评标尺子（checklist_params 携带 asset_liability_ratio_max）＞
调用方传入的 thresholds（规则页真实配置）＞ rules_data.THRESHOLDS 兜底默认值。

属地细则：仅在正文已写到对应主题（临边/扫地杆/扬尘）却缺少启用包中的量化要求时扣分，
不因未写该主题而凭空否决。
"""

import re

from .rules_data import THRESHOLDS

PERFORMANCE_KEYWORDS = ["业绩", "类似项目", "施工业绩"]
FOUR_PIECES = ["中标通知书", "合同", "竣工验收", "官网"]

ASSET_LIABILITY_PATTERN = re.compile(r"资产负债率\D{0,10}(\d{1,3}(?:\.\d+)?)\s*%")
PRICE_WAN_PATTERN = re.compile(r"(?:投标报价|总报价|投标总价)\D{0,12}(-?\d{1,3}(?:,\d{3})*(?:\.\d+)?)\s*万元")
BASE_PRICE_PATTERN = re.compile(r"(?:评标基准价|基准价|拦标价)\D{0,12}(\d{1,3}(?:,\d{3})*(?:\.\d+)?)\s*万元")

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


def _item_enabled(local_items: list[str], hint: str) -> bool:
    return any(hint in (item or "") for item in local_items)


def run(
    paragraphs: list[dict],
    checklist_params: dict | None = None,
    thresholds: dict | None = None,
    local_items: list[str] | None = None,
    context=None,
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

    flagged_windows: set[int] = set()
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
                    excerpt=text[:150],
                    rule="F03.05 业绩四件套齐全才计分",
                    suggestion=f"该业绩缺少：{'、'.join(missing)}，请补充佐证材料，否则该项业绩不予计分",
                )
            )

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
                        excerpt=f"投标报价 {price} 万元，基准价 {base} 万元，偏离 {deviation:.1f}%",
                        rule="F02.01 报价偏离预警",
                        suggestion=f"相对评标基准价偏离超过 {warn_dev}%，请附成本分析或合理说明，避免被认定为异常价",
                    )
                )
            elif deviation > ok_dev:
                findings.append(
                    _finding(
                        severity="扣分",
                        location="商务标 / 投标报价",
                        excerpt=f"投标报价 {price} 万元，基准价 {base} 万元，偏离 {deviation:.1f}%",
                        rule="F02.01 报价偏离扣分",
                        suggestion=f"相对评标基准价偏离超过 {ok_dev}%，请复核报价组成",
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
                excerpt="、".join(spec["topic"]),
                rule=spec["rule"],
                suggestion=spec["suggestion"],
            )
        )

    findings.extend(_context_findings(full_text, context))
    return findings


def _has_qual(quals: list, *keywords: str, kind: str | None = None) -> bool:
    for item in quals:
        if kind and item.kind != kind:
            continue
        blob = item.blob or ""
        if any(k in blob for k in keywords):
            return True
    return False


def _context_findings(full_text: str, context) -> list[dict]:
    if context is None:
        return []
    extra: list[dict] = []
    quals = list(getattr(context, "quals", []) or [])

    if any(k in full_text for k in ("ISO", "iso", "荣誉", "奖项", "体系认证")):
        if not _has_qual(quals, "ISO", "iso", "荣誉", "奖", "认证", kind="cert") and not _has_qual(
            quals, "ISO", "荣誉", "奖"
        ):
            extra.append(
                _finding(
                    severity="扣分",
                    location="商务标 / 荣誉认证",
                    excerpt="正文写到荣誉或体系认证，但资质库未录入对应有效证书",
                    rule="F03.06 荣誉认证须附有效期内证书",
                    suggestion="请在资质证照库录入 ISO/奖项扫描件并填写有效期，系统按库内材料核验，不联网外部颁证机构",
                )
            )
        expired = [q for q in quals if q.expired and any(k in (q.blob or "") for k in ("ISO", "荣誉", "奖", "认证"))]
        if expired:
            extra.append(
                _finding(
                    severity="扣分",
                    location="商务标 / 荣誉认证",
                    excerpt=f"资质库「{expired[0].name}」已过有效期",
                    rule="F03.06 荣誉认证须在有效期内",
                    suggestion="请更新仍在有效期内的证书后再计分",
                )
            )

    local_keys = ("本地分支", "分支机构", "售后网点", "备品备件", "应急响应")
    if any(k in full_text for k in local_keys):
        missing = [k for k in ("分支", "网点", "备品", "应急") if k not in full_text]
        if len(missing) >= 3:
            extra.append(
                _finding(
                    severity="扣分",
                    location="商务标 / 本地化服务",
                    excerpt="正文提到本地化服务，但分支机构/网点/备品/应急响应未写全",
                    rule="F03.07 本地化服务要素",
                    suggestion="请补齐本地分支机构、售后网点、备品备件库与应急响应方案的具体地址或时限",
                )
            )

    people = [q for q in quals if q.kind == "people"]
    if any(k in full_text for k in ("项目经理", "安全员", "八大员", "人员配置", "持证")):
        if len(people) == 0:
            extra.append(
                _finding(
                    severity="扣分",
                    location="商务标 / 人员配置",
                    excerpt="正文写到人员配置，但资质库未录入人员证书",
                    rule="F03.08 岗位证书人数",
                    suggestion="请在资质证照库按岗位录入持证人员，系统按库内人数核验，不编造证书编号",
                )
            )

    equipment = [q for q in quals if q.kind == "equipment"]
    if any(k in full_text for k in ("设备", "机械", "盾构", "塔吊")):
        if not equipment:
            extra.append(
                _finding(
                    severity="扣分",
                    location="商务标 / 设备机械",
                    excerpt="正文写到设备或机械，但资质库未录入设备台账",
                    rule="F03.09 设备清单与权属",
                    suggestion="请在资质证照库录入设备型号，并附购置发票或租赁协议扫描件",
                )
            )
        elif not any("发票" in full_text or "租赁" in full_text or "发票" in (q.blob or "") or "租赁" in (q.blob or "") for q in equipment):
            extra.append(
                _finding(
                    severity="建议",
                    location="商务标 / 设备机械",
                    excerpt="设备已入库，但正文与条目均未写明购置发票或租赁协议",
                    rule="F03.09 设备权属证明",
                    suggestion="请补充发票或租赁协议扫描件",
                )
            )

    if any(k in full_text for k in ("信用中国", "政府采购网", "失信")):
        credit = [q for q in quals if q.kind == "credit"]
        if not credit:
            extra.append(
                _finding(
                    severity="扣分",
                    location="商务标 / 信用记录",
                    excerpt="正文涉及信用查询，但资质库未录入信用中国/政府采购网查询截图",
                    rule="F03.10 信用记录须附查询截图",
                    suggestion="请在资质证照库上传查询截图。本系统不联网信用中国，只核验已入库材料",
                )
            )

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
                    excerpt=f"高峰人数 {headcount} 人，宿舍/临建面积 {area}㎡，人均不足 4㎡",
                    rule="F06.07 高峰人数与宿舍面积交叉验算",
                    suggestion="请按人均不少于 4㎡ 调整临建面积或劳动力峰值，使数据可交叉验证",
                )
            )

    if "废止" in full_text and re.search(r"GB[/\s]?\d|JGJ|JTG", full_text):
        extra.append(
            _finding(
                severity="建议",
                location="技术标 / 规范引用",
                excerpt="正文同时出现规范编号与「废止」字样，请确认未引用已废止条文",
                rule="F06.08 不使用废止规范",
                suggestion="本系统无国家现行规范库，请对照知识库或官方废止公告核对条文号",
            )
        )

    return extra
