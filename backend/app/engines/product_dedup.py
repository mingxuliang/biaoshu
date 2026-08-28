"""产品库功能点去重：大模型判断是否同一功能；合并时优先保留有配图的条目。"""

from __future__ import annotations

import hashlib
import logging
import os
import re

import jieba
from sqlalchemy.orm import Session, selectinload

from ..config import get_settings
from ..models import ProductFeature, ProductFeatureImage, ProductSourceDoc, gen_id
from .. import storage
from .llm import LlmError, chat_complete

logger = logging.getLogger(__name__)

STRIP_SUFFIX = re.compile(r"(系统|功能模块|功能点|功能|模块|支持|提供)+$")
SPACE_RE = re.compile(r"[\s\u3000]+")
PUNCT_RE = re.compile(r"[“”\"'（）()【】\[\]《》,，.。:：;；、]")
GRAY_JACCARD = 0.32
MAX_LLM_PAIRS = 80


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def normalize_name(name: str) -> str:
    text = SPACE_RE.sub("", (name or "").strip())
    text = text.replace("　", "")
    text = PUNCT_RE.sub("", text)
    text = STRIP_SUFFIX.sub("", text)
    return text.lower()


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


def goods_key(item: dict | ProductFeature) -> str:
    if isinstance(item, ProductFeature):
        return f"{(item.brand or '').strip()}|{(item.model or '').strip()}"
    return f"{(item.get('brand') or '').strip()}|{(item.get('model') or '').strip()}"


def _image_count(item: dict | ProductFeature) -> int:
    if isinstance(item, ProductFeature):
        return len(item.images or [])
    return len(item.get("images") or [])


def merge_candidates_in_doc(candidates: list[dict]) -> list[dict]:
    """同一份技术标内去重：名称相同或大模型判定相同则合并，保留配图更多的那条。"""
    merged: list[dict] = []
    llm_used = 0
    for cand in candidates:
        children = list(cand.get("children") or [])
        parent = dict(cand)
        parent["children"] = []
        host, llm_used = _merge_into_list(merged, parent, llm_used)
        host.setdefault("children", [])
        for child in children:
            child = dict(child)
            child["children"] = []
            _, llm_used = _merge_into_list(host["children"], child, llm_used)
    return merged


def _merge_into_list(pool: list[dict], cand: dict, llm_used: int) -> tuple[dict, int]:
    key = normalize_name(cand.get("name") or "")
    if not key:
        pool.append(cand)
        return cand, llm_used
    hit, score = _best_match_dict(cand, pool)
    same = False
    if hit and normalize_name(hit.get("name") or "") == key and goods_key(cand) == goods_key(hit):
        same = True
    elif hit and score >= GRAY_JACCARD and llm_used < MAX_LLM_PAIRS:
        llm_used += 1
        same = _llm_same_pair(cand, hit) == "相同"
    if same and hit:
        prefer_incoming = _image_count(cand) > _image_count(hit)
        if prefer_incoming:
            idx = pool.index(hit)
            _union_candidate(cand, hit)
            pool[idx] = cand
            return cand, llm_used
        _union_candidate(hit, cand)
        return hit, llm_used
    pool.append(cand)
    return cand, llm_used


def _best_match_dict(cand: dict, existing: list[dict]) -> tuple[dict | None, float]:
    best: dict | None = None
    best_score = 0.0
    for feat in existing:
        score = name_jaccard(cand.get("name") or "", feat.get("name") or "")
        for alias in feat.get("aliases") or []:
            score = max(score, name_jaccard(cand.get("name") or "", alias))
        if score > best_score:
            best, best_score = feat, score
    return best, best_score


