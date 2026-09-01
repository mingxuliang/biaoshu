from typing import Literal, Optional

from pydantic import BaseModel


class UploadDocOut(BaseModel):
    id: str
    filename: str
    size_bytes: int
    source: str


class BidDocumentSummaryOut(BaseModel):
    id: str
    filename: str
    source: str
    sizeBytes: int
    uploadedAt: str


class CreateJobIn(BaseModel):
    bid_document_id: str
    scope: Literal["full"] = "full"


class JobStatusOut(BaseModel):
    job_id: str
    status: Literal["queued", "running", "done", "failed"]
    round: int
    error: Optional[str] = None


# 以下三个模型字段严格对齐前端 src/mocks/preReview.ts 的
# PreReviewLevel / PreReviewIssue / dimensionBreakdown 类型，
# 保证 audit 页面组件无需改动，只需替换数据源。


class PreReviewLevelOut(BaseModel):
    key: str
    name: str
    desc: str
    score: float
    full: int = 100
    issues: int
    status: Literal["通过", "风险", "未达标"]


class PreReviewIssueOut(BaseModel):
    id: str
    level: str
    severity: Literal["废标", "降档", "扣分", "建议"]
    location: str
    excerpt: str
    rule: str
    tenderQuote: str
    suggestion: str
    resolved: bool = False


class DimensionOut(BaseModel):
    name: str
    weight: int
    score: float


class ReviewReportOut(BaseModel):
    round: int
    overall: float
    waste: int
    risk: int
    suggest: int
    light: Literal["绿", "橙", "红"]
    levels: list[PreReviewLevelOut]
    dimensions: list[DimensionOut]
    issues: list[PreReviewIssueOut]


class TrendPointOut(BaseModel):
    round: int
    score: float
    issues: int


# 以下模型对应招标文件解析与评标尺子锁定（P1），字段严格对齐前端 src/mocks/parse.ts 的
# ScoreRule / MustRespond 类型，以及 ReportPreview.tsx 中现有的 QualificationItem / FormatItem 结构。


class TenderUploadOut(BaseModel):
    id: str
    filename: str
    size_bytes: int


class CreateTenderParseJobIn(BaseModel):
    tender_document_id: str


class TenderParseJobOut(BaseModel):
    job_id: str
    status: Literal["queued", "running", "done", "failed"]
    version: int
    error: Optional[str] = None


class ScoreRuleOut(BaseModel):
    id: str
    dimension: str
    weight: float
    detail: str
    subject: bool
    sectionPath: str
    responseStatus: Literal["未覆盖", "部分", "已覆盖"] = "未覆盖"
    isEssential: bool = False


class MustRespondOut(BaseModel):
    id: str
    clause: str
    original: str
    type: Literal["星号条款", "废标条款", "实质性条款"]
    status: Literal["待响应", "已响应"] = "待响应"


class QualificationItemOut(BaseModel):
    title: str
    desc: str
    source: str
    level: Literal["星号", "废标", "建议"]


class FormatItemOut(BaseModel):
    title: str
    desc: str
    source: str
    level: Literal["废标", "建议", "强制"]


class ParseRowOut(BaseModel):
    label: str
    content: str = ""


class ParseSectionOut(BaseModel):
    id: str
    title: str
    rows: list[ParseRowOut] = []


class ParseSubItemOut(BaseModel):
    id: str
    label: str
    sections: list[ParseSectionOut] = []


class ParseDimensionOut(BaseModel):
    key: str
    label: str
    completed: bool = False
    items: list[ParseSubItemOut] = []


class VetoParamsOut(BaseModel):
    validity_days_required: Optional[int] = None
    budget_cap_wan: Optional[float] = None
    asset_liability_ratio_max: Optional[float] = None
    qualification_keywords: list[str] = []
    anonymity_required: bool = False


class ChecklistOut(BaseModel):
    id: str
    project_id: str
    tender_document_id: str
    version: int
    status: Literal["queued", "running", "done", "failed"]
    locked: bool
    scoreRules: list[ScoreRuleOut] = []
    mustRespond: list[MustRespondOut] = []
    qualification: list[QualificationItemOut] = []
    formatRequirements: list[FormatItemOut] = []
    dimensions: list[ParseDimensionOut] = []
    vetoParams: VetoParamsOut = VetoParamsOut()
    error: Optional[str] = None


