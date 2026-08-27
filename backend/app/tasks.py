from datetime import datetime
import os
import re

from celery.utils.log import get_task_logger
from sqlalchemy.orm.attributes import flag_modified

from .celery_app import celery_app
from .db import SessionLocal
from .engines import e0_tender_parse, e_writer
from .engines.docx_extract import extract_document_plain_text, extract_full_text
from .engines.knowledge_extract import extract_docx_images
from .engines.legacy_doc import as_docx
from .engines.knowledge_retrieval import list_knowledge_headings, retrieve_by_doc_and_headings, retrieve_for_chapter
from .engines.orchestrator import run_prereview
from .engines.product_dedup import match_ingested_features
from .engines.product_extract import run_extract_for_source_doc
from .engines.qualification_extract import run_extract_for_source_doc as run_qualification_extract
from .engines.tender_toc import extract_stipulated_toc
from . import storage
from .models import (
    EvaluationChecklist,
    KnowledgeDocument,
    ProductFeature,
    ProductLibrary,
    Project,
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


_DIAGRAM_CHAPTER_RE = re.compile(r"架构|流程|组织|拓扑|部署|系统图|网络|实施方案|功能模块|技术方案|总体方案|建设目标")
_QUOTE_CHAPTER_RE = re.compile(r"报价|价格|投标报价")
_PLACEHOLDER_RE = re.compile(r"【此处插入图[:：]?[^】]*】")


def _knowledge_doc_ids_for_chapter(draft: WriterDraft, chapter_id: str) -> list[str]:
    refs = (draft.knowledge_refs_json or {}).get(chapter_id) or []
    ids = [r.get("docId") for r in refs if r.get("docId")]
    if ids:
        return list(dict.fromkeys(ids))
    return list(draft.selected_knowledge_json or [])


def attach_knowledge_images_for_chapter(
    db, draft: WriterDraft, chapter_id: str, chapter_title: str, content: str
) -> str:
    title = chapter_title or ""
    if _QUOTE_CHAPTER_RE.search(title):
        return _PLACEHOLDER_RE.sub("", content)
    wants = bool(_DIAGRAM_CHAPTER_RE.search(title)) or bool(_PLACEHOLDER_RE.search(content or ""))
    if not wants:
        return content

    doc_ids = _knowledge_doc_ids_for_chapter(draft, chapter_id)
    if not doc_ids:
        return content

    markdown_lines: list[str] = []
    for doc in db.query(KnowledgeDocument).filter(KnowledgeDocument.id.in_(doc_ids)).all():
        path = doc.storage_path or ""
        if not path.lower().endswith((".docx", ".doc")) or not storage.exists(path):
            continue
        with storage.as_local(path) as local_path:
            with as_docx(local_path) as word_path:
                blobs = extract_docx_images(word_path)
        for idx, (blob, ext) in enumerate(blobs[:4], start=1):
            prompt_key = f"knowledge:{doc.id}:{idx}"
            existing = (
                db.query(WriterImage)
                .filter(WriterImage.project_id == draft.project_id, WriterImage.prompt == prompt_key)
                .first()
            )
            if existing:
                img = existing
            else:
                key = storage.put_bytes(f"writer-images/{draft.project_id}", blob, ext)
                img = WriterImage(
                    id=gen_id("wimg"),
                    project_id=draft.project_id,
                    source="knowledge",
                    mode="arch" if "架构" in title else "flow" if "流程" in title else "normal",
                    prompt=prompt_key,
                    filename=f"{doc.title[:40]}-{idx}{ext}",
                    storage_path=key,
                )
                db.add(img)
                db.flush()
            alt = f"{doc.title} 附图{idx}"
            markdown_lines.append(f"![{alt}](/api/writer-images/{img.id}/file)")

    if not markdown_lines:
        return _PLACEHOLDER_RE.sub("", content)

    stripped = _PLACEHOLDER_RE.sub("", content).rstrip()
    return stripped + "\n\n" + "\n\n".join(markdown_lines)


def _product_features_for_chapter(db, draft: WriterDraft, query: str) -> tuple[str | None, list[ProductFeature]]:
    library_id = draft.selected_product_library_id
    if not library_id:
        return None, []
    library = db.get(ProductLibrary, library_id)
    name = library.name if library else None
    features = match_ingested_features(db, library_id, query, top_k=6)
    return name, features


def attach_product_images_for_chapter(db, draft: WriterDraft, features: list[ProductFeature], content: str) -> str:
    if not features:
        return content
    markdown_lines: list[str] = []
    for feat in features:
        for pimg in list(feat.images)[:4]:
            if not pimg.storage_path or not storage.exists(pimg.storage_path):
                continue
            prompt_key = f"product:{feat.id}:{pimg.id}"
            existing = (
                db.query(WriterImage)
                .filter(WriterImage.project_id == draft.project_id, WriterImage.prompt == prompt_key)
                .first()
            )
            if existing:
                img = existing
            else:
                ext = os.path.splitext(pimg.filename or pimg.storage_path)[1] or ".png"
                key = storage.copy_object(pimg.storage_path, f"writer-images/{draft.project_id}", ext)
                img = WriterImage(
                    id=gen_id("wimg"),
                    project_id=draft.project_id,
                    source="product",
                    mode="arch" if pimg.kind == "架构" else "flow" if pimg.kind == "流程" else "normal",
                    prompt=prompt_key,
                    filename=pimg.filename,
                    storage_path=key,
                )
                db.add(img)
                db.flush()
            alt = pimg.caption or feat.name
            markdown_lines.append(f"![{alt}](/api/writer-images/{img.id}/file)")
    if not markdown_lines:
        return content
    stripped = _PLACEHOLDER_RE.sub("", content).rstrip()
    return stripped + "\n\n" + "\n\n".join(markdown_lines)


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
        for n in outline:
            if n.get("status") == "用原文" or e_writer.is_original_form_title(str(n.get("title") or "")):
                body = e_writer.original_form_markdown(str(n.get("title") or ""), str(n.get("idea") or ""))
                contents[n["id"]] = body
                n["status"] = "用原文"
                n["words"] = len(body.replace(" ", "").replace("\n", ""))
        draft.outline_json = outline
        flag_modified(draft, "outline_json")
        draft.chapter_contents_json = contents
        flag_modified(draft, "chapter_contents_json")
        draft.knowledge_refs_json = {}
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

        score_rules, must_respond = _latest_checklist_data(db, draft.project_id)
        dimension_detail = None
        if node.get("dimension"):
            dimension_detail = next((r for r in score_rules if r.get("dimension") == node["dimension"]), None)

        project = db.get(Project, draft.project_id)
        project_name = project.name if project else ""

        query = f"{node.get('title', '')} {node.get('idea', '')}".strip()
        knowledge_snippets = _knowledge_snippets_for_chapter(db, draft, job.chapter_id, query)
        library_name, product_rows = _product_features_for_chapter(db, draft, query)
        product_payload = None
        if draft.selected_product_library_id:
            product_payload = [
                {
                    "name": f.name,
                    "module": f.module,
                    "params": f.params,
                    "intro": f.intro,
                    "bidCopy": f.bid_copy,
                }
                for f in product_rows
            ]

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
        )
        if product_rows:
            content = attach_product_images_for_chapter(db, draft, product_rows, content)
        else:
            content = attach_knowledge_images_for_chapter(
                db, draft, job.chapter_id, node.get("title", ""), content
            )
        is_form = e_writer.is_original_form_title(str(node.get("title") or "")) or node.get("status") == "用原文"

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
