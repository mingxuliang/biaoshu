from datetime import datetime
import base64
import os
import re

from celery.utils.log import get_task_logger
from sqlalchemy.orm import joinedload, selectinload
from sqlalchemy.orm.attributes import flag_modified

from .celery_app import celery_app
from .db import SessionLocal
from .engines import e0_tender_parse, e_writer
from .engines.docx_extract import extract_document_plain_text, extract_full_text
from .engines.knowledge_retrieval import list_knowledge_headings, retrieve_by_doc_and_headings, retrieve_for_chapter
from .engines.orchestrator import run_prereview
from .engines.product_extract import run_extract_for_source_doc
from .engines.qualification_extract import run_extract_for_source_doc as run_qualification_extract
from .engines.tender_form import extract_forms_from_storage
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
    WriterImage,
    WriterJob,
    gen_id,
)

logger = get_task_logger(__name__)


@celery_app.task(name="run_prereview_task")
def run_prereview_task(run_id: str) -> None:
    db = SessionLocal()
    try:
        run_prereview(db, run_id)
    except Exception as exc:  # noqa: BLE001 —— 任一引擎异常都要把任务状态置为 failed，而不是让 worker 静默丢失
        logger.exception("prereview run %s failed", run_id)
        run = db.get(ReviewRun, run_id)
        if run:
            run.status = "failed"
            run.error_message = str(exc)
            run.finished_at = datetime.utcnow()
            db.commit()
    finally:
        db.close()


@celery_app.task(name="run_tender_parse_task")
def run_tender_parse_task(checklist_id: str) -> None:
    db = SessionLocal()
    try:
        checklist = db.get(EvaluationChecklist, checklist_id)
        if not checklist:
            return

        checklist.status = "running"
        db.commit()

        tender_doc = db.get(TenderDocument, checklist.tender_document_id)
        if not tender_doc:
            raise RuntimeError("招标文件不存在，请重新上传")

        with storage.as_local(tender_doc.storage_path) as path:
            full_text = extract_full_text(path)
        result = e0_tender_parse.run(full_text)

        checklist.checklist_json = {
            "dimensions": result["dimensions"],
            "scoreRules": result["scoreRules"],
            "mustRespond": result["mustRespond"],
            "qualification": result["qualification"],
            "formatRequirements": result["formatRequirements"],
        }
        checklist.engine_params_json = result["vetoParams"]
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


_QUAL_CHAPTER_RE = re.compile(
    r"企业资质|资格审查|资格证明|证照|营业执照|业绩证明|类似业绩|"
    r"荣誉|人员配备|项目经理|建造师|商务标|资格文件"
)
_QUAL_KIND_HINTS = (
    (re.compile(r"人员|建造师|职称|社保|项目经理"), "people"),
    (re.compile(r"业绩|中标"), "achievement"),
    (re.compile(r"合同"), "contract"),
    (re.compile(r"财务|审计|纳税"), "financial"),
    (re.compile(r"信用中国|失信"), "credit"),
    (re.compile(r"设备|机具"), "equipment"),
    (re.compile(r"资质|证照|证书|执照|荣誉|ISO|认证"), "cert"),
)


def _qualifications_for_chapter(db, draft: WriterDraft, chapter_id: str, query: str) -> list[QualificationAsset]:
    picked_ids: list[str] = []
    for ref in _refs_of(_chapter_refs(draft, chapter_id), "qualification"):
        picked_ids.extend([x for x in (ref.get("chapters") or []) if x])
    if picked_ids:
        return (
            db.query(QualificationAsset)
            .options(joinedload(QualificationAsset.images))
            .filter(QualificationAsset.id.in_(picked_ids))
            .all()
        )
    if not _QUAL_CHAPTER_RE.search(query or ""):
        return []
    kinds = [kind for pat, kind in _QUAL_KIND_HINTS if pat.search(query or "")]
    rows = (
        db.query(QualificationAsset)
        .options(joinedload(QualificationAsset.images))
        .filter(QualificationAsset.review_status == "已入库")
        .all()
    )
    if kinds:
        rows = [item for item in rows if item.kind in kinds]
    return rows


def _latest_checklist_data(db, project_id: str) -> tuple[list[dict], list[dict]]:
    checklist = (
        db.query(EvaluationChecklist)
        .filter(EvaluationChecklist.project_id == project_id)
        .order_by(EvaluationChecklist.version.desc())
        .first()
    )
    data = (checklist.checklist_json or {}) if checklist else {}
    return data.get("scoreRules", []), data.get("mustRespond", [])


def _project_tender_path(db, project_id: str) -> str | None:
    checklist = (
        db.query(EvaluationChecklist)
        .filter(EvaluationChecklist.project_id == project_id)
        .order_by(EvaluationChecklist.version.desc())
        .first()
    )
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


