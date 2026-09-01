// AI 预审引擎后端 API 封装（对应 backend/app/routers）。
// 五引擎相关请求全部走这里，页面组件不直接拼 URL。

import type { PreReviewIssue, PreReviewLevel } from "@/mocks/preReview";
import type {
  ProductItem,
  ProductKind,
  ProductLibrary,
  ProductLibraryCategory,
  ProductParseJob,
  ProductStatus,
} from "@/mocks/products";

export interface DimensionScore {
  name: string;
  weight: number;
  score: number;
}

export interface ReviewReport {
  round: number;
  overall: number;
  waste: number;
  risk: number;
  suggest: number;
  light: "绿" | "橙" | "红";
  levels: PreReviewLevel[];
  dimensions: DimensionScore[];
  issues: PreReviewIssue[];
}

export interface TrendPoint {
  round: number;
  score: number;
  issues: number;
}

export interface UploadedDoc {
  id: string;
  filename: string;
  size_bytes: number;
  source: "upload" | "workbench";
}

export interface JobStatus {
  job_id: string;
  status: "queued" | "running" | "done" | "failed";
  round: number;
  error?: string | null;
}

export interface TenderUploadedDoc {
  id: string;
  filename: string;
  size_bytes: number;
}

export interface TenderParseJobStatus {
  job_id: string;
  status: "queued" | "running" | "done" | "failed";
  version: number;
  error?: string | null;
}

export interface ScoreRule {
  id: string;
  dimension: string;
  weight: number;
  detail: string;
  subject: boolean;
  sectionPath: string;
  responseStatus: "未覆盖" | "部分" | "已覆盖";
  isEssential: boolean;
}

export interface MustRespond {
  id: string;
  clause: string;
  original: string;
  type: "星号条款" | "废标条款" | "实质性条款";
  status: "待响应" | "已响应";
}

export interface QualificationItem {
  title: string;
  desc: string;
  source: string;
  level: "星号" | "废标" | "建议";
}

export interface FormatItem {
  title: string;
  desc: string;
  source: string;
  level: "废标" | "建议" | "强制";
}

export interface VetoParams {
  validity_days_required: number | null;
  budget_cap_wan: number | null;
  asset_liability_ratio_max: number | null;
  qualification_keywords: string[];
  anonymity_required: boolean;
}

export interface ParseRow {
  label: string;
  content: string;
}

export interface ParseSection {
  id: string;
  title: string;
  rows: ParseRow[];
}

export interface ParseSubItem {
  id: string;
  label: string;
  sections: ParseSection[];
}

export interface ParseDimension {
  key: string;
  label: string;
  completed: boolean;
  items: ParseSubItem[];
}

export interface Checklist {
  id: string;
  project_id: string;
  tender_document_id: string;
  version: number;
  status: "queued" | "running" | "done" | "failed";
  locked: boolean;
  scoreRules: ScoreRule[];
  mustRespond: MustRespond[];
  qualification: QualificationItem[];
  formatRequirements: FormatItem[];
  dimensions: ParseDimension[];
  vetoParams: VetoParams;
  error?: string | null;
}

class ApiError extends Error {
  status: number;

  constructor(message: string, status: number) {
    super(message);
    this.status = status;
  }
}

async function request<T>(path: string, init?: Parameters<typeof fetch>[1]): Promise<T> {
  const headers = new Headers(init?.headers);
  const token = localStorage.getItem("zhbiao_token");
  if (token && !headers.has("Authorization")) {
    headers.set("Authorization", `Bearer ${token}`);
  }
  const res = await fetch(path, { ...init, headers });
  if (!res.ok) {
    let message = `请求失败（${res.status}）`;
    try {
      const body = await res.json();
      if (body?.detail) message = body.detail;
    } catch {
      // ignore json parse error, use default message
    }
    throw new ApiError(message, res.status);
  }
  return res.json() as Promise<T>;
}

export async function uploadBidDocument(projectId: string, file: File): Promise<UploadedDoc> {
  const form = new FormData();
  form.append("project_id", projectId);
  form.append("file", file);
  return request<UploadedDoc>("/api/bid-documents", { method: "POST", body: form });
}

export async function fetchSampleDocument(projectId: string): Promise<UploadedDoc> {
  const form = new FormData();
  form.append("project_id", projectId);
  return request<UploadedDoc>("/api/bid-documents/from-sample", { method: "POST", body: form });
}

export interface BidDocumentSummary {
  id: string;
  filename: string;
  source: string;
  sizeBytes: number;
  uploadedAt: string;
}

export async function listProjectBidDocuments(projectId: string): Promise<BidDocumentSummary[]> {
  return request<BidDocumentSummary[]>(`/api/projects/${projectId}/bid-documents`);
}

export async function createPrereviewJob(projectId: string, bidDocumentId: string): Promise<JobStatus> {
  return request<JobStatus>(`/api/projects/${projectId}/prereview-jobs`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ bid_document_id: bidDocumentId, scope: "full" }),
  });
}

export async function getJobStatus(jobId: string): Promise<JobStatus> {
  return request<JobStatus>(`/api/prereview-jobs/${jobId}`);
}

export async function getLatestReviewRun(projectId: string): Promise<ReviewReport> {
  return request<ReviewReport>(`/api/projects/${projectId}/review-runs/latest`);
}

export async function exportLatestReviewReport(projectId: string): Promise<Blob> {
  return fetchBlob(`/api/projects/${projectId}/review-runs/latest/export`);
}

export async function getReviewRunTrend(projectId: string): Promise<TrendPoint[]> {
  return request<TrendPoint[]>(`/api/projects/${projectId}/review-runs`);
}

/** 轮询任务直至完成/失败，intervalMs 控制轮询间隔，timeoutMs 控制最长等待时间。 */
export async function pollJobUntilDone(
  jobId: string,
  { intervalMs = 1500, timeoutMs = 5 * 60 * 1000 }: { intervalMs?: number; timeoutMs?: number } = {},
): Promise<JobStatus> {
  const startedAt = Date.now();
  while (true) {
    const status = await getJobStatus(jobId);
    if (status.status === "done" || status.status === "failed") return status;
    if (Date.now() - startedAt > timeoutMs) {
      throw new ApiError("预审任务超时，请稍后在历史趋势中查看结果", 408);
    }
    await new Promise((resolve) => setTimeout(resolve, intervalMs));
  }
}

// 招标文件解析与评标尺子锁定（P1）相关请求。

