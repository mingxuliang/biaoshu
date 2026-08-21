// AI 预审引擎后端 API 封装（对应 backend/app/routers）。
// 五引擎相关请求全部走这里，页面组件不直接拼 URL。

import type { PreReviewIssue, PreReviewLevel } from "@/mocks/preReview";

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
  const res = await fetch(path, init);
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
}

export interface CreateProjectPayload {
  name: string;
  code: string;
  type: ProjectDto["type"];
  budget?: string;
  deadline?: string;
  owner?: string;
  tenderDoc?: TenderUploadMeta;
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

export type OutlineNodeStatus = "待生成" | "生成中" | "已完成";

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
}

export interface KnowledgeRef {
  docId: string;
  docTitle: string;
  chapters: string[]; // 选中的知识文档章节（heading）
  mode: "manual" | "ai";
}

export interface WriterDraft {
  id: string;
  projectId: string;
  modelId: string;
  selectedKnowledge: string[];
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
  knowledgeRefs?: Record<string, KnowledgeRef[]>;
  settings?: Record<string, unknown>;
  interpretSource?: "reuse" | "upload";
  outline?: OutlineNode[];
  step?: number;
}

export interface WriterJob {
  jobId: string;
  kind: "outline" | "chapter";
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

export interface KnowledgeChapter {
  heading: string;
  sliceCount: number;
}

export interface KnowledgeChapterDetail {
  docTitle: string;
  heading: string;
  paragraphs: string[];
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

export interface BidParagraph {
  id: string;
  text: string;
  problem?: BidProblem;
}

export interface BidSection {
  id: string;
  heading: string;
  level: 1 | 2 | 3;
  paragraphs: BidParagraph[];
}

export interface BidRevision {
  id: string;
  projectId: string;
  bidDocumentId: string;
  reviewRunId: string;
  sections: BidSection[];
  issues: PreReviewIssue[];
  contentState: Record<string, unknown> | null;
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
  blocks: RevisionBlock[];
  contentState: Record<string, unknown>;
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

export { ApiError };
