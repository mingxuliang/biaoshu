from datetime import datetime
import base64
import os
import re

from celery.utils.log import get_task_logger
from sqlalchemy.orm import joinedload, selectinload
from sqlalchemy.orm.attributes import flag_modified

from .celery_app import celery_app
from .db import SessionLocal
from .engines import e0_tender_parse, e_writer, engineering_writer, parse_schema
from .engines.docx_extract import extract_document_plain_text, extract_full_text
from .engines.tender_package import (
    KIND_BOQ,
    KIND_DRAWING,
    attach_extracts,
    compose_addendum_text,
    compose_parse_text,
    effective_kind,
    engineering_package_warnings,
    extract_file_bundle,
    extra_fills_from_package,
    package_slots,
)
from .engines.extract_quality import merge_stats, parse_fail_reason
from .engines.drawing_intel import analyze_drawings, merge_drawing_fills
from .engines.drawing_rules import extract_drawing_rules
from .engines.drawing_facts import extract_drawing_facts
from .engines.drawing_derive import derive_rules
from .engines.project_rules import compose_project_rules
from .engines.standard_ingest import detect_specialty, detect_work_type
from .engines.tech_rules import extract_tech_rules
from .engines.knowledge_retrieval import list_knowledge_headings, retrieve_by_doc_and_headings, retrieve_for_chapter
from .engines.orchestrator import run_prereview
from .engines.product_extract import run_extract_for_source_doc
from .engines.qualification_extract import run_extract_for_source_doc as run_qualification_extract
from .engines.tender_form import extract_forms_from_storage
from .engines.tender_style import extract_tender_typography_from_storage
from .engines.tender_toc import extract_stipulated_toc
from . import storage
from .models import (
    EvaluationChecklist,
    ProductFeature,
    ProductLibrary,
    Project,
    QualificationAsset,
    ReviewRun,
    TenderDocument,
    WriterDraft,
    WriterChatMessage,
    WriterChatFile,
    WriterImage,
    WriterJob,
    gen_id,
)

logger = get_task_logger(__name__)


@celery_app.task(name="run_prereview_task", soft_time_limit=38 * 60, time_limit=42 * 60)
def run_prereview_task(run_id: str) -> None:
    db = SessionLocal()
    try:
        run_prereview(db, run_id)
    except Exception as exc:  # noqa: BLE001 —— 任一引擎异常都要把任务状态置为 failed，而不是让 worker 静默丢失
        logger.exception("prereview run %s failed", run_id)
        try:
            db.rollback()
            run = db.get(ReviewRun, run_id)
            if run:
                run.status = "failed"
                run.error_message = str(exc)
                run.finished_at = datetime.utcnow()
                db.commit()
        except Exception:
            logger.exception("prereview run %s could not mark failed after rollback", run_id)
    finally:
        db.close()


@celery_app.task(name="run_tender_parse_task", soft_time_limit=36 * 60, time_limit=40 * 60)
def run_tender_parse_task(checklist_id: str) -> None:
    db = SessionLocal()
    try:
        checklist = db.get(EvaluationChecklist, checklist_id)
        if not checklist:
            return

        checklist.status = "running"
        db.commit()

        pending = checklist.checklist_json or {}
        package_ids = [str(x) for x in (pending.get("packageDocIds") or []) if x]
        if not package_ids and checklist.tender_document_id:
            package_ids = [checklist.tender_document_id]

        docs: list[TenderDocument] = []
        seen: set[str] = set()
        for doc_id in package_ids:
            if doc_id in seen:
                continue
            seen.add(doc_id)
            found = db.get(TenderDocument, doc_id)
            if found and found.project_id == checklist.project_id:
                docs.append(found)
        if not docs:
            raise RuntimeError("招标文件不存在，请重新上传")

        project = db.get(Project, checklist.project_id)
        category = parse_schema.normalize_category(project.category if project else None)
        engineering = parse_schema.is_engineering_category(category)

        parts: list[dict] = []
        drawing_intel_failed = False
        drawing_refs: dict[str, str] = {}
        drawing_names: dict[str, str] = {}
        for tender_doc in docs:
            kind = effective_kind(tender_doc.kind, tender_doc.filename, category)
            # 软件服务类不识别施工图纸和工程量清单表格
            if not engineering and kind in (KIND_DRAWING, KIND_BOQ):
                parts.append(
                    {
                        "kind": kind,
                        "filename": tender_doc.filename,
                        "text": "",
                        "boqItems": [],
                        "stats": {},
                        "error": "",
                    }
                )
                continue
            if engineering and kind == KIND_DRAWING and tender_doc.storage_path:
                drawing_refs[tender_doc.id] = tender_doc.storage_path
                drawing_names[tender_doc.id] = tender_doc.filename or "未命名"
            with storage.as_local(tender_doc.storage_path) as path:
                bundle = extract_file_bundle(path, kind=kind, filename=tender_doc.filename, category=category)
            boq_items = bundle.get("boqItems") or []
            if kind == KIND_BOQ and not boq_items:
                boq_items = []
            parts.append(
                {
                    "kind": kind,
                    "filename": tender_doc.filename,
                    "text": bundle.get("text") or "",
                    "boqItems": boq_items,
                    "stats": bundle.get("stats") or {},
                    "error": bundle.get("error") or "",
                }
            )

        extract_stats = merge_stats(parts)
        full_text, notes = compose_parse_text(parts, include_addendum_body=False)
        addendum_text = compose_addendum_text(parts)
        extra_fills = extra_fills_from_package(
            parts,
            notes,
            project_name=project.name if project else "",
            project_type=project.type if project else "",
            category=category,
        )
        if drawing_refs:
            try:
                with storage.as_local_map(drawing_refs) as local_paths:
                    drawing_files = [
                        {"path": local_paths[doc_id], "filename": drawing_names.get(doc_id) or "未命名"}
                        for doc_id in local_paths
                    ]
                    extra_fills = merge_drawing_fills(extra_fills, analyze_drawings(drawing_files))
            except Exception:
                logger.exception("drawing intel failed for checklist %s", checklist_id)
                drawing_intel_failed = True
        result = e0_tender_parse.run(
            full_text, category=category, extra_fills=extra_fills, addendum_text=addendum_text
        )
        filled, _total = parse_schema.filled_row_counts(result.get("dimensions") or [])
        omitted = result.get("omittedCount") or {}
        extract_stats = {
            **extract_stats,
            "filledRows": filled,
            "omittedCount": omitted,
            "tenderCorpusChars": len(full_text or ""),
        }
        fail = parse_fail_reason(extract_stats, filled=filled, llm_error=result.get("error"))
        try:
            tech_pack = extract_tech_rules(result.get("dimensions") or [], full_text or "")
        except Exception:
            logger.exception("tech leaf extract failed for checklist %s", checklist_id)
            tech_pack = {"rules": [], "note": "技术标叶子规则未抽出"}
        extract_stats = {
            **extract_stats,
            "techRuleCount": len(tech_pack.get("rules") or []),
            "techRuleNote": tech_pack.get("note") or "",
        }
        drawing_pack = {"rules": [], "note": ""}
        fact_pack = {"facts": [], "note": ""}
        if drawing_refs:
            try:
                with storage.as_local_map(drawing_refs) as local_paths:
                    files = [
                        {"path": local_paths[doc_id], "filename": drawing_names.get(doc_id) or "未命名"}
                        for doc_id in local_paths
                    ]
                    drawing_pack = extract_drawing_rules(
                        files,
                        tech_pack.get("rules") or [],
                        result.get("dimensions") or [],
                        db=db,
                    )
                    fact_pack = extract_drawing_facts(files, vision=True)
            except Exception:
                logger.exception("drawing rule extract failed for checklist %s", checklist_id)
                drawing_pack = {"rules": [], "note": "图纸评审规则未抽出"}
                fact_pack = {"facts": [], "note": "图纸事实未抽出"}
        extract_stats = {
            **extract_stats,
            "drawingRuleCount": len(drawing_pack.get("rules") or []),
            "drawingRuleNote": drawing_pack.get("note") or "",
        }
        if engineering:
            extract_stats["engineeringWarnings"] = engineering_package_warnings(
                parts, drawing_intel_failed, drawing_pack
            )

        # 清单项目特征是评标得分点，原样保留（项目编码+项目特征+名称/单位/数量/备注），
        # 供图纸事实、规则推导按行对照；现有四列汇总展示（qty-boq）不受影响。
        boq_rows: list[dict] = []
        if engineering:
            for part in parts:
                if part.get("kind") != KIND_BOQ:
                    continue
                for row in part.get("boqItems") or []:
                    if not isinstance(row, dict):
                        continue
                    boq_rows.append(
                        {
                            "code": str(row.get("code") or "")[:40],
                            "name": str(row.get("name") or "")[:120],
                            "unit": str(row.get("unit") or "")[:20],
                            "qty": str(row.get("qty") or "")[:20],
                            "feature": str(row.get("feature") or "")[:400],
                            "remark": str(row.get("remark") or "")[:200],
                        }
                    )
                    if len(boq_rows) >= 2000:
                        break
                if len(boq_rows) >= 2000:
                    break

        # 专业与工程类型只有工程类项目才有意义；用户在项目表单里选过的不覆盖。
        # 工程标通用解析成水利时不回写，避免对话和撰写突然套上水利规则。
        if engineering and not (project.specialty or "").strip():
            specialty_blob = f"{project.name if project else ''}\n{(full_text or '')[:60_000]}"
            project.specialty = engineering_writer.apply_detected_specialty("", detect_specialty(specialty_blob))
        if engineering and not (project.work_type or "").strip():
            work_type_blob = f"{project.name if project else ''}\n{(full_text or '')[:20_000]}"
            project.work_type = detect_work_type(work_type_blob)
        derived = derive_rules(fact_pack.get("facts") or [], project.specialty or "") if engineering else []
        project_rules = (
            compose_project_rules(
                tech_rules=tech_pack.get("rules") or [],
                boq_rows=boq_rows,
                derived_rules=derived,
                specialty=project.specialty or "",
            )
            if engineering
            else []
        )

        checklist.checklist_json = {
            "dimensions": result["dimensions"],
            "scoreRules": result["scoreRules"],
            "mustRespond": result["mustRespond"],
            "qualification": result["qualification"],
            "formatRequirements": result["formatRequirements"],
            "packageDocIds": [d.id for d in docs],
            "package": attach_extracts(package_slots(docs, category), parts),
            "extractStats": extract_stats,
            "tenderCorpus": (full_text or "")[:200_000],
            "omittedCount": omitted,
            "techRules": tech_pack.get("rules") or [],
            "drawingRules": drawing_pack.get("rules") or [],
            "drawingFacts": fact_pack.get("facts") or [],
            "projectRules": project_rules,
            "boqRows": boq_rows,
            "techBidResponseRequirements": "",
            "businessBidResponse": "",
        }
        try:
            from .engines.bid_requirements import extract_bid_requirements

            bid_reqs = extract_bid_requirements(full_text or "")
            checklist.checklist_json["techBidResponseRequirements"] = bid_reqs.get("techBidResponseRequirements") or ""
            checklist.checklist_json["businessBidResponse"] = bid_reqs.get("businessBidResponse") or ""
            extract_stats = {
                **extract_stats,
                "bidRequirementNote": bid_reqs.get("note") or "",
            }
            checklist.checklist_json["extractStats"] = extract_stats
        except Exception:
            logger.exception("bid requirement extract failed for checklist %s", checklist_id)
            extract_stats = {**extract_stats, "bidRequirementNote": "应答需求未抽出"}
            checklist.checklist_json["extractStats"] = extract_stats
        flag_modified(checklist, "checklist_json")
        checklist.engine_params_json = result["vetoParams"]
        if fail:
            checklist.error = fail
            checklist.status = "failed"
        else:
            checklist.error = result.get("error")
            checklist.status = "done"
        checklist.finished_at = datetime.utcnow()
        db.commit()
    except Exception as exc:  # noqa: BLE001 —— 解析失败也要把任务状态置为 failed，而不是让 worker 静默丢失
        logger.exception("tender parse %s failed", checklist_id)
        checklist = db.get(EvaluationChecklist, checklist_id)
        if checklist:
            checklist.status = "failed"
            checklist.error = str(exc)
            checklist.finished_at = datetime.utcnow()
            db.commit()
    finally:
        db.close()