export async function uploadTenderDocument(projectId: string, file: File): Promise<TenderUploadedDoc> {
  const form = new FormData();
  form.append("project_id", projectId);
  form.append("file", file);
  return request<TenderUploadedDoc>("/api/tender-documents", { method: "POST", body: form });
}

export async function createTenderParseJob(
  projectId: string,
  tenderDocumentId: string,
): Promise<TenderParseJobStatus> {
  return request<TenderParseJobStatus>(`/api/projects/${projectId}/tender-parse-jobs`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ tender_document_id: tenderDocumentId }),
  });
}

export async function getTenderParseJobStatus(jobId: string): Promise<TenderParseJobStatus> {
  return request<TenderParseJobStatus>(`/api/tender-parse-jobs/${jobId}`);
}

export async function getLatestChecklist(projectId: string): Promise<Checklist> {
  return request<Checklist>(`/api/projects/${projectId}/checklist/latest`);
}

export async function lockChecklist(projectId: string, checklistId: string): Promise<Checklist> {
  return request<Checklist>(`/api/projects/${projectId}/checklist/${checklistId}/lock`, { method: "POST" });
}

/** 轮询招标解析任务直至完成/失败。 */
export async function pollTenderParseJobUntilDone(
  jobId: string,
  { intervalMs = 1500, timeoutMs = 5 * 60 * 1000 }: { intervalMs?: number; timeoutMs?: number } = {},
): Promise<TenderParseJobStatus> {
  const startedAt = Date.now();
  while (true) {
    const status = await getTenderParseJobStatus(jobId);
    if (status.status === "done" || status.status === "failed") return status;
    if (Date.now() - startedAt > timeoutMs) {
      throw new ApiError("解析任务超时，请稍后重试", 408);
    }
    await new Promise((resolve) => setTimeout(resolve, intervalMs));
  }
}

// 项目 / 认证真正落库（P0）相关请求。

export interface AuthUser {
  id: string;
  name: string;
  email: string;
  phone: string;
  company: string;
  position: string;
  role: string;
}

export interface AuthResult {
  token: string;
  user: AuthUser;
}

export interface TenderUploadMeta {
  name: string;
  size: string;
  format: string;
  pages?: number;
}

export interface TeamMember {
  id: string;
  name: string;
  email: string;
  role: string;
  phone?: string;
  disabled?: boolean;
  projectCount?: number;
  joinedAt?: string;
}

export interface ProjectDto {
  id: string;
  code: string;
  name: string;
  type: "工程" | "政采" | "医疗" | "交通" | "IT" | "能源";
  owner: string;
  budget: string;
  deadline: string;
  progress: number;
  score: number;
  status: "撰写中" | "评标中" | "已提交" | "已中标" | "未中标";
  createdAt: string;
  tenderDoc?: TenderUploadMeta;
  team?: TeamMember[];
}

export interface CreateProjectPayload {
  name: string;
  code: string;
  type: ProjectDto["type"];
  budget?: string;
  deadline?: string;
  owner?: string;
}

export type UpdateProjectPayload = Partial<CreateProjectPayload> & {
  progress?: number;
  score?: number;
  status?: ProjectDto["status"];
};

function authHeaders(token: string): Record<string, string> {
  return { Authorization: `Bearer ${token}`, "Content-Type": "application/json" };
}

export async function apiRegister(payload: {
  name: string;
  email: string;
  password: string;
  phone?: string;
  company?: string;
  position?: string;
}): Promise<AuthResult> {
  return request<AuthResult>("/api/auth/register", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
}

export async function apiLogin(email: string, password: string): Promise<AuthResult> {
  return request<AuthResult>("/api/auth/login", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ email, password }),
  });
}

export async function apiGetMe(token: string): Promise<AuthUser> {
  return request<AuthUser>("/api/auth/me", { headers: authHeaders(token) });
}

export async function apiUpdateProfile(
  token: string,
  patch: Partial<{ name: string; email: string; phone: string; company: string; position: string; password: string }>,
): Promise<AuthUser> {
  return request<AuthUser>("/api/auth/me", {
    method: "PATCH",
    headers: authHeaders(token),
    body: JSON.stringify(patch),
  });
}

export async function listProjects(token: string): Promise<ProjectDto[]> {
  return request<ProjectDto[]>("/api/projects", { headers: authHeaders(token) });
}

export async function getProjectApi(token: string, id: string): Promise<ProjectDto> {
  return request<ProjectDto>(`/api/projects/${id}`, { headers: authHeaders(token) });
}

export async function createProject(token: string, payload: CreateProjectPayload): Promise<ProjectDto> {
  return request<ProjectDto>("/api/projects", {
    method: "POST",
    headers: authHeaders(token),
    body: JSON.stringify(payload),
  });
}

export async function updateProjectApi(
  token: string,
  id: string,
  patch: UpdateProjectPayload,
): Promise<ProjectDto> {
  return request<ProjectDto>(`/api/projects/${id}`, {
    method: "PATCH",
    headers: authHeaders(token),
    body: JSON.stringify(patch),
  });
}

// AI 撰写工作台真实后端接入相关请求。

export type OutlineNodeStatus = "待生成" | "生成中" | "已完成" | "用原文";

export interface OutlineNode {
  id: string;
  num: string;
  title: string;
  parentId: string | null;
  expanded: boolean;
  weight: number;
  dimension: string | null;
  idea: string;
  aiIdea: string;
  optimized: boolean;
  status: OutlineNodeStatus;
  words: number;
  aiRounds: number;
  sourceIndex?: number | null;
  part?: "tech" | "business" | "form" | null;
  requirement?: string;
}

export type KnowledgeRefSource = "knowledge" | "product" | "qualification";

export interface KnowledgeRef {
  source?: KnowledgeRefSource;
  docId: string;
  docTitle: string;
  chapters: string[];
  mode: "manual" | "ai";
}

export interface WriterDraft {
  id: string;
  projectId: string;
  modelId: string;
  selectedKnowledge: string[];
  selectedProductLibraryId?: string | null;
  knowledgeRefs: Record<string, KnowledgeRef[]>;
  settings: Record<string, unknown>;
  interpretSource: "reuse" | "upload";
  outline: OutlineNode[];
  chapterContents: Record<string, string>;
  step: number;
}

