// 企业端 SaaS 接口：企业资料与认证、部门、自定义角色、费用中心、发票、协作与通知。
// 企业 ID 只由登录令牌决定，这里的接口都不传企业 ID。

import { apiRequest as request, type TenantKind } from "./api";

const json = (body: unknown, method = "POST") => ({
  method,
  headers: { "Content-Type": "application/json" },
  body: JSON.stringify(body),
});

// ---------------------------------------------------------------------------
// 企业与组织
// ---------------------------------------------------------------------------

export interface TenantProfile {
  id: string;
  name: string;
  kind: TenantKind;
  status: string;
  planCode: string;
  seats: number;
  storageQuotaMb: number;
  features: Record<string, boolean>;
  verifyStatus: string;
  verifyNote: string;
  licenseNo: string;
  hasLicense: boolean;
  contactName: string;
  contactPhone: string;
  contactEmail: string;
  trialEndsAt: string;
  expiresAt: string;
  lowBalanceThreshold: number;
  createdAt: string;
}

export const getTenantProfile = () => request<TenantProfile>("/api/org/tenant");

export const updateTenantProfile = (p: {
  name: string;
  contactName: string;
  contactPhone: string;
  contactEmail: string;
  lowBalanceThreshold: number;
}) => request<TenantProfile>("/api/org/tenant", json(p, "PUT"));

export const upgradeToEnterprise = (companyName: string) => request<TenantProfile>("/api/org/tenant/upgrade", json({ companyName }));

export function submitTenantVerify(licenseNo: string, file: File) {
  const form = new FormData();
  form.append("licenseNo", licenseNo);
  form.append("file", file);
  return request<TenantProfile>("/api/org/tenant/verify", { method: "POST", body: form });
}

export interface Department {
  id: string;
  name: string;
  parentId: string | null;
  leaderId: string | null;
  leaderName: string;
  sortOrder: number;
  memberCount: number;
}

export const listDepartments = () => request<Department[]>("/api/org/departments");
export const createDepartment = (p: { name: string; parentId?: string | null; leaderId?: string | null; sortOrder?: number }) =>
  request<Department>("/api/org/departments", json(p));
export const updateDepartment = (id: string, p: { name: string; parentId?: string | null; leaderId?: string | null; sortOrder?: number }) =>
  request<Department>(`/api/org/departments/${id}`, json(p, "PUT"));
export const deleteDepartment = (id: string) => request<{ ok: boolean }>(`/api/org/departments/${id}`, { method: "DELETE" });

export interface CustomRole {
  id: string;
  name: string;
  perms: string[];
  dataScope: string;
  memberCount: number;
}

export const getPermCatalog = () => request<{ perms: { id: string; name: string }[]; scopes: string[] }>("/api/org/perm-catalog");
export const listCustomRoles = () => request<CustomRole[]>("/api/org/roles");
export const createCustomRole = (p: { name: string; perms: string[]; dataScope: string }) => request<CustomRole>("/api/org/roles", json(p));
export const updateCustomRole = (id: string, p: { name: string; perms: string[]; dataScope: string }) =>
  request<CustomRole>(`/api/org/roles/${id}`, json(p, "PUT"));
export const deleteCustomRole = (id: string) => request<{ ok: boolean }>(`/api/org/roles/${id}`, { method: "DELETE" });

export interface SupportGrant {
  id: string;
  grantedBy: string;
  reason: string;
  expiresAt: string;
  active: boolean;
  revoked: boolean;
  createdAt: string;
}

export const listSupportGrants = () => request<SupportGrant[]>("/api/org/support-grants");
export const createSupportGrant = (hours: number, reason: string) => request<SupportGrant>("/api/org/support-grants", json({ hours, reason }));
export const revokeSupportGrant = (id: string) => request<SupportGrant>(`/api/org/support-grants/${id}`, { method: "DELETE" });

export interface Announcement {
  id: string;
  title: string;
  body: string;
  level: "info" | "warning";
  createdAt: string;
}

export const listAnnouncements = () => request<Announcement[]>("/api/org/announcements");

// ---------------------------------------------------------------------------
// 费用中心
// ---------------------------------------------------------------------------

export interface WalletBalance {
  balance: number;
  held: number;
  available: number;
  expiringIn30Days: number;
  totalRecharged: number;
  totalConsumed: number;
}

export interface Plan {
  code: string;
  kind: "套餐" | "加油包";
  audience: "企业" | "个人" | "通用";
  name: string;
  priceCents: number;
  durationDays: number;
  seats: number;
  credits: number;
  bonusCredits: number;
  storageMb: number;
  rechargeBonusPct: number;
  features: Record<string, boolean>;
  description: string;
}

export interface BillingSummary {
  wallet: WalletBalance;
  plan: Plan | null;
  tokensPerCredit: number;
  tenant: {
    id: string;
    name: string;
    kind: TenantKind;
    status: string;
    seats: number;
    seatsUsed: number;
    storageQuotaMb: number;
    storageUsedBytes: number | null;
    trialEndsAt: string;
    expiresAt: string;
    lowBalanceThreshold: number;
    verifyStatus: string;
  };
  me: { monthSpent: number; monthlyLimit: number | null };
  lowBalance: boolean;
  canManage: boolean;
}

