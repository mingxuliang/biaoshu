"""技术方案目录 ↔ 产品功能库：用大模型按语义匹配，不用标题关键词/BM25。"""

from __future__ import annotations

import json
import logging
import re

from sqlalchemy.orm import Session, selectinload

from ..models import ProductFeature, ProductLibrary, WriterDraft
from .llm import LlmError, chat_complete

logger = logging.getLogger(__name__)

_MATCH_SYSTEM = """你是投标技术方案匹配专家。任务：把「技术标目录章节」对应到本公司产品功能库中真正相关的功能点。

规则：
1. 按招标需求语义对应，不要因为个别字相同就匹配；标题、模块、培训/平台/课程等同类能力应选上，不要漏掉明显相关的功能。
2. 一章可以对应多个功能点（一级及其下级二级都可以选）；一个功能点也可以被多章引用，但优先给最贴切的那一章。
3. featureIds 必须逐字复制清单里的 id，禁止编造，也不要用功能名称代替 id。
4. 每条输入章节都必须出现在 items 里；确实完全无关再给空数组 []。
5. 只输出 JSON：{"items":[{"chapterId":"与输入完全一致","featureIds":["id1","id2"]}]}
"""

_DISABLED_STATUS = {"已停用"}
CATALOG_SNIPPET_CHARS = 90  # 清单里每个功能给模型看的摘要字数
REQUIREMENT_CHARS = 400  # 每个待匹配章节给模型看的需求字数
CATALOG_CHUNK_LINES = 120  # 功能清单超过这个行数就按一级功能分块，不再整库重发


def _usable(status: str | None) -> bool:
    return (status or "待审核") not in _DISABLED_STATUS


def _norm_name(value: str) -> str:
    return re.sub(r"\s+", "", (value or "").strip()).lower()


def catalog_library_features(db: Session, library_id: str) -> tuple[str, set[str], dict[str, str], str]:
    """返回 (给模型的功能清单文本, 合法 id 集合, 名称→id, 产品库名称)。待审核与已入库均可匹配，排除已停用。"""
    library = db.get(ProductLibrary, library_id)
    name = library.name if library else "产品库"
    roots = (
        db.query(ProductFeature)
        .options(selectinload(ProductFeature.children))
        .filter(ProductFeature.library_id == library_id, ProductFeature.parent_id.is_(None))
        .order_by(ProductFeature.name.asc())
        .all()
    )
    lines: list[str] = []
    ids: set[str] = set()
    name_to_id: dict[str, str] = {}

    def _add(fid: str, fname: str, level: str, intro: str) -> None:
        if not fid:
            return
        ids.add(fid)
        key = _norm_name(fname)
        if key and key not in name_to_id:
            name_to_id[key] = fid
        snippet = re.sub(r"\s+", " ", intro).strip()[:CATALOG_SNIPPET_CHARS]
        lines.append(f"{fid}\t{fname}\t{level}" + (f"\t{snippet}" if snippet else ""))

    for feat in roots:
        if not _usable(feat.status):
            continue
        _add(feat.id, feat.name or "", "一级", feat.intro or feat.params or "")
        for child in feat.children or []:
            if not _usable(child.status):
                continue
            _add(child.id, child.name or "", feat.name or "二级", child.intro or child.params or "")
    return "\n".join(lines), ids, name_to_id, name


def tech_chapters_for_match(outline: list[dict], chapter_ids: list[str] | None = None) -> list[dict]:
    from .e_writer import chapter_kind, is_original_form_title

    wanted = set(chapter_ids or [])
    # 整份目录匹配时只管叶子章：批量撰写只写叶子，父节点（如 4.1 小节）没有正文可挂功能
    parents = {str(n.get("parentId")) for n in outline if isinstance(n, dict) and n.get("parentId")}
    out: list[dict] = []
    for n in outline:
        if not isinstance(n, dict):
            continue
        cid = str(n.get("id") or "")
        if wanted and cid not in wanted:
            continue
        if not wanted and cid in parents:
            continue
        title = str(n.get("title") or "")
        kind = chapter_kind(
            title, n.get("part"), str(n.get("idea") or ""), str(n.get("requirement") or "")
        )
        if kind != "tech" or is_original_form_title(title):
            continue
        req = (str(n.get("requirement") or "") or str(n.get("idea") or "")).strip()
        req = re.sub(r"\s+", " ", req)[:REQUIREMENT_CHARS]
        out.append(
            {
                "chapterId": cid,
                "num": str(n.get("num") or ""),
                "title": title,
                "requirement": req,
            }
        )
    return out