# 以下模型对应项目 / 认证真正落库（P0），字段严格对齐前端 src/context/AuthContext.tsx 的
# UserProfile 类型与 src/mocks/projects.ts 的 Project 类型（camelCase）。


class UserOut(BaseModel):
    id: str
    name: str
    email: str
    phone: str = ""
    company: str = ""
    position: str = ""
    role: str = "成员"


class RegisterIn(BaseModel):
    name: str
    email: str
    password: str
    phone: str = ""
    company: str = ""
    position: str = ""


class LoginIn(BaseModel):
    email: str
    password: str


class AuthOut(BaseModel):
    token: str
    user: UserOut


class UpdateProfileIn(BaseModel):
    name: Optional[str] = None
    email: Optional[str] = None
    phone: Optional[str] = None
    company: Optional[str] = None
    position: Optional[str] = None
    password: Optional[str] = None


class TenderUploadMetaOut(BaseModel):
    name: str
    size: str
    format: str
    pages: Optional[int] = None


class TeamMemberOut(BaseModel):
    id: str
    name: str
    email: str
    role: str
    phone: str = ""
    disabled: bool = False
    projectCount: int = 0
    joinedAt: str = ""


class InviteUserIn(BaseModel):
    name: str
    email: str
    phone: str = ""
    role: str = "撰写专家"


class InviteUserOut(TeamMemberOut):
    initialPassword: str = ""


class UpdateUserIn(BaseModel):
    name: Optional[str] = None
    phone: Optional[str] = None
    role: Optional[str] = None
    disabled: Optional[bool] = None


class QualificationImageOut(BaseModel):
    id: str
    caption: str = ""
    url: str = ""


class QualificationOut(BaseModel):
    id: str
    kind: Literal["cert", "people", "achievement", "equipment", "credit", "contract", "financial"]
    name: str
    level: str = ""
    number: str = ""
    validUntil: str = "长期"
    status: Literal["有效", "将到期", "已过期"]
    warnDays: Optional[int] = None
    owner: str = ""
    detail: str = ""
    filename: str = ""
    hasFile: bool = False
    ocrText: str = ""
    ocrStatus: str = ""
    reviewStatus: Literal["待审核", "已入库"] = "已入库"
    mergeStatus: Literal["新增", "并入已有", "疑似重复", "信息冲突"] = "新增"
    aliases: list[str] = []
    sources: list[dict] = []
    evidence: list[dict] = []
    fieldConflict: list[str] = []
    suspectedIds: list[str] = []
    images: list[QualificationImageOut] = []
    updatedAt: str = ""


class QualificationMergeIn(BaseModel):
    otherId: str


class QualificationResolveIn(BaseModel):
    keepId: str
    dropId: str
    action: Literal["merge", "keep_both"]


class QualificationParseJobOut(BaseModel):
    id: str
    filename: str
    status: Literal["解析中", "已完成", "抽取失败"]
    extracted: int = 0
    merged: int = 0
    suspected: int = 0
    conflicts: int = 0
    sizeLabel: str = ""
    uploadedAt: str
    note: str = ""
    error: Optional[str] = None


class QualificationExtractJobOut(BaseModel):
    jobId: str
    status: Literal["queued", "running", "done", "failed"]
    extracted: int = 0
    merged: int = 0
    suspected: int = 0
    conflicts: int = 0
    error: Optional[str] = None
    note: str = ""


class ProjectOut(BaseModel):
    id: str
    code: str
    name: str
    type: Literal["工程", "政采", "医疗", "交通", "IT", "能源"]
    owner: str
    budget: str
    deadline: str
    progress: int
    score: float
    status: Literal["撰写中", "评标中", "已提交", "已中标", "未中标"]
    createdAt: str
    tenderDoc: Optional[TenderUploadMetaOut] = None
    team: list[TeamMemberOut] = []


class CreateProjectIn(BaseModel):
    name: str
    code: str
    type: Literal["工程", "政采", "医疗", "交通", "IT", "能源"]
    budget: Optional[str] = None
    deadline: Optional[str] = None
    owner: Optional[str] = None


class TenderParagraphOut(BaseModel):
    index: int
    text: str
    style: str
    outlineLevel: Optional[int] = None


# 以下模型对应「AI 撰写工作台」真实后端接入：统一目录节点（融合原前端 PlanNode 编写思路字段
# 与 ChapterNode 生成状态字段），以及撰写草稿 / 异步生成任务模型。


