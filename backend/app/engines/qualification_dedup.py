"""资质证照库去重：营业执照全局唯一，证号优先，灰区 Jaccard + LLM。"""

from __future__ import annotations

import hashlib
import logging
import os
import re

import jieba
from sqlalchemy.orm import Session, joinedload

from ..config import get_settings
from ..models import QualificationAsset, QualificationAssetImage, QualificationSourceDoc, gen_id
from .. import storage
from .llm import LlmError, chat_complete

logger = logging.getLogger(__name__)

STRIP_SUFFIX = re.compile(r"(复印件|扫描件|附件|证书|证照)+$")
SPACE_RE = re.compile(r"[\s\u3000]+")
PUNCT_RE = re.compile(r"[“”\"'（）()【】\[\]《》,，.。:：;；、]")
LICENSE_RE = re.compile(r"营业执照|统一社会信用代码")
AUTO_JACCARD = 0.72
GRAY_JACCARD = 0.45
MAX_LLM_PAIRS = 20
VALID_KINDS = {"cert", "people", "achievement", "equipment", "credit", "contract", "financial"}


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def normalize_name(name: str) -> str:
    text = SPACE_RE.sub("", (name or "").strip())
    text = PUNCT_RE.sub("", text)
    text = STRIP_SUFFIX.sub("", text)
    return text.lower()


def normalize_number(number: str) -> str:
    return re.sub(r"[\s\-]", "", (number or "").strip()).upper()


def is_business_license(name: str, number: str = "", detail: str = "") -> bool:
    blob = f"{name} {number} {detail}"
    return bool(LICENSE_RE.search(blob))


def _tokens(text: str) -> set[str]:
    return {t for t in jieba.lcut(text or "") if t.strip() and len(t.strip()) > 1}


def name_jaccard(a: str, b: str) -> float:
    na, nb = normalize_name(a), normalize_name(b)
    if not na or not nb:
        return 0.0
    if na == nb:
        return 1.0
    ta, tb = _tokens(na) | set(na), _tokens(nb) | set(nb)
    if not ta or not tb:
        return 0.0
    return len(ta & tb) / len(ta | tb)


def identity_key(item: dict | QualificationAsset) -> str | None:
    if isinstance(item, QualificationAsset):
        name, number, kind, valid_until, detail, owner = (
            item.name or "",
            item.number or "",
            item.kind or "",
            item.valid_until or "",
            item.detail or "",
            item.owner or "",
        )
    else:
        name = item.get("name") or ""
        number = item.get("number") or ""
        kind = item.get("kind") or ""
        valid_until = item.get("validUntil") or ""
        detail = item.get("detail") or ""
        owner = item.get("owner") or ""
    if is_business_license(name, number, detail):
        return "cert|__biz_license__"
    num = normalize_number(number)
    if kind == "people":
        owner_n = normalize_name(owner)
        name_n = normalize_name(name)
        if num and owner_n:
            return f"people|{owner_n}|{num}"
        if num:
            return f"people|{num}"
        if owner_n and name_n:
            return f"people|{owner_n}|{name_n}"
        return None
    if kind == "financial":
        year = _year_hint(valid_until, name, detail)
        if num:
            return f"financial|{num}"
        if year:
            return f"financial|{normalize_name(name)}|{year}"
        return f"financial|{normalize_name(name)}" if normalize_name(name) else None
    if num:
        return f"{kind or 'cert'}|{num}"
    return None


def _year_hint(*parts: str) -> str:
    for part in parts:
        match = re.search(r"(20\d{2})", part or "")
        if match:
            return match.group(1)
    return ""


def merge_candidates_in_doc(candidates: list[dict]) -> list[dict]:
    merged: list[dict] = []
    index: dict[str, int] = {}
    for cand in candidates:
        key = identity_key(cand) or f"name|{normalize_name(cand.get('name') or '')}"
        if not key or key.endswith("|"):
            merged.append(cand)
            continue
        if key in index:
            _union_candidate(merged[index[key]], cand)
            continue
        index[key] = len(merged)
        merged.append(cand)
    return merged


