"""水利施组收口校核。

对照区段账、节点账和已生成正文，找出数字对不上、图前没有文字、工艺节没有规范编号的地方。
只服务专业为水利的工程技术标。房建市政公路不走这里。
"""

from __future__ import annotations

import re

from .engineering_writer import KIND_FIGURE, normalize_facts, section_kind

_CODE_RE = re.compile(
    r"(?:JGJ|JG|GB|CJJ|JTG|SL|NB|DL)/?\s*T?\s*\d+(?:\.\d+)*\s*[-–—]\s*(?:19|20)\d{2}",
    re.I,
)
_PROCESS_RE = re.compile(r"施工方法|施工工艺|清淤|护坡|护岸|挡墙|堰|导流|防汛道路|填筑|搅拌桩|防洪墙|衬砌|基坑")
_LABOR_RE = re.compile(r"劳动力|备电|发电机|用电")
_TIER_RE = re.compile(r"由\s*\d+(?:\.\d+)?\s*(?:人|kW|kw|KW)?\s*增至\s*\d+")


def _issue(axis: str, message: str, chapter_id: str = "", title: str = "") -> dict:
    return {"axis": axis, "chapterId": chapter_id, "title": title, "message": message}


def _km(text: str) -> float | None:
    match = re.search(r"(\d+(?:\.\d+)?)\s*(?:km|公里|千米)", text or "", re.I)
    if not match:
        return None
    try:
        return float(match.group(1))
    except ValueError:
        return None


def _leaves(outline: list[dict]) -> list[dict]:
    parents = {n.get("parentId") for n in outline if n.get("parentId")}
    return [n for n in outline if n.get("id") not in parents]


def _plain(text: str) -> str:
    body = re.sub(r"<br\s*/?>", "", text or "", flags=re.I)
    body = re.sub(r"[|#*`>\-]", "", body)
    return re.sub(r"\s+", "", body)


def region_sum_problems(facts: dict) -> tuple[list[dict], list[dict]]:
    blocking: list[dict] = []
    advisory: list[dict] = []
    regions = facts.get("regions") or []
    total = _km(facts.get("regionTotalLength") or "")
    lengths = [_km(row.get("length") or "") for row in regions]
    known = [n for n in lengths if n is not None]
    if regions and len(known) < len(regions):
        advisory.append(_issue("针对性", "有的区段长度没写成带 km 的数字，加总时跳过了"))
    if total is None:
        if regions:
            advisory.append(_issue("针对性", "公告总长没有写入区段账，无法核对各段相加"))
        return blocking, advisory
    if not known:
        return blocking, advisory
    gap = abs(sum(known) - total)
    if gap > max(0.05, total * 0.02):
        blocking.append(
            _issue(
                "针对性",
                f"区段长度相加为 {sum(known):.2f} km，公告总长 {total:.2f} km，对不上",
            )
        )
    return blocking, advisory


def milestone_conflict_problems(facts: dict, outline: list[dict], contents: dict) -> list[dict]:
    problems: list[dict] = []
    by_id = {n.get("id"): n for n in outline}
    for node in facts.get("controlNodes") or []:
        name = (node.get("name") or "").strip()
        if len(name) < 2:
            continue
        allowed = set(re.findall(r"\d+(?:\.\d+)?", f"{node.get('window') or ''}{node.get('note') or ''}"))
        if not allowed:
            continue
        for chapter_id, text in (contents or {}).items():
            if name not in (text or ""):
                continue
            extras: set[str] = set()
            for match in re.finditer(re.escape(name), text):
                window = text[max(0, match.start() - 8) : match.end() + 36]
                extras.update(re.findall(r"\d+(?:\.\d+)?", window))
            extra = sorted(extras - allowed, key=lambda item: float(item))
            if not extra:
                continue
            title = str((by_id.get(chapter_id) or {}).get("title") or "")
            problems.append(
                _issue(
                    "规范性",
                    f"「{name}」附近出现账上没有的数字 {'、'.join(extra[:6])}",
                    str(chapter_id),
                    title,
                )
            )
    return problems


def standard_anchor_problems(facts: dict, outline: list[dict], contents: dict) -> list[dict]:
    if not facts.get("standardsRefs"):
        return [_issue("合规性", "依据账里没有规范编号，工艺节无法挂锚点")]
    problems = []
    for node in _leaves(outline):
        title = str(node.get("title") or "")
        if not _PROCESS_RE.search(title):
            continue
        if section_kind(node) == "group":
            continue
        text = contents.get(node.get("id")) or ""
        if not text.strip():
            continue
        if _CODE_RE.search(text):
            continue
        problems.append(_issue("合规性", f"「{title}」没有引用依据账里的规范编号", str(node.get("id") or ""), title))
    return problems