def _union_candidate(base: dict, extra: dict) -> None:
    alias = list(base.get("aliases") or [])
    extra_name = (extra.get("name") or "").strip()
    if extra_name and extra_name != base.get("name") and extra_name not in alias:
        alias.append(extra_name)
    base["aliases"] = alias
    if extra.get("params") and extra["params"] not in (base.get("params") or ""):
        base["params"] = _join_params(base.get("params") or "", extra["params"])
    prefer_extra_text = _image_count(extra) > _image_count(base) or (
        _image_count(extra) > 0 and _image_count(base) == 0
    )
    if prefer_extra_text:
        if extra.get("name"):
            if base.get("name") and extra["name"] != base["name"] and base["name"] not in alias:
                alias.append(base["name"])
                base["aliases"] = alias
            base["name"] = extra["name"]
        if extra.get("intro"):
            base["intro"] = extra["intro"]
        if extra.get("bidCopy"):
            base["bidCopy"] = extra["bidCopy"]
        if extra.get("module"):
            base["module"] = extra["module"]
    else:
        if extra.get("intro") and not base.get("intro"):
            base["intro"] = extra["intro"]
        if extra.get("bidCopy") and not base.get("bidCopy"):
            base["bidCopy"] = extra["bidCopy"]
        if extra.get("module") and not base.get("module"):
            base["module"] = extra["module"]
    ev = list(base.get("evidence") or [])
    for row in extra.get("evidence") or []:
        if row not in ev:
            ev.append(row)
    base["evidence"] = ev
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


def _join_params(left: str, right: str) -> str:
    parts = [p.strip() for p in re.split(r"[；;\n]", left) if p.strip()]
    for piece in re.split(r"[；;\n]", right):
        text = piece.strip()
        if text and text not in parts:
            parts.append(text)
    return "；".join(parts)


def _param_clauses(text: str) -> list[str]:
    return [p.strip() for p in re.split(r"[；;\n]", text or "") if p.strip()]


def _conflict_clauses(existing: str, incoming: str) -> list[str]:
    old = _param_clauses(existing)
    new = _param_clauses(incoming)
    conflicts: list[str] = []
    number_re = re.compile(r"\d+")
    for clause in new:
        nums = number_re.findall(clause)
        if not nums:
            continue
        for other in old:
            if number_re.findall(other) and nums != number_re.findall(other) and _tokens(clause) & _tokens(other):
                conflicts.append(f"{other} ⇄ {clause}")
    return conflicts


def _extract_model_id() -> str:
    from .llm import get_default_model_id

    return get_default_model_id()


def _llm_same_pair(a: dict | ProductFeature, b: dict | ProductFeature) -> str:
    """返回 相同 / 应分开 / 不同。失败时视为不同。"""

    def pack(item: dict | ProductFeature) -> tuple[str, str, str, str, int]:
        if isinstance(item, ProductFeature):
            return (
                item.name or "",
                item.module or "",
                (item.intro or "")[:180],
                (item.params or "")[:180],
                _image_count(item),
            )
        return (
            item.get("name") or "",
            item.get("module") or "",
            (item.get("intro") or "")[:180],
            (item.get("params") or "")[:180],
            _image_count(item),
        )

    an, am, ai, ap, aimg = pack(a)
    bn, bm, bi, bp, bimg = pack(b)
    prompt = (
        "判断下面两条是否为同一产品能力。只回复三个词之一：相同、应分开、不同。\n"
        "相同=实质同一功能，应合并成一条；应分开=相关但写标时要两条；不同=无关。\n"
        "名称相近但能力不同不要判相同。\n\n"
        f"A 名称：{an} 菜单：{am or '无'} 有配图：{'是' if aimg else '否'} 说明：{ai or '无'} 参数：{ap or '无'}\n"
        f"B 名称：{bn} 菜单：{bm or '无'} 有配图：{'是' if bimg else '否'} 说明：{bi or '无'} 参数：{bp or '无'}\n"
    )
    try:
        text = chat_complete(
            model_id=_extract_model_id(),
            messages=[
                {"role": "system", "content": "你只做产品功能点是否重复的判定，不要解释。"},
                {"role": "user", "content": prompt},
            ],
            temperature=0,
            timeout=30,
            max_tokens=20,
        )
    except LlmError:
        return "不同"
    except Exception:
        logger.exception("feature pairwise judge failed")
        return "不同"
    raw = (text or "").strip()
    if "应分开" in raw:
        return "应分开"
    if "相同" in raw:
        return "相同"
    return "不同"