class OutlineNodeOut(BaseModel):
    id: str
    num: str
    title: str
    parentId: Optional[str] = None
    expanded: bool = False
    weight: float = 0
    dimension: Optional[str] = None
    idea: str = ""
    aiIdea: str = ""
    optimized: bool = False
    status: Literal["待生成", "生成中", "已完成", "用原文"] = "待生成"
    words: int = 0
    aiRounds: int = 0
    sourceIndex: Optional[int] = None
    part: Optional[Literal["tech", "business", "form"]] = None
    requirement: Optional[str] = None


class OutlineNodeIn(OutlineNodeOut):
    pass


class KnowledgeRefIn(BaseModel):
    source: Literal["knowledge", "product", "qualification"] = "knowledge"
    docId: str
    docTitle: str = ""
    chapters: list[str] = []
    mode: Literal["manual", "ai"] = "manual"


class WriterDraftOut(BaseModel):
    id: str
    projectId: str
    modelId: str
    selectedKnowledge: list[str] = []
    selectedProductLibraryId: Optional[str] = None
    knowledgeRefs: dict[str, list[KnowledgeRefIn]] = {}
    settings: dict = {}
    interpretSource: Literal["reuse", "upload"] = "reuse"
    outline: list[OutlineNodeOut] = []
    chapterContents: dict[str, str] = {}
    step: int = 1


class UpdateWriterDraftIn(BaseModel):
    modelId: Optional[str] = None
    selectedKnowledge: Optional[list[str]] = None
    selectedProductLibraryId: Optional[str] = None
    knowledgeRefs: Optional[dict[str, list[KnowledgeRefIn]]] = None
    settings: Optional[dict] = None
    interpretSource: Optional[Literal["reuse", "upload"]] = None
    outline: Optional[list[OutlineNodeIn]] = None
    step: Optional[int] = None


class WriterJobOut(BaseModel):
    jobId: str
    kind: Literal["outline", "chapter", "product-match"]
    chapterId: Optional[str] = None
    status: Literal["queued", "running", "done", "failed"]
    error: Optional[str] = None


class SaveChapterContentIn(BaseModel):
    content: str


class WriterImageOut(BaseModel):
    id: str
    projectId: str
    source: Literal["generated", "upload", "knowledge", "product"]
    mode: Literal["normal", "flow", "arch"]
    prompt: str = ""
    filename: str
    url: str
    createdAt: str


class GenerateWriterImageIn(BaseModel):
    prompt: str
    mode: Literal["normal", "flow", "arch"] = "normal"


class OptimizeImagePromptIn(BaseModel):
    prompt: str
    mode: Literal["normal", "flow", "arch"] = "normal"


class OptimizeImagePromptOut(BaseModel):
    prompt: str


class WriterChatMessageIn(BaseModel):
    role: Literal["user", "assistant"]
    content: str


class WriterChatIn(BaseModel):
    message: str
    history: list[WriterChatMessageIn] = []
    chapterTitle: Optional[str] = None
    chapterExcerpt: Optional[str] = None


class WriterChatOut(BaseModel):
    reply: str
    hasChecklist: bool = False


# 以下模型对应「审核后修改闭环」真实后端接入：把预审 Finding 锚定到投标书真实段落，
# 并支持 Word 编辑器内容的持久化保存 / 版本历史 / 导出。


class BidProblemOut(BaseModel):
    issueId: str
    highlight: str


class BidParagraphOut(BaseModel):
    id: str
    text: str
    problem: Optional[BidProblemOut] = None
    align: Optional[str] = ""
    font: Optional[str] = ""
    fontSizePt: Optional[float] = None
    bold: Optional[bool] = False


class BidSectionOut(BaseModel):
    id: str
    heading: str
    level: Literal[1, 2, 3]
    paragraphs: list[BidParagraphOut] = []
    align: Optional[str] = ""
    font: Optional[str] = ""
    fontSizePt: Optional[float] = None
    bold: Optional[bool] = False


class BidRevisionOut(BaseModel):
    id: str
    projectId: str
    bidDocumentId: str
    reviewRunId: str
    reviewRound: Optional[int] = None
    sections: list[BidSectionOut] = []
    issues: list[PreReviewIssueOut] = []
    contentState: Optional[dict] = None
    layout: Optional[dict] = None
    resolvedIds: list[str] = []
    runSwitched: bool = False