export interface UpdateWriterDraftPayload {
  modelId?: string;
  selectedKnowledge?: string[];
  selectedProductLibraryId?: string | null;
  knowledgeRefs?: Record<string, KnowledgeRef[]>;
  settings?: Record<string, unknown>;
  interpretSource?: "reuse" | "upload";
  outline?: OutlineNode[];
  step?: number;
}

export interface WriterJob {
  jobId: string;
  kind: "outline" | "chapter" | "product-match";
  chapterId?: string | null;
  status: "queued" | "running" | "done" | "failed";
  error?: string | null;
}

export interface TenderParagraph {
  index: number;
  text: string;
  style: string;
  outlineLevel: number | null;
}

export async function getOrCreateWriterDraft(projectId: string): Promise<WriterDraft> {
  return request<WriterDraft>(`/api/projects/${projectId}/writer-draft`);
}

export async function updateWriterDraft(
  draftId: string,
  patch: UpdateWriterDraftPayload,
): Promise<WriterDraft> {
  return request<WriterDraft>(`/api/writer-drafts/${draftId}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(patch),
  });
}

export async function createOutlineJob(draftId: string): Promise<WriterJob> {
  return request<WriterJob>(`/api/writer-drafts/${draftId}/outline-jobs`, { method: "POST" });
}

export async function createProductMatchJob(draftId: string): Promise<WriterJob> {
  return request<WriterJob>(`/api/writer-drafts/${draftId}/product-match-jobs`, { method: "POST" });
}

export async function getWriterJobStatus(jobId: string): Promise<WriterJob> {
  return request<WriterJob>(`/api/writer-jobs/${jobId}`);
}

/** 轮询撰写工作台的目录/正文生成任务直至完成/失败。 */
export async function pollWriterJobUntilDone(
  jobId: string,
  { intervalMs = 1500, timeoutMs = 5 * 60 * 1000 }: { intervalMs?: number; timeoutMs?: number } = {},
): Promise<WriterJob> {
  const startedAt = Date.now();
  while (true) {
    const status = await getWriterJobStatus(jobId);
    if (status.status === "done" || status.status === "failed") return status;
    if (Date.now() - startedAt > timeoutMs) {
      throw new ApiError("生成任务超时，请稍后重试", 408);
    }
    await new Promise((resolve) => setTimeout(resolve, intervalMs));
  }
}

export async function createChapterGenerateJob(draftId: string, chapterId: string): Promise<WriterJob> {
  return request<WriterJob>(`/api/writer-drafts/${draftId}/chapters/${chapterId}/generate-jobs`, {
    method: "POST",
  });
}

export async function saveChapterContent(
  draftId: string,
  chapterId: string,
  content: string,
): Promise<WriterDraft> {
  return request<WriterDraft>(`/api/writer-drafts/${draftId}/chapters/${chapterId}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ content }),
  });
}

export async function getTenderParagraphs(tenderDocumentId: string): Promise<TenderParagraph[]> {
  return request<TenderParagraph[]>(`/api/tender-documents/${tenderDocumentId}/paragraphs`);
}

export async function downloadChecklistReport(projectId: string, checklistId: string): Promise<Blob> {
  return fetchBlob(`/api/projects/${projectId}/checklist/${checklistId}/export`);
}

export async function exportWriterDraftDocx(draftId: string): Promise<Blob> {
  const res = await fetch(`/api/writer-drafts/${draftId}/export`);
  if (!res.ok) {
    let message = `导出失败（${res.status}）`;
    try {
      const body = await res.json();
      if (body?.detail) message = body.detail;
    } catch {
      // ignore
    }
    throw new ApiError(message, res.status);
  }
  return res.blob();
}

export type WriterImageMode = "normal" | "flow" | "arch";

export interface WriterImageItem {
  id: string;
  projectId: string;
  source: "generated" | "upload" | "knowledge";
  mode: WriterImageMode;
  prompt: string;
  filename: string;
  url: string;
  createdAt: string;
}

export async function generateWriterImage(
  token: string,
  projectId: string,
  prompt: string,
  mode: WriterImageMode,
): Promise<WriterImageItem> {
  return request<WriterImageItem>(`/api/projects/${projectId}/writer-images/generate`, {
    method: "POST",
    headers: authHeaders(token),
    body: JSON.stringify({ prompt, mode }),
  });
}

export async function uploadWriterImage(
  token: string,
  projectId: string,
  file: File,
): Promise<WriterImageItem> {
  const form = new FormData();
  form.append("file", file);
  return request<WriterImageItem>(`/api/projects/${projectId}/writer-images/upload`, {
    method: "POST",
    headers: { Authorization: `Bearer ${token}` },
    body: form,
  });
}

export async function listWriterImages(token: string, projectId: string): Promise<WriterImageItem[]> {
  return request<WriterImageItem[]>(`/api/projects/${projectId}/writer-images`, {
    headers: authHeaders(token),
  });
}

export async function optimizeWriterImagePrompt(
  token: string,
  prompt: string,
  mode: WriterImageMode,
): Promise<string> {
  const out = await request<{ prompt: string }>("/api/writer-images/optimize-prompt", {
    method: "POST",
    headers: authHeaders(token),
    body: JSON.stringify({ prompt, mode }),
  });
  return out.prompt;
}

export interface WriterChatResult {
  reply: string;
  hasChecklist: boolean;
}

export async function writerChat(
  token: string,
  draftId: string,
  payload: {
    message: string;
    history?: { role: "user" | "assistant"; content: string }[];
    chapterTitle?: string;
    chapterExcerpt?: string;
  },
): Promise<WriterChatResult> {
  return request<WriterChatResult>(`/api/writer-drafts/${draftId}/chat`, {
    method: "POST",
    headers: authHeaders(token),
    body: JSON.stringify(payload),
  });
}

// 文档知识库真实后端接入相关请求。

export const KNOWLEDGE_SCOPES = ["全部", "企业库", "项目库", "个人库"] as const;
export const KNOWLEDGE_TYPES = ["历史中标标书", "专项方案", "施工工艺", "规范条文", "制度表单", "图表模板"] as const;

export interface KnowledgeDoc {
  id: string;
  scope: "企业库" | "项目库" | "个人库";
  type: string;
  title: string;
  tags: string[];
  projectId: string | null;
  source: string;
  sliceCount: number;
  reviewFlag: string | null;
  updatedAt: string;
}

export interface KnowledgeSliceImage {
  id: string;
  caption: string;
  url: string;
}

export interface KnowledgeChapter {
  heading: string;
  sliceCount: number;
  level?: "一级" | "二级" | "三级" | string;
  imageCount?: number;
  excerpt?: string;
  images?: KnowledgeSliceImage[];
  children?: KnowledgeChapter[];
}