def _knowledge_snippets_for_chapter(db, draft: WriterDraft, chapter_id: str, query: str) -> list[dict]:
    """章节级引用优先（按 docId+heading 精确取片段）；否则回退到全局文档池做 BM25 检索。"""
    refs = (draft.knowledge_refs_json or {}).get(chapter_id) or []
    if refs:
        snippets: list[dict] = []
        for ref in refs:
            source = ref.get("source") or "knowledge"
            if source != "knowledge":
                continue
            doc_id = ref.get("docId")
            if not doc_id:
                continue
            snippets.extend(retrieve_by_doc_and_headings(db, doc_id, ref.get("chapters") or []))
        if snippets:
            return snippets

    doc_ids = draft.selected_knowledge_json or []
    if not doc_ids or not query.strip():
        return []
    return retrieve_for_chapter(db, doc_ids, query)


_QUOTE_CHAPTER_RE = re.compile(r"报价|价格|投标报价")
_PLACEHOLDER_RE = re.compile(r"【此处插入图[:：]?[^】]*】")
_PLACEHOLDER_NUM_RE = re.compile(r"【此处插入图[:：]?\s*(\d+)[^】]*】")
_IMAGE_MIME = {
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".png": "image/png",
    ".gif": "image/gif",
    ".webp": "image/webp",
    ".bmp": "image/bmp",
}
MAX_VISION_IMAGES = 32
MAX_VISION_BYTES_EACH = 2 * 1024 * 1024
MAX_VISION_BYTES_TOTAL = 8 * 1024 * 1024


def _mime_of(filename: str) -> str:
    ext = os.path.splitext(filename or "")[1].lower()
    return _IMAGE_MIME.get(ext, "image/png")


def _knowledge_images_from_snippets(snippets: list[dict]) -> list[dict]:
    """按整包顺序收集知识库原图元数据。"""
    images: list[dict] = []
    seen: set[str] = set()
    for snippet in snippets or []:
        heading = snippet.get("heading") or ""
        for img in snippet.get("images") or []:
            img_id = str(img.get("id") or img.get("storage_path") or "")
            path = img.get("storage_path") or ""
            if not img_id or not path or img_id in seen:
                continue
            seen.add(img_id)
            filename = img.get("filename") or path
            images.append(
                {
                    "id": img.get("id"),
                    "caption": img.get("caption") or heading or "原文附图",
                    "heading": heading,
                    "storage_path": path,
                    "filename": filename,
                    "mime": _mime_of(filename),
                    "b64": "",
                    "prompt_key": f"knowledge-slice:{img.get('id') or path}",
                    "source": "knowledge",
                    "mode": "normal",
                }
            )
    return images


def _images_from_product_features(features: list[ProductFeature]) -> list[dict]:
    images: list[dict] = []
    seen: set[str] = set()

    def walk(feat: ProductFeature, heading: str) -> None:
        for pimg in feat.images or []:
            if not pimg.id or pimg.id in seen or not pimg.storage_path:
                continue
            seen.add(pimg.id)
            kind = pimg.kind or ""
            filename = pimg.filename or pimg.storage_path
            images.append(
                {
                    "id": pimg.id,
                    "caption": pimg.caption or feat.name,
                    "heading": heading,
                    "storage_path": pimg.storage_path,
                    "filename": filename,
                    "mime": _mime_of(filename),
                    "b64": "",
                    "prompt_key": f"product:{feat.id}:{pimg.id}",
                    "source": "product",
                    "mode": "arch" if kind == "架构" else "flow" if kind == "流程" else "normal",
                }
            )
        for child in feat.children or []:
            walk(child, f"{feat.name} / {child.name}")

    for feat in features or []:
        walk(feat, feat.name)
    return images


def _images_from_qualifications(assets: list[QualificationAsset]) -> list[dict]:
    images: list[dict] = []
    seen: set[str] = set()
    for asset in assets or []:
        refs: list[tuple[str, str, str, str]] = []
        for pimg in asset.images or []:
            if pimg.storage_path:
                refs.append((pimg.id, pimg.storage_path, pimg.filename or "", pimg.caption or asset.name))
        if not refs and asset.storage_path:
            refs.append((asset.id, asset.storage_path, asset.filename or "", asset.name))
        for img_id, path, filename, caption in refs:
            key = img_id or path
            if not key or key in seen:
                continue
            seen.add(key)
            images.append(
                {
                    "id": img_id,
                    "caption": caption or asset.name,
                    "heading": asset.name,
                    "storage_path": path,
                    "filename": filename or path,
                    "mime": _mime_of(filename or path),
                    "b64": "",
                    "prompt_key": f"qual:{asset.id}:{img_id}",
                    "source": "qualification",
                    "mode": "normal",
                }
            )
    return images


def _fill_vision(images: list[dict]) -> None:
    vision_total = 0
    vision_count = 0
    for item in images:
        if vision_count >= MAX_VISION_IMAGES:
            break
        path = item.get("storage_path") or ""
        if not path:
            continue
        try:
            blob = storage.get_bytes(path)
        except FileNotFoundError:
            continue
        if (
            blob
            and len(blob) <= MAX_VISION_BYTES_EACH
            and vision_total + len(blob) <= MAX_VISION_BYTES_TOTAL
        ):
            item["b64"] = base64.b64encode(blob).decode("ascii")
            vision_total += len(blob)
            vision_count += 1