class PatchRevisionContentIn(BaseModel):
    contentState: dict


class RevisionBlockIn(BaseModel):
    type: Literal["heading", "paragraph"]
    level: Optional[int] = None
    text: str = ""


class CreateVersionIn(BaseModel):
    blocks: list[RevisionBlockIn] = []
    contentState: dict = {}
    note: str = ""
    wordCount: int = 0
    author: str = ""


class PatchIssueResolvedIn(BaseModel):
    resolved: bool = True


class BidRevisionVersionOut(BaseModel):
    id: str
    label: str
    note: str
    author: str
    wordCount: int
    bidDocumentId: Optional[str] = None
    createdAt: str


class RestoreVersionOut(BaseModel):
    contentState: dict


# 以下模型对应「文档知识库」真实后端接入：真实存储 + 分段切片 + 轻量级检索，
# 供 Writer 撰写章节时引用（见 engines/knowledge_extract.py / knowledge_retrieval.py）。


class KnowledgeDocumentOut(BaseModel):
    id: str
    scope: Literal["企业库", "项目库", "个人库"]
    type: str
    title: str
    tags: list[str] = []
    projectId: Optional[str] = None
    source: str
    sliceCount: int = 0
    reviewFlag: Optional[str] = None
    updatedAt: str


class KnowledgeSliceImageOut(BaseModel):
    id: str
    caption: str = ""
    url: str


class KnowledgeChapterOut(BaseModel):
    heading: str
    sliceCount: int
    level: str = "一级"
    imageCount: int = 0
    excerpt: str = ""
    images: list[KnowledgeSliceImageOut] = []
    children: list["KnowledgeChapterOut"] = []


class KnowledgeChapterDetailOut(BaseModel):
    docTitle: str
    heading: str
    paragraphs: list[str]
    level: str = "一级"
    images: list[KnowledgeSliceImageOut] = []


class KnowledgeSuggestIn(BaseModel):
    query: str


class KnowledgeSuggestOut(BaseModel):
    docId: str
    docTitle: str
    chapters: list[str] = []


class ExportCheckItemOut(BaseModel):
    key: str
    label: str
    ok: bool
    note: str = ""


class ExportChecksOut(BaseModel):
    revisionId: str
    versionLabel: str
    wordCount: int
    updatedAt: str
    items: list[ExportCheckItemOut] = []
    blocked: bool
    blockReason: str = ""


class CreateExportIn(BaseModel):
    mode: Literal["明标", "暗标"]


class ExportRecordOut(BaseModel):
    id: str
    projectId: str
    mode: Literal["明标", "暗标"]
    operator: str
    checkStatus: Literal["通过", "阻断"]
    checkNote: str = ""
    fileSize: int = 0
    fileHash: str = ""
    filename: str = ""
    createdAt: str


class UpdateProjectIn(BaseModel):
    name: Optional[str] = None
    code: Optional[str] = None
    type: Optional[Literal["工程", "政采", "医疗", "交通", "IT", "能源"]] = None
    owner: Optional[str] = None
    budget: Optional[str] = None
    deadline: Optional[str] = None
    progress: Optional[int] = None
    score: Optional[float] = None
    status: Optional[Literal["撰写中", "评标中", "已提交", "已中标", "未中标"]] = None


# 以下模型对应「预审规则真实后端接入」：五维权重 / 虚词表 / 查重阈值 / 属地细则包
# 四组真实规则数据的 CRUD，字段严格对齐前端 src/mocks/rules.ts 的展示结构。


class WeightTemplateOut(BaseModel):
    id: str
    name: str
    completeness: float
    relevance: float
    compliance: float
    feasibility: float
    standardization: float
    scope: str
    active: bool


class WeightTemplateIn(BaseModel):
    name: str
    completeness: float
    relevance: float
    compliance: float
    feasibility: float
    standardization: float
    scope: str = "全局默认"


class UpdateWeightTemplateIn(BaseModel):
    name: Optional[str] = None
    completeness: Optional[float] = None
    relevance: Optional[float] = None
    compliance: Optional[float] = None
    feasibility: Optional[float] = None
    standardization: Optional[float] = None
    scope: Optional[str] = None


class FillerWordRuleOut(BaseModel):
    id: str
    category: str
    level: Literal["高危", "中危", "低危"]
    word: str
    rewrite: str = ""
    enabled: bool


