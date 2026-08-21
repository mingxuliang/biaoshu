import uuid
from datetime import datetime

from sqlalchemy import JSON, Boolean, Column, DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import relationship

from .db import Base


def gen_id(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:12]}"


class User(Base):
    """真实用户账号（P0 落地后替换 AuthContext 的 localStorage 假登录）。"""

    __tablename__ = "users"

    id = Column(String, primary_key=True, default=lambda: gen_id("user"))
    name = Column(String, nullable=False)
    email = Column(String, unique=True, index=True, nullable=False)
    password_hash = Column(String, nullable=False)
    phone = Column(String, default="")
    company = Column(String, default="")
    position = Column(String, default="")
    role = Column(String, default="成员")
    created_at = Column(DateTime, default=datetime.utcnow)


class Project(Base):
    """真实项目（P0 落地后替换 ProjectContext 的内存 state）。

    owner 为展示用姓名字符串（沿用前端既有字段），owner_id 指向创建者，仅用于记录，
    不做权限过滤——团队内所有登录用户共享可见全部项目。
    """

    __tablename__ = "projects"

    id = Column(String, primary_key=True, default=lambda: gen_id("proj"))
    code = Column(String, nullable=False)
    name = Column(String, nullable=False)
    type = Column(String, nullable=False)
    owner = Column(String, default="")
    owner_id = Column(String, ForeignKey("users.id"), nullable=True)
    budget = Column(String, default="待定")
    deadline = Column(String, default="")
    progress = Column(Integer, default=0)
    score = Column(Float, default=0)
    status = Column(String, default="撰写中")
    created_at = Column(DateTime, default=datetime.utcnow)
    tender_doc_json = Column(JSON, nullable=True)


class BidDocument(Base):
    """上传/工作台选定的投标文件。project_id 对应 Project.id（字符串，未加 FK 约束，
    以兼容历史数据与跨表的宽松引用风格）。"""

    __tablename__ = "bid_documents"

    id = Column(String, primary_key=True, default=lambda: gen_id("doc"))
    project_id = Column(String, index=True, nullable=False)
    filename = Column(String, nullable=False)
    storage_path = Column(String, nullable=False)
    size_bytes = Column(Integer, default=0)
    source = Column(String, default="upload")  # upload | workbench
    uploaded_at = Column(DateTime, default=datetime.utcnow)


class TenderDocument(Base):
    """上传的招标文件（评标尺子解析的输入），结构与 BidDocument 一致。"""

    __tablename__ = "tender_documents"

    id = Column(String, primary_key=True, default=lambda: gen_id("tdoc"))
    project_id = Column(String, index=True, nullable=False)
    filename = Column(String, nullable=False)
    storage_path = Column(String, nullable=False)
    size_bytes = Column(Integer, default=0)
    uploaded_at = Column(DateTime, default=datetime.utcnow)


class EvaluationChecklist(Base):
    """招标文件解析出的「评标尺子」，可迭代出多个版本，其中最多一个版本被锁定为项目当前生效尺子。

    checklist_json：展示用数据（scoreRules/mustRespond/qualification/formatRequirements），
    engine_params_json：归一化后供 E1/E2 引擎直接消费的数值参数（vetoParams）。
    """

    __tablename__ = "evaluation_checklists"

    id = Column(String, primary_key=True, default=lambda: gen_id("chk"))
    project_id = Column(String, index=True, nullable=False)
    tender_document_id = Column(String, ForeignKey("tender_documents.id"), nullable=False)
    version = Column(Integer, nullable=False, default=1)
    status = Column(String, default="queued")  # queued | running | done | failed
    locked = Column(Boolean, default=False)

    checklist_json = Column(JSON, default=dict)
    engine_params_json = Column(JSON, default=dict)

    error = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    finished_at = Column(DateTime, nullable=True)


class ReviewRun(Base):
    """一次完整的 L1-L5 预审运行记录。"""

    __tablename__ = "review_runs"

    id = Column(String, primary_key=True, default=lambda: gen_id("run"))
    project_id = Column(String, index=True, nullable=False)
    bid_document_id = Column(String, ForeignKey("bid_documents.id"), nullable=False)
    round = Column(Integer, nullable=False)
    status = Column(String, default="queued")  # queued | running | done | failed

    overall = Column(Float, default=0)
    waste = Column(Integer, default=0)
    risk = Column(Integer, default=0)
    suggest = Column(Integer, default=0)
    light = Column(String, default="橙")

    levels_json = Column(JSON, default=list)
    dimensions_json = Column(JSON, default=list)

    error_message = Column(Text, nullable=True)
    started_at = Column(DateTime, default=datetime.utcnow)
    finished_at = Column(DateTime, nullable=True)

    findings = relationship("ReviewFinding", back_populates="run", cascade="all, delete-orphan")