def labor_tier_problems(outline: list[dict], contents: dict) -> list[dict]:
    problems = []
    for node in _leaves(outline):
        title = str(node.get("title") or "")
        if not _LABOR_RE.search(title):
            continue
        text = contents.get(node.get("id")) or ""
        if not text.strip() or _TIER_RE.search(text):
            continue
        problems.append(
            _issue("可落地性", f"「{title}」没有写成常态到高峰的两档，例如由 65 人增至 90 人", str(node.get("id") or ""), title)
        )
    return problems


def figure_digest_problems(outline: list[dict], contents: dict) -> list[dict]:
    problems = []
    for node in outline:
        if section_kind(node) != KIND_FIGURE:
            continue
        text = contents.get(node.get("id")) or ""
        if not text.strip():
            continue
        title = str(node.get("title") or "")
        if len(_plain(text)) < 200:
            problems.append(
                _issue("完整性", f"「{title}」的文字说明不足 200 字，机器读不到关键线路或布置原则", str(node.get("id") or ""), title)
            )
    return problems


def _title_of(nodes: list[dict], chapter_id: str) -> str:
    return str(next((n.get("title") for n in nodes if n.get("id") == chapter_id), "") or "")


def standard_code_problems(
    facts: dict, outline: list[dict], contents: dict, known_codes
) -> list[dict]:
    """正文里的规范编号既不在招标文本、也不在已入库规范里时提示核对。库里没收录不等于编造，所以只提示。"""
    if known_codes is None:
        return []
    from .water_design import code_key

    allowed = {code_key(c) for c in known_codes} | {code_key(c) for c in facts.get("standardsRefs") or []}
    problems: list[dict] = []
    seen: set[str] = set()
    for node in _leaves(outline):
        text = contents.get(node.get("id")) or ""
        for match in _CODE_RE.finditer(text):
            code = re.sub(r"\s+", " ", match.group(0)).strip()
            key = code_key(code)
            if key in allowed or key in seen:
                continue
            seen.add(key)
            title = str(node.get("title") or "")
            problems.append(
                _issue(
                    "合规性",
                    f"「{code}」不在招标文本和已入库规范里，请核对编号和年号是否写对",
                    str(node.get("id") or ""),
                    title,
                )
            )
            if len(problems) >= 12:
                return problems
    return problems


def cited_standard_problems(cited_findings: list[dict] | None) -> tuple[list[dict], list[dict]]:
    """已废止或被替代的标准号拦截，仅年号偏旧的提示。输入是 standard_review.cited_standard_findings 的结果。"""
    blocking: list[dict] = []
    advisory: list[dict] = []
    for item in cited_findings or []:
        rule = str(item.get("rule") or "")
        message = f"{rule}：{item.get('suggestion') or ''}".strip("：")
        if rule.endswith("已废止") or rule.endswith("已被替代"):
            blocking.append(_issue("合规性", message))
        else:
            advisory.append(_issue("合规性", message))
    return blocking, advisory


_POWER_UNIT = {"kw": 1.0, "千瓦": 1.0, "mw": 1000.0, "万千瓦": 10000.0}


def structure_count_problems(facts: dict, outline: list[dict], contents: dict) -> list[dict]:
    """正文写的座数、总装机和构筑物账对不上。招标写明的数量不能另起一套。"""
    problems: list[dict] = []
    for row in facts.get("structures") or []:
        name = (row.get("name") or "").strip()
        if len(name) < 2:
            continue
        if name == "总装机":
            ledger = re.match(r"([\d.]+)\s*(kW|KW|kw|千瓦|MW|万千瓦)", row.get("spec") or "")
            if not ledger:
                continue
            want = float(ledger.group(1)) * _POWER_UNIT[ledger.group(2).lower()]
            pattern = re.compile(r"总装机(?:容量|功率)?\s*(?:约)?\s*([\d.]+)\s*(kW|KW|kw|千瓦|MW|万千瓦)")
            for chapter_id, text in (contents or {}).items():
                for match in pattern.finditer(text or ""):
                    got = float(match.group(1)) * _POWER_UNIT[match.group(2).lower()]
                    if abs(got - want) > max(0.5, want * 0.01):
                        problems.append(
                            _issue(
                                "针对性",
                                f"总装机写成 {match.group(1)}{match.group(2)}，账上是 {row.get('spec')}",
                                str(chapter_id),
                                "",
                            )
                        )
                        break
            continue
        count = (row.get("count") or "").strip()
        if not count.isdigit():
            continue
        pattern = re.compile(re.escape(name) + r"\s*(?:共|合计)?\s*(\d{1,3})\s*座")
        for chapter_id, text in (contents or {}).items():
            bad = next((m.group(1) for m in pattern.finditer(text or "") if m.group(1) != count), None)
            if bad is not None:
                problems.append(_issue("针对性", f"「{name}」账上是 {count} 座，正文写成 {bad} 座", str(chapter_id), ""))
                break
    for item in problems:
        item["title"] = _title_of(outline, item["chapterId"])
    return problems


