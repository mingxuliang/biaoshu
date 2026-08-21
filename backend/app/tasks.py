from datetime import datetime

from celery.utils.log import get_task_logger
from sqlalchemy.orm.attributes import flag_modified

from .celery_app import celery_app
from .db import SessionLocal
from .engines import e0_tender_parse, e_writer
from .engines.docx_extract import extract_full_text
from .engines.knowledge_retrieval import retrieve_by_doc_and_headings, retrieve_for_chapter
from .engines.orchestrator import run_prereview
from .models import EvaluationChecklist, Project, ReviewRun, TenderDocument, WriterDraft, WriterJob

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

        full_text = extract_full_text(tender_doc.storage_path)
        result = e0_tender_parse.run(full_text)

        checklist.checklist_json = {
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


def _latest_checklist_data(db, project_id: str) -> tuple[list[dict], list[dict]]:
    checklist = (
        db.query(EvaluationChecklist)
        .filter(EvaluationChecklist.project_id == project_id)
        .order_by(EvaluationChecklist.version.desc())
        .first()
    )
    data = (checklist.checklist_json or {}) if checklist else {}
    return data.get("scoreRules", []), data.get("mustRespond", [])


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

        outline = e_writer.generate_outline(project_name, score_rules, must_respond)

        draft.outline_json = outline
        flag_modified(draft, "outline_json")
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

        content = e_writer.generate_chapter_content(
            project_name,
            node.get("title", ""),
            node.get("idea", ""),
            dimension_detail,
            must_respond,
            knowledge_snippets,
        )

        contents = dict(draft.chapter_contents_json or {})
        contents[job.chapter_id] = content
        draft.chapter_contents_json = contents
        flag_modified(draft, "chapter_contents_json")

        for n in outline:
            if n.get("id") == job.chapter_id:
                n["status"] = "已完成"
                n["words"] = len(content.replace(" ", "").replace("\n", ""))
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
