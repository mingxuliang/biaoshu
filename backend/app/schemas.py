from typing import Literal, Optional

from pydantic import BaseModel


class UploadDocOut(BaseModel):
    id: str
    filename: str
    size_bytes: int
    source: str


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


class CreateProjectIn(BaseModel):
    name: str
    code: str
    type: Literal["工程", "政采", "医疗", "交通", "IT", "能源"]
    budget: Optional[str] = None
    deadline: Optional[str] = None
    owner: Optional[str] = None
    tenderDoc: Optional[TenderUploadMetaOut] = None


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
    status: Literal["待生成", "生成中", "已完成"] = "待生成"
    words: int = 0
    aiRounds: int = 0


class OutlineNodeIn(OutlineNodeOut):
    pass


class KnowledgeRefIn(BaseModel):
    docId: str
    docTitle: str = ""
    chapters: list[str] = []
    mode: Literal["manual", "ai"] = "manual"


class WriterDraftOut(BaseModel):
    id: str
    projectId: str
    modelId: str
    selectedKnowledge: list[str] = []
    knowledgeRefs: dict[str, list[KnowledgeRefIn]] = {}
    settings: dict = {}
    interpretSource: Literal["reuse", "upload"] = "reuse"
    outline: list[OutlineNodeOut] = []
    chapterContents: dict[str, str] = {}
    step: int = 1


class UpdateWriterDraftIn(BaseModel):
    modelId: Optional[str] = None
    selectedKnowledge: Optional[list[str]] = None
    knowledgeRefs: Optional[dict[str, list[KnowledgeRefIn]]] = None
    settings: Optional[dict] = None
    interpretSource: Optional[Literal["reuse", "upload"]] = None
    outline: Optional[list[OutlineNodeIn]] = None
    step: Optional[int] = None


class WriterJobOut(BaseModel):
    jobId: str
    kind: Literal["outline", "chapter"]
    chapterId: Optional[str] = None
    status: Literal["queued", "running", "done", "failed"]
    error: Optional[str] = None


class SaveChapterContentIn(BaseModel):
    content: str


# 以下模型对应「审核后修改闭环」真实后端接入：把预审 Finding 锚定到投标书真实段落，
# 并支持 Word 编辑器内容的持久化保存 / 版本历史 / 导出。


class BidProblemOut(BaseModel):
    issueId: str
    highlight: str


class BidParagraphOut(BaseModel):
    id: str
    text: str
    problem: Optional[BidProblemOut] = None


class BidSectionOut(BaseModel):
    id: str
    heading: str
    level: Literal[1, 2, 3]
    paragraphs: list[BidParagraphOut] = []


class BidRevisionOut(BaseModel):
    id: str
    projectId: str
    bidDocumentId: str
    reviewRunId: str
    sections: list[BidSectionOut] = []
    issues: list[PreReviewIssueOut] = []
    contentState: Optional[dict] = None


class PatchRevisionContentIn(BaseModel):
    contentState: dict


class RevisionBlockIn(BaseModel):
    type: Literal["heading", "paragraph"]
    level: Optional[int] = None
    text: str = ""


class CreateVersionIn(BaseModel):
    blocks: list[RevisionBlockIn]
    contentState: dict
    note: str = ""
    wordCount: int = 0
    author: str = ""


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


class KnowledgeChapterOut(BaseModel):
    heading: str
    sliceCount: int


class KnowledgeChapterDetailOut(BaseModel):
    docTitle: str
    heading: str
    paragraphs: list[str]


class KnowledgeSuggestIn(BaseModel):
    query: str


class KnowledgeSuggestOut(BaseModel):
    docId: str
    docTitle: str
    chapters: list[str] = []


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
    tenderDoc: Optional[TenderUploadMetaOut] = None
