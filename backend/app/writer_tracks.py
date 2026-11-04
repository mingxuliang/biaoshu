"""技术标 / 商务标两条撰写轨道的拆分与共享字段镜像。

放在路由之外，避免单测为了验证拆分逻辑去导入 Celery 任务链。
"""

from __future__ import annotations

from sqlalchemy.orm import Session
from sqlalchemy.orm.attributes import flag_modified

from .models import WriterDraft

DOC_KINDS = ("tech", "business")
SHARED_DRAFT_FIELDS = ("modelId", "selectedKnowledge", "selectedProductLibraryId", "settings", "interpretSource")


def other_doc_kind(kind: str) -> str:
    return "business" if kind == "tech" else "tech"


def sibling_draft(db: Session, draft: WriterDraft) -> WriterDraft | None:
    return (
        db.query(WriterDraft)
        .filter(
            WriterDraft.project_id == draft.project_id,
            WriterDraft.doc_kind == other_doc_kind(draft.doc_kind or "tech"),
        )
        .first()
    )


def branch_legacy_draft(db: Session, legacy: WriterDraft, wanted_doc_kind: str) -> WriterDraft:
    """旧版单份混合草稿第一次被按 doc_kind 访问时，按顶层子树的叶子多数票拆成两条轨道。

    legacy 行留下和自己 doc_kind 一致的那一半，另一半搬进新建的行并返回。
    """
    from .engines.e_writer import split_outline_by_doc_kind

    legacy_kind = legacy.doc_kind or "tech"
    other_kind = other_doc_kind(legacy_kind)
    tech_bundle, business_bundle = split_outline_by_doc_kind(
        legacy.outline_json, legacy.chapter_contents_json, legacy.knowledge_refs_json
    )
    bundles = {"tech": tech_bundle, "business": business_bundle}

    legacy.outline_json, legacy.chapter_contents_json, legacy.knowledge_refs_json = bundles[legacy_kind]
    flag_modified(legacy, "outline_json")
    flag_modified(legacy, "chapter_contents_json")
    flag_modified(legacy, "knowledge_refs_json")

    other_outline, other_contents, other_refs = bundles[other_kind]
    shared_step = legacy.step if (legacy.step or 1) <= 2 else 3
    other = WriterDraft(
        project_id=legacy.project_id,
        doc_kind=other_kind,
        model_id=legacy.model_id,
        selected_knowledge_json=list(legacy.selected_knowledge_json or []),
        selected_product_library_id=legacy.selected_product_library_id,
        knowledge_refs_json=other_refs,
        settings_json=dict(legacy.settings_json or {}),
        interpret_source=legacy.interpret_source,
        outline_json=other_outline,
        chapter_contents_json=other_contents,
        step=shared_step,
    )
    db.add(other)
    db.commit()
    db.refresh(legacy)
    db.refresh(other)
    return other if wanted_doc_kind == other_kind else legacy


def mirror_shared_fields(db: Session, draft: WriterDraft, data: dict) -> WriterDraft | None:
    """标书设置（第一步）/标书解读来源（第二步）在技术标、商务标两条轨道间共享。

    目录（outline）/正文/知识引用，以及第 3、4 步的步骤推进完全独立，不镜像。
    返回被镜像更新的兄弟行（没有兄弟行或没有需要镜像的字段时返回 None）。
    """
    if not (any(key in data for key in SHARED_DRAFT_FIELDS) or ("step" in data and data["step"] <= 2)):
        return None
    sibling = sibling_draft(db, draft)
    if sibling is None:
        return None
    if "modelId" in data:
        sibling.model_id = data["modelId"]
    if "selectedKnowledge" in data:
        sibling.selected_knowledge_json = data["selectedKnowledge"]
        flag_modified(sibling, "selected_knowledge_json")
    if "selectedProductLibraryId" in data:
        sibling.selected_product_library_id = data["selectedProductLibraryId"] or None
    if "settings" in data:
        sibling.settings_json = data["settings"]
        flag_modified(sibling, "settings_json")
    if "interpretSource" in data:
        sibling.interpret_source = data["interpretSource"]
    if "step" in data and data["step"] <= 2 and (sibling.step or 1) <= 2:
        sibling.step = data["step"]
    db.commit()
    db.refresh(sibling)
    return sibling