export interface KnowledgeChapterDetail {
  docTitle: string;
  heading: string;
  paragraphs: string[];
  level?: string;
  images?: KnowledgeSliceImage[];
}

export interface KnowledgeSuggestion {
  docId: string;
  docTitle: string;
  chapters: string[];
}

export interface UploadKnowledgeDocPayload {
  scope: KnowledgeDoc["scope"];
  type: string;
  title?: string;
  tags?: string[];
  projectId?: string;
  file: File;
}

export async function listKnowledgeDocuments(params: {
  scope?: string;
  type?: string;
  projectId?: string;
  keyword?: string;
} = {}): Promise<KnowledgeDoc[]> {
  const query = new URLSearchParams();
  if (params.scope) query.set("scope", params.scope);
  if (params.type) query.set("type", params.type);
  if (params.projectId) query.set("project_id", params.projectId);
  if (params.keyword) query.set("keyword", params.keyword);
  const qs = query.toString();
  return request<KnowledgeDoc[]>(`/api/knowledge-documents${qs ? `?${qs}` : ""}`);
}

export async function uploadKnowledgeDocument(
  token: string,
  payload: UploadKnowledgeDocPayload,
): Promise<KnowledgeDoc> {
  const form = new FormData();
  form.append("scope", payload.scope);
  form.append("type", payload.type);
  if (payload.title) form.append("title", payload.title);
  if (payload.tags?.length) form.append("tags", payload.tags.join(","));
  if (payload.projectId) form.append("project_id", payload.projectId);
  form.append("file", payload.file);
  return request<KnowledgeDoc>("/api/knowledge-documents", {
    method: "POST",
    headers: { Authorization: `Bearer ${token}` },
    body: form,
  });
}

export async function deleteKnowledgeDocument(id: string): Promise<void> {
  await request(`/api/knowledge-documents/${id}`, { method: "DELETE" });
}

export async function rechunkKnowledgeDocument(id: string): Promise<KnowledgeDoc> {
  return request<KnowledgeDoc>(`/api/knowledge-documents/${id}/rechunk`, { method: "POST" });
}

export async function getKnowledgeChapters(docId: string): Promise<KnowledgeChapter[]> {
  return request<KnowledgeChapter[]>(`/api/knowledge-documents/${docId}/chapters`);
}

export async function getKnowledgeChapterDetail(
  docId: string,
  heading: string,
): Promise<KnowledgeChapterDetail> {
  return request<KnowledgeChapterDetail>(
    `/api/knowledge-documents/${docId}/chapter-detail?heading=${encodeURIComponent(heading)}`,
  );
}

export async function suggestKnowledgeForChapter(
  projectId: string,
  query: string,
): Promise<KnowledgeSuggestion[]> {
  return request<KnowledgeSuggestion[]>(`/api/projects/${projectId}/knowledge-suggest`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ query }),
  });
}

// 审核后修改闭环（Review）真实后端接入相关请求。

export interface BidProblem {
  issueId: string;
  highlight: string;
}

export type BidParagraphAlign = "" | "left" | "center" | "right" | "justify";

export interface BidParagraph {
  id: string;
  text: string;
  problem?: BidProblem;
  align?: BidParagraphAlign;
  font?: string;
  fontSizePt?: number;
  bold?: boolean;
}

export interface BidSection {
  id: string;
  heading: string;
  level: 1 | 2 | 3;
  paragraphs: BidParagraph[];
  align?: BidParagraphAlign;
  font?: string;
  fontSizePt?: number;
  bold?: boolean;
}

/** 投标书整体的字体/字号/首行缩进画像，来自 extract_bid_typography，供编辑器原样还原排版 */
export interface BidLayout {
  bodyFont?: string;
  bodySizePt?: number;
  headingFont?: string;
  headingSizePt?: number;
  headingBold?: boolean;
  indentPt?: number;
  indentChars?: number;
  lineSpacingMul?: number;
}

export interface BidRevision {
  id: string;
  projectId: string;
  bidDocumentId: string;
  reviewRunId: string;
  reviewRound?: number | null;
  sections: BidSection[];
  issues: PreReviewIssue[];
  contentState: Record<string, unknown> | null;
  layout?: BidLayout | null;
  resolvedIds?: string[];
  runSwitched?: boolean;
}

export interface BidRevisionVersion {
  id: string;
  label: string;
  note: string;
  author: string;
  wordCount: number;
  bidDocumentId: string | null;
  createdAt: string;
}

export interface RevisionBlock {
  type: "heading" | "paragraph";
  level?: number;
  text: string;
}

export interface CreateVersionPayload {
  blocks?: RevisionBlock[];
  contentState?: Record<string, unknown>;
  note?: string;
  wordCount?: number;
  author?: string;
}

export async function getOrCreateBidRevision(projectId: string): Promise<BidRevision> {
  return request<BidRevision>(`/api/projects/${projectId}/bid-revision`);
}

export async function regenerateBidRevision(revisionId: string): Promise<BidRevision> {
  return request<BidRevision>(`/api/bid-revisions/${revisionId}/regenerate`, { method: "POST" });
}

export async function autosaveBidRevisionContent(
  revisionId: string,
  contentState: Record<string, unknown>,
): Promise<BidRevision> {
  return request<BidRevision>(`/api/bid-revisions/${revisionId}/content`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ contentState }),
  });
}

export async function patchBidRevisionIssueResolved(
  revisionId: string,
  issueId: string,
  resolved: boolean,
): Promise<BidRevision> {
  return request<BidRevision>(`/api/bid-revisions/${revisionId}/issues/${issueId}/resolve`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ resolved }),
  });
}