def _knowledge_doc_ids_for_chapter(draft: WriterDraft, chapter_id: str) -> list[str]:
    refs = (draft.knowledge_refs_json or {}).get(chapter_id) or []
    ids = [r.get("docId") for r in refs if r.get("docId")]
    if ids:
        return list(dict.fromkeys(ids))
    return list(draft.selected_knowledge_json or [])


def _knowledge_headings_by_doc(draft: WriterDraft, chapter_id: str) -> dict[str, list[str]]:
    mapping: dict[str, list[str]] = {}
    for ref in _refs_of(_chapter_refs(draft, chapter_id), "knowledge"):
        doc_id = ref.get("docId")
        if not doc_id:
            continue
        mapping.setdefault(doc_id, [])
        mapping[doc_id].extend([h for h in (ref.get("chapters") or []) if h])
    return mapping


def _pack_images_from_refs(db, draft: WriterDraft, chapter_id: str) -> list[dict]:
    heading_map = _knowledge_headings_by_doc(draft, chapter_id)
    snippets: list[dict] = []
    if heading_map:
        for doc_id, headings in heading_map.items():
            snippets.extend(retrieve_by_doc_and_headings(db, doc_id, headings))
    else:
        for doc_id in _knowledge_doc_ids_for_chapter(draft, chapter_id):
            snippets.extend(retrieve_by_doc_and_headings(db, doc_id, []))
    return _knowledge_images_from_snippets(snippets)


def _writer_markdown_for_knowledge_image(db, draft: WriterDraft, src: dict, idx: int, mode: str) -> str | None:
    src_id = src.get("id") or ""
    prompt_key = src.get("prompt_key") or (
        f"knowledge-slice:{src_id}" if src_id else f"knowledge-path:{src.get('storage_path')}"
    )
    source = src.get("source") or "knowledge"
    img_mode = src.get("mode") or mode
    existing = (
        db.query(WriterImage)
        .filter(WriterImage.project_id == draft.project_id, WriterImage.prompt == prompt_key)
        .first()
    )
    if existing:
        wimg = existing
    else:
        path = src.get("storage_path") or ""
        if not path:
            return None
        try:
            blob = storage.get_bytes(path)
        except FileNotFoundError:
            return None
        ext = os.path.splitext(src.get("filename") or path)[1] or ".png"
        key = storage.put_bytes(f"writer-images/{draft.project_id}", blob, ext)
        wimg = WriterImage(
            id=gen_id("wimg"),
            project_id=draft.project_id,
            source=source,
            mode=img_mode,
            prompt=prompt_key,
            filename=src.get("filename") or f"{(src.get('heading') or '附图')[:40]}-{idx}{ext}",
            storage_path=key,
        )
        db.add(wimg)
        db.flush()
    alt = src.get("caption") or src.get("heading") or f"原文附图{idx}"
    return f"![{alt}](/api/writer-images/{wimg.id}/file)"


def attach_knowledge_images_for_chapter(
    db,
    draft: WriterDraft,
    chapter_id: str,
    chapter_title: str,
    content: str,
    pack_images: list[dict] | None = None,
) -> str:
    """把整包对象存储原图全部插入正文：占位符按编号替换，未引用的补到章末。"""
    title = chapter_title or ""
    if _QUOTE_CHAPTER_RE.search(title):
        return _PLACEHOLDER_RE.sub("", content)

    images = list(pack_images or []) or _pack_images_from_refs(db, draft, chapter_id)
    if not images:
        return _PLACEHOLDER_RE.sub("", content)

    mode = "arch" if "架构" in title else "flow" if "流程" in title else "normal"
    markdown_by_index: dict[int, str] = {}
    for idx, src in enumerate(images, start=1):
        md = _writer_markdown_for_knowledge_image(db, draft, src, idx, mode)
        if md:
            markdown_by_index[idx] = md

    if not markdown_by_index:
        return _PLACEHOLDER_RE.sub("", content)

    used: set[int] = set()

    def _replace_numbered(match: re.Match) -> str:
        n = int(match.group(1))
        md = markdown_by_index.get(n)
        if md:
            used.add(n)
            return md
        return ""

    replaced = _PLACEHOLDER_NUM_RE.sub(_replace_numbered, content or "")
    leftover = [markdown_by_index[i] for i in sorted(markdown_by_index) if i not in used]
    stripped = _PLACEHOLDER_RE.sub("", replaced).rstrip()
    if leftover:
        return stripped + "\n\n" + "\n\n".join(leftover)
    return stripped


def _chapter_refs(draft: WriterDraft, chapter_id: str) -> list[dict]:
    return list((draft.knowledge_refs_json or {}).get(chapter_id) or [])


def _refs_of(refs: list[dict], source: str) -> list[dict]:
    return [row for row in refs if (row.get("source") or "knowledge") == source]


def _product_features_for_chapter(
    db, draft: WriterDraft, chapter_id: str, query: str
) -> tuple[str | None, list[ProductFeature]]:
    picked_ids: list[str] = []
    library_id = draft.selected_product_library_id
    for ref in _refs_of(_chapter_refs(draft, chapter_id), "product"):
        if ref.get("docId"):
            library_id = ref.get("docId") or library_id
        picked_ids.extend([x for x in (ref.get("chapters") or []) if x])
    library = db.get(ProductLibrary, library_id) if library_id else None
    name = library.name if library else None
    if picked_ids:
        rows = (
            db.query(ProductFeature)
            .options(
                selectinload(ProductFeature.images),
                selectinload(ProductFeature.children).selectinload(ProductFeature.images),
            )
            .filter(ProductFeature.id.in_(picked_ids))
            .all()
        )
        if rows and not name:
            lib = db.get(ProductLibrary, rows[0].library_id)
            name = lib.name if lib else None
        return name, rows
    # 技术方案不再用 BM25 规则猜功能；未勾选/未自动匹配则本章不带产品能力
    return name, []


def _qualifications_for_chapter(db, draft: WriterDraft, chapter_id: str, query: str) -> list[QualificationAsset]:
    picked_ids: list[str] = []
    for ref in _refs_of(_chapter_refs(draft, chapter_id), "qualification"):
        picked_ids.extend([x for x in (ref.get("chapters") or []) if x])
    # 资质材料只取用户在本章勾选的已入库条目；商务章的取材由 business_materials 按招标要求查库，不再按关键词猜
    if not picked_ids:
        return []
    return (
        db.query(QualificationAsset)
        .options(joinedload(QualificationAsset.images))
        .filter(QualificationAsset.id.in_(picked_ids), QualificationAsset.review_status == "已入库")
        .all()
    )


def _latest_checklist_data(db, project_id: str) -> tuple[list[dict], list[dict]]:
    data = _latest_checklist_json(db, project_id)
    return data.get("scoreRules", []), data.get("mustRespond", [])


def _latest_response_fields(db, project_id: str) -> tuple[str, str, list]:
    data = _latest_checklist_json(db, project_id)
    formats = data.get("formatRequirements") or []
    if not isinstance(formats, list):
        formats = []
    return (
        str(data.get("techBidResponseRequirements") or ""),
        str(data.get("businessBidResponse") or ""),
        formats,
    )


def _latest_checklist_json(db, project_id: str) -> dict:
    from .engines.rules_config import select_checklist

    checklist = select_checklist(db, project_id)
    data = (checklist.checklist_json or {}) if checklist else {}
    return data if isinstance(data, dict) else {}


def _project_tender_path(db, project_id: str) -> str | None:
    from .engines.rules_config import select_checklist

    checklist = select_checklist(db, project_id)
    doc = None
    if checklist and checklist.tender_document_id:
        doc = db.get(TenderDocument, checklist.tender_document_id)
    if not doc:
        doc = (
            db.query(TenderDocument)
            .filter(TenderDocument.project_id == project_id)
            .order_by(TenderDocument.uploaded_at.desc())
            .first()
        )
    if doc and doc.storage_path and storage.exists(doc.storage_path):
        return doc.storage_path
    return None


def _fill_form_contents(
    db,
    project_id: str,
    outline: list[dict],
    contents: dict[str, str],
    registry: list[dict],
    tender_text: str = "",
) -> None:
    """登记过格式的章节，正文直接取登记原文；偏离表按每条要求逐行填、报价金额写待填。"""
    from .engines.form_registry import form_content
    from .engines.req_ledger import collect_responses, full_project_ledger

    targets = [n for n in outline if isinstance(n, dict) and n.get("formKeys")]
    if not targets or not registry:
        return
    ledger = full_project_ledger(project_id, tender_text)
    responses = collect_responses(db, project_id)
    for node in targets:
        body = form_content(list(node.get("formKeys") or []), registry, ledger, responses)
        if not body:
            continue
        contents[node["id"]] = body
        node["status"] = "用原文"
        node["part"] = "form"
        node["words"] = len(body.replace(" ", "").replace("\n", ""))