def _union_candidate(base: dict, extra: dict) -> None:
    alias = list(base.get("aliases") or [])
    extra_name = (extra.get("name") or "").strip()
    if extra_name and extra_name != base.get("name") and extra_name not in alias:
        alias.append(extra_name)
    base["aliases"] = alias
    if extra.get("number") and not base.get("number"):
        base["number"] = extra["number"]
    if extra.get("level") and not base.get("level"):
        base["level"] = extra["level"]
    if extra.get("owner") and not base.get("owner"):
        base["owner"] = extra["owner"]
    if extra.get("validUntil") and (not base.get("validUntil") or base.get("validUntil") == "长期"):
        if extra["validUntil"] != "长期":
            base["validUntil"] = extra["validUntil"]
    if extra.get("detail") and len(extra["detail"]) > len(base.get("detail") or ""):
        base["detail"] = extra["detail"]
    evidence = list(base.get("evidence") or [])
    for row in extra.get("evidence") or []:
        if row not in evidence:
            evidence.append(row)
    base["evidence"] = evidence
    images = list(base.get("images") or [])
    seen = {img.get("sha256") for img in images if img.get("sha256")}
    for img in extra.get("images") or []:
        digest = img.get("sha256") or ""
        if digest and digest in seen:
            continue
        images.append(img)
        if digest:
            seen.add(digest)
    base["images"] = images


def _extract_model_id() -> str:
    settings = get_settings()
    if settings.ark_api_key:
        return "doubao"
    return "deepseek-v4-flash"


def _llm_same_asset(a: dict, b: QualificationAsset) -> str:
    prompt = (
        "判断下面两条是否为同一份企业资质/合同/财务材料。只回复三个词之一：相同、应分开、不同。\n"
        "营业执照全公司只有一套，名称相近即相同。财务报表按年度区分。合同按合同号区分。"
        "人员证书按持有人+证号区分，同名证书不同人必须应分开。\n\n"
        f"A 名称：{a.get('name')} 类型：{a.get('kind')} 编号：{a.get('number') or '无'} "
        f"持有人：{a.get('owner') or '无'} 有效期：{a.get('validUntil') or '无'}\n"
        f"B 名称：{b.name} 类型：{b.kind} 编号：{b.number or '无'} "
        f"持有人：{b.owner or '无'} 有效期：{b.valid_until or '无'}\n"
    )
    try:
        text = chat_complete(
            model_id=_extract_model_id(),
            messages=[
                {"role": "system", "content": "你只做商务材料是否重复的判定，不要解释。"},
                {"role": "user", "content": prompt},
            ],
            temperature=0,
            timeout=30,
            max_tokens=20,
        )
    except LlmError:
        return "不同"
    except Exception:
        logger.exception("qualification pairwise judge failed")
        return "不同"
    raw = (text or "").strip()
    if "应分开" in raw:
        return "应分开"
    if "相同" in raw:
        return "相同"
    return "不同"


def apply_to_library(
    db: Session,
    source_doc: QualificationSourceDoc,
    candidates: list[dict],
) -> dict[str, int]:
    existing = (
        db.query(QualificationAsset)
        .options(joinedload(QualificationAsset.images))
        .with_for_update()
        .all()
    )
    stats = {"extracted": 0, "merged": 0, "suspected": 0, "conflicts": 0}
    gray_used = 0
    source_row = {"docId": source_doc.id, "filename": source_doc.filename}

    for cand in candidates:
        name = (cand.get("name") or "").strip()
        if not name:
            continue
        hit, score, by_key = _best_match(cand, existing)
        action = "new"
        if by_key:
            action = "merge"
        elif hit and score >= AUTO_JACCARD:
            action = "merge"
        elif hit and GRAY_JACCARD <= score < AUTO_JACCARD and gray_used < MAX_LLM_PAIRS:
            gray_used += 1
            verdict = _llm_same_asset(cand, hit)
            if verdict == "相同":
                action = "merge"
            elif verdict == "应分开":
                action = "suspect"
            else:
                action = "new"

        if action == "merge" and hit:
            _merge_into_asset(hit, cand, source_row)
            _save_candidate_images(db, hit, cand.get("images") or [])
            stats["merged"] += 1
            if hit.merge_status == "信息冲突":
                stats["conflicts"] += 1
            continue

        item = _insert_asset(db, cand, source_row, "疑似重复" if action == "suspect" else "新增")
        _save_candidate_images(db, item, cand.get("images") or [])
        existing.append(item)
        stats["extracted"] += 1
        if action == "suspect" and hit:
            ids = list(item.suspected_ids_json or [])
            if hit.id not in ids:
                ids.append(hit.id)
            item.suspected_ids_json = ids
            other = list(hit.suspected_ids_json or [])
            if item.id not in other:
                other.append(item.id)
            hit.suspected_ids_json = other
            if hit.review_status != "已入库":
                hit.merge_status = "疑似重复"
            stats["suspected"] += 1

    return stats