_DMS_RE = re.compile(r"\d{2,3}\s*°\s*\d{1,2}\s*[′'’]|\d{2,3}\s*度\s*\d{1,2}\s*分\s*\d{0,2}")
_DEC_COORD_RE = re.compile(r"(?:经度|纬度|东经|北纬|坐标)[^。\n]{0,12}?(\d{2,3}\.\d{4,})")


def coordinate_problems(facts: dict, outline: list[dict], contents: dict) -> list[dict]:
    """勘察资料账里没有的坐标一律当编造。正文自己写出经纬度，说明模型在补数。"""
    site = facts.get("siteSurvey") or {}
    allowed_text = " ".join(
        [str(site.get("boundaries") or ""), str(site.get("access") or ""), str(site.get("crsNote") or "")]
        + [f"{p.get('name', '')}{p.get('note', '')}" for p in site.get("sensitivePoints") or []]
    )
    problems: list[dict] = []
    for node in _leaves(outline):
        text = contents.get(node.get("id")) or ""
        hits = [m.group(0) for m in _DMS_RE.finditer(text)] + [m.group(1) for m in _DEC_COORD_RE.finditer(text)]
        bad = [h for h in hits if re.sub(r"\s+", "", h) not in re.sub(r"\s+", "", allowed_text)]
        if bad:
            title = str(node.get("title") or "")
            problems.append(
                _issue("真实性", f"「{title}」出现勘察资料账里没有的坐标 {bad[0]}，疑似编造，请删除或补进勘察资料", str(node.get("id") or ""), title)
            )
    return problems


def flood_standard_problems(facts: dict, outline: list[dict], contents: dict) -> tuple[list[dict], list[dict]]:
    blocking: list[dict] = []
    advisory: list[dict] = []
    ledger = (facts.get("projectGrade") or {}).get("floodStandard") or ""
    ledger_n = re.search(r"(\d{1,3})", ledger)
    flood_nodes = [n for n in outline if re.search(r"度汛|导流|围堰", str(n.get("title") or ""))]
    if ledger_n:
        pattern = re.compile(r"(?:设计洪水|防洪标准)[^。\n]{0,10}?(\d{1,3})\s*年一遇")
        for chapter_id, text in (contents or {}).items():
            bad = next((m.group(1) for m in pattern.finditer(text or "") if m.group(1) != ledger_n.group(1)), None)
            if bad is not None:
                blocking.append(
                    _issue(
                        "针对性",
                        f"设计洪水写成 {bad} 年一遇，工程等别账是 {ledger}",
                        str(chapter_id),
                        _title_of(outline, str(chapter_id)),
                    )
                )
                break
    if (facts.get("floodSeason") or {}).get("spansFlood"):
        texts = [contents.get(n.get("id")) or "" for n in flood_nodes]
        if any(t.strip() for t in texts) and not any("年一遇" in t for t in texts):
            advisory.append(_issue("针对性", "工期跨汛，但度汛导流各节都没有写洪水重现期（年一遇）"))
    return blocking, advisory


def mechanism_problems(outline: list[dict], contents: dict) -> list[dict]:
    problems = []
    for node in _leaves(outline):
        title = str(node.get("title") or "")
        if not re.search(r"智慧工地|BIM", title):
            continue
        text = contents.get(node.get("id")) or ""
        if not text.strip():
            continue
        lacking = []
        if "阈值" not in text:
            lacking.append("预警阈值")
        if not re.search(r"触发|预警", text):
            lacking.append("触发动作")
        if lacking:
            problems.append(
                _issue("可落地性", f"「{title}」只罗列了系统，缺少{'、'.join(lacking)}", str(node.get("id") or ""), title)
            )
    return problems