def _extract_business_originals(
    tender_path: str | None, outline: list[dict], model_id: str | None = None
) -> dict[str, str]:
    titles = []
    parent_ids = {str(n.get("parentId")) for n in outline if isinstance(n, dict) and n.get("parentId")}
    for n in outline:
        if not isinstance(n, dict) or n.get("formKeys"):
            continue
        title = str(n.get("title") or "")
        if e_writer.should_paste_tender_original(
            title,
            n.get("part"),
            str(n.get("idea") or ""),
            str(n.get("requirement") or ""),
            has_children=str(n.get("id")) in parent_ids,
        ):
            titles.append(title)
    if not titles or not tender_path:
        return {}
    try:
        return extract_forms_from_storage(tender_path, titles, model_id)
    except Exception:  # noqa: BLE001 —— 原文抽取失败时仍用占位说明，不阻断目录
        logger.exception("extract business originals failed")
        return {}


ENG_OUTLINE_REVIEW_ROUNDS = 2


def _engineering_outline_via_agent(
    draft: WriterDraft,
    job: WriterJob,
    project_name: str,
    tender_text: str,
    facts: dict,
    specialty: str,
    track: str,
    report: dict,
) -> list[dict]:
    """智能体编施组目录，编完按事实账核对，有漏项再让它改一轮。失败返回空列表。"""
    from .engines.writer_harness import HarnessError, write_engineering_outline_markdown

    feedback = ""
    nodes: list[dict] = []
    for attempt in range(ENG_OUTLINE_REVIEW_ROUNDS):
        try:
            markdown = write_engineering_outline_markdown(
                user_id=str(job.user_id or ""),
                project_id=draft.project_id,
                draft_id=draft.id,
                job_id=f"{job.id}-r{attempt + 1}" if attempt else job.id,
                model_id=draft.model_id,
                project_name=project_name,
                tender_text=tender_text,
                facts=facts,
                specialty=specialty,
                track=track,
                review_feedback=feedback,
            )
        except HarnessError:
            logger.exception("engineering outline harness failed")
            return nodes
        except Exception:  # noqa: BLE001 —— 智能体异常不拖垮目录，回退骨架
            logger.exception("engineering outline harness crashed")
            return nodes
        parsed = engineering_writer.outline_from_markdown(markdown, facts, specialty)
        if not parsed:
            return nodes
        nodes = parsed
        issues = engineering_writer.outline_problems(nodes, facts, specialty)
        if not issues or attempt + 1 >= ENG_OUTLINE_REVIEW_ROUNDS:
            break
        feedback = "上一版目录核对未通过，请只补齐这些问题后重新输出整份目录：\n" + "\n".join(
            f"- {item}" for item in issues
        )
    report["agentOutline"] = True
    return nodes


def _generate_engineering_outline(
    db, draft: WriterDraft, job: WriterJob, project_name: str, score_rules: list, tender_text: str, tender_path: str, settings: dict
) -> None:
    """工程技术标：抽工程事实作为撰写输入，目录由智能体通读招标原文编制。

    不做产品匹配、不挂知识库。智能体不可用时回退确定性施组骨架，并在报告里标明。
    """
    project = db.get(Project, draft.project_id)
    specialty = (project.specialty or "").strip() if project else ""
    saved = settings.get(engineering_writer.FACTS_KEY)
    if isinstance(saved, dict) and saved.get("edited"):
        facts = {**engineering_writer.normalize_facts(saved), "edited": True}
    else:
        facts = engineering_writer.extract_facts(
            tender_text, draft.model_id, project_name=project_name, score_rules=score_rules, specialty=specialty
        )
    track = engineering_writer.writer_track(
        project.category if project else "", specialty, draft.doc_kind or "tech"
    )
    report = engineering_writer.outline_coverage(facts, specialty)
    outline = _engineering_outline_via_agent(draft, job, project_name, tender_text, facts, specialty, track, report)
    if not outline:
        outline = engineering_writer.generate_outline(facts, None, specialty)
        report["fallbackOutline"] = True
    report["reviewIssues"] = engineering_writer.outline_problems(outline, facts, specialty)
    if specialty == "水利":
        # 大纲定稿时给每个工艺节预绑定真实条款，正文只许引用这些和招标自带的编号
        try:
            from .engines.standard_review import search_clauses
            from .engines.water_design import attach_clause_refs

            report["clauseBound"] = attach_clause_refs(outline, lambda title: search_clauses(db, title, "水利", limit=3))
        except Exception:  # noqa: BLE001 —— 预绑定失败时正文照旧现查条款
            logger.exception("prebind standard clauses failed")
    settings[engineering_writer.FACTS_KEY] = facts
    for key in ("ledger", "formRegistry", "responses", "placedFeatures"):
        settings.pop(key, None)
    if tender_path:
        try:
            extracted = extract_tender_typography_from_storage(tender_path)
            extracted.pop("margins", None)
            layout = dict(settings.get("layout") or {}) if isinstance(settings.get("layout"), dict) else {}
            layout.update(extracted)
            layout["fromTender"] = True
            settings["layout"] = layout
        except Exception:  # noqa: BLE001 —— 排版识别失败不阻断目录
            logger.exception("extract tender typography failed")
    draft.settings_json = settings
    flag_modified(draft, "settings_json")
    draft.outline_json = outline
    flag_modified(draft, "outline_json")
    draft.chapter_contents_json = {}
    flag_modified(draft, "chapter_contents_json")
    draft.knowledge_refs_json = {}
    flag_modified(draft, "knowledge_refs_json")
    job.status = "done"
    job.finished_at = datetime.utcnow()
    job.result_json = {"coverage": report}
    flag_modified(job, "result_json")
    db.commit()


@celery_app.task(name="run_outline_generate_task")
def run_outline_generate_task(job_id: str) -> None:
    db = SessionLocal()
    try:
        job = db.get(WriterJob, job_id)
        if not job:
            return

        job.status = "running"
        db.commit()

        draft = db.get(WriterDraft, job.draft_id)
        if not draft:
            raise RuntimeError("撰写草稿不存在")

        score_rules, must_respond = _latest_checklist_data(db, draft.project_id)
        # 目录生成不再依赖招标解析模块预抽出的「技术标应答需求」「商务标应答」摘要，
        # 这两段只给对话/正文生成等其它场景用；目录改成智能体自己通读原文。
        _tech_unused, _business_unused, format_requirements = _latest_response_fields(db, draft.project_id)
        del _tech_unused, _business_unused
        project = db.get(Project, draft.project_id)
        project_name = project.name if project else ""
        knowledge_headings = list_knowledge_headings(db, draft.selected_knowledge_json or [], limit=50)
        tender_path = _project_tender_path(db, draft.project_id)
        if not tender_path:
            raise RuntimeError("请先上传招标文件，目录生成需要通读招标书原文")
        tender_toc = {"compose": [], "tech": []}
        tender_text = ""
        with storage.as_local(tender_path) as local_tender:
            tender_toc = extract_stipulated_toc(local_tender)
            try:
                tender_text = extract_document_plain_text(local_tender)
            except Exception:  # noqa: BLE001 —— 表格抽取失败时退回纯段落，仍把正文交给模型
                tender_text = extract_full_text(local_tender)
        from .engines.writer_tool_runtime import load_supplement_text

        supplement = load_supplement_text(draft.project_id)
        if supplement:
            tender_text = f"{tender_text}\n\n{supplement}"
        from .engines.form_registry import scan_forms_from_storage

        form_registry = scan_forms_from_storage(tender_path)

        if not job.user_id:
            raise RuntimeError("目录生成缺少用户隔离信息")
        doc_kind = draft.doc_kind or "tech"
        current_settings = dict(draft.settings_json or {}) if isinstance(draft.settings_json, dict) else {}
        coverage_report: dict = {}
        ledger_rows: list = []
        if engineering_writer.is_engineering_tech(project.category if project else "", doc_kind):
            _generate_engineering_outline(db, draft, job, project_name, score_rules, tender_text, tender_path, current_settings)
            return
        outline = e_writer.generate_outline(
            project_name,
            score_rules,
            must_respond,
            knowledge_headings,
            tender_toc,
            tender_text,
            draft.model_id,
            harness={
                "user_id": job.user_id,
                "project_id": draft.project_id,
                "draft_id": draft.id,
                "job_id": job.id,
            },
            format_requirements=format_requirements,
            doc_kind=doc_kind,
            page=current_settings.get("page") if isinstance(current_settings.get("page"), dict) else None,
            layout=current_settings.get("layout") if isinstance(current_settings.get("layout"), dict) else None,
            report=coverage_report,
            ledger_out=ledger_rows,
            form_registry=form_registry,
        )
        settings = dict(draft.settings_json or {}) if isinstance(draft.settings_json, dict) else {}
        if ledger_rows:
            settings["ledger"] = ledger_rows
        if form_registry:
            settings["formRegistry"] = form_registry
        else:
            settings.pop("formRegistry", None)
        settings.pop("responses", None)  # 目录重做后旧的逐条应答记录作废
        settings.pop("placedFeatures", None)
        draft.settings_json = settings
        flag_modified(draft, "settings_json")

        if tender_path:
            try:
                extracted = extract_tender_typography_from_storage(tender_path)
                settings = dict(draft.settings_json or {}) if isinstance(draft.settings_json, dict) else {}
                layout = dict(settings.get("layout") or {}) if isinstance(settings.get("layout"), dict) else {}
                extracted.pop("margins", None)
                layout.update(extracted)
                layout["fromTender"] = True
                settings["layout"] = layout
                draft.settings_json = settings
                flag_modified(draft, "settings_json")
            except Exception:  # noqa: BLE001 —— 排版识别失败不阻断目录
                logger.exception("extract tender typography failed")

        contents: dict[str, str] = {}
        originals = _extract_business_originals(tender_path, outline, draft.model_id)
        e_writer.fill_business_originals(outline, contents, originals)
        _fill_form_contents(db, draft.project_id, outline, contents, form_registry, tender_text)
        draft.outline_json = outline
        flag_modified(draft, "outline_json")
        draft.chapter_contents_json = contents
        flag_modified(draft, "chapter_contents_json")
        refs: dict = {}
        if draft.selected_product_library_id:
            try:
                from .engines.product_match import apply_outline_product_match

                draft.knowledge_refs_json = {}
                apply_outline_product_match(db, draft, keep_manual=False)
                refs = dict(draft.knowledge_refs_json or {})
            except Exception:  # noqa: BLE001 —— 产品匹配失败不阻断目录
                logger.exception("outline product match failed")
                refs = {}
        draft.knowledge_refs_json = refs
        flag_modified(draft, "knowledge_refs_json")
        db.commit()

        job.status = "done"
        job.finished_at = datetime.utcnow()
        if doc_kind != "business" and not draft.selected_product_library_id and not (draft.selected_knowledge_json or []):
            coverage_report["noKnowledgeSource"] = True
        if coverage_report:
            job.result_json = {"coverage": coverage_report}
            flag_modified(job, "result_json")
        db.commit()
    except Exception as exc:  # noqa: BLE001 —— 生成失败也要把任务状态置为 failed，而不是让 worker 静默丢失
        logger.exception("outline generate job %s failed", job_id)
        job = db.get(WriterJob, job_id)
        if job:
            job.status = "failed"
            job.error = str(exc)
            job.finished_at = datetime.utcnow()
            db.commit()
    finally:
        db.close()


