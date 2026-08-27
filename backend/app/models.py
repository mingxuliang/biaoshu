import uuid
from datetime import datetime

from sqlalchemy import (
    JSON,
    Boolean,
    Column,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
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
    disabled = Column(Boolean, default=False)
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

    checklist_json：展示用数据（dimensions 一级/二级固定指标树，以及派生的 scoreRules/mustRespond/qualification/formatRequirements），
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
    model_id = Column(String, default="deepseek-v4-pro")
    selected_knowledge_json = Column(JSON, default=list)  # 全局知识库文档池，供无章节级引用时的检索兜底
    selected_product_library_id = Column(String, nullable=True)  # 撰写匹配用的产品库，一项目对应一个产品
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


class WriterImage(Base):
    """撰写工作台插图：豆包生成或本机上传，按项目归档。"""

    __tablename__ = "writer_images"

    id = Column(String, primary_key=True, default=lambda: gen_id("wimg"))
    project_id = Column(String, index=True, nullable=False)
    source = Column(String, default="generated")  # generated | upload
    mode = Column(String, default="normal")  # normal | flow | arch
    prompt = Column(String, default="")
    filename = Column(String, nullable=False)
    storage_path = Column(String, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)


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


class ProjectMember(Base):
    """项目级人员分配（团队分配），非"团队管理"整页的邀请/权限体系。"""

    __tablename__ = "project_members"

    id = Column(String, primary_key=True, default=lambda: gen_id("pm"))
    project_id = Column(String, index=True, nullable=False)
    user_id = Column(String, ForeignKey("users.id"), nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)

    __table_args__ = (UniqueConstraint("project_id", "user_id", name="uq_project_member"),)


class QualificationAsset(Base):
    """企业资质证照库条目（全公司一套，不按项目拆分）。status / warnDays 不落库，按 valid_until 动态计算。"""

    __tablename__ = "qualification_assets"

    id = Column(String, primary_key=True, default=lambda: gen_id("qual"))
    kind = Column(String, nullable=False)  # cert | people | achievement | equipment | credit | contract | financial
    name = Column(String, nullable=False)
    level = Column(String, default="")
    number = Column(String, default="")
    valid_until = Column(String, default="长期")  # 长期 或 YYYY-MM-DD
    owner = Column(String, default="")
    detail = Column(Text, default="")
    filename = Column(String, default="")
    storage_path = Column(String, default="")
    ocr_text = Column(Text, default="")
    ocr_status = Column(String, default="")  # ok | empty | unavailable
    review_status = Column(String, default="已入库")  # 待审核 | 已入库
    merge_status = Column(String, default="新增")  # 新增 | 并入已有 | 疑似重复 | 信息冲突
    aliases_json = Column(JSON, default=list)
    sources_json = Column(JSON, default=list)
    evidence_json = Column(JSON, default=list)
    field_conflict_json = Column(JSON, default=list)
    suspected_ids_json = Column(JSON, default=list)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    images = relationship(
        "QualificationAssetImage", back_populates="asset", cascade="all, delete-orphan"
    )


class QualificationAssetImage(Base):
    """从商务标抽出的证照/合同扫描图。"""

    __tablename__ = "qualification_asset_images"

    id = Column(String, primary_key=True, default=lambda: gen_id("qimg"))
    asset_id = Column(String, ForeignKey("qualification_assets.id"), nullable=False, index=True)
    caption = Column(String, default="")
    filename = Column(String, nullable=False)
    storage_path = Column(String, nullable=False)
    sha256 = Column(String, default="", index=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    asset = relationship("QualificationAsset", back_populates="images")


class QualificationSourceDoc(Base):
    """资质库内上传的一份商务标及异步抽取任务。全公司共用，无 project_id。"""

    __tablename__ = "qualification_source_docs"

    id = Column(String, primary_key=True, default=lambda: gen_id("qdoc"))
    filename = Column(String, nullable=False)
    storage_path = Column(String, nullable=False)
    size_bytes = Column(Integer, default=0)
    status = Column(String, default="queued")  # queued | running | done | failed
    extracted = Column(Integer, default=0)
    merged = Column(Integer, default=0)
    suspected = Column(Integer, default=0)
    conflicts = Column(Integer, default=0)
    note = Column(Text, default="")
    error = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    finished_at = Column(DateTime, nullable=True)


class WeightTemplate(Base):
    """五维评分权重模板（预审规则页「五维权重」tab），同一时刻只允许一条 active=True。"""

    __tablename__ = "weight_templates"

    id = Column(String, primary_key=True, default=lambda: gen_id("wt"))
    name = Column(String, nullable=False)
    completeness = Column(Float, default=30)
    relevance = Column(Float, default=25)
    compliance = Column(Float, default=20)
    feasibility = Column(Float, default=15)
    standardization = Column(Float, default=10)
    scope = Column(String, default="全局默认")
    active = Column(Boolean, default=False)
    created_at = Column(DateTime, default=datetime.utcnow)


class FillerWordRule(Base):
    """虚词识别规则（预审规则页「虚词表」tab），驱动 E4 虚词密度检测与知识库 review_flag。"""

    __tablename__ = "filler_word_rules"

    id = Column(String, primary_key=True, default=lambda: gen_id("fw"))
    category = Column(String, nullable=False)
    level = Column(String, default="中危")  # 高危 | 中危 | 低危
    word = Column(String, nullable=False)
    rewrite = Column(String, default="")  # 改写建议，E4 命中高危词时写入 Finding.suggestion
    enabled = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)


class ThresholdRule(Base):
    """真实生效的数值阈值（预审规则页「查重阈值」tab）。本企业跨项目两项驱动 E4 查重。"""

    __tablename__ = "threshold_rules"

    id = Column(String, primary_key=True, default=lambda: gen_id("th"))
    key = Column(String, unique=True, nullable=False)
    label = Column(String, nullable=False)
    value = Column(Float, nullable=False)
    unit = Column(String, default="%")
    description = Column(String, default="")


class RulePackage(Base):
    """属地细则包：启用后由 E2 在正文已写到对应主题时核验量化要求。"""

    __tablename__ = "rule_packages"

    id = Column(String, primary_key=True, default=lambda: gen_id("rp"))
    name = Column(String, nullable=False)
    region = Column(String, default="全国")
    status = Column(String, default="启用")  # 启用 | 停用
    items_json = Column(JSON, default=list)
    created_at = Column(DateTime, default=datetime.utcnow)


class VetoRule(Base):
    """青天一票否决清单（预审规则页「一票否决」tab）。"""

    __tablename__ = "veto_rules"

    id = Column(String, primary_key=True, default=lambda: gen_id("vt"))
    key = Column(String, unique=True, nullable=False)
    category = Column(String, nullable=False)
    point = Column(String, nullable=False)
    items_json = Column(JSON, default=list)
    wired = Column(String, default="仅对照")  # 接入判定 | 部分接入 | 仅对照
    wired_note = Column(String, default="")
    engine = Column(String, default="")
    seq = Column(Integer, default=0)
    created_at = Column(DateTime, default=datetime.utcnow)


class CatalogRule(Base):
    """青天其余目录：商务自查 / 技术评分 / 查重防废标 / 高分策略。"""

    __tablename__ = "catalog_rules"

    id = Column(String, primary_key=True, default=lambda: gen_id("cr"))
    kind = Column(String, index=True, nullable=False)  # business | tech | dup_check | strategy
    key = Column(String, nullable=False)
    category = Column(String, nullable=False)
    point = Column(String, nullable=False)
    items_json = Column(JSON, default=list)
    wired = Column(String, default="仅对照")
    wired_note = Column(String, default="")
    engine = Column(String, default="")
    seq = Column(Integer, default=0)
    created_at = Column(DateTime, default=datetime.utcnow)

    __table_args__ = (UniqueConstraint("kind", "key", name="uq_catalog_kind_key"),)


class ProductLibrary(Base):
    """企业产品库：一个库对应一个可投标产品，功能点不跨库混用。"""

    __tablename__ = "product_libraries"

    id = Column(String, primary_key=True, default=lambda: gen_id("plib"))
    name = Column(String, nullable=False)
    category = Column(String, default="软件系统")  # 软件系统 | 货物设备 | 综合方案
    description = Column(Text, default="")
    owner = Column(String, default="")
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    features = relationship(
        "ProductFeature", back_populates="library", cascade="all, delete-orphan"
    )
    source_docs = relationship(
        "ProductSourceDoc", back_populates="library", cascade="all, delete-orphan"
    )


class ProductSourceDoc(Base):
    """产品库内上传的一份技术标及异步抽取任务。"""

    __tablename__ = "product_source_docs"

    id = Column(String, primary_key=True, default=lambda: gen_id("pdoc"))
    library_id = Column(String, ForeignKey("product_libraries.id"), nullable=False, index=True)
    filename = Column(String, nullable=False)
    storage_path = Column(String, nullable=False)
    size_bytes = Column(Integer, default=0)
    status = Column(String, default="queued")  # queued | running | done | failed
    extracted = Column(Integer, default=0)
    merged = Column(Integer, default=0)
    suspected = Column(Integer, default=0)
    conflicts = Column(Integer, default=0)
    note = Column(Text, default="")
    error = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    finished_at = Column(DateTime, nullable=True)

    library = relationship("ProductLibrary", back_populates="source_docs")


class ProductFeature(Base):
    """产品库内唯一功能点；多份技术标的同义提及合并到这一行。"""

    __tablename__ = "product_features"

    id = Column(String, primary_key=True, default=lambda: gen_id("pfe"))
    library_id = Column(String, ForeignKey("product_libraries.id"), nullable=False, index=True)
    name = Column(String, nullable=False)
    kind = Column(String, default="软件功能")  # 软件功能 | 货物产品 | 模块方案
    module = Column(String, default="")
    params = Column(Text, default="")
    intro = Column(Text, default="")
    bid_copy = Column(Text, default="")
    brand = Column(String, default="")
    model = Column(String, default="")
    unit = Column(String, default="")
    status = Column(String, default="待审核")  # 待审核 | 已入库 | 已停用
    merge_status = Column(String, default="新增")  # 新增 | 并入已有 | 疑似重复 | 参数冲突
    aliases_json = Column(JSON, default=list)
    sources_json = Column(JSON, default=list)
    evidence_json = Column(JSON, default=list)
    params_conflict_json = Column(JSON, default=list)
    suspected_ids_json = Column(JSON, default=list)
    locked_copy = Column(Boolean, default=False)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    library = relationship("ProductLibrary", back_populates="features")
    images = relationship(
        "ProductFeatureImage", back_populates="feature", cascade="all, delete-orphan"
    )


class ProductFeatureImage(Base):
    """功能点原图（从技术标抽出或手工上传），写标时插入原图像素。"""

    __tablename__ = "product_feature_images"

    id = Column(String, primary_key=True, default=lambda: gen_id("pimg"))
    feature_id = Column(String, ForeignKey("product_features.id"), nullable=False, index=True)
    caption = Column(String, default="")
    kind = Column(String, default="界面")  # 界面 | 架构 | 流程 | 实物
    filename = Column(String, nullable=False)
    storage_path = Column(String, nullable=False)
    sha256 = Column(String, default="", index=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    feature = relationship("ProductFeature", back_populates="images")


class AuditLog(Base):
    """关键业务操作留痕：解析、确认对标、引用知识、发起预审、AI 改写、改写接受、导出。"""

    __tablename__ = "audit_logs"

    id = Column(String, primary_key=True, default=lambda: gen_id("aud"))
    action = Column(String, index=True, nullable=False)
    user_name = Column(String, default="系统")
    target = Column(String, default="")
    version = Column(String, default="—")
    detail = Column(Text, default="")
    result = Column(String, default="成功")  # 成功 | 阻断 | 失败
    extra_json = Column(JSON, default=dict)
    created_at = Column(DateTime, default=datetime.utcnow, index=True)


class ExportRecord(Base):
    """「Word 导出与交付」的一次导出记录。

    明标模式直接复用修改闭环最新保存版本的 BidDocument；暗标模式会另存一份清空
    core_properties（作者等身份信息）的新 BidDocument，分别记录在 bid_document_id 上。
    """

    __tablename__ = "export_records"

    id = Column(String, primary_key=True, default=lambda: gen_id("exp"))
    project_id = Column(String, index=True, nullable=False)
    revision_id = Column(String, ForeignKey("bid_revisions.id"), nullable=False)
    bid_document_id = Column(String, ForeignKey("bid_documents.id"), nullable=False)
    mode = Column(String, nullable=False)  # 明标 | 暗标
    operator = Column(String, default="")
    check_status = Column(String, nullable=False)  # 通过 | 阻断
    check_note = Column(Text, default="")
    file_size = Column(Integer, default=0)
    file_hash = Column(String, default="")
    created_at = Column(DateTime, default=datetime.utcnow)