def _parse_items(text: str) -> list[dict]:
    raw = (text or "").strip()
    if raw.startswith("```"):
        raw = re.sub(r"^```[a-zA-Z]*\s*\n?", "", raw)
        raw = re.sub(r"\n?```\s*$", "", raw).strip()
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        m = re.search(r"\{[\s\S]*\}", raw)
        if not m:
            return []
        try:
            data = json.loads(m.group(0))
        except json.JSONDecodeError:
            return []
    if isinstance(data, dict) and isinstance(data.get("items"), list):
        return [x for x in data["items"] if isinstance(x, dict)]
    if isinstance(data, list):
        return [x for x in data if isinstance(x, dict)]
    return []


def _resolve_chapter_id(raw: str, by_id: dict[str, dict], by_num: dict[str, str], by_title: dict[str, str]) -> str:
    cid = (raw or "").strip()
    if cid in by_id:
        return cid
    if cid in by_num:
        return by_num[cid]
    compact = _norm_name(cid)
    if compact in by_title:
        return by_title[compact]
    return ""


def _resolve_feature_id(raw: str, valid_ids: set[str], name_to_id: dict[str, str]) -> str:
    sid = str(raw or "").strip()
    if sid in valid_ids:
        return sid
    return name_to_id.get(_norm_name(sid), "")


def match_chapters_to_features(
    chapters: list[dict],
    catalog: str,
    valid_ids: set[str],
    model_id: str | None,
    name_to_id: dict[str, str] | None = None,
    stats: dict | None = None,
) -> dict[str, list[str]]:
    """chapterId -> featureIds。全部批次都失败时抛错。

    功能清单超过 CATALOG_CHUNK_LINES 行时按一级功能分块，每块各问一遍再合并，不整库重发。
    stats 若传入，会写入 failedChapterIds：所属批次调用失败、没有得到结果的章节。"""
    if not chapters or not catalog.strip() or not valid_ids:
        return {}
    names = name_to_id or {}
    by_id = {str(c.get("chapterId") or ""): c for c in chapters if c.get("chapterId")}
    by_num = {str(c.get("num") or "").strip(): str(c["chapterId"]) for c in chapters if c.get("num")}
    by_title = {_norm_name(str(c.get("title") or "")): str(c["chapterId"]) for c in chapters if c.get("title")}
    out: dict[str, list[str]] = {}
    answered: set[str] = set()
    failed: set[str] = set()
    batch_size = 20
    rows = list(chapters)
    chunks = _catalog_chunks(catalog)
    llm_ok = False
    for i in range(0, len(rows), batch_size):
        batch = rows[i : i + batch_size]
        chap_txt = "\n".join(
            f"{c['chapterId']}\t{c.get('num') or ''}\t{c.get('title') or ''}\t{c.get('requirement') or ''}"
            for c in batch
        )
        batch_ids = {str(c.get("chapterId") or "") for c in batch}
        for chunk in chunks:
            user = (
                "产品功能清单（id\\t名称\\t层级或上级\\t摘要）：\n"
                f"{chunk}\n\n"
                "待匹配的技术标章节（chapterId 必须原样写回；编号\\t标题\\t需求摘要）：\n"
                f"{chap_txt}\n"
            )
            try:
                text = chat_complete(
                    model_id=model_id,
                    messages=[
                        {"role": "system", "content": _MATCH_SYSTEM},
                        {"role": "user", "content": user},
                    ],
                    temperature=0.1,
                    timeout=180,
                    max_tokens=4096,
                )
                llm_ok = True
            except LlmError:
                logger.exception("llm product-outline match failed")
                failed.update(batch_ids)
                continue
            parsed = _parse_items(text)
            if not parsed:
                logger.warning("product-outline match returned unparseable JSON: %s", (text or "")[:400])
                failed.update(batch_ids)
                continue
            for item in parsed:
                cid = _resolve_chapter_id(
                    str(item.get("chapterId") or item.get("id") or ""),
                    by_id,
                    by_num,
                    by_title,
                )
                if not cid:
                    continue
                raw_ids = item.get("featureIds") or item.get("features") or item.get("feature_ids") or []
                if not isinstance(raw_ids, list):
                    continue
                answered.add(cid)
                ids = out.setdefault(cid, [])
                for fid in raw_ids:
                    sid = _resolve_feature_id(fid, valid_ids, names)
                    if sid and sid not in ids:
                        ids.append(sid)
    if not llm_ok:
        raise LlmError("产品功能匹配失败：大模型不可用")
    if stats is not None:
        stats["failedChapterIds"] = sorted(failed - answered)
    return out