@celery_app.task(name="run_chapter_generate_task")
def run_chapter_generate_task(job_id: str) -> None:
    db = SessionLocal()
    try:
        job = db.get(WriterJob, job_id)
        if not job or job.kind != "chapter" or not job.chapter_id:
            return

        job.status = "running"
        db.commit()
        if not job.user_id:
            raise RuntimeError("章节生成缺少用户隔离信息")
        _generate_one_chapter(db, job.draft_id, job.chapter_id, job.user_id, job.id)

        job = db.get(WriterJob, job_id)
        job.status = "done"
        job.finished_at = datetime.utcnow()
        db.commit()
    except Exception as exc:  # noqa: BLE001 —— 生成失败也要把任务状态置为 failed，而不是让 worker 静默丢失
        logger.exception("chapter generate job %s failed", job_id)
        db.rollback()
        job = db.get(WriterJob, job_id)
        if job:
            job.status = "failed"
            job.error = str(exc)
            job.finished_at = datetime.utcnow()
            db.commit()
    finally:
        db.close()


def _team_form_unfilled(draft: WriterDraft, node: dict) -> bool:
    """团队表章节只有登记原文、还没按资质库填过人员。"""
    settings = draft.settings_json if isinstance(draft.settings_json, dict) else {}
    registry = settings.get("formRegistry") or []
    team = settings.get("teamFill") if isinstance(settings.get("teamFill"), dict) else {}
    return any(
        isinstance(k, int) and 0 <= k < len(registry) and registry[k].get("kind") == "team" and str(k) not in team
        for k in node.get("formKeys") or []
    )


_TEAM_LEDGER_RE = re.compile(r"团队|人员|项目经理|岗位|拟派|驻场")


def _fill_team_forms(db, draft: WriterDraft, keys: list[int], registry: list[dict], ledger: list[dict]) -> dict[str, str]:
    """团队类格式表按岗位从资质证照库挑人，结果存进草稿 settings.teamFill，之后刷新表单时沿用。"""
    from .engines.business_materials import fill_team_form

    targets = [k for k in keys if 0 <= k < len(registry) and registry[k].get("kind") == "team"]
    if not targets:
        return {}
    ledger_text = "\n".join(
        str(e.get("text") or "") for e in ledger if e.get("volume") == "business" and _TEAM_LEDGER_RE.search(str(e.get("text") or ""))
    )
    filled: dict[str, str] = {}
    for key in targets:
        try:
            md, _missing = fill_team_form(db, str(registry[key].get("md") or ""), ledger_text, draft.model_id)
        except Exception:  # noqa: BLE001 —— 填表失败时保留空白原表，不拖垮整章
            logger.exception("team form fill failed for key %s", key)
            continue
        filled[str(key)] = md
    if filled:
        row = (
            db.query(WriterDraft).filter(WriterDraft.id == draft.id).with_for_update().populate_existing().first()
        )
        if row is not None:
            settings = dict(row.settings_json or {}) if isinstance(row.settings_json, dict) else {}
            team = dict(settings.get("teamFill") or {})
            team.update(filled)
            settings["teamFill"] = team
            row.settings_json = settings
            flag_modified(row, "settings_json")
            db.commit()
    return filled


def _material_chapter(
    db, draft: WriterDraft, node: dict, outline: list[dict], chapter_id: str, kind: str
) -> tuple[str, list[str]] | None:
    """商务应答章：按招标要求查资质库取材料。没有材料需求的条款返回 None，走原有写法。"""
    from .engines import business_materials as bm
    from .engines import standard_product as sp

    title = str(node.get("title") or "")
    req, _facts = e_writer.resolve_chapter_requirement(
        outline,
        chapter_id,
        str(node.get("requirement") or ""),
        str(node.get("idea") or ""),
        draft.project_id,
        title,
    )
    if not req.strip() and kind == "business":
        originals = _extract_business_originals(_project_tender_path(db, draft.project_id), [node], draft.model_id)
        req = originals.get(title) or ""
    if not req.strip():
        return None
    try:
        built = bm.build_chapter(db, title, req, draft.model_id)
    except Exception:  # noqa: BLE001 —— 查库失败不能把空白当作命中，交回原有流程
        logger.exception("business materials failed for %s", chapter_id)
        return None
    if not built:
        return None
    evidence = list(dict.fromkeys(built["evidence"]))
    assets = (
        db.query(QualificationAsset)
        .options(joinedload(QualificationAsset.images))
        .filter(QualificationAsset.id.in_(evidence))
        .all()
        if evidence
        else []
    )
    images = {src["prompt_key"]: src for src in _images_from_qualifications(assets)}
    counter = {"n": 0}

    def put_image(match: re.Match) -> str:
        src = images.get(match.group(1))
        if not src:
            return ""
        counter["n"] += 1
        return _writer_markdown_for_knowledge_image(db, draft, src, counter["n"], "normal") or ""

    body = sp.IMG_TOKEN_RE.sub(put_image, built["body"])
    layout = (draft.settings_json or {}).get("layout") if isinstance(draft.settings_json, dict) else None
    return e_writer._wrap_tech_chapter(req, body, layout), evidence


def _is_engineering_draft(db, draft: WriterDraft) -> bool:
    project = db.get(Project, draft.project_id)
    return engineering_writer.is_engineering_tech(project.category if project else "", draft.doc_kind)


def _engineering_facts(db, draft: WriterDraft) -> dict:
    """草稿里没有工程事实（旧草稿）时现抽一次并存回，后续章节复用。"""
    settings = draft.settings_json if isinstance(draft.settings_json, dict) else {}
    facts = settings.get(engineering_writer.FACTS_KEY)
    if isinstance(facts, dict) and facts:
        return facts
    project = db.get(Project, draft.project_id)
    score_rules, _ = _latest_checklist_data(db, draft.project_id)
    facts = engineering_writer.extract_facts(
        engineering_writer.project_tender_text(draft.project_id),
        draft.model_id,
        project_name=project.name if project else "",
        score_rules=score_rules,
    )
    row = db.query(WriterDraft).filter(WriterDraft.id == draft.id).with_for_update().populate_existing().first()
    if row is not None:
        data = dict(row.settings_json or {}) if isinstance(row.settings_json, dict) else {}
        data.setdefault(engineering_writer.FACTS_KEY, facts)
        row.settings_json = data
        flag_modified(row, "settings_json")
        db.commit()
    return facts