export async function createBidRevisionVersion(
  revisionId: string,
  payload: CreateVersionPayload,
): Promise<BidRevisionVersion> {
  return request<BidRevisionVersion>(`/api/bid-revisions/${revisionId}/versions`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
}

export async function listBidRevisionVersions(revisionId: string): Promise<BidRevisionVersion[]> {
  return request<BidRevisionVersion[]>(`/api/bid-revisions/${revisionId}/versions`);
}

export async function restoreBidRevisionVersion(
  revisionId: string,
  versionId: string,
): Promise<{ contentState: Record<string, unknown> }> {
  return request(`/api/bid-revisions/${revisionId}/versions/${versionId}/restore`, { method: "POST" });
}

export async function exportBidRevisionDocx(revisionId: string): Promise<Blob> {
  const res = await fetch(`/api/bid-revisions/${revisionId}/export`);
  if (!res.ok) {
    let message = `导出失败（${res.status}）`;
    try {
      const body = await res.json();
      if (body?.detail) message = body.detail;
    } catch {
      // ignore json parse error, use default message
    }
    throw new ApiError(message, res.status);
  }
  return res.blob();
}

// Word 导出中心真实后端接入相关请求。

export interface ExportCheckItem {
  key: string;
  label: string;
  ok: boolean;
  note: string;
}

export interface ExportChecks {
  revisionId: string;
  versionLabel: string;
  wordCount: number;
  updatedAt: string;
  items: ExportCheckItem[];
  blocked: boolean;
  blockReason: string;
}

export interface ExportRecord {
  id: string;
  projectId: string;
  mode: "明标" | "暗标";
  operator: string;
  checkStatus: "通过" | "阻断";
  checkNote: string;
  fileSize: number;
  fileHash: string;
  filename: string;
  createdAt: string;
}

export async function getExportChecks(
  token: string,
  projectId: string,
  mode: "明标" | "暗标" = "明标",
): Promise<ExportChecks> {
  return request<ExportChecks>(`/api/projects/${projectId}/export-checks?mode=${encodeURIComponent(mode)}`, {
    headers: { Authorization: `Bearer ${token}` },
  });
}

export async function createExport(
  token: string,
  projectId: string,
  mode: "明标" | "暗标",
): Promise<ExportRecord> {
  return request<ExportRecord>(`/api/projects/${projectId}/exports`, {
    method: "POST",
    headers: authHeaders(token),
    body: JSON.stringify({ mode }),
  });
}

export async function listExportRecords(token: string, projectId: string): Promise<ExportRecord[]> {
  return request<ExportRecord[]>(`/api/projects/${projectId}/export-records`, {
    headers: { Authorization: `Bearer ${token}` },
  });
}

export async function downloadExportRecord(token: string, recordId: string): Promise<Blob> {
  const res = await fetch(`/api/export-records/${recordId}/download`, {
    headers: { Authorization: `Bearer ${token}` },
  });
  if (!res.ok) {
    let message = `下载失败（${res.status}）`;
    try {
      const body = await res.json();
      if (body?.detail) message = body.detail;
    } catch {
      // ignore json parse error, use default message
    }
    throw new ApiError(message, res.status);
  }
  return res.blob();
}

// 项目中心补全：用户列表 / 成员分配 / 文件归档 / 时间线 / 招标文件。

export interface TenderDocumentSummary {
  id: string;
  filename: string;
  sizeBytes: number;
  uploadedAt: string;
}

export interface ProjectDocuments {
  tenderDocuments: TenderDocumentSummary[];
  bidDocuments: BidDocumentSummary[];
}

export interface TimelineStage {
  id: string;
  label: string;
  date: string;
  status: "已完成" | "进行中" | "待开始";
  desc: string;
}

export async function listUsers(token: string): Promise<TeamMember[]> {
  return request<TeamMember[]>("/api/users", { headers: authHeaders(token) });
}

export async function inviteUser(
  token: string,
  payload: { name: string; email: string; phone?: string; role: string },
): Promise<TeamMember & { initialPassword: string }> {
  return request<TeamMember & { initialPassword: string }>("/api/users", {
    method: "POST",
    headers: authHeaders(token),
    body: JSON.stringify(payload),
  });
}

export async function updateUser(
  token: string,
  userId: string,
  payload: { name?: string; phone?: string; role?: string; disabled?: boolean },
): Promise<TeamMember> {
  return request<TeamMember>(`/api/users/${userId}`, {
    method: "PATCH",
    headers: authHeaders(token),
    body: JSON.stringify(payload),
  });
}

export type QualificationKind =
  | "cert"
  | "people"
  | "achievement"
  | "equipment"
  | "credit"
  | "contract"
  | "financial";

export interface QualificationImage {
  id: string;
  caption: string;
  url: string;
}

export interface QualificationAsset {
  id: string;
  kind: QualificationKind;
  name: string;
  level: string;
  number: string;
  validUntil: string;
  status: "有效" | "将到期" | "已过期";
  warnDays?: number | null;
  owner: string;
  detail: string;
  filename: string;
  hasFile: boolean;
  ocrText?: string;
  ocrStatus?: string;
  reviewStatus?: "待审核" | "已入库";
  mergeStatus?: "新增" | "并入已有" | "疑似重复" | "信息冲突";
  aliases?: string[];
  sources?: { docId?: string; filename?: string }[];
  evidence?: { heading?: string; excerpt?: string }[];
  fieldConflict?: string[];
  suspectedIds?: string[];
  images?: QualificationImage[];
  updatedAt: string;
}

export interface QualificationParseJob {
  id: string;
  filename: string;
  status: "解析中" | "已完成" | "抽取失败";
  extracted: number;
  merged: number;
  suspected: number;
  conflicts: number;
  sizeLabel: string;
  uploadedAt: string;
  note: string;
  error?: string | null;
}

export interface QualificationExtractJob {
  jobId: string;
  status: "queued" | "running" | "done" | "failed";
  extracted: number;
  merged: number;
  suspected: number;
  conflicts: number;
  error?: string | null;
  note: string;
}

export async function listQualifications(token: string): Promise<QualificationAsset[]> {
  return request<QualificationAsset[]>("/api/qualifications", { headers: authHeaders(token) });
}

export async function createQualification(
  token: string,
  payload: {
    kind: QualificationKind;
    name: string;
    level?: string;
    number?: string;
    validUntil?: string;
    owner?: string;
    detail?: string;
    file?: File | null;
  },
): Promise<QualificationAsset> {
  const form = new FormData();
  form.append("kind", payload.kind);
  form.append("name", payload.name);
  form.append("level", payload.level || "");
  form.append("number", payload.number || "");
  form.append("valid_until", payload.validUntil || "长期");
  form.append("owner", payload.owner || "");
  form.append("detail", payload.detail || "");
  if (payload.file) form.append("file", payload.file);
  return request<QualificationAsset>("/api/qualifications", {
    method: "POST",
    headers: { Authorization: `Bearer ${token}` },
    body: form,
  });
}

export async function updateQualification(
  token: string,
  id: string,
  payload: {
    kind?: QualificationKind;
    name?: string;
    level?: string;
    number?: string;
    validUntil?: string;
    owner?: string;
    detail?: string;
    reviewStatus?: "待审核" | "已入库";
    file?: File | null;
  },
): Promise<QualificationAsset> {
  const form = new FormData();
  if (payload.kind) form.append("kind", payload.kind);
  if (payload.name != null) form.append("name", payload.name);
  if (payload.level != null) form.append("level", payload.level);
  if (payload.number != null) form.append("number", payload.number);
  if (payload.validUntil != null) form.append("valid_until", payload.validUntil);
  if (payload.owner != null) form.append("owner", payload.owner);
  if (payload.detail != null) form.append("detail", payload.detail);
  if (payload.reviewStatus) form.append("review_status", payload.reviewStatus);
  if (payload.file) form.append("file", payload.file);
  return request<QualificationAsset>(`/api/qualifications/${id}`, {
    method: "PATCH",
    headers: { Authorization: `Bearer ${token}` },
    body: form,
  });
}

export async function deleteQualification(token: string, id: string): Promise<void> {
  await request<{ ok: boolean }>(`/api/qualifications/${id}`, {
    method: "DELETE",
    headers: authHeaders(token),
  });
}

export async function resolveQualificationPair(
  token: string,
  keepId: string,
  dropId: string,
  action: "merge" | "keep_both",
): Promise<QualificationAsset> {
  return request<QualificationAsset>("/api/qualifications/resolve", {
    method: "POST",
    headers: { ...authHeaders(token), "Content-Type": "application/json" },
    body: JSON.stringify({ keepId, dropId, action }),
  });
}

export async function listQualificationSourceDocs(token: string): Promise<QualificationParseJob[]> {
  return request<QualificationParseJob[]>("/api/qualification-source-docs", { headers: authHeaders(token) });
}

export async function uploadQualificationSourceDocs(token: string, files: File[]): Promise<QualificationParseJob[]> {
  const form = new FormData();
  files.forEach((file) => form.append("files", file));
  return request<QualificationParseJob[]>("/api/qualification-source-docs", {
    method: "POST",
    headers: { Authorization: `Bearer ${token}` },
    body: form,
  });
}

export async function getQualificationExtractJob(token: string, jobId: string): Promise<QualificationExtractJob> {
  return request<QualificationExtractJob>(`/api/qualification-extract-jobs/${jobId}`, {
    headers: authHeaders(token),
  });
}

export async function pollQualificationExtractJobUntilDone(
  token: string,
  jobId: string,
  { intervalMs = 1500, timeoutMs = 10 * 60 * 1000 }: { intervalMs?: number; timeoutMs?: number } = {},
): Promise<QualificationExtractJob> {
  const startedAt = Date.now();
  while (true) {
    const status = await getQualificationExtractJob(token, jobId);
    if (status.status === "done" || status.status === "failed") return status;
    if (Date.now() - startedAt > timeoutMs) {
      throw new ApiError("抽取任务超时，请稍后在文件解析中查看进度", 408);
    }
    await new Promise((resolve) => setTimeout(resolve, intervalMs));
  }
}

export async function getProjectMembers(token: string, projectId: string): Promise<TeamMember[]> {
  return request<TeamMember[]>(`/api/projects/${projectId}/members`, { headers: authHeaders(token) });
}

export async function setProjectMembers(
  token: string,
  projectId: string,
  userIds: string[],
): Promise<TeamMember[]> {
  return request<TeamMember[]>(`/api/projects/${projectId}/members`, {
    method: "PUT",
    headers: authHeaders(token),
    body: JSON.stringify({ user_ids: userIds }),
  });
}

export async function getProjectDocuments(token: string, projectId: string): Promise<ProjectDocuments> {
  return request<ProjectDocuments>(`/api/projects/${projectId}/documents`, { headers: authHeaders(token) });
}

export async function getProjectTimeline(token: string, projectId: string): Promise<TimelineStage[]> {
  return request<TimelineStage[]>(`/api/projects/${projectId}/timeline`, { headers: authHeaders(token) });
}

export async function listProjectTenderDocuments(
  token: string,
  projectId: string,
): Promise<TenderDocumentSummary[]> {
  return request<TenderDocumentSummary[]>(`/api/projects/${projectId}/tender-documents`, {
    headers: authHeaders(token),
  });
}

async function fetchBlob(path: string): Promise<Blob> {
  const headers = new Headers();
  const token = localStorage.getItem("zhbiao_token");
  if (token) headers.set("Authorization", `Bearer ${token}`);
  const res = await fetch(path, { headers });
  if (!res.ok) {
    let message = `下载失败（${res.status}）`;
    try {
      const body = await res.json();
      if (body?.detail) message = body.detail;
    } catch {
      // ignore json parse error, use default message
    }
    throw new ApiError(message, res.status);
  }
  return res.blob();
}

export async function downloadTenderDocument(id: string): Promise<Blob> {
  return fetchBlob(`/api/tender-documents/${id}/download`);
}

export async function downloadBidDocumentFile(id: string): Promise<Blob> {
  return fetchBlob(`/api/bid-documents/${id}/download`);
}

export async function downloadKnowledgeDocument(id: string): Promise<Blob> {
  return fetchBlob(`/api/knowledge-documents/${id}/download`);
}

export function triggerFileDownload(blob: Blob, filename: string): void {
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  a.remove();
  URL.revokeObjectURL(url);
}

// 预审规则真实后端接入相关请求。

export interface WeightTemplate {
  id: string;
  name: string;
  completeness: number;
  relevance: number;
  compliance: number;
  feasibility: number;
  standardization: number;
  scope: string;
  active: boolean;
}

export interface WeightTemplatePayload {
  name: string;
  completeness: number;
  relevance: number;
  compliance: number;
  feasibility: number;
  standardization: number;
  scope?: string;
}

export interface FillerWordRule {
  id: string;
  category: string;
  level: "高危" | "中危" | "低危";
  word: string;
  rewrite: string;
  enabled: boolean;
}

export interface FillerWordRulePayload {
  category: string;
  level?: "高危" | "中危" | "低危";
  word: string;
  rewrite?: string;
}

export interface ThresholdRule {
  id: string;
  key: string;
  label: string;
  value: number;
  unit: string;
  description: string;
}

export interface RulePackage {
  id: string;
  name: string;
  region: string;
  status: "启用" | "停用";
  items: string[];
}

export interface RulePackagePayload {
  name: string;
  region?: string;
  items?: string[];
}

export interface VetoRule {
  id: string;
  key: string;
  category: string;
  point: string;
  items: string[];
  wired: "接入判定" | "部分接入" | "仅对照";
  wiredNote: string;
  engine: string;
  seq: number;
  enabled: boolean;
}

export type CatalogKind = "business" | "tech" | "dup_check" | "strategy";

export interface CatalogRule extends VetoRule {
  kind: CatalogKind;
}

export async function listWeightTemplates(): Promise<WeightTemplate[]> {
  return request<WeightTemplate[]>("/api/rules/weight-templates");
}

export async function createWeightTemplate(payload: WeightTemplatePayload): Promise<WeightTemplate> {
  return request<WeightTemplate>("/api/rules/weight-templates", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
}

export async function updateWeightTemplate(
  id: string,
  patch: Partial<WeightTemplatePayload>,
): Promise<WeightTemplate> {
  return request<WeightTemplate>(`/api/rules/weight-templates/${id}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(patch),
  });
}

export async function activateWeightTemplate(id: string): Promise<WeightTemplate> {
  return request<WeightTemplate>(`/api/rules/weight-templates/${id}/activate`, { method: "POST" });
}

export async function listWordRules(): Promise<FillerWordRule[]> {
  return request<FillerWordRule[]>("/api/rules/word-rules");
}

export async function createWordRule(payload: FillerWordRulePayload): Promise<FillerWordRule> {
  return request<FillerWordRule>("/api/rules/word-rules", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
}

export async function updateWordRule(
  id: string,
  patch: Partial<FillerWordRulePayload & { enabled: boolean }>,
): Promise<FillerWordRule> {
  return request<FillerWordRule>(`/api/rules/word-rules/${id}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(patch),
  });
}

export async function listThresholds(): Promise<ThresholdRule[]> {
  return request<ThresholdRule[]>("/api/rules/thresholds");
}

export async function updateThreshold(id: string, value: number): Promise<ThresholdRule> {
  return request<ThresholdRule>(`/api/rules/thresholds/${id}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ value }),
  });
}

export async function listRulePackages(): Promise<RulePackage[]> {
  return request<RulePackage[]>("/api/rules/packages");
}

export async function createRulePackage(payload: RulePackagePayload): Promise<RulePackage> {
  return request<RulePackage>("/api/rules/packages", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
}

export async function updateRulePackage(
  id: string,
  patch: Partial<RulePackagePayload & { status: "启用" | "停用" }>,
): Promise<RulePackage> {
  return request<RulePackage>(`/api/rules/packages/${id}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(patch),
  });
}