def _catalog_chunks(catalog: str) -> list[str]:
    """按一级功能切块：同一个一级功能和它的下级始终在同一块里。"""
    lines = [ln for ln in (catalog or "").split("\n") if ln.strip()]
    if len(lines) <= CATALOG_CHUNK_LINES:
        return ["\n".join(lines)]
    groups: list[list[str]] = []
    for ln in lines:
        parts = ln.split("\t")
        is_root = len(parts) >= 3 and parts[2] == "一级"
        if is_root or not groups:
            groups.append([ln])
        else:
            groups[-1].append(ln)
    chunks: list[list[str]] = [[]]
    for group in groups:
        if chunks[-1] and len(chunks[-1]) + len(group) > CATALOG_CHUNK_LINES:
            chunks.append([])
        chunks[-1].extend(group)
    return ["\n".join(c) for c in chunks if c]


def merge_product_refs(
    existing: dict,
    matches: dict[str, list[str]],
    library_id: str,
    library_name: str,
    *,
    keep_manual: bool = True,
) -> dict:
    """把匹配结果写入 knowledge_refs。默认不覆盖用户手动勾选的产品功能。"""
    out: dict = {str(k): list(v) for k, v in (existing or {}).items() if isinstance(v, list)}
    for chapter_id, feat_ids in matches.items():
        refs = list(out.get(chapter_id) or [])
        kept: list[dict] = []
        skip_product = False
        for ref in refs:
            if not isinstance(ref, dict):
                continue
            if (ref.get("source") or "knowledge") != "product":
                kept.append(ref)
                continue
            if keep_manual and ref.get("mode") == "manual" and (ref.get("chapters") or []):
                kept.append(ref)
                skip_product = True
        if not skip_product and feat_ids:
            kept.append(
                {
                    "source": "product",
                    "docId": library_id,
                    "docTitle": library_name,
                    "chapters": feat_ids,
                    "mode": "ai",
                }
            )
        out[chapter_id] = kept
    return out