def _engineering_plan(db, draft: WriterDraft, facts: dict) -> dict:
    """全书共用的施工计划账。工程事实或清单变了才重编，批量写章前先编好，各章照抄同一本账。"""
    import hashlib

    project = db.get(Project, draft.project_id)
    specialty = (project.specialty or "").strip() if project else ""
    rows = engineering_writer.boq_rows_for(draft.project_id)
    sig_src = engineering_writer.facts_brief(facts, specialty=specialty) + "\n" + engineering_writer._boq_digest(rows)
    sig = hashlib.sha1(sig_src.encode("utf-8")).hexdigest()[:16]
    settings = draft.settings_json if isinstance(draft.settings_json, dict) else {}
    saved = settings.get(engineering_writer.PLAN_KEY)
    if isinstance(saved, dict) and saved.get("sig") == sig:
        return saved
    plan = {**engineering_writer.build_plan(facts, rows, draft.model_id, specialty=specialty), "sig": sig}
    row = db.query(WriterDraft).filter(WriterDraft.id == draft.id).with_for_update().populate_existing().first()
    if row is not None:
        data = dict(row.settings_json or {}) if isinstance(row.settings_json, dict) else {}
        current = data.get(engineering_writer.PLAN_KEY)
        if isinstance(current, dict) and current.get("sig") == sig:
            db.commit()
            return current
        data[engineering_writer.PLAN_KEY] = plan
        row.settings_json = data
        flag_modified(row, "settings_json")
        db.commit()
    return plan


def _generate_one_chapter(
    db, draft_id: str, chapter_id: str, user_id: str, work_id: str, enable_figures: bool = True
) -> str:
    """生成并写回一章。单章任务和批量任务共用；写回时锁草稿行，并发章节互不覆盖。
    返回 tech / form / business，失败直接抛出。"""
    from .engines.writer_harness import DraftBinding

    draft = db.get(WriterDraft, draft_id)
    if not draft:
        raise RuntimeError("撰写草稿不存在")

    binding = DraftBinding(user_id, draft_id, chapter_id)
    outline = [dict(n) for n in (draft.outline_json or [])]
    node = next((n for n in outline if n.get("id") == chapter_id), None)
    if not node:
        raise RuntimeError("章节不存在，可能已被删除")

    has_kids = any(n.get("parentId") == chapter_id for n in outline)
    kind = e_writer.chapter_kind(
        str(node.get("title") or ""),
        node.get("part"),
        str(node.get("idea") or ""),
        str(node.get("requirement") or ""),
        has_children=has_kids,
    )
    if node.get("part") == "tech" and _is_engineering_draft(db, draft):
        from .engines.writer_harness import write_engineering_chapter

        settings = draft.settings_json if isinstance(draft.settings_json, dict) else {}
        layout = settings.get("layout") if isinstance(settings.get("layout"), dict) else None
        project = db.get(Project, draft.project_id)
        facts = _engineering_facts(db, draft)
        try:
            plan = _engineering_plan(db, draft, facts)
        except Exception:  # noqa: BLE001 —— 计划账编不出来时这一节照常写，数字标待核实
            logger.exception("engineering plan for chapter failed")
            plan = None
        content = write_engineering_chapter(
            user_id=user_id,
            project_id=draft.project_id,
            draft_id=draft.id,
            job_id=work_id,
            model_id=draft.model_id,
            node=node,
            outline=outline,
            facts=facts,
            layout=layout,
            specialty=(project.specialty or "").strip() if project else "",
            plan=plan,
        )
        binding.persist_chapter(chapter_id, content, status="已完成", ai_round=True)
        return "tech"
    if kind == "form" and node.get("formKeys"):
        from .engines.form_registry import form_content
        from .engines.req_ledger import collect_responses, full_project_ledger

        settings = draft.settings_json if isinstance(draft.settings_json, dict) else {}
        registry = settings.get("formRegistry") or []
        ledger = full_project_ledger(draft.project_id)
        filled = _fill_team_forms(db, draft, list(node.get("formKeys") or []), registry, ledger)
        content = form_content(
            list(node.get("formKeys") or []),
            registry,
            ledger,
            collect_responses(db, draft.project_id),
            filled,
        )
        if content:
            binding.persist_chapter(chapter_id, content, status="用原文", ai_round=False, part="form")
            return "form"
    # 带条款的商务应答由智能体写。证照、业绩这类商务章才照抄资质库。
    if kind == "business" and not node.get("formKeys"):
        built = _material_chapter(db, draft, node, outline, chapter_id, kind)
        if built is not None:
            content, evidence_ids = built
            binding.persist_chapter(chapter_id, content, status="已完成", ai_round=False, part="business")
            _record_chapter_answer(db, draft_id, node, content, "资质库", evidence_ids, {})
            return "business"
    if kind in ("form", "business"):
        title = str(node.get("title") or "")
        originals = _extract_business_originals(
            _project_tender_path(db, draft.project_id), [node], draft.model_id
        )
        original = originals.get(title) or ""
        content = (
            e_writer.original_form_markdown(title, str(node.get("idea") or ""), original)
            if kind == "form"
            else e_writer.business_skip_markdown(title, original)
        )
        binding.persist_chapter(chapter_id, content, status="用原文", ai_round=False, part=kind)
        return kind

    score_rules, must_respond = _latest_checklist_data(db, draft.project_id)
    dimension_detail = None
    if node.get("dimension"):
        dimension_detail = next((r for r in score_rules if r.get("dimension") == node["dimension"]), None)

    project = db.get(Project, draft.project_id)
    project_name = project.name if project else ""

    query = f"{node.get('title', '')} {node.get('idea', '')}".strip()
    knowledge_snippets = _knowledge_snippets_for_chapter(db, draft, chapter_id, query)
    library_name, product_rows = _product_features_for_chapter(db, draft, chapter_id, query)
    qual_rows = _qualifications_for_chapter(db, draft, chapter_id, query)
    product_payload = None
    if product_rows or draft.selected_product_library_id:
        picked: set[str] = set()
        for ref in _refs_of(_chapter_refs(draft, chapter_id), "product"):
            picked.update(x for x in (ref.get("chapters") or []) if x)
        product_payload = []
        emitted: set[str] = set()

        def _feat_images(feat: ProductFeature) -> list[dict]:
            return [
                {"caption": img.caption or feat.name}
                for img in (feat.images or [])
                if img.storage_path
            ]

        def _add_feat(name: str, module: str, feat: ProductFeature) -> None:
            if feat.id in emitted:
                return
            emitted.add(feat.id)
            product_payload.append(
                {
                    "name": name,
                    "module": module,
                    "params": feat.params or "",
                    "intro": feat.intro or "",
                    "bidCopy": feat.bid_copy or "",
                    "images": _feat_images(feat),
                }
            )

        for feat in product_rows:
            parent_picked = (not picked) or feat.id in picked
            if parent_picked:
                _add_feat(feat.name, feat.module, feat)
            for child in feat.children or []:
                if parent_picked or child.id in picked:
                    _add_feat(f"{feat.name} / {child.name}", feat.name, child)
            if feat.parent_id and feat.id in picked:
                _add_feat(feat.name, feat.module, feat)

    qual_payload = [
        {
            "name": item.name,
            "kind": item.kind,
            "number": item.number,
            "owner": item.owner,
            "validUntil": item.valid_until,
            "detail": item.detail or "",
            "ocrText": item.ocr_text or "",
            "images": [
                {"caption": img.caption or item.name}
                for img in (item.images or [])
                if img.storage_path
            ]
            or ([{"caption": item.name}] if item.storage_path else []),
        }
        for item in qual_rows
    ] or None

    pack_images = _knowledge_images_from_snippets(knowledge_snippets)
    pack_images.extend(_images_from_product_features(product_rows))
    pack_images.extend(_images_from_qualifications(qual_rows))
    _fill_vision(pack_images)

    if not user_id:
        raise RuntimeError("章节生成缺少用户隔离信息")
    def write(requirement_override: str | None = None, idea_override: str | None = None) -> str:
        return e_writer.generate_chapter_content(
            project_name,
            node.get("title", ""),
            idea_override or node.get("idea", ""),
            dimension_detail,
            must_respond,
            knowledge_snippets,
            draft.settings_json or {},
            draft.model_id,
            product_payload,
            library_name,
            qual_payload,
            pack_images,
            node.get("part"),
            requirement_override or node.get("requirement") or "",
            outline,
            chapter_id,
            user_id=user_id,
            project_id=draft.project_id,
            draft_id=draft.id,
            job_id=work_id,
            enable_figures=enable_figures,
        )

    source_label = "自行撰写"
    evidence_ids: list[str] = []
    placed_new: dict[str, dict] = {}
    # 产品功能和知识库只作为写作材料放进提示词，不再用标品拼装结果替换整章。
    content = write()
    kind = e_writer.chapter_kind(
        str(node.get("title") or ""),
        node.get("part"),
        str(node.get("idea") or ""),
        str(node.get("requirement") or ""),
        has_children=has_kids,
    )
    if pack_images and kind == "tech":
        content = attach_knowledge_images_for_chapter(
            db, draft, chapter_id, node.get("title", ""), content, pack_images
        )
    is_form = kind in ("form", "business") or node.get("status") == "用原文"

    binding.persist_chapter(
        chapter_id, content, status="用原文" if is_form else "已完成", ai_round=not is_form
    )
    if not is_form:
        _record_chapter_answer(db, draft_id, node, content, source_label, evidence_ids, placed_new)
    return "form" if is_form else "tech"


