"""商务标看图：识读证件/表格原图，核验有效期，并评估扫描件分辨率。"""

from __future__ import annotations

import base64
import json
import logging
import re
import time
from datetime import datetime

from .llm import LlmError, chat_complete, get_vision_model_id, is_vision_model

logger = logging.getLogger(__name__)

MAX_IMAGES = 40
BATCH = 2
TIMEOUT = 180
BATCH_RETRIES = 2
LOW_SIDE = 800
FAIL_SIDE = 400
LOW_DPI = 96
FAIL_DPI = 72

CERT_HINTS = (
    "营业执照",
    "安全生产许可证",
    "资质证书",
    "资格",
    "证书",
    "建造师",
    "职称",
    "身份证",
    "社保",
    "ISO",
    "认证",
    "中标通知书",
    "合同协议",
    "竣工验收",
    "信用中国",
    "审计报告",
    "财务报表",
    "开户许可证",
    "基本账户",
)
TECH_SKIP = ("网络图", "横道图", "甘特图", "总平面", "工艺流程", "施工部署图")
REQUIRED_CERTS = ("营业执照", "安全生产许可证", "资质证书")

_DATE = re.compile(r"^(\d{4})[-/.年](\d{1,2})[-/.月](\d{1,2})")


def _enabled(key: str, enabled_keys: set[str] | None) -> bool:
    return enabled_keys is None or key in enabled_keys


def _finding(level: str, severity: str, location: str, excerpt: str, rule: str, suggestion: str, quote: str = "") -> dict:
    return {
        "engine": "e_business_vision",
        "level": level,
        "severity": severity,
        "location": location,
        "excerpt": excerpt[:200],
        "rule": rule,
        "tenderQuote": quote[:500],
        "suggestion": suggestion,
        "confidence": 0.7,
    }


def _loads(raw: str) -> dict:
    text = (raw or "").strip()
    if text.startswith("```"):
        text = re.sub(r"^```[a-zA-Z]*\n?", "", text)
        text = re.sub(r"\n?```$", "", text).strip()
    try:
        data = json.loads(text)
        return data if isinstance(data, dict) else {}
    except json.JSONDecodeError:
        left, right = text.find("{"), text.rfind("}")
        if left >= 0 and right > left:
            try:
                data = json.loads(text[left : right + 1])
                return data if isinstance(data, dict) else {}
            except json.JSONDecodeError:
                return {}
    return {}


def _nearby_blob(paragraphs: list[dict], seq: int, radius: int = 8) -> str:
    idx = next((i for i, p in enumerate(paragraphs or []) if int(p.get("imageSeq") or 0) == seq), -1)
    if idx < 0:
        return ""
    window = (paragraphs or [])[max(0, idx - radius) : idx + radius + 1]
    return "\n".join((p.get("text") or "") for p in window)


def _is_cert_like(img: dict, nearby: str) -> bool:
    blob = f"{img.get('heading') or ''} {img.get('marker') or ''} {nearby}"
    if any(skip in blob for skip in TECH_SKIP) and not any(k in blob for k in REQUIRED_CERTS):
        return False
    return any(k in blob for k in CERT_HINTS)


def _pick_images(paragraphs: list[dict], images: list[dict]) -> list[dict]:
    scored: list[tuple[int, dict]] = []
    for img in images or []:
        nearby = _nearby_blob(paragraphs, int(img.get("seq") or 0))
        cert = _is_cert_like(img, nearby)
        table = bool(img.get("fromTable"))
        score = 0
        if cert:
            score += 30
        if table:
            score += 8
        if img.get("jpeg"):
            score += 4
        if img.get("vector"):
            score += 2
        if score <= 0 and not img.get("jpeg"):
            continue
        img = dict(img)
        img["_nearby"] = nearby
        img["_cert_like"] = cert
        scored.append((score, img))
    scored.sort(key=lambda x: (-x[0], int(x[1].get("seq") or 0)))
    picked = [img for score, img in scored if score >= 8][:MAX_IMAGES]
    if len(picked) < 8:
        extra = [img for score, img in scored if img not in picked][: max(0, 12 - len(picked))]
        picked.extend(extra)
    return picked


def _caption(img: dict, fallback: str = "资格文件") -> str:
    return ((img.get("heading") or "").strip() or fallback)[:80]