class FillerWordRuleIn(BaseModel):
    category: str
    level: Literal["高危", "中危", "低危"] = "中危"
    word: str
    rewrite: str = ""


class UpdateFillerWordRuleIn(BaseModel):
    category: Optional[str] = None
    level: Optional[Literal["高危", "中危", "低危"]] = None
    word: Optional[str] = None
    rewrite: Optional[str] = None
    enabled: Optional[bool] = None


class ThresholdRuleOut(BaseModel):
    id: str
    key: str
    label: str
    value: float
    unit: str = "%"
    description: str = ""


class UpdateThresholdIn(BaseModel):
    value: float


class RulePackageOut(BaseModel):
    id: str
    name: str
    region: str
    status: Literal["启用", "停用"]
    items: list[str] = []


class RulePackageIn(BaseModel):
    name: str
    region: str = "全国"
    items: list[str] = []


class UpdateRulePackageIn(BaseModel):
    name: Optional[str] = None
    region: Optional[str] = None
    status: Optional[Literal["启用", "停用"]] = None
    items: Optional[list[str]] = None


class VetoRuleOut(BaseModel):
    id: str
    key: str
    category: str
    point: str
    items: list[str] = []
    wired: Literal["接入判定", "部分接入", "仅对照"]
    wiredNote: str = ""
    engine: str = ""
    seq: int = 0
    enabled: bool = True


class UpdateVetoRuleIn(BaseModel):
    enabled: Optional[bool] = None


class CatalogRuleOut(BaseModel):
    id: str
    kind: Literal["business", "tech", "dup_check", "strategy"]
    key: str
    category: str
    point: str
    items: list[str] = []
    wired: Literal["接入判定", "部分接入", "仅对照"]
    wiredNote: str = ""
    engine: str = ""
    seq: int = 0
    enabled: bool = True


class UpdateCatalogRuleIn(BaseModel):
    enabled: Optional[bool] = None


# 以下模型对应「项目中心补全」：团队分配 / 文件归档 / 进度时间线 / 招标文件真实落库。


class SetProjectMembersIn(BaseModel):
    user_ids: list[str]


class TenderDocumentSummaryOut(BaseModel):
    id: str
    filename: str
    sizeBytes: int
    uploadedAt: str


class ProjectDocumentsOut(BaseModel):
    tenderDocuments: list[TenderDocumentSummaryOut] = []
    bidDocuments: list[BidDocumentSummaryOut] = []


class TimelineStageOut(BaseModel):
    id: str
    label: str
    date: str
    status: Literal["已完成", "进行中", "待开始"]
    desc: str = ""


class AuditLogOut(BaseModel):
    id: str
    time: str
    user: str
    action: str
    target: str
    version: str
    detail: str
    result: str = "成功"


class AuditLogListOut(BaseModel):
    items: list[AuditLogOut]
    total: int
    weekTotal: int
    weekExport: int
    aiCount: int


class SearchProjectHit(BaseModel):
    id: str
    name: str
    code: str
    type: str


class SearchMemberHit(BaseModel):
    id: str
    name: str
    email: str
    role: str
    position: str = ""


class SearchDocumentHit(BaseModel):
    id: str
    title: str
    kind: str
    href: str


class SearchOut(BaseModel):
    projects: list[SearchProjectHit] = []
    members: list[SearchMemberHit] = []
    documents: list[SearchDocumentHit] = []


ProductLibraryCategory = Literal["软件系统", "货物设备", "综合方案"]
ProductKindLit = Literal["软件功能", "货物产品", "模块方案"]
ProductStatusLit = Literal["待审核", "已入库", "已停用"]
ProductMergeStatusLit = Literal["新增", "并入已有", "疑似重复", "参数冲突"]
ProductImageKindLit = Literal["界面", "架构", "流程", "实物"]


class ProductLibraryIn(BaseModel):
    name: str
    category: ProductLibraryCategory = "软件系统"
    description: str = ""
    owner: str = ""


class ProductLibraryOut(BaseModel):
    id: str
    name: str
    category: ProductLibraryCategory
    description: str = ""
    owner: str = ""
    createdAt: str
    updatedAt: str
    featureCount: int = 0
    pendingCount: int = 0
    imageCount: int = 0
    sourceCount: int = 0


class ProductImageOut(BaseModel):
    id: str
    caption: str = ""
    kind: ProductImageKindLit = "界面"
    url: str = ""