export interface PriceRule {
  feature: string;
  name: string;
  mode: "per_1k_tokens" | "per_call" | "free";
  unitPrice: number;
  estimate: number;
}

export interface LedgerRow {
  id: string;
  kind: string;
  amount: number;
  balanceAfter: number;
  feature: string;
  refId: string;
  note: string;
  operator: string;
  userName: string;
  createdAt: string;
}

export interface UsageStats {
  days: number;
  byFeature: { feature: string; name: string; credits: number; promptTokens: number; completionTokens: number; calls: number }[];
  byUser: { userId: string; userName: string; credits: number }[];
}

export type PayChannel = "alipay" | "wechat" | "bank" | "mock";
export type OrderKind = "充值" | "套餐" | "加油包";

export interface Order {
  id: string;
  kind: OrderKind;
  itemCode: string;
  subject: string;
  amountCents: number;
  credits: number;
  bonusCredits: number;
  channel: PayChannel;
  status: "待支付" | "待确认" | "已支付" | "已关闭" | "已退款";
  payUrl: string;
  codeUrl: string;
  transferCode: string;
  paidAt: string;
  expiresAt: string;
  createdAt: string;
  invoicedCents: number;
  userName: string;
  note: string;
}

export const getBillingSummary = () => request<BillingSummary>("/api/billing/summary");
export const listPlans = () => request<Plan[]>("/api/billing/plans");
export const listPrices = () => request<{ creditsPerYuan: number; tokensPerCredit: number; rules: PriceRule[] }>("/api/billing/prices");

/** 积分折合 Token 的展示文案，按标准模型估算 */
export function tokensLabel(credits: number, tokensPerCredit: number): string {
  const tokens = credits * (tokensPerCredit || 1000);
  if (tokens >= 1e8) return `约 ${(tokens / 1e8).toFixed(tokens >= 1e9 ? 0 : 1)} 亿 Token`;
  if (tokens >= 1e4) return `约 ${Math.round(tokens / 1e4).toLocaleString("zh-CN")} 万 Token`;
  return `约 ${Math.round(tokens).toLocaleString("zh-CN")} Token`;
}
export const listPayChannels = () => request<{ id: PayChannel; name: string; ready: boolean }[]>("/api/billing/channels");
export const getBankAccount = () => request<{ accountName: string; accountNo: string; bankName: string }>("/api/billing/bank-account");
export const listLedger = (page = 1, kind = "") =>
  request<{ total: number; items: LedgerRow[] }>(`/api/billing/ledger?page=${page}&size=20${kind ? `&kind=${encodeURIComponent(kind)}` : ""}`);
export const getUsage = (days = 30) => request<UsageStats>(`/api/billing/usage?days=${days}`);
export const quoteOrder = (p: { kind: OrderKind; itemCode?: string; amountCents?: number }) =>
  request<{ amountCents: number; credits: number; bonusCredits: number; subject: string }>("/api/billing/quote", json(p));
export const createOrder = (p: { kind: OrderKind; itemCode?: string; amountCents?: number; channel: PayChannel }) =>
  request<Order>("/api/billing/orders", json(p));
export const listOrders = (page = 1) => request<{ total: number; items: Order[] }>(`/api/billing/orders?page=${page}&size=20`);
export const getOrder = (id: string) => request<Order>(`/api/billing/orders/${id}`);
export const closeOrder = (id: string) => request<Order>(`/api/billing/orders/${id}/close`, { method: "POST" });
export const mockPay = (id: string) => request<Order>(`/api/billing/orders/${id}/mock-pay`, { method: "POST" });

export function submitTransfer(id: string, p: { payerName: string; payerAccount: string; bankSerial: string; amountCents: number; file?: File | null }) {
  const form = new FormData();
  form.append("payerName", p.payerName);
  form.append("payerAccount", p.payerAccount);
  form.append("bankSerial", p.bankSerial);
  form.append("amountCents", String(p.amountCents));
  if (p.file) form.append("file", p.file);
  return request<Order>(`/api/billing/orders/${id}/transfer`, { method: "POST", body: form });
}

export interface InvoiceTitle {
  id: string;
  kind: "普票" | "专票";
  title: string;
  taxNo: string;
  address: string;
  phone: string;
  bankName: string;
  bankAccount: string;
  email: string;
  isDefault: boolean;
}

export type InvoiceTitleInput = Omit<InvoiceTitle, "id">;

export interface Invoice {
  id: string;
  kind: string;
  title: Record<string, string>;
  amountCents: number;
  orderIds: string[];
  status: "待审核" | "开具中" | "已开具" | "已驳回" | "已红冲";
  invoiceNo: string;
  fileName: string;
  hasFile: boolean;
  rejectReason: string;
  applicantName: string;
  issuedAt: string;
  createdAt: string;
}