def _res_issue(img: dict) -> dict | None:
    w = int(img.get("width") or 0)
    h = int(img.get("height") or 0)
    dpi = int(img.get("dpi") or 0)
    short = min(w, h) if w and h else 0
    marker = img.get("marker") or f"【附图{img.get('seq')}】"
    heading = _caption(img)
    excerpt = heading
    loc = f"商务标 / 证件原图 / {heading}"
    if img.get("vector") and not img.get("jpeg"):
        return _finding(
            "L1",
            "降档",
            loc,
            excerpt,
            "F02.02 资质证件须为可识读原件扫描",
            f"{marker} 为未能解码的矢量图，无法核验证件原件与有效期。请改为清晰的 JPG/PNG 扫描件或照片后重新插入",
        )
    if not short:
        if not img.get("decoded"):
            return _finding(
                "L1",
                "建议",
                loc,
                excerpt,
                "F02.02 资质证件扫描件须可识别",
                f"{marker} 未能抽出像素，当前图片可能无法识别。请更换为清晰扫描件",
            )
        return None
    size_txt = f"{w}×{h}像素" + (f"，{dpi}dpi" if dpi else "")
    sharp_enough = (dpi >= 150 and short >= 600) or (short >= LOW_SIDE and (not dpi or dpi >= LOW_DPI))
    if short < FAIL_SIDE or (dpi and dpi < FAIL_DPI and short < LOW_SIDE):
        return _finding(
            "L1",
            "降档",
            loc,
            excerpt,
            "F02.02 资质证件分辨率过低",
            f"当前图片分辨率过低（{size_txt}），可能存在无法识别风险。请按短边不少于 {FAIL_SIDE} 像素、建议 150dpi 以上重新扫描后插入",
        )
    if not sharp_enough:
        return _finding(
            "L1",
            "建议",
            loc,
            excerpt,
            "F02.02 资质证件分辨率偏低",
            f"当前图片分辨率过低（{size_txt}），可能存在无法识别风险。建议使用短边不少于 {LOW_SIDE} 像素、150dpi 以上的彩色扫描件，避免评标时无法核验证号与有效期",
        )
    return None


def _parse_date(value: str) -> datetime | None:
    raw = (value or "").strip()
    if not raw or raw in ("长期", "永久", "无固定期限"):
        return None
    m = _DATE.search(raw.replace("年", "-").replace("月", "-").replace("日", ""))
    if not m:
        return None
    y, mo, d = map(int, m.groups())
    try:
        return datetime(y, mo, d)
    except ValueError:
        return None


def _call_batch(model_id: str, batch: list[dict], today: datetime) -> list[dict]:
    intro = (
        f"今天是 {today.strftime('%Y-%m-%d')}。以下是投标文件商务标/资格文件中的原图（证件扫描件、表格截图或证明材料）。"
        "必须阅读每张原图和可见表格文字。看不清就标明 readable=false，不要编造证号或日期。\n"
        "只返回 JSON："
        '{"items":[{"seq":1,"kind":"营业执照|安全生产许可证|资质证书|人员证书|荣誉证书|业绩证明|表格|其他",'
        '"name":"","number":"","owner":"","validUntil":"YYYY-MM-DD或长期或空","expired":false,'
        '"readable":true,"tableText":"表格可见文字","note":"模糊/遮挡/复印件说明"}]}'
    )
    parts: list[dict] = [{"type": "text", "text": intro}]
    ready: list[dict] = []
    for img in batch:
        jpeg = img.get("jpeg")
        if not jpeg:
            continue
        seq = img.get("seq")
        w = int(img.get("width") or 0)
        h = int(img.get("height") or 0)
        parts.append(
            {
                "type": "text",
                "text": f"\n{img.get('marker') or f'【附图{seq}】'} 章节：{img.get('heading') or ''} 原始像素 {w}×{h}。请识读：",
            }
        )
        b64 = base64.b64encode(jpeg).decode("ascii")
        parts.append({"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{b64}"}})
        ready.append(img)
    if not ready:
        return []
    raw = chat_complete(
        model_id=model_id,
        messages=[{"role": "user", "content": parts}],
        temperature=0.1,
        timeout=TIMEOUT,
        extra={"response_format": {"type": "json_object"}, "thinking": {"type": "disabled"}},
    )
    data = _loads(raw)
    items = data.get("items") if isinstance(data.get("items"), list) else []
    by_seq = {int(it.get("seq") or 0): it for it in items if isinstance(it, dict)}
    out: list[dict] = []
    for i, img in enumerate(ready):
        seq = int(img.get("seq") or 0)
        row = by_seq.get(seq)
        if row is None and i < len(items) and isinstance(items[i], dict):
            row = items[i]
        if not isinstance(row, dict):
            continue
        row["seq"] = seq
        out.append(row)
    return out