export async function listVetoRules(): Promise<VetoRule[]> {
  return request<VetoRule[]>("/api/rules/veto-points");
}

export async function updateVetoRule(id: string, patch: { enabled: boolean }): Promise<VetoRule> {
  return request<VetoRule>(`/api/rules/veto-points/${id}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(patch),
  });
}

export async function listCatalogRules(kind?: CatalogKind): Promise<CatalogRule[]> {
  const query = kind ? `?kind=${kind}` : "";
  return request<CatalogRule[]>(`/api/rules/catalog${query}`);
}

export async function updateCatalogRule(id: string, patch: { enabled: boolean }): Promise<CatalogRule> {
  return request<CatalogRule>(`/api/rules/catalog/${id}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(patch),
  });
}

export interface AuditLogItem {
  id: string;
  time: string;
  user: string;
  action: string;
  target: string;
  version: string;
  detail: string;
  result: string;
}

export interface AuditLogList {
  items: AuditLogItem[];
  total: number;
  weekTotal: number;
  weekExport: number;
  aiCount: number;
}

export async function listAuditLogs(
  token: string,
  params?: { action?: string; keyword?: string },
): Promise<AuditLogList> {
  const q = new URLSearchParams();
  if (params?.action && params.action !== "全部") q.set("action", params.action);
  if (params?.keyword) q.set("keyword", params.keyword);
  const qs = q.toString();
  return request<AuditLogList>(`/api/audit-logs${qs ? `?${qs}` : ""}`, {
    headers: authHeaders(token),
  });
}