def apply_to_library(
    db: Session,
    source_doc: ProductSourceDoc,
    candidates: list[dict],
) -> dict[str, int]:
    """把本份候选并入产品库。返回 extracted/merged/suspected/conflicts 计数。"""
    existing = (
        db.query(ProductFeature)
        .options(selectinload(ProductFeature.images))
        .filter(ProductFeature.library_id == source_doc.library_id)
        .all()
    )
    stats = {"extracted": 0, "merged": 0, "suspected": 0, "conflicts": 0}
    gray_used = 0
    source_row = {"docId": source_doc.id, "filename": source_doc.filename}

    def apply_one(cand: dict, pool: list[ProductFeature], parent_id: str | None) -> ProductFeature | None:
        nonlocal gray_used
        name = (cand.get("name") or "").strip()
        if not name:
            return None
        hit, score = _best_match(cand, pool)
        action = "new"
        exact = bool(hit and normalize_name(hit.name) == normalize_name(name))
        if hit and exact:
            if (cand.get("kind") == "货物产品" or hit.kind == "货物产品") and goods_key(cand) != goods_key(hit) and goods_key(cand) != "|" and goods_key(hit) != "|":
                action = "new"
            else:
                action = "merge"
        elif hit and score >= GRAY_JACCARD and gray_used < MAX_LLM_PAIRS:
            gray_used += 1
            verdict = _llm_same_pair(cand, hit)
            if verdict == "相同":
                action = "merge"
            elif verdict == "应分开":
                action = "suspect"
            else:
                action = "new"

        if action == "merge" and hit:
            _merge_into_feature(db, hit, cand, source_row)
            stats["merged"] += 1
            if hit.merge_status == "参数冲突":
                stats["conflicts"] += 1
            return hit

        feature = _insert_feature(
            db,
            source_doc.library_id,
            cand,
            source_row,
            "疑似重复" if action == "suspect" else "新增",
            parent_id=parent_id,
        )
        existing.append(feature)
        pool.append(feature)
        stats["extracted"] += 1
        if action == "suspect" and hit:
            ids = list(feature.suspected_ids_json or [])
            if hit.id not in ids:
                ids.append(hit.id)
            feature.suspected_ids_json = ids
            other = list(hit.suspected_ids_json or [])
            if feature.id not in other:
                other.append(feature.id)
            hit.suspected_ids_json = other
            hit.merge_status = "疑似重复" if hit.status != "已入库" else hit.merge_status
            stats["suspected"] += 1
        _save_candidate_images(db, feature, cand.get("images") or [])
        return feature

    roots = [feat for feat in existing if not feat.parent_id]
    for cand in candidates:
        parent = apply_one(cand, roots, None)
        if parent is None:
            continue
        siblings = [feat for feat in existing if feat.parent_id == parent.id]
        for child in cand.get("children") or []:
            apply_one(child, siblings, parent.id)

    return stats


def _best_match(cand: dict, existing: list[ProductFeature]) -> tuple[ProductFeature | None, float]:
    best: ProductFeature | None = None
    best_score = 0.0
    for feat in existing:
        score = name_jaccard(cand.get("name") or "", feat.name)
        for alias in feat.aliases_json or []:
            score = max(score, name_jaccard(cand.get("name") or "", alias))
        if score > best_score:
            best, best_score = feat, score
    return best, best_score