def _best_match(
    cand: dict, existing: list[QualificationAsset]
) -> tuple[QualificationAsset | None, float, bool]:
    cand_key = identity_key(cand)
    if cand_key:
        for item in existing:
            if identity_key(item) == cand_key:
                return item, 1.0, True
    best: QualificationAsset | None = None
    best_score = 0.0
    cand_kind = cand.get("kind") or ""
    cand_owner = normalize_name(cand.get("owner") or "")
    cand_num = normalize_number(cand.get("number") or "")
    for item in existing:
        if cand_kind and item.kind and cand_kind != item.kind and not (
            is_business_license(cand.get("name") or "") and is_business_license(item.name)
        ):
            continue
        if cand_kind == "people" and item.kind == "people":
            item_owner = normalize_name(item.owner or "")
            item_num = normalize_number(item.number or "")
            if cand_owner and item_owner and cand_owner != item_owner:
                continue
            if not cand_owner and not item_owner and not cand_num and not item_num:
                continue
        score = name_jaccard(cand.get("name") or "", item.name)
        for alias in item.aliases_json or []:
            score = max(score, name_jaccard(cand.get("name") or "", alias))
        if score > best_score:
            best, best_score = item, score
    return best, best_score, False


def _later_valid(left: str, right: str) -> str:
    a, b = (left or "").strip(), (right or "").strip()
    if not a:
        return b or "长期"
    if not b:
        return a
    if a in ("长期", "长期有效") or b in ("长期", "长期有效"):
        return "长期"
    return max(a, b)


def _merge_into_asset(item: QualificationAsset, cand: dict, source_row: dict) -> None:
    extra_name = (cand.get("name") or "").strip()
    aliases = list(item.aliases_json or [])
    if extra_name and extra_name != item.name and extra_name not in aliases:
        aliases.append(extra_name)
    item.aliases_json = aliases

    sources = list(item.sources_json or [])
    if not any(s.get("docId") == source_row.get("docId") for s in sources):
        sources.append(source_row)
    item.sources_json = sources

    evidence = list(item.evidence_json or [])
    for row in cand.get("evidence") or []:
        if row not in evidence:
            evidence.append(row)
    item.evidence_json = evidence

    conflicts = list(item.field_conflict_json or [])
    incoming_number = (cand.get("number") or "").strip()
    if incoming_number and item.number and normalize_number(incoming_number) != normalize_number(item.number):
        conflicts.append(f"编号 {item.number} ⇄ {incoming_number}")
    elif incoming_number and not item.number:
        item.number = incoming_number

    incoming_valid = (cand.get("validUntil") or "").strip()
    if incoming_valid and item.valid_until and incoming_valid != item.valid_until:
        if incoming_valid not in ("长期", "长期有效") and item.valid_until not in ("长期", "长期有效", ""):
            conflicts.append(f"有效期 {item.valid_until} ⇄ {incoming_valid}")
        item.valid_until = _later_valid(item.valid_until, incoming_valid)
    elif incoming_valid and not item.valid_until:
        item.valid_until = incoming_valid

    if cand.get("level") and not item.level:
        item.level = cand["level"]
    if cand.get("owner") and not item.owner:
        item.owner = cand["owner"]
    if cand.get("detail"):
        if not item.detail:
            item.detail = cand["detail"]
        elif cand["detail"] not in item.detail:
            item.detail = f"{item.detail}\n{cand['detail']}"[:2000]

    if conflicts:
        item.field_conflict_json = list(dict.fromkeys(conflicts))
        item.merge_status = "信息冲突"
        item.review_status = "待审核"
    else:
        item.merge_status = "并入已有"
        if item.review_status == "已入库":
            item.review_status = "待审核"