export interface SearchResult {
  projects: { id: string; name: string; code: string; type: string }[];
  members: { id: string; name: string; email: string; role: string; position: string }[];
  documents: { id: string; title: string; kind: string; href: string }[];
}

export async function globalSearch(token: string, q: string): Promise<SearchResult> {
  const qs = new URLSearchParams({ q });
  return request<SearchResult>(`/api/search?${qs.toString()}`, {
    headers: authHeaders(token),
  });
}

export async function deleteProjectApi(token: string, id: string): Promise<void> {
  const res = await fetch(`/api/projects/${id}`, { method: "DELETE", headers: authHeaders(token) });
  if (!res.ok && res.status !== 204) {
    let message = `请求失败（${res.status}）`;
    try {
      const body = await res.json();
      if (body?.detail) message = body.detail;
    } catch {
      // ignore json parse error, use default message
    }
    throw new ApiError(message, res.status);
  }
}

export type {
  ProductItem,
  ProductKind,
  ProductLibrary,
  ProductLibraryCategory,
  ProductParseJob,
  ProductStatus,
};

export interface ProductLibraryIn {
  name: string;
  category: ProductLibraryCategory;
  description: string;
  owner: string;
}

export interface ProductFeatureIn {
  name: string;
  kind: ProductKind;
  module: string;
  params: string;
  intro: string;
  bidCopy: string;
  brand: string;
  model: string;
  unit: string;
  status?: ProductStatus;
  parentId?: string;
}

export interface ProductExtractJob {
  jobId: string;
  status: "queued" | "running" | "done" | "failed";
  extracted: number;
  merged: number;
  suspected: number;
  conflicts: number;
  error?: string | null;
  note: string;
}

export async function listProductLibraries(): Promise<ProductLibrary[]> {
  return request<ProductLibrary[]>("/api/product-libraries");
}