def _record_chapter_answer(
    db, draft_id: str, node: dict, content: str, source: str, evidence: list[str], placed_new: dict[str, dict]
) -> None:
    """本章应答结果记到它引用的每条台账上，并登记已放置的标品功能（别的章再引用只写详见）。"""
    from .engines.req_ledger import record_responses

    row = (
        db.query(WriterDraft)
        .filter(WriterDraft.id == draft_id)
        .with_for_update()
        .populate_existing()
        .first()
    )
    if row is None:
        return
    settings = dict(row.settings_json or {}) if isinstance(row.settings_json, dict) else {}
    responses = dict(settings.get("responses") or {})
    refs = [str(r) for r in (node.get("sourceRefs") or [])]
    if refs:
        record_responses(responses, refs, str(node.get("title") or ""), content, source, evidence)
        settings["responses"] = responses
    if placed_new:
        placed = dict(settings.get("placedFeatures") or {})
        placed.update(placed_new)
        settings["placedFeatures"] = placed
    row.settings_json = settings
    flag_modified(row, "settings_json")
    db.commit()


def _standard_chapter(
    db, draft: WriterDraft, node: dict, outline: list[dict], chapter_id: str,
    product_rows: list, knowledge_snippets: list[dict], write,
):
    """标品逐条匹配。章节生成不再调用，避免用拼装结果替换智能体正文。"""
    from .engines import standard_product as sp
    from .engines.writer_tool_runtime import extract_hard_facts, missing_hard_facts

    req, fact_text = e_writer.resolve_chapter_requirement(
        outline,
        chapter_id,
        str(node.get("requirement") or ""),
        str(node.get("idea") or ""),
        draft.project_id,
        str(node.get("title") or ""),
    )
    if not req.strip():
        return None
    rows = list(product_rows)
    library_id = draft.selected_product_library_id
    if library_id:
        pool = (
            db.query(ProductFeature)
            .options(selectinload(ProductFeature.images))
            .filter(ProductFeature.library_id == library_id)
            .all()
        )
        pool = [f for f in pool if (f.status or "待审核") != "已停用"]
        have = {f.id for f in rows}
        rows.extend(f for f in sp.rank_features([f for f in pool if f.id not in have], req) if f.id not in have)
    # 勾选的功能点有下级时也带上下级
    expanded: list = []
    seen_ids: set[str] = set()
    for feat in rows:
        for item in [feat, *(feat.children or [])]:
            if item.id not in seen_ids:
                seen_ids.add(item.id)
                expanded.append(item)
    views = [sp.feature_view(f) for f in expanded[:14]]
    snippets = [s for s in knowledge_snippets if (s.get("text") or "").strip()][:10]
    if not views and not snippets:
        return None
    decision = sp.judge(req, views, snippets, draft.model_id)
    if decision["verdict"] == "无":
        return None
    settings = draft.settings_json if isinstance(draft.settings_json, dict) else {}
    placed = dict(settings.get("placedFeatures") or {})
    body, evidence = sp.build_answer(decision, views, snippets, placed, chapter_id)
    verdict = decision["verdict"]
    gap = decision.get("gap") or ""
    facts = extract_hard_facts(fact_text) if fact_text.strip() else []
    absent = missing_hard_facts(facts, body) if facts else []
    if absent and verdict == "满足":
        verdict = "部分满足"
        gap = "；".join(absent)
        body = body.replace("**响应情况：满足**", "**响应情况：部分满足**", 1)
    gap_body = ""
    if verdict == "部分满足":
        gap_text = gap or "；".join(absent) or req
        wrapped = write(
            f"本章仅需补答下列未被标准产品覆盖的要点：{gap_text}。（完整招标要求：{req}）",
            f"仅补答标准产品未覆盖的要点：{gap_text}",
        )
        gap_body = sp.solution_of(wrapped)
        if not gap_body.strip():
            return None
    body = sp.append_gap_and_deviation(body, verdict, gap, gap_body)
    original = ""
    try:
        from .engines.writer_tool_runtime import load_original_tender_text
        from .engines.tender_toc import extract_response_rules, response_checks

        original = "\n".join(extract_response_rules(load_original_tender_text(draft.project_id)))
        marks = response_checks(original) if e_writer.chapter_follows_response_rule(str(node.get("title") or "")) else []
        if any(m in ("点对点", "逐条", "逐项") for m in marks) and not all(m in body for m in ("点对点", "逐条", "逐项") if m in marks):
            body = "以下按招标要求逐条、逐项、点对点响应。\n\n" + body
    except Exception:  # noqa: BLE001
        logger.exception("response mark check skipped")
    # 把图片占位换成真实图片
    images: dict[str, dict] = {}
    for src in _images_from_product_features(expanded):
        images[f"product:{src['id']}"] = src
    for src in _knowledge_images_from_snippets(snippets):
        images[f"knowledge:{src['id']}"] = src
    counter = {"n": 0}

    def put_image(match: re.Match) -> str:
        src = images.get(match.group(1))
        if not src:
            return ""
        counter["n"] += 1
        md = _writer_markdown_for_knowledge_image(db, draft, src, counter["n"], "normal")
        return md or ""

    body = sp.IMG_TOKEN_RE.sub(put_image, body)
    layout = (draft.settings_json or {}).get("layout") if isinstance(draft.settings_json, dict) else None
    content = e_writer._wrap_tech_chapter(req, body, layout)
    placed_new = {
        fid: {"chapterId": chapter_id, "title": str(node.get("title") or "")}
        for fid in decision.get("featureIds") or []
        if fid not in placed or placed[fid].get("chapterId") == chapter_id
    }
    return content, decision["source"], evidence, placed_new


def _batch_leaf_nodes(outline: list[dict]) -> list[dict]:
    nodes = [n for n in (outline or []) if isinstance(n, dict) and n.get("id")]
    parents = {str(n.get("parentId")) for n in nodes if n.get("parentId")}
    return [n for n in nodes if str(n["id"]) not in parents]


@celery_app.task(name="run_batch_generate_task")
def run_batch_generate_task(job_id: str) -> None:
    """按目录一次生成全部叶子章：默认只补空章节，并发写，单章失败不拖垮整批。"""
    import os
    import threading
    from .ctx_executor import ContextThreadPoolExecutor as ThreadPoolExecutor

    from .engines.writer_harness import DraftBinding

    db = SessionLocal()
    try:
        job = db.get(WriterJob, job_id)
        if not job or job.kind != "batch":
            return
        if not job.user_id:
            raise RuntimeError("批量生成缺少用户隔离信息")
        user_id = job.user_id
        draft_id = job.draft_id
        job.status = "running"
        db.commit()

        draft = db.get(WriterDraft, draft_id)
        if not draft:
            raise RuntimeError("撰写草稿不存在")
        overwrite = bool((job.result_json or {}).get("overwrite")) if isinstance(job.result_json, dict) else False
        contents = dict(draft.chapter_contents_json or {})
        leaves = _batch_leaf_nodes(draft.outline_json or [])
        todo: list[dict] = []
        items: list[dict] = []
        for node in leaves:
            filled = bool(str(contents.get(node["id"]) or "").strip())
            if filled and _team_form_unfilled(draft, node):
                filled = False
            row = {"id": node["id"], "title": str(node.get("title") or ""), "status": "queued"}
            if filled and not overwrite:
                row["status"] = "skipped"
            else:
                todo.append(node)
            items.append(row)
        if not leaves:
            raise RuntimeError("目录里没有可生成的章节")

        if todo and _is_engineering_draft(db, draft):
            try:
                _engineering_plan(db, draft, _engineering_facts(db, draft))
            except Exception:  # noqa: BLE001 —— 计划账编不出来时各章照常写，数字标待核实
                logger.exception("engineering plan before batch failed")
            db.expire_all()
            draft = db.get(WriterDraft, draft_id)

        lock = threading.Lock()
        state = {"overwrite": overwrite, "total": len(todo), "done": 0, "skipped": len(leaves) - len(todo), "items": items}

        def publish() -> None:
            session = SessionLocal()
            try:
                row = session.get(WriterJob, job_id)
                if row is None:
                    return
                row.result_json = {
                    **state,
                    "items": [dict(item) for item in items],
                    "failed": [dict(item) for item in items if item["status"] == "failed"],
                }
                flag_modified(row, "result_json")
                session.commit()
            finally:
                session.close()

        def mark(node_id: str, status: str, error: str = "") -> None:
            with lock:
                for item in items:
                    if item["id"] == node_id:
                        item["status"] = status
                        if error:
                            item["error"] = error[:300]
                if status in ("done", "failed"):
                    state["done"] += 1
                publish()

        publish()

        def work(index: int, node: dict) -> None:
            node_id = str(node["id"])
            previous = "已完成" if str(contents.get(node_id) or "").strip() else "待生成"
            binding = DraftBinding(user_id, draft_id, node_id)
            mark(node_id, "running")
            try:
                binding.set_chapter_status(node_id, "生成中")
                session = SessionLocal()
                try:
                    _generate_one_chapter(session, draft_id, node_id, user_id, f"{job_id}-{index}")
                finally:
                    session.close()
                mark(node_id, "done")
            except Exception as exc:  # noqa: BLE001 —— 单章失败只记录，不中断整批
                logger.exception("batch chapter %s failed", node_id)
                try:
                    binding.set_chapter_status(node_id, previous)
                except Exception:  # noqa: BLE001
                    logger.exception("restore chapter status failed")
                mark(node_id, "failed", str(exc))

        workers = max(1, min(int(os.environ.get("WRITER_BATCH_CONCURRENCY", "3") or 3), 6))
        with ThreadPoolExecutor(max_workers=workers) as pool:
            for index, node in enumerate(todo):
                pool.submit(work, index, node)

        failed = [item for item in items if item["status"] == "failed"]
        db.expire_all()  # 进度是别的会话写的，这里要读最新
        job = db.get(WriterJob, job_id)
        if todo and len(failed) == len(todo):
            job.status = "failed"
            job.error = f"全部 {len(failed)} 章生成失败：" + (failed[0].get("error") or "")
        draft = db.get(WriterDraft, draft_id)
        project = db.get(Project, draft.project_id) if draft else None
        if (
            draft is not None
            and project is not None
            and (project.specialty or "").strip() == "水利"
            and draft.doc_kind == "tech"
        ):
            from .engines.engineering_check import run_water_check

            settings = dict(draft.settings_json or {}) if isinstance(draft.settings_json, dict) else {}
            checked = run_water_check(
                db,
                draft.project_id,
                settings.get(engineering_writer.FACTS_KEY),
                draft.outline_json or [],
                draft.chapter_contents_json or {},
            )
            settings["waterCheckJson"] = checked
            draft.settings_json = settings
            flag_modified(draft, "settings_json")
            state["waterCheck"] = checked
            publish()
        else:
            job.status = "done"
        job.finished_at = datetime.utcnow()
        db.commit()
        publish_after = dict(job.result_json or {})
        publish_after["finished"] = True
        job.result_json = publish_after
        flag_modified(job, "result_json")
        if state.get("waterCheck"):
            publish_after["waterCheck"] = state["waterCheck"]
        db.commit()
    except Exception as exc:  # noqa: BLE001
        logger.exception("batch generate job %s failed", job_id)
        db.rollback()
        job = db.get(WriterJob, job_id)
        if job:
            job.status = "failed"
            job.error = str(exc)
            job.finished_at = datetime.utcnow()
            db.commit()
    finally:
        db.close()