def _extract_business_originals(
    tender_path: str | None, outline: list[dict], model_id: str | None = None
) -> dict[str, str]:
    titles = []
    for n in outline:
        if not isinstance(n, dict):
            continue
        title = str(n.get("title") or "")
        kind = e_writer.chapter_kind(
            title, n.get("part"), str(n.get("idea") or ""), str(n.get("requirement") or "")
        )
        if kind in ("form", "business") or e_writer.is_original_form_title(title):
            titles.append(title)
    if not titles or not tender_path:
        return {}
    try:
        return extract_forms_from_storage(tender_path, titles, model_id)
    except Exception:  # noqa: BLE001 —— 原文抽取失败时仍用占位说明，不阻断目录
        logger.exception("extract business originals failed")
        return {}


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
        project = db.get(Project, draft.project_id)
        project_name = project.name if project else ""
        knowledge_headings = list_knowledge_headings(db, draft.selected_knowledge_json or [], limit=50)
        tender_path = _project_tender_path(db, draft.project_id)
        tender_toc = {"compose": [], "tech": []}
        tender_text = ""
        if tender_path:
            with storage.as_local(tender_path) as local_tender:
                tender_toc = extract_stipulated_toc(local_tender)
                try:
                    tender_text = extract_document_plain_text(local_tender)
                except Exception:  # noqa: BLE001 —— 表格抽取失败时退回纯段落，仍把正文交给模型
                    tender_text = extract_full_text(local_tender)

        outline = e_writer.generate_outline(
            project_name, score_rules, must_respond, knowledge_headings, tender_toc, tender_text, draft.model_id
        )

        contents: dict[str, str] = {}
        originals = _extract_business_originals(tender_path, outline, draft.model_id)
        e_writer.fill_business_originals(outline, contents, originals)
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

        draft = db.get(WriterDraft, job.draft_id)
        if not draft:
            raise RuntimeError("撰写草稿不存在")

        outline = [dict(n) for n in (draft.outline_json or [])]
        node = next((n for n in outline if n.get("id") == job.chapter_id), None)
        if not node:
            raise RuntimeError("章节不存在，可能已被删除")

        kind = e_writer.chapter_kind(
            str(node.get("title") or ""),
            node.get("part"),
            str(node.get("idea") or ""),
            str(node.get("requirement") or ""),
        )
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
            contents = dict(draft.chapter_contents_json or {})
            contents[job.chapter_id] = content
            draft.chapter_contents_json = contents
            flag_modified(draft, "chapter_contents_json")
            for n in outline:
                if n.get("id") == job.chapter_id:
                    n["status"] = "用原文"
                    n["words"] = len(content.replace(" ", "").replace("\n", ""))
                    n["part"] = kind
            draft.outline_json = outline
            flag_modified(draft, "outline_json")
            db.commit()
            job.status = "done"
            job.finished_at = datetime.utcnow()
            db.commit()
            return

        score_rules, must_respond = _latest_checklist_data(db, draft.project_id)
        dimension_detail = None
        if node.get("dimension"):
            dimension_detail = next((r for r in score_rules if r.get("dimension") == node["dimension"]), None)

        project = db.get(Project, draft.project_id)
        project_name = project.name if project else ""

        query = f"{node.get('title', '')} {node.get('idea', '')}".strip()
        knowledge_snippets = _knowledge_snippets_for_chapter(db, draft, job.chapter_id, query)
        library_name, product_rows = _product_features_for_chapter(db, draft, job.chapter_id, query)
        qual_rows = _qualifications_for_chapter(db, draft, job.chapter_id, query)
        product_payload = None
        if product_rows or draft.selected_product_library_id:
            picked: set[str] = set()
            for ref in _refs_of(_chapter_refs(draft, job.chapter_id), "product"):
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

        content = e_writer.generate_chapter_content(
            project_name,
            node.get("title", ""),
            node.get("idea", ""),
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
            node.get("requirement") or "",
        )
        kind = e_writer.chapter_kind(
            str(node.get("title") or ""),
            node.get("part"),
            str(node.get("idea") or ""),
            str(node.get("requirement") or ""),
        )
        if pack_images and kind == "tech":
            content = attach_knowledge_images_for_chapter(
                db, draft, job.chapter_id, node.get("title", ""), content, pack_images
            )
        is_form = kind in ("form", "business") or node.get("status") == "用原文"

        contents = dict(draft.chapter_contents_json or {})
        contents[job.chapter_id] = content
        draft.chapter_contents_json = contents
        flag_modified(draft, "chapter_contents_json")

        for n in outline:
            if n.get("id") == job.chapter_id:
                n["status"] = "用原文" if is_form else "已完成"
                n["words"] = len(content.replace(" ", "").replace("\n", ""))
                if not is_form:
                    n["aiRounds"] = (n.get("aiRounds") or 0) + 1
        draft.outline_json = outline
        flag_modified(draft, "outline_json")

        db.commit()

        job.status = "done"
        job.finished_at = datetime.utcnow()
        db.commit()
    except Exception as exc:  # noqa: BLE001 —— 生成失败也要把任务状态置为 failed，而不是让 worker 静默丢失
        logger.exception("chapter generate job %s failed", job_id)
        job = db.get(WriterJob, job_id)
        if job:
            job.status = "failed"
            job.error = str(exc)
            job.finished_at = datetime.utcnow()
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