export async function createProductLibrary(payload: ProductLibraryIn): Promise<ProductLibrary> {
  return request<ProductLibrary>("/api/product-libraries", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
}

export async function updateProductLibrary(id: string, payload: ProductLibraryIn): Promise<ProductLibrary> {
  return request<ProductLibrary>(`/api/product-libraries/${id}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
}

export async function deleteProductLibrary(id: string): Promise<void> {
  await request(`/api/product-libraries/${id}`, { method: "DELETE" });
}

export async function getProductLibrary(id: string): Promise<ProductLibrary> {
  return request<ProductLibrary>(`/api/product-libraries/${id}`);
}

export async function listProductFeatures(libraryId: string): Promise<ProductItem[]> {
  return request<ProductItem[]>(`/api/product-libraries/${libraryId}/features`);
}

export async function createProductFeature(libraryId: string, payload: ProductFeatureIn): Promise<ProductItem> {
  return request<ProductItem>(`/api/product-libraries/${libraryId}/features`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
}

export async function patchProductFeature(featureId: string, payload: Partial<ProductFeatureIn>): Promise<ProductItem> {
  return request<ProductItem>(`/api/product-features/${featureId}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
}

export async function deleteProductFeature(featureId: string): Promise<void> {
  await request(`/api/product-features/${featureId}`, { method: "DELETE" });
}

export async function mergeProductFeatures(keepId: string, otherId: string): Promise<ProductItem> {
  return request<ProductItem>(`/api/product-features/${keepId}/merge`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ otherId }),
  });
}

export async function resolveProductPair(
  libraryId: string,
  keepId: string,
  dropId: string,
  action: "merge" | "keep_both",
): Promise<ProductItem> {
  return request<ProductItem>(`/api/product-libraries/${libraryId}/resolve`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ keepId, dropId, action }),
  });
}

export async function uploadProductFeatureImages(
  featureId: string,
  files: File[],
  captions: string[] = [],
  kinds: string[] = [],
): Promise<ProductItem> {
  const form = new FormData();
  files.forEach((file) => form.append("files", file));
  if (captions.length) form.append("captions", captions.join("|"));
  if (kinds.length) form.append("kinds", kinds.join("|"));
  return request<ProductItem>(`/api/product-features/${featureId}/images`, { method: "POST", body: form });
}

export async function deleteProductImage(imageId: string): Promise<void> {
  await request(`/api/product-images/${imageId}`, { method: "DELETE" });
}

export async function listProductSourceDocs(libraryId: string): Promise<ProductParseJob[]> {
  return request<ProductParseJob[]>(`/api/product-libraries/${libraryId}/source-docs`);
}

export async function uploadProductSourceDocs(libraryId: string, files: File[]): Promise<ProductParseJob[]> {
  const form = new FormData();
  files.forEach((file) => form.append("files", file));
  return request<ProductParseJob[]>(`/api/product-libraries/${libraryId}/source-docs`, { method: "POST", body: form });
}

export async function getProductExtractJob(jobId: string): Promise<ProductExtractJob> {
  return request<ProductExtractJob>(`/api/product-extract-jobs/${jobId}`);
}

export async function pollProductExtractJobUntilDone(
  jobId: string,
  { intervalMs = 1500, timeoutMs = 10 * 60 * 1000 }: { intervalMs?: number; timeoutMs?: number } = {},
): Promise<ProductExtractJob> {
  const startedAt = Date.now();
  while (true) {
    const status = await getProductExtractJob(jobId);
    if (status.status === "done" || status.status === "failed") return status;
    if (Date.now() - startedAt > timeoutMs) {
      throw new ApiError("抽取任务超时，请稍后在文件解析中查看进度", 408);
    }
    await new Promise((resolve) => setTimeout(resolve, intervalMs));
  }
}

export { ApiError };

export type LlmProviderKind = "deepseek" | "doubao" | "qwen" | "siliconflow" | "openai" | "custom" | "local";

export interface WriterLlmModel {
  id: string;
  providerId: string;
  providerKind: LlmProviderKind;
  providerName: string;
  name: string;
  apiModel: string;
  thinking: boolean;
  enabled: boolean;
  isDefault: boolean;
  ctx: string;
  speed: string;
  vision: boolean;
  ready: boolean;
}

export interface LlmProvider {
  id: string;
  name: string;
  kind: LlmProviderKind;
  baseUrl: string;
  apiKeyMasked: string;
  hasKey: boolean;
  enabled: boolean;
  note: string;
  ready: boolean;
  models: WriterLlmModel[];
}

export interface LlmPreset {
  kind: LlmProviderKind;
  label: string;
  defaultBaseUrl: string;
  keyRequired: boolean;
  hint: string;
  sampleModels: { name: string; api_model?: string; thinking?: boolean; ctx?: string; speed?: string }[];
}

export interface LlmTestResult {
  ok: boolean;
  message: string;
  latencyMs: number;
  preview: string;
}

export async function listWriterModels(): Promise<WriterLlmModel[]> {
  return request<WriterLlmModel[]>("/api/llm-models");
}

export async function listLlmPresets(): Promise<LlmPreset[]> {
  return request<LlmPreset[]>("/api/llm-presets");
}

export async function listLlmProviders(): Promise<LlmProvider[]> {
  return request<LlmProvider[]>("/api/llm-providers");
}

export async function createLlmProvider(payload: {
  name: string;
  kind: LlmProviderKind;
  baseUrl?: string;
  apiKey?: string;
  note?: string;
}): Promise<LlmProvider> {
  return request<LlmProvider>("/api/llm-providers", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
}

export async function patchLlmProvider(
  id: string,
  payload: { name?: string; baseUrl?: string; apiKey?: string; enabled?: boolean; note?: string; clearKey?: boolean },
): Promise<LlmProvider> {
  return request<LlmProvider>(`/api/llm-providers/${id}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
}

export async function deleteLlmProvider(id: string): Promise<void> {
  await request(`/api/llm-providers/${id}`, { method: "DELETE" });
}

export async function createLlmModel(
  providerId: string,
  payload: { name: string; apiModel: string; thinking?: boolean; enabled?: boolean; isDefault?: boolean; ctx?: string; speed?: string },
): Promise<WriterLlmModel> {
  return request<WriterLlmModel>(`/api/llm-providers/${providerId}/models`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
}

export async function patchLlmModel(
  id: string,
  payload: {
    name?: string;
    apiModel?: string;
    thinking?: boolean;
    enabled?: boolean;
    isDefault?: boolean;
    ctx?: string;
    speed?: string;
  },
): Promise<WriterLlmModel> {
  return request<WriterLlmModel>(`/api/llm-models/${id}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
}

export async function deleteLlmModel(id: string): Promise<void> {
  await request(`/api/llm-models/${id}`, { method: "DELETE" });
}

export async function testLlmModel(id: string): Promise<LlmTestResult> {
  return request<LlmTestResult>(`/api/llm-models/${id}/test`, { method: "POST" });
}