def is_transport_stub_finding(location: str = "", suggestion: str = "") -> bool:
    """看图接口抖动时曾写入「证件识读」占位，不是投标书里的真实问题。"""
    sug = suggestion or ""
    loc = (location or "").strip()
    if "调用看图模型失败" in sug or "本批证件原图调用看图模型失败" in sug:
        return True
    return loc.endswith("证件识读") or loc == "商务标 / 证件识读"


def _call_with_retry(model_id: str, batch: list[dict], today: datetime, retries: int = BATCH_RETRIES) -> list[dict]:
    last: Exception | None = None
    for attempt in range(max(1, retries)):
        try:
            return _call_batch(model_id, batch, today)
        except (LlmError, Exception) as exc:  # noqa: BLE001
            last = exc
            if attempt + 1 >= retries:
                break
            time.sleep(0.8 * (attempt + 1))
    if last:
        raise last
    return []


def run(
    paragraphs: list[dict] | None,
    images: list[dict] | None,
    checklist_params: dict | None = None,
    veto_keys: set[str] | None = None,
    biz_keys: set[str] | None = None,
    today: datetime | None = None,
) -> dict:
    """返回 {findings, paragraphs}。paragraphs 为识读摘要，供 E1/E2 关键词核验。"""
    today = today or datetime.utcnow()
    findings: list[dict] = []
    extra_paras: list[dict] = []
    picked = _pick_images(paragraphs or [], images or [])
    if not picked:
        return {"findings": findings, "paragraphs": extra_paras}

    qual_on = _enabled("qualification", veto_keys)
    honor_on = _enabled("honor", biz_keys)
    personnel_on = _enabled("personnel", veto_keys)
    performance_on = _enabled("performance", biz_keys)

    cert_targets = [img for img in picked if img.get("_cert_like") or img.get("vector") or not img.get("decoded")]
    if not cert_targets:
        cert_targets = picked
    seen_res: set[int] = set()
    for img in cert_targets:
        seq = int(img.get("seq") or 0)
        if seq in seen_res:
            continue
        issue = _res_issue(img)
        if issue:
            seen_res.add(seq)
            findings.append(issue)

    vision_id = None
    try:
        vision_id = get_vision_model_id()
        if vision_id and not is_vision_model(vision_id):
            vision_id = None
    except Exception:
        vision_id = None

    read_rows: list[dict] = []
    ready = [img for img in picked if img.get("jpeg")]
    if vision_id and ready:
        for i in range(0, len(ready), BATCH):
            batch = ready[i : i + BATCH]
            try:
                read_rows.extend(_call_with_retry(vision_id, batch, today))
                continue
            except (LlmError, Exception):  # noqa: BLE001
                logger.exception("business vision batch failed, fallback to single images")
            for img in batch:
                try:
                    read_rows.extend(_call_with_retry(vision_id, [img], today))
                except (LlmError, Exception) as exc:  # noqa: BLE001
                    logger.exception("business vision single failed seq=%s", img.get("seq"))
                    heading = _caption(img)
                    findings.append(
                        _finding(
                            "L1",
                            "建议",
                            f"商务标 / 证件原图 / {heading}",
                            heading,
                            "F02.02 证件原件识读",
                            f"{heading} 原图识读失败，请人工核验证号与有效期（{exc.__class__.__name__}）",
                        )
                    )

    seen_kinds: set[str] = set()
    img_by_seq = {int(img.get("seq") or 0): img for img in picked}
    for row in read_rows:
        seq = int(row.get("seq") or 0)
        kind = str(row.get("kind") or "其他").strip()
        name = str(row.get("name") or kind).strip()
        number = str(row.get("number") or "").strip()
        owner = str(row.get("owner") or "").strip()
        until = str(row.get("validUntil") or "").strip()
        table_text = str(row.get("tableText") or "").strip()
        readable = row.get("readable") is not False
        img = img_by_seq.get(seq) or {}
        heading = _caption(img, name or kind)
        marker = img.get("marker") or f"【附图{seq}】"
        bits = [marker, kind, name, owner, number, f"有效期{until}" if until else "", table_text]
        digest = " ".join(b for b in bits if b)
        extra_paras.append(
            {
                "index": 900000 + seq,
                "text": digest,
                "style": "",
                "fromTable": bool(table_text),
                "isHeading": False,
                "isImage": False,
                "fromVision": True,
            }
        )
        if kind in REQUIRED_CERTS or "执照" in kind or "许可" in kind or "资质" in kind:
            seen_kinds.add(next((k for k in REQUIRED_CERTS if k in kind or k in name), kind))
        if "荣誉" in kind or "ISO" in kind.upper() or "认证" in kind:
            seen_kinds.add("荣誉证书")
        if not readable:
            findings.append(
                _finding(
                    "L1",
                    "降档",
                    f"商务标 / 证件原图 / {heading}",
                    heading,
                    "F02.02 证件原件无法识读",
                    f"{marker}（{name or kind}）原图模糊、遮挡或分辨率不足，无法核验证号与有效期。请更换清晰彩色扫描件",
                )
            )
            continue
        expire_at = _parse_date(until)
        is_expired = bool(row.get("expired")) or (expire_at is not None and expire_at < today)
        certish = any(k in (kind + name) for k in ("执照", "许可", "资质", "建造师", "职称", "证书", "ISO", "认证"))
        if is_expired and certish and (qual_on or honor_on or personnel_on):
            level = "L1" if any(k in (kind + name) for k in REQUIRED_CERTS) else "L2"
            findings.append(
                _finding(
                    level,
                    "废标" if level == "L1" else "降档",
                    f"商务标 / 证件有效期 / {heading}",
                    heading,
                    "F02.02 资质证书须在有效期内",
                    f"原件「{name or kind}」有效期至 {until or expire_at.date().isoformat()}，已过期，须更新为有效证书后重新提交",
                )
            )
        elif certish and not until and qual_on:
            findings.append(
                _finding(
                    "L1",
                    "建议",
                    f"商务标 / 证件有效期 / {heading}",
                    heading,
                    "F02.02 证件有效期须可核验",
                    f"已从原图识别「{name or kind}」{('，证号 ' + number) if number else ''}，但未读到有效期。请确认扫描件包含有效期并保证字迹清晰",
                )
            )
        if performance_on and kind == "业绩证明" and table_text and len(table_text) < 12:
            findings.append(
                _finding(
                    "L2",
                    "建议",
                    f"商务标 / 业绩表格 / {heading}",
                    heading,
                    "F03.05 业绩证明表格须可识读",
                    f"{marker} 业绩/合同类表格文字过少或模糊，请提供清晰原表扫描件",
                )
            )

    extra_names = checklist_params.get("qualification_keywords") if isinstance(checklist_params, dict) else None
    required = list(REQUIRED_CERTS)
    for name in extra_names or []:
        if isinstance(name, str) and name.strip() and name.strip() not in required:
            required.append(name.strip())
    if qual_on:
        blob = "\n".join((p.get("text") or "") for p in (paragraphs or []) + extra_paras)
        for cert_name in required:
            if cert_name in blob:
                continue
            if any(cert_name in k for k in seen_kinds):
                continue
            mentioned = any(
                cert_name in (img.get("_nearby") or "") or cert_name in (img.get("heading") or "") for img in picked
            )
            if not mentioned:
                continue
            if any(cert_name in (row.get("kind") or "") + (row.get("name") or "") for row in read_rows):
                continue
            findings.append(
                _finding(
                    "L1",
                    "降档",
                    f"资格文件 / {cert_name}",
                    cert_name,
                    "F02.02 须附证件原件扫描",
                    f"章节或标题提到「{cert_name}」，但原图中未能识读到对应证件。请插入清晰、有效期内的原件扫描件",
                )
            )

    logger.info("business vision: picked=%s read=%s findings=%s", len(picked), len(read_rows), len(findings))
    return {"findings": findings, "paragraphs": extra_paras}