def _merge_into_feature(db: Session, feat: ProductFeature, cand: dict, source_row: dict) -> None:
    extra_name = (cand.get("name") or "").strip()
    aliases = list(feat.aliases_json or [])
    if extra_name and extra_name != feat.name and extra_name not in aliases:
        aliases.append(extra_name)
    feat.aliases_json = aliases

    sources = list(feat.sources_json or [])
    if source_row not in sources and not any(s.get("docId") == source_row.get("docId") for s in sources):
        sources.append(source_row)
    feat.sources_json = sources

    evidence = list(feat.evidence_json or [])
    for row in cand.get("evidence") or []:
        if row not in evidence:
            evidence.append(row)
    feat.evidence_json = evidence

    prefer_incoming = _image_count(cand) > _image_count(feat) or (
        _image_count(cand) > 0 and _image_count(feat) == 0
    )
    incoming_params = (cand.get("params") or "").strip()
    conflicts = _conflict_clauses(feat.params or "", incoming_params)
    if incoming_params:
        feat.params = (
            _join_params(incoming_params, feat.params or "")
            if prefer_incoming
            else _join_params(feat.params or "", incoming_params)
        )
    if conflicts:
        feat.params_conflict_json = list(dict.fromkeys((feat.params_conflict_json or []) + conflicts))
        feat.merge_status = "参数冲突"
        feat.status = "待审核"
    else:
        feat.merge_status = "并入已有"
        if feat.status == "已入库":
            feat.status = "待审核"

    if prefer_incoming:
        if extra_name:
            if feat.name and extra_name != feat.name and feat.name not in aliases:
                aliases.append(feat.name)
                feat.aliases_json = aliases
            feat.name = extra_name
        if cand.get("intro"):
            feat.intro = cand["intro"]
        if cand.get("bidCopy") and not feat.locked_copy:
            feat.bid_copy = cand["bidCopy"]
        if cand.get("module"):
            feat.module = cand["module"]
    else:
        if cand.get("module") and not feat.module:
            feat.module = cand["module"]
        if cand.get("intro") and not feat.intro:
            feat.intro = cand["intro"]
        if cand.get("bidCopy") and not feat.locked_copy and not feat.bid_copy:
            feat.bid_copy = cand["bidCopy"]
    if cand.get("brand") and not feat.brand:
        feat.brand = cand["brand"]
    if cand.get("model") and not feat.model:
        feat.model = cand["model"]
    if cand.get("unit") and not feat.unit:
        feat.unit = cand["unit"]

    _save_candidate_images(db, feat, cand.get("images") or [])


def _insert_feature(
    db: Session,
    library_id: str,
    cand: dict,
    source_row: dict,
    merge_status: str,
    parent_id: str | None = None,
) -> ProductFeature:
    feat = ProductFeature(
        library_id=library_id,
        name=(cand.get("name") or "").strip()[:80],
        kind=_safe_kind(cand.get("kind")),
        module=(cand.get("module") or "").strip()[:80],
        params=(cand.get("params") or "").strip(),
        intro=(cand.get("intro") or "").strip(),
        bid_copy=(cand.get("bidCopy") or cand.get("intro") or "").strip(),
        brand=(cand.get("brand") or "").strip(),
        model=(cand.get("model") or "").strip(),
        unit=(cand.get("unit") or "").strip(),
        status="待审核",
        merge_status=merge_status,
        aliases_json=list(cand.get("aliases") or []),
        sources_json=[source_row],
        evidence_json=list(cand.get("evidence") or []),
        params_conflict_json=[],
        suspected_ids_json=[],
        parent_id=parent_id,
    )
    db.add(feat)
    db.flush()
    return feat


def _safe_kind(kind: str | None) -> str:
    if kind in ("软件功能", "货物产品", "模块方案"):
        return kind
    return "软件功能"


def _save_candidate_images(db: Session, feat: ProductFeature, images: list[dict]) -> None:
    if not images:
        return
    existing = {img.sha256 for img in feat.images if img.sha256}
    for img in images:
        blob = img.get("blob")
        if not blob:
            continue
        digest = img.get("sha256") or sha256_bytes(blob)
        if digest in existing:
            continue
        ext = img.get("ext") or ".png"
        key = storage.put_bytes(f"product-images/{feat.library_id}", blob, ext)
        db.add(
            ProductFeatureImage(
                id=gen_id("pimg"),
                feature_id=feat.id,
                caption=(img.get("caption") or feat.name)[:80],
                kind=_safe_image_kind(img.get("kind")),
                filename=os.path.basename(key),
                storage_path=key,
                sha256=digest,
            )
        )
        existing.add(digest)


def _safe_image_kind(kind: str | None) -> str:
    if kind in ("界面", "架构", "流程", "实物"):
        return kind
    return "界面"