def _insert_asset(db: Session, cand: dict, source_row: dict, merge_status: str) -> QualificationAsset:
    kind = cand.get("kind") if cand.get("kind") in VALID_KINDS else "cert"
    if is_business_license(cand.get("name") or "", cand.get("number") or "", cand.get("detail") or ""):
        kind = "cert"
    if re.search(r"荣誉|奖状|获奖", cand.get("name") or "") and kind == "credit":
        kind = "cert"
    item = QualificationAsset(
        kind=kind,
        name=(cand.get("name") or "").strip()[:80],
        level=(cand.get("level") or "").strip()[:80],
        number=(cand.get("number") or "").strip()[:80],
        valid_until=(cand.get("validUntil") or "长期").strip() or "长期",
        owner=(cand.get("owner") or "").strip()[:80],
        detail=(cand.get("detail") or "").strip()[:2000],
        review_status="待审核",
        merge_status=merge_status,
        aliases_json=list(cand.get("aliases") or []),
        sources_json=[source_row],
        evidence_json=list(cand.get("evidence") or []),
        field_conflict_json=[],
        suspected_ids_json=[],
    )
    db.add(item)
    db.flush()
    return item


def _save_candidate_images(db: Session, item: QualificationAsset, images: list[dict]) -> None:
    if not images:
        return
    existing = {img.sha256 for img in (item.images or []) if img.sha256}
    from .ocr import ocr_image_bytes

    for img in images:
        blob = img.get("blob")
        if not blob:
            continue
        digest = img.get("sha256") or sha256_bytes(blob)
        if digest in existing:
            continue
        ext = img.get("ext") or ".png"
        key = storage.put_bytes("qualification-images", blob, ext)
        db.add(
            QualificationAssetImage(
                id=gen_id("qimg"),
                asset_id=item.id,
                caption=(img.get("caption") or item.name)[:80],
                filename=os.path.basename(key),
                storage_path=key,
                sha256=digest,
            )
        )
        existing.add(digest)
        if not item.storage_path:
            item.storage_path = key
            item.filename = os.path.basename(key)
        if not (item.ocr_text or "").strip():
            text, status = ocr_image_bytes(blob)
            item.ocr_status = status
            if text:
                item.ocr_text = text[:4000]
                if not item.number:
                    num = re.search(
                        r"(?:证号|证书编号|编号|合同号|合同编号|统一社会信用代码)[:：\s]*([A-Za-z0-9\-]{4,})",
                        text,
                    )
                    if num:
                        item.number = num.group(1)[:80]


def merge_assets(db: Session, keep: QualificationAsset, drop: QualificationAsset) -> QualificationAsset:
    dummy = {
        "name": drop.name,
        "kind": drop.kind,
        "number": drop.number,
        "level": drop.level,
        "validUntil": drop.valid_until,
        "owner": drop.owner,
        "detail": drop.detail,
        "evidence": drop.evidence_json or [],
    }
    for src in drop.sources_json or []:
        sources = list(keep.sources_json or [])
        if not any(s.get("docId") == src.get("docId") for s in sources):
            sources.append(src)
        keep.sources_json = sources
    _merge_into_asset(keep, dummy, {"docId": "", "filename": ""})
    aliases = list(keep.aliases_json or [])
    if drop.name not in aliases and drop.name != keep.name:
        aliases.append(drop.name)
    for alias in drop.aliases_json or []:
        if alias not in aliases and alias != keep.name:
            aliases.append(alias)
    keep.aliases_json = aliases
    keep.merge_status = "并入已有"
    keep.suspected_ids_json = [x for x in (keep.suspected_ids_json or []) if x != drop.id]
    seen = {img.sha256 for img in (keep.images or []) if img.sha256}
    for img in list(drop.images or []):
        if img.sha256 and img.sha256 in seen:
            storage.delete(img.storage_path)
            continue
        ext = os.path.splitext(img.filename or img.storage_path or "")[1] or ".png"
        old_ref = img.storage_path
        if old_ref and storage.exists(old_ref):
            img.storage_path = storage.copy_object(old_ref, "qualification-images", ext)
            if img.storage_path != old_ref:
                storage.delete(old_ref)
        img.asset_id = keep.id
        seen.add(img.sha256)
        if not keep.storage_path:
            keep.storage_path = img.storage_path
            keep.filename = img.filename or os.path.basename(img.storage_path or "")
    db.delete(drop)
    db.flush()
    return keep


def mark_keep_both(keep: QualificationAsset, other: QualificationAsset) -> None:
    keep.suspected_ids_json = [x for x in (keep.suspected_ids_json or []) if x != other.id]
    other.suspected_ids_json = [x for x in (other.suspected_ids_json or []) if x != keep.id]
    if keep.merge_status == "疑似重复":
        keep.merge_status = "新增"
    if other.merge_status == "疑似重复":
        other.merge_status = "新增"