def design_param_problems(design: list[dict] | None, outline: list[dict], contents: dict) -> list[dict]:
    """正文数值与设计参数账对照。账里没有对应参数时不判断。"""
    from .water_design import concrete_tuple_missing, design_params

    params = design_params(design)
    if not any(params.values()):
        return []
    problems: list[dict] = []
    grade_re = re.compile(r"(?<![A-Za-z])C(\d{2})(?!\d)")
    compact_re = re.compile(r"压实度[^。；;\n]{0,8}?(\d{2,3}(?:\.\d+)?)\s*%")
    dosage_re = re.compile(r"掺量[^。；;\n]{0,8}?(\d{1,2}(?:\.\d+)?)\s*%")
    flagged: set[str] = set()
    for node in _leaves(outline):
        text = contents.get(node.get("id")) or ""
        if not text.strip():
            continue
        title = str(node.get("title") or "")
        cid = str(node.get("id") or "")
        if params["grade"]:
            for n in grade_re.findall(text):
                tag = f"C{n}"
                if tag not in params["grade"] and tag not in flagged:
                    flagged.add(tag)
                    problems.append(
                        _issue("针对性", f"「{title}」写了混凝土 {tag}，设计参数账里是 {'、'.join(sorted(params['grade']))}", cid, title)
                    )
        for label, regex, key in (("压实度", compact_re, "compaction"), ("掺量", dosage_re, "dosage")):
            if not params[key]:
                continue
            for value in regex.findall(text):
                tag = f"{label}{value}"
                if value not in params[key] and tag not in flagged:
                    flagged.add(tag)
                    problems.append(
                        _issue("针对性", f"「{title}」写了{label} {value}%，设计参数账里是 {'、'.join(sorted(params[key]))}%", cid, title)
                    )
        missing = concrete_tuple_missing(text, params)
        if missing:
            problems.append(
                _issue("完整性", f"「{title}」写了混凝土强度等级，但没有成组写出{'、'.join(missing)}", cid, title)
            )
    return problems[:20]


_STOP_TOKENS = {"必须", "应当", "要求", "说明", "措施", "方案", "保障", "施工", "工程", "相关", "进行", "符合", "满足", "招标", "文件"}


def coverage_rules(checklist) -> list[dict]:
    """写作需要落地的点：招标技术规则叶子，加上已启用的、不是纯资格商务类的项目规则。"""
    rows: list[dict] = []
    seen: set[str] = set()
    for rule in getattr(checklist, "tech_rules", None) or []:
        if not isinstance(rule, dict):
            continue
        title = str(rule.get("factor") or rule.get("name") or "").strip()
        need = str(rule.get("mustWrite") or "").strip()
        if title and need and title not in seen:
            seen.add(title)
            rows.append({"title": title, "requirement": need})
    for rule in getattr(checklist, "project_rules", None) or []:
        if not isinstance(rule, dict) or rule.get("enabled") is False:
            continue
        if rule.get("checkType") == "建议":
            continue
        if rule.get("source") == "规则池" and rule.get("evidence") != "技术":
            continue
        title = str(rule.get("title") or "").strip()
        if title and title not in seen:
            seen.add(title)
            rows.append({"title": title, "requirement": str(rule.get("requirement") or "")})
    return rows


def _rule_tokens(rule: dict) -> list[str]:
    blob = f"{rule.get('title') or ''} {rule.get('requirement') or ''}"
    tokens: list[str] = []
    for word in re.findall(r"[\u4e00-\u9fa5A-Za-z0-9]{2,8}", blob):
        if word in _STOP_TOKENS or word in tokens:
            continue
        tokens.append(word)
        if len(tokens) >= 5:
            break
    return tokens