class WriterDraft(Base):
    """AI 撰写工作台草稿，每个项目仅维护一份（project_id 唯一）。

    outline_json 存储统一的目录节点列表（融合原 PlanNode 编写思路字段与 ChapterNode 生成状态字段），
    chapter_contents_json 存储各章节正文（{chapterId: content}）。
    """

    __tablename__ = "writer_drafts"

    id = Column(String, primary_key=True, default=lambda: gen_id("draft"))
    project_id = Column(String, index=True, nullable=False, unique=True)
    model_id = Column(String, default="glm")
    selected_knowledge_json = Column(JSON, default=list)  # 全局知识库文档池，供无章节级引用时的检索兜底
    knowledge_refs_json = Column(JSON, default=dict)  # {chapterId: [{docId, docTitle, chapters, mode}]}
    settings_json = Column(JSON, default=dict)  # style/page/layout/image 透传存储
    interpret_source = Column(String, default="reuse")  # reuse | upload
    outline_json = Column(JSON, default=list)
    chapter_contents_json = Column(JSON, default=dict)
    step = Column(Integer, default=1)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class WriterJob(Base):
    """撰写工作台的 AI 异步生成任务（目录生成 / 单章正文生成），沿用招标解析的排队模式。"""

    __tablename__ = "writer_jobs"

    id = Column(String, primary_key=True, default=lambda: gen_id("wjob"))
    draft_id = Column(String, ForeignKey("writer_drafts.id"), nullable=False)
    kind = Column(String, nullable=False)  # outline | chapter
    chapter_id = Column(String, nullable=True)
    status = Column(String, default="queued")  # queued | running | done | failed
    error = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    finished_at = Column(DateTime, nullable=True)


class ReviewFinding(Base):
    """五引擎产出的统一 Finding 记录（对应技术方案第四章的 Finding 契约）。"""

    __tablename__ = "review_findings"

    id = Column(String, primary_key=True, default=lambda: gen_id("finding"))
    run_id = Column(String, ForeignKey("review_runs.id"), nullable=False)

    engine = Column(String, nullable=False)
    level = Column(String, nullable=False)
    severity = Column(String, nullable=False)
    location = Column(String, default="")
    excerpt = Column(Text, default="")
    rule = Column(String, default="")
    tender_quote = Column(Text, default="")
    suggestion = Column(Text, default="")
    evidence_json = Column(JSON, default=dict)
    confidence = Column(Float, default=1.0)

    run = relationship("ReviewRun", back_populates="findings")


class BidRevision(Base):
    """修改闭环的工作草稿，每个项目仅维护一份（project_id 唯一）。

    首次创建时基于该项目最新一轮 done 的 ReviewRun：解析投标书真实段落 + 把
    ReviewFinding 锚定回具体段落，写入 sections_json / issues_json；
    之后编辑器的每次改动持续覆盖 content_state_json（Lexical 序列化状态）。
    """

    __tablename__ = "bid_revisions"

    id = Column(String, primary_key=True, default=lambda: gen_id("rev"))
    project_id = Column(String, index=True, nullable=False, unique=True)
    bid_document_id = Column(String, ForeignKey("bid_documents.id"), nullable=False)
    review_run_id = Column(String, ForeignKey("review_runs.id"), nullable=False)
    sections_json = Column(JSON, default=list)
    issues_json = Column(JSON, default=list)
    content_state_json = Column(JSON, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    versions = relationship(
        "BidRevisionVersion", back_populates="revision", cascade="all, delete-orphan"
    )


class KnowledgeDocument(Base):
    """文档知识库条目：企业库（全员可见）/ 项目库（挂某个项目）/ 个人库（记录上传者）。

    上传时即完成分段切片（KnowledgeSlice）与虚词密度自检（review_flag），
    供 Writer 章节生成时做轻量级检索（BM25 + jieba，见 engines/knowledge_retrieval.py）。
    """

    __tablename__ = "knowledge_documents"

    id = Column(String, primary_key=True, default=lambda: gen_id("kdoc"))
    scope = Column(String, nullable=False)  # 企业库 | 项目库 | 个人库
    type = Column(String, nullable=False)  # 历史中标标书 | 专项方案 | 施工工艺 | 规范条文 | 制度表单 | 图表模板
    title = Column(String, nullable=False)
    tags_json = Column(JSON, default=list)
    project_id = Column(String, nullable=True)  # scope=项目库 时必填
    owner_id = Column(String, ForeignKey("users.id"), nullable=True)  # scope=个人库 时记录上传者
    filename = Column(String, nullable=False)
    storage_path = Column(String, nullable=False)
    size_bytes = Column(Integer, default=0)
    slice_count = Column(Integer, default=0)
    review_flag = Column(String, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    slices = relationship(
        "KnowledgeSlice", back_populates="document", cascade="all, delete-orphan"
    )


class KnowledgeSlice(Base):
    """知识文档按标题分组、再按字数切片后的正文片段，供检索与「章节详情预览」使用。"""

    __tablename__ = "knowledge_slices"

    id = Column(String, primary_key=True, default=lambda: gen_id("kslice"))
    document_id = Column(String, ForeignKey("knowledge_documents.id"), nullable=False)
    heading = Column(String, default="全文")
    seq = Column(Integer, default=0)
    text = Column(Text, nullable=False)

    document = relationship("KnowledgeDocument", back_populates="slices")


class BidRevisionVersion(Base):
    """修改闭环的保存版本记录，持有该次保存时生成的 docx（新 BidDocument）。"""

    __tablename__ = "bid_revision_versions"

    id = Column(String, primary_key=True, default=lambda: gen_id("rev_v"))
    revision_id = Column(String, ForeignKey("bid_revisions.id"), nullable=False)
    label = Column(String, nullable=False)
    note = Column(Text, default="")
    author = Column(String, default="")
    word_count = Column(Integer, default=0)
    content_state_json = Column(JSON, default=dict)
    bid_document_id = Column(String, ForeignKey("bid_documents.id"), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    revision = relationship("BidRevision", back_populates="versions")
