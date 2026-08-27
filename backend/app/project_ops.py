"""项目级级联删除：表之间没有完整 FK cascade，删除项目前先清关联行。"""

from sqlalchemy.orm import Session

from . import storage
from .models import (
    BidDocument,
    BidRevision,
    BidRevisionVersion,
    EvaluationChecklist,
    ExportRecord,
    KnowledgeDocument,
    KnowledgeSlice,
    Project,
    ProjectMember,
    ReviewFinding,
    ReviewRun,
    TenderDocument,
    WriterDraft,
    WriterImage,
    WriterJob,
)


def delete_project_cascade(db: Session, project_id: str) -> None:
    refs: list[str] = []
    for row in db.query(BidDocument).filter(BidDocument.project_id == project_id).all():
        refs.append(row.storage_path)
    for row in db.query(TenderDocument).filter(TenderDocument.project_id == project_id).all():
        refs.append(row.storage_path)
    for row in db.query(WriterImage).filter(WriterImage.project_id == project_id).all():
        refs.append(row.storage_path)
    kdocs = db.query(KnowledgeDocument).filter(KnowledgeDocument.project_id == project_id).all()
    kdoc_ids = [row.id for row in kdocs]
    for row in kdocs:
        refs.append(row.storage_path)

    drafts = db.query(WriterDraft.id).filter(WriterDraft.project_id == project_id).all()
    draft_ids = [row[0] for row in drafts]
    if draft_ids:
        db.query(WriterJob).filter(WriterJob.draft_id.in_(draft_ids)).delete(synchronize_session=False)

    revisions = db.query(BidRevision.id).filter(BidRevision.project_id == project_id).all()
    revision_ids = [row[0] for row in revisions]
    if revision_ids:
        db.query(ExportRecord).filter(ExportRecord.revision_id.in_(revision_ids)).delete(synchronize_session=False)
        db.query(BidRevisionVersion).filter(BidRevisionVersion.revision_id.in_(revision_ids)).delete(
            synchronize_session=False
        )
        db.query(BidRevision).filter(BidRevision.id.in_(revision_ids)).delete(synchronize_session=False)

    runs = db.query(ReviewRun.id).filter(ReviewRun.project_id == project_id).all()
    run_ids = [row[0] for row in runs]
    if run_ids:
        db.query(ReviewFinding).filter(ReviewFinding.run_id.in_(run_ids)).delete(synchronize_session=False)
        db.query(ReviewRun).filter(ReviewRun.id.in_(run_ids)).delete(synchronize_session=False)

    db.query(ExportRecord).filter(ExportRecord.project_id == project_id).delete(synchronize_session=False)
    db.query(WriterDraft).filter(WriterDraft.project_id == project_id).delete(synchronize_session=False)
    db.query(WriterImage).filter(WriterImage.project_id == project_id).delete(synchronize_session=False)
    db.query(BidDocument).filter(BidDocument.project_id == project_id).delete(synchronize_session=False)
    db.query(EvaluationChecklist).filter(EvaluationChecklist.project_id == project_id).delete(
        synchronize_session=False
    )
    db.query(TenderDocument).filter(TenderDocument.project_id == project_id).delete(synchronize_session=False)

    if kdoc_ids:
        db.query(KnowledgeSlice).filter(KnowledgeSlice.document_id.in_(kdoc_ids)).delete(synchronize_session=False)
        db.query(KnowledgeDocument).filter(KnowledgeDocument.id.in_(kdoc_ids)).delete(synchronize_session=False)

    db.query(ProjectMember).filter(ProjectMember.project_id == project_id).delete(synchronize_session=False)
    db.query(Project).filter(Project.id == project_id).delete(synchronize_session=False)
    for ref in refs:
        storage.delete(ref)