class ProductFeatureSourceOut(BaseModel):
    docId: str = ""
    filename: str = ""


class ProductFeatureOut(BaseModel):
    id: str
    libraryId: str
    name: str
    kind: ProductKindLit
    module: str = ""
    params: str = ""
    intro: str = ""
    bidCopy: str = ""
    brand: str = ""
    model: str = ""
    unit: str = ""
    sourceDoc: str = ""
    status: ProductStatusLit
    mergeStatus: ProductMergeStatusLit = "新增"
    aliases: list[str] = []
    sources: list[ProductFeatureSourceOut] = []
    evidence: list[dict] = []
    paramsConflict: list[str] = []
    suspectedIds: list[str] = []
    images: list[ProductImageOut] = []
    parentId: str = ""
    children: list["ProductFeatureOut"] = []
    updatedAt: str


class ProductFeatureIn(BaseModel):
    name: str
    kind: ProductKindLit = "软件功能"
    module: str = ""
    params: str = ""
    intro: str = ""
    bidCopy: str = ""
    brand: str = ""
    model: str = ""
    unit: str = ""
    status: Optional[ProductStatusLit] = None
    parentId: Optional[str] = None


class ProductFeaturePatchIn(BaseModel):
    name: Optional[str] = None
    kind: Optional[ProductKindLit] = None
    module: Optional[str] = None
    params: Optional[str] = None
    intro: Optional[str] = None
    bidCopy: Optional[str] = None
    brand: Optional[str] = None
    model: Optional[str] = None
    unit: Optional[str] = None
    status: Optional[ProductStatusLit] = None


class ProductMergeIn(BaseModel):
    otherId: str


class ProductResolveIn(BaseModel):
    keepId: str
    dropId: str
    action: Literal["merge", "keep_both"]


class ProductParseJobOut(BaseModel):
    id: str
    libraryId: str
    filename: str
    status: Literal["解析中", "已完成", "抽取失败"]
    extracted: int = 0
    merged: int = 0
    suspected: int = 0
    conflicts: int = 0
    sizeLabel: str = ""
    uploadedAt: str
    note: str = ""
    error: Optional[str] = None


class ProductExtractJobOut(BaseModel):
    jobId: str
    status: Literal["queued", "running", "done", "failed"]
    extracted: int = 0
    merged: int = 0
    suspected: int = 0
    conflicts: int = 0
    error: Optional[str] = None
    note: str = ""


class LlmModelOut(BaseModel):
    id: str
    providerId: str
    providerKind: str
    providerName: str
    name: str
    apiModel: str
    thinking: bool = False
    enabled: bool = True
    isDefault: bool = False
    ctx: str = ""
    speed: str = ""
    vision: bool = False
    ready: bool = False


class LlmProviderOut(BaseModel):
    id: str
    name: str
    kind: str
    baseUrl: str = ""
    apiKeyMasked: str = ""
    hasKey: bool = False
    enabled: bool = True
    note: str = ""
    ready: bool = False
    models: list[LlmModelOut] = []


class LlmProviderIn(BaseModel):
    name: str
    kind: str
    baseUrl: str = ""
    apiKey: Optional[str] = None
    enabled: bool = True
    note: str = ""


class LlmProviderPatchIn(BaseModel):
    name: Optional[str] = None
    baseUrl: Optional[str] = None
    apiKey: Optional[str] = None
    enabled: Optional[bool] = None
    note: Optional[str] = None
    clearKey: bool = False


class LlmModelIn(BaseModel):
    name: str
    apiModel: str
    thinking: bool = False
    enabled: bool = True
    isDefault: bool = False
    ctx: str = ""
    speed: str = ""


class LlmModelPatchIn(BaseModel):
    name: Optional[str] = None
    apiModel: Optional[str] = None
    thinking: Optional[bool] = None
    enabled: Optional[bool] = None
    isDefault: Optional[bool] = None
    ctx: Optional[str] = None
    speed: Optional[str] = None


class LlmTestOut(BaseModel):
    ok: bool
    message: str
    latencyMs: int = 0
    preview: str = ""


class LlmPresetOut(BaseModel):
    kind: str
    label: str
    defaultBaseUrl: str
    keyRequired: bool
    hint: str = ""
    sampleModels: list[dict] = []


ProductFeatureOut.model_rebuild()