def merge_features(db: Session, keep: ProductFeature, drop: ProductFeature) -> ProductFeature:
    """人工确认把 drop 并入 keep；有配图的名称与说明优先保留。"""
    if _image_count(drop) > _image_count(keep) or (_image_count(drop) > 0 and _image_count(keep) == 0):
        keep, drop = drop, keep

    drop_children = (
        db.query(ProductFeature)
        .filter(ProductFeature.parent_id == drop.id)
        .all()
    )
    keep_children = (
        db.query(ProductFeature)
        .filter(ProductFeature.parent_id == keep.id)
        .all()
    )
    for child in drop_children:
        hit = next(
            (row for row in keep_children if normalize_name(row.name) == normalize_name(child.name)),
            None,
        )
        if hit:
            merge_features(db, hit, child)
            keep_children = [row for row in keep_children if row.id != child.id]
        else:
            child.parent_id = keep.id
            child.module = keep.name
            keep_children.append(child)

    dummy = {
        "name": drop.name,
        "module": drop.module,
        "params": drop.params,
        "intro": drop.intro,
        "bidCopy": drop.bid_copy,
        "brand": drop.brand,
        "model": drop.model,
        "unit": drop.unit,
        "evidence": drop.evidence_json or [],
        "images": [],
    }
    for src in drop.sources_json or []:
        sources = list(keep.sources_json or [])
        if not any(s.get("docId") == src.get("docId") for s in sources):
            sources.append(src)
        keep.sources_json = sources
    _merge_into_feature(db, keep, dummy, {"docId": "", "filename": ""})
    aliases = list(keep.aliases_json or [])
    if drop.name not in aliases and drop.name != keep.name:
        aliases.append(drop.name)
    for alias in drop.aliases_json or []:
        if alias not in aliases and alias != keep.name:
            aliases.append(alias)
    keep.aliases_json = aliases
    keep.merge_status = "并入已有"
    ids = [x for x in (keep.suspected_ids_json or []) if x != drop.id]
    keep.suspected_ids_json = ids

    seen = {img.sha256 for img in keep.images if img.sha256}
    for img in list(drop.images):
        if img.sha256 and img.sha256 in seen:
            storage.delete(img.storage_path)
            continue
        ext = os.path.splitext(img.filename or img.storage_path or "")[1] or ".png"
        old_ref = img.storage_path
        if old_ref and storage.exists(old_ref):
            img.storage_path = storage.copy_object(old_ref, f"product-images/{keep.library_id}", ext)
            if img.storage_path != old_ref:
                storage.delete(old_ref)
        img.feature_id = keep.id
        seen.add(img.sha256)
    db.expire(drop, ["children"])
    db.delete(drop)
    db.flush()
    return keep


def mark_keep_both(keep: ProductFeature, other: ProductFeature) -> None:
    keep.suspected_ids_json = [x for x in (keep.suspected_ids_json or []) if x != other.id]
    other.suspected_ids_json = [x for x in (other.suspected_ids_json or []) if x != keep.id]
    if keep.merge_status == "疑似重复":
        keep.merge_status = "新增"
    if other.merge_status == "疑似重复":
        other.merge_status = "新增"


def match_ingested_features(db: Session, library_id: str, query: str, top_k: int = 6) -> list[ProductFeature]:
    """在已入库一级功能菜单上按章节标题/思路做 BM25 匹配，检索文本含二级目录。"""
    from rank_bm25 import BM25Okapi
    from sqlalchemy.orm import selectinload

    features = (
        db.query(ProductFeature)
        .options(
            selectinload(ProductFeature.children).selectinload(ProductFeature.images),
            selectinload(ProductFeature.images),
        )
        .filter(
            ProductFeature.library_id == library_id,
            ProductFeature.status == "已入库",
            ProductFeature.parent_id.is_(None),
        )
        .all()
    )
    if not features or not (query or "").strip():
        return []
    corpus = []
    for feat in features:
        child_blob = " ".join(
            " ".join([child.name, child.intro or "", child.params or "", child.bid_copy or ""])
            for child in (feat.children or [])
        )
        blob = " ".join(
            [
                feat.name,
                " ".join(feat.aliases_json or []),
                feat.module or "",
                feat.params or "",
                feat.intro or "",
                feat.bid_copy or "",
                child_blob,
            ]
        )
        corpus.append([t for t in jieba.lcut(blob) if t.strip()])
    bm25 = BM25Okapi(corpus)
    scores = bm25.get_scores([t for t in jieba.lcut(query) if t.strip()])
    ranked = sorted(zip(features, scores), key=lambda x: x[1], reverse=True)
    out: list[ProductFeature] = []
    for feat, score in ranked[:top_k]:
        if score <= 0:
            continue
        out.append(feat)
    return out