def point_coverage_problems(rules: list[dict] | None, outline: list[dict], contents: dict) -> list[dict]:
    """预审点有没有落进正文：任一小节命中过半关键词算落地。"""
    texts = [t for t in (contents or {}).values() if isinstance(t, str) and t.strip()]
    if not rules or not texts:
        return []
    problems: list[dict] = []
    for rule in rules:
        tokens = _rule_tokens(rule)
        if not tokens:
            continue
        need = max(1, (len(tokens) + 1) // 2)
        if any(sum(1 for t in tokens if t in text) >= need for text in texts):
            continue
        problems.append(_issue("完整性", f"预审点「{str(rule.get('title'))[:30]}」在正文里没有落地，请补写或确认已覆盖"))
        if len(problems) >= 12:
            break
    return problems


def water_check(
    facts: dict | None,
    outline: list | None,
    contents: dict | None,
    *,
    known_codes=None,
    cited_findings: list[dict] | None = None,
    design: list[dict] | None = None,
    rules: list[dict] | None = None,
) -> dict:
    """返回 blocking（导出前要处理）和 advisory（只提示）。后四个参数可省，省了就不做对应检查。"""
    data = normalize_facts(facts)
    nodes = [n for n in (outline or []) if isinstance(n, dict)]
    body = contents if isinstance(contents, dict) else {}
    blocking: list[dict] = []
    advisory: list[dict] = []
    region_block, region_note = region_sum_problems(data)
    blocking.extend(region_block)
    advisory.extend(region_note)
    blocking.extend(milestone_conflict_problems(data, nodes, body))
    advisory.extend(standard_anchor_problems(data, nodes, body))
    advisory.extend(labor_tier_problems(nodes, body))
    blocking.extend(figure_digest_problems(nodes, body))
    blocking.extend(structure_count_problems(data, nodes, body))
    blocking.extend(coordinate_problems(data, nodes, body))
    flood_block, flood_note = flood_standard_problems(data, nodes, body)
    blocking.extend(flood_block)
    advisory.extend(flood_note)
    advisory.extend(mechanism_problems(nodes, body))
    advisory.extend(design_param_problems(design, nodes, body))
    advisory.extend(standard_code_problems(data, nodes, body, known_codes))
    cited_block, cited_note = cited_standard_problems(cited_findings)
    blocking.extend(cited_block)
    advisory.extend(cited_note)
    advisory.extend(point_coverage_problems(rules, nodes, body))
    from .engineering_writer import site_gaps

    return {"ok": not blocking, "blocking": blocking, "advisory": advisory, "siteGaps": site_gaps(data)}


def edit_block_reason(
    facts,
    outline,
    contents,
    chapter_id: str,
    new_text: str,
    extra: dict | None = None,
) -> tuple[str, list[str]]:
    """对话改写一节时用。返回 (拒绝原因, 本节仍在的建议)。

    拒绝只针对本节自己的拦截项，以及这次修改新带进来的拦截项。
    其他章节里原来就有的问题不挡住这次修改。
    extra 是 check_inputs 的结果，查库失败时可以不传。
    """
    old = contents if isinstance(contents, dict) else {}
    updated = dict(old)
    updated[chapter_id] = new_text
    kwargs = extra if isinstance(extra, dict) else {}
    before = water_check(facts, outline, old, **kwargs)
    after = water_check(facts, outline, updated, **kwargs)
    seen_before = {item.get("message") for item in before["blocking"]}
    messages: list[str] = []
    for item in after["blocking"]:
        message = str(item.get("message") or "")
        own = str(item.get("chapterId") or "") == chapter_id
        introduced = message not in seen_before
        if message and (own or introduced) and message not in messages:
            messages.append(message)
    notes = []
    for item in after["advisory"]:
        if str(item.get("chapterId") or "") not in {"", chapter_id}:
            continue
        message = str(item.get("message") or "")
        if message and message not in notes:
            notes.append(message)
    if not messages:
        return "", notes[:6]
    lines = [f"{index}. {message}" for index, message in enumerate(messages[:8], start=1)]
    return "水利施组校核未通过，本次修改不能写回：\n" + "\n".join(lines), notes[:6]


def check_inputs(db, project_id: str, contents: dict | None) -> dict:
    """批量收尾和导出共用：查库拿已入库规范编号、设计参数账、预审点。任何一项失败都只是少做那项检查。"""
    out: dict = {}
    body = "\n".join(t for t in (contents or {}).values() if isinstance(t, str))
    try:
        from .engineering_writer import _load_checklist, _standard_codes, project_tender_text
        from .standard_review import cited_standard_findings
        from .water_design import code_key, design_ledger, known_standard_codes

        known = known_standard_codes(db)
        known |= {code_key(c) for c in _standard_codes(project_tender_text(project_id), limit=400)}
        out["known_codes"] = known
        out["cited_findings"] = cited_standard_findings(body)
        checklist = _load_checklist(project_id)
        if checklist is not None:
            out["design"] = design_ledger(checklist)
            out["rules"] = coverage_rules(checklist)
    except Exception:  # noqa: BLE001 —— 附加检查失败不能挡住基础校核
        import logging

        logging.getLogger(__name__).exception("water check inputs failed")
    return out


def run_water_check(db, project_id: str, facts, outline, contents) -> dict:
    return water_check(facts, outline, contents, **check_inputs(db, project_id, contents))


def blocking_message(check: dict | None) -> str:
    items = (check or {}).get("blocking") or []
    if not items:
        return ""
    lines = [f"{index}. {item.get('message')}" for index, item in enumerate(items[:12], start=1)]
    extra = f"\n另有 {len(items) - 12} 条未列出。" if len(items) > 12 else ""
    return "水利施组校核未通过，请先处理后再导出。确认后可以强制导出：\n" + "\n".join(lines) + extra