def apply_outline_product_match(
    db: Session,
    draft: WriterDraft,
    *,
    chapter_ids: list[str] | None = None,
    keep_manual: bool = True,
    stats: dict | None = None,
) -> int:
    """匹配并写回 draft.knowledge_refs_json。返回绑定了功能点的章节数。

    stats 若传入会写入 productMatch 覆盖信息：total、hit、unmatched（未命中小节标题）、
    failedChapterIds（调用失败的章节，不会被记成「已匹配、没有功能」）、pendingFeatures（用到的待审核功能数）。"""
    library_id = draft.selected_product_library_id
    if not library_id:
        return 0
    outline = list(draft.outline_json or [])
    chapters = tech_chapters_for_match(outline, chapter_ids)
    catalog, valid_ids, name_to_id, lib_name = catalog_library_features(db, library_id)
    if not valid_ids:
        raise RuntimeError("所选产品功能库没有可匹配的功能点（已停用除外），请先在产品功能库抽取功能")
    if not chapters:
        raise RuntimeError("当前目录没有可匹配的技术标章节")
    inner: dict = {}
    matches = match_chapters_to_features(
        chapters, catalog, valid_ids, draft.model_id, name_to_id=name_to_id, stats=inner
    )
    failed_ids = set(inner.get("failedChapterIds") or [])
    if not matches and not chapter_ids and not failed_ids:
        return 0
    wanted = list(chapter_ids) if chapter_ids else [
        str(ch.get("chapterId") or "") for ch in chapters if ch.get("chapterId")
    ]
    for cid in wanted:
        if cid not in failed_ids:
            matches.setdefault(cid, [])
    if stats is not None:
        titles = {str(ch.get("chapterId") or ""): str(ch.get("title") or "") for ch in chapters}
        used = {fid for ids in matches.values() for fid in ids}
        pending = (
            db.query(ProductFeature)
            .filter(ProductFeature.id.in_(used), ProductFeature.status == "待审核")
            .count()
            if used
            else 0
        )
        stats.update(
            {
                "libraryId": library_id,
                "libraryName": lib_name,
                "total": len(wanted),
                "hit": sum(1 for cid in wanted if matches.get(cid)),
                "unmatched": [titles.get(cid, cid) for cid in wanted if cid not in failed_ids and not matches.get(cid)],
                "failedChapterIds": sorted(failed_ids),
                "pendingFeatures": pending,
            }
        )
    refs = merge_product_refs(
        draft.knowledge_refs_json or {},
        matches,
        library_id,
        lib_name,
        keep_manual=keep_manual,
    )
    draft.knowledge_refs_json = refs
    hit = sum(1 for ids in matches.values() if ids)
    logger.info(
        "product match draft=%s library=%s features=%s tech_chapters=%s hit=%s",
        draft.id,
        library_id,
        len(valid_ids),
        len(chapters),
        hit,
    )
    return hit


def match_single_chapter(db: Session, draft_id: str, chapter_id: str) -> bool:
    """生成某章时发现它从没匹配过（目录阶段匹配失败），单独补匹配一次并写回。

    匹配本身不持锁；写回时锁草稿行再合并，批量并发生成时互不覆盖。失败只记日志，返回 False。"""
    from sqlalchemy.orm.attributes import flag_modified

    draft = db.get(WriterDraft, draft_id)
    if not draft or not draft.selected_product_library_id:
        return False
    library_id = draft.selected_product_library_id
    try:
        chapters = tech_chapters_for_match(list(draft.outline_json or []), [chapter_id])
        catalog, valid_ids, name_to_id, lib_name = catalog_library_features(db, library_id)
        if not chapters or not valid_ids:
            return False
        inner: dict = {}
        matches = match_chapters_to_features(
            chapters, catalog, valid_ids, draft.model_id, name_to_id=name_to_id, stats=inner
        )
        if chapter_id in (inner.get("failedChapterIds") or []):
            return False
        matches.setdefault(chapter_id, [])
        row = (
            db.query(WriterDraft)
            .filter(WriterDraft.id == draft_id)
            .with_for_update()
            .populate_existing()
            .first()
        )
        if row is None:
            return False
        row.knowledge_refs_json = merge_product_refs(
            row.knowledge_refs_json or {}, {chapter_id: matches[chapter_id]}, library_id, lib_name, keep_manual=True
        )
        flag_modified(row, "knowledge_refs_json")
        db.commit()
        db.refresh(draft)
        return True
    except Exception:  # noqa: BLE001 —— 单章补匹配失败不阻断写章
        logger.exception("single chapter product match failed chapter=%s", chapter_id)
        db.rollback()
        return False