export const listInvoiceTitles = () => request<InvoiceTitle[]>("/api/billing/invoice-titles");
export const createInvoiceTitle = (p: InvoiceTitleInput) => request<InvoiceTitle>("/api/billing/invoice-titles", json(p));
export const updateInvoiceTitle = (id: string, p: InvoiceTitleInput) => request<InvoiceTitle>(`/api/billing/invoice-titles/${id}`, json(p, "PUT"));
export const deleteInvoiceTitle = (id: string) => request<{ ok: boolean }>(`/api/billing/invoice-titles/${id}`, { method: "DELETE" });
export const listInvoices = () => request<Invoice[]>("/api/billing/invoices");
export const applyInvoice = (titleId: string, orderIds: string[]) => request<Invoice>("/api/billing/invoices", json({ titleId, orderIds }));

export async function downloadInvoice(id: string): Promise<Blob> {
  const token = localStorage.getItem("zhbiao_token");
  const res = await fetch(`/api/billing/invoices/${id}/file`, { headers: token ? { Authorization: `Bearer ${token}` } : undefined });
  if (!res.ok) throw new Error(`下载失败（${res.status}）`);
  return res.blob();
}

// ---------------------------------------------------------------------------
// 协作与通知
// ---------------------------------------------------------------------------

export interface NotificationItem {
  id: string;
  kind: string;
  title: string;
  body: string;
  link: string;
  read: boolean;
  createdAt: string;
}

export const listNotifications = (unread = false) =>
  request<{ unread: number; items: NotificationItem[] }>(`/api/collab/notifications?limit=30${unread ? "&unread=true" : ""}`);
export const markNotificationsRead = (ids: string[] | "all") =>
  request<{ updated: number }>("/api/collab/notifications/read", json(ids === "all" ? { all: true } : { ids }));

export interface ChapterAssignment {
  chapterId: string;
  assigneeId: string | null;
  assigneeName: string;
  reviewerId: string | null;
  reviewerName: string;
  status: "待撰写" | "撰写中" | "待审核" | "已完成";
  version: number;
  lockedBy: string | null;
  lockedByName: string;
  updatedAt: string;
}

export const listAssignments = (draftId: string) => request<ChapterAssignment[]>(`/api/collab/drafts/${draftId}/assignments`);
export const saveAssignment = (
  draftId: string,
  chapterId: string,
  p: { assigneeId?: string | null; reviewerId?: string | null; status?: string; version?: number },
) => request<ChapterAssignment>(`/api/collab/drafts/${draftId}/assignments/${encodeURIComponent(chapterId)}`, json(p, "PUT"));
export const lockChapter = (draftId: string, chapterId: string) =>
  request<ChapterAssignment>(`/api/collab/drafts/${draftId}/assignments/${encodeURIComponent(chapterId)}/lock`, { method: "POST" });
export const unlockChapter = (draftId: string, chapterId: string) =>
  request<{ ok: boolean }>(`/api/collab/drafts/${draftId}/assignments/${encodeURIComponent(chapterId)}/lock`, { method: "DELETE" });

export interface ProjectComment {
  id: string;
  projectId: string;
  draftId: string | null;
  chapterId: string | null;
  userId: string;
  userName: string;
  content: string;
  mentions: { id: string; name: string }[];
  resolved: boolean;
  createdAt: string;
}

export const listComments = (projectId: string, q: { draftId?: string; chapterId?: string } = {}) => {
  const params = new URLSearchParams();
  if (q.draftId) params.set("draftId", q.draftId);
  if (q.chapterId) params.set("chapterId", q.chapterId);
  const qs = params.toString();
  return request<ProjectComment[]>(`/api/collab/projects/${projectId}/comments${qs ? `?${qs}` : ""}`);
};
export const addComment = (projectId: string, p: { content: string; draftId?: string; chapterId?: string; mentions?: string[] }) =>
  request<ProjectComment>(`/api/collab/projects/${projectId}/comments`, json(p));
export const resolveComment = (id: string, resolved: boolean) => request<ProjectComment>(`/api/collab/comments/${id}`, json({ resolved }, "PATCH"));
export const deleteComment = (id: string) => request<{ ok: boolean }>(`/api/collab/comments/${id}`, { method: "DELETE" });

export interface ProjectActivityItem {
  id: string;
  userName: string;
  action: string;
  detail: string;
  createdAt: string;
}

export const listActivities = (projectId: string) => request<ProjectActivityItem[]>(`/api/collab/projects/${projectId}/activities`);

// ---------------------------------------------------------------------------
// 展示工具
// ---------------------------------------------------------------------------

export const yuan = (cents: number) => `¥${(cents / 100).toLocaleString("zh-CN", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;

export function formatBytes(bytes: number | null | undefined): string {
  if (bytes == null) return "—";
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  if (bytes < 1024 * 1024 * 1024) return `${(bytes / 1024 / 1024).toFixed(1)} MB`;
  return `${(bytes / 1024 / 1024 / 1024).toFixed(2)} GB`;
}

export function saveBlob(blob: Blob, filename: string) {
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  a.click();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}