@celery_app.task(name="run_writer_chat_task")
def run_writer_chat_task(job_id: str) -> None:
    from .engines.writer_harness import HarnessError, run_chat

    db = SessionLocal()
    try:
        job = db.get(WriterJob, job_id)
        if not job or job.kind != "chat":
            return
        job.status = "running"
        db.commit()

        draft = db.get(WriterDraft, job.draft_id)
        if not draft:
            raise RuntimeError("撰写草稿不存在")
        if not job.user_id:
            raise RuntimeError("对话缺少用户隔离信息")
        payload = job.result_json if isinstance(job.result_json, dict) else {}
        message = db.get(WriterChatMessage, str(payload.get("messageId") or ""))
        if message is None or message.user_id != job.user_id or message.draft_id != draft.id:
            raise RuntimeError("对话消息不存在")
        history_rows = (
            db.query(WriterChatMessage)
            .filter(
                WriterChatMessage.user_id == job.user_id,
                WriterChatMessage.draft_id == draft.id,
                WriterChatMessage.id != message.id,
            )
            .order_by(WriterChatMessage.created_at.asc())
            .all()
        )
        history = [{"role": row.role, "content": row.content or ""} for row in history_rows[-12:]]
        file_ids = [item for item in (payload.get("fileIds") or []) if item]
        attached = []
        if file_ids:
            attached = (
                db.query(WriterChatFile)
                .filter(
                    WriterChatFile.id.in_(file_ids),
                    WriterChatFile.user_id == job.user_id,
                    WriterChatFile.draft_id == draft.id,
                )
                .all()
            )
        def publish_trace(steps: list[dict], reply: str = "") -> None:
            session = SessionLocal()
            try:
                row = session.get(WriterJob, job_id)
                if row is None or row.status in ("done", "failed"):
                    return
                current = dict(row.result_json or {})
                current["engine"] = "AgentScope"
                current["trace"] = steps
                if reply:
                    current["reply"] = reply
                row.result_json = current
                flag_modified(row, "result_json")
                session.commit()
            finally:
                session.close()

        result = run_chat(
            user_id=job.user_id,
            project_id=draft.project_id,
            draft_id=draft.id,
            job_id=job.id,
            model_id=draft.model_id,
            chapter_id=job.chapter_id,
            history=history,
            message=message.content or "",
            uploads=[{"filename": item.filename, "storagePath": item.storage_path} for item in attached],
            on_trace=publish_trace,
        )
        edits = result.get("edits") or []
        reply = str(result.get("reply") or "")
        trace = result.get("trace") or []
        db.add(
            WriterChatMessage(
                user_id=job.user_id,
                draft_id=draft.id,
                role="assistant",
                content=reply,
                edits_json=edits,
                trace_json=trace,
            )
        )
        job.result_json = {
            "reply": reply,
            "edits": edits,
            "hasChecklist": False,
            "engine": "AgentScope",
            "trace": trace,
        }
        flag_modified(job, "result_json")
        job.status = "done"
        job.finished_at = datetime.utcnow()
        db.commit()
    except (HarnessError, Exception) as exc:  # noqa: BLE001 —— 对话失败要写回任务状态
        logger.exception("writer chat job %s failed", job_id)
        job = db.get(WriterJob, job_id)
        if job:
            job.status = "failed"
            job.error = str(exc)
            job.finished_at = datetime.utcnow()
            db.commit()
    finally:
        db.close()


@celery_app.task(name="import_platform_standard_task")
def import_platform_standard_task(path: str, filename: str, catalog_id: str) -> None:
    from .db import platform_session
    from .engines.standard_ingest import save_platform_standard
    from .platform_models import StdCatalog

    try:
        save_platform_standard(path, filename, catalog_id)
    except Exception as exc:
        db = platform_session()
        try:
            row = db.get(StdCatalog, catalog_id)
            if row is not None:
                row.status = "失败"
                row.note = str(exc)[:200]
                db.commit()
        finally:
            db.close()


@celery_app.task(name="run_product_match_task")
def run_product_match_task(job_id: str) -> None:
    db = SessionLocal()
    try:
        job = db.get(WriterJob, job_id)
        if not job or job.kind != "product-match":
            return
        job.status = "running"
        db.commit()
        draft = db.get(WriterDraft, job.draft_id)
        if not draft:
            raise RuntimeError("撰写草稿不存在")
        if not draft.selected_product_library_id:
            raise RuntimeError("请先在标书设置中选择产品功能库")
        from .engines.product_match import apply_outline_product_match

        chapter_ids = [job.chapter_id] if job.chapter_id else None
        apply_outline_product_match(db, draft, chapter_ids=chapter_ids, keep_manual=True)
        flag_modified(draft, "knowledge_refs_json")
        db.commit()
        job.status = "done"
        job.finished_at = datetime.utcnow()
        db.commit()
    except Exception as exc:  # noqa: BLE001
        logger.exception("product match job %s failed", job_id)
        job = db.get(WriterJob, job_id)
        if job:
            job.status = "failed"
            job.error = str(exc)
            job.finished_at = datetime.utcnow()
            db.commit()
    finally:
        db.close()


@celery_app.task(name="run_product_extract_task")
def run_product_extract_task(source_doc_id: str) -> None:
    db = SessionLocal()
    try:
        run_extract_for_source_doc(db, source_doc_id)
    except Exception:  # noqa: BLE001 —— 状态已在引擎内置 failed
        logger.exception("product extract task %s failed", source_doc_id)
    finally:
        db.close()


@celery_app.task(name="run_qualification_extract_task")
def run_qualification_extract_task(source_doc_id: str) -> None:
    db = SessionLocal()
    try:
        run_qualification_extract(db, source_doc_id)
    except Exception:  # noqa: BLE001
        logger.exception("qualification extract task %s failed", source_doc_id)
    finally:
        db.close()


@celery_app.task(name="run_knowledge_ingest_task")
def run_knowledge_ingest_task(doc_id: str) -> None:
    from .engines.knowledge_ingest import ingest_knowledge_document

    db = SessionLocal()
    try:
        ingest_knowledge_document(db, doc_id)
    except Exception:  # noqa: BLE001
        logger.exception("knowledge ingest task %s failed", doc_id)
    finally:
        db.close()
