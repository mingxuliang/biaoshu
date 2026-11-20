// 平台管理后台接口。令牌与企业端完全分开（不同的 localStorage 键、不同的 JWT aud），
// 企业用户的令牌调不了 /api/admin，后台令牌也进不了企业端。

import type { LlmPreset, LlmProvider, LlmProviderKind, LlmTestResult, WriterLlmModel } from "@/lib/api";
import type { Invoice, LedgerRow, Order, Plan } from "@/lib/saasApi";

export const ADMIN_TOKEN_KEY = "zhbiao_admin_token";
export const ADMIN_UNAUTHORIZED = "zhbiao:admin-unauthorized";

export class AdminApiError extends Error {
  status: number;
  constructor(message: string, status: number) {
    super(message);
    this.status = status;
  }
}

async function parseError(res: Response): Promise<AdminApiError> {
  let message = `请求失败（${res.status}）`;
  try {
    const body = await res.json();
    if (typeof body?.detail === "string") message = body.detail;
    else if (Array.isArray(body?.detail) && body.detail[0]?.msg) message = `参数有误：${body.detail[0].msg}`;
  } catch {
    // 非 JSON 响应沿用默认文案
  }
  return new AdminApiError(message, res.status);
}

type FetchInit = Parameters<typeof fetch>[1];

function authHeaders(init?: ConstructorParameters<typeof Headers>[0]): Headers {
  const headers = new Headers(init);
  const token = localStorage.getItem(ADMIN_TOKEN_KEY);
  if (token && !headers.has("Authorization")) headers.set("Authorization", `Bearer ${token}`);
  return headers;
}

export async function adminRequest<T>(path: string, init?: FetchInit): Promise<T> {
  const res = await fetch(path, { ...init, headers: authHeaders(init?.headers) });
  if (!res.ok) {
    if (res.status === 401 && !path.endsWith("/auth/login")) window.dispatchEvent(new Event(ADMIN_UNAUTHORIZED));
    throw await parseError(res);
  }
  if (res.status === 204) return undefined as T;
  const text = await res.text();
  return (text ? JSON.parse(text) : undefined) as T;
}

export async function adminBlob(path: string): Promise<Blob> {
  const res = await fetch(path, { headers: authHeaders() });
  if (!res.ok) throw await parseError(res);
  return res.blob();
}

const body = (data: unknown, method = "POST"): FetchInit => ({
  method,
  headers: { "Content-Type": "application/json" },
  body: JSON.stringify(data),
});

const qs = (params: Record<string, string | number | undefined>) => {
  const p = new URLSearchParams();
  for (const [k, v] of Object.entries(params)) if (v !== undefined && v !== "") p.set(k, String(v));
  const s = p.toString();
  return s ? `?${s}` : "";
};

export interface Paged<T> {
  total: number;
  items: T[];
}

// ---------------------------------------------------------------------------
// 登录与后台账号
// ---------------------------------------------------------------------------

export type AdminRole = "超级管理员" | "运营" | "财务" | "只读";
export const ADMIN_ROLES: AdminRole[] = ["超级管理员", "运营", "财务", "只读"];

export interface AdminUser {
  id: string;
  email: string;
  name: string;
  role: AdminRole;
  disabled: boolean;
  totpEnabled: boolean;
  lastLoginAt: string;
}

export const adminLogin = (email: string, password: string, totp: string) =>
  adminRequest<{ token: string; admin: AdminUser }>("/api/admin/auth/login", body({ email, password, totp }));
export const adminMe = () => adminRequest<AdminUser>("/api/admin/auth/me");
export const changeAdminPassword = (oldPassword: string, newPassword: string) =>
  adminRequest<{ token: string }>("/api/admin/auth/password", body({ oldPassword, newPassword }));
export const totpSetup = () => adminRequest<{ secret: string; uri: string }>("/api/admin/auth/totp/setup", { method: "POST" });
export const totpEnable = (secret: string, code: string) => adminRequest<AdminUser>("/api/admin/auth/totp/enable", body({ secret, code }));
export const totpDisable = (code: string) => adminRequest<AdminUser>("/api/admin/auth/totp/disable", body({ code }));

export const listAdmins = () => adminRequest<AdminUser[]>("/api/admin/admins");
export const createAdmin = (p: { email: string; name: string; role: AdminRole }) =>
  adminRequest<AdminUser & { initialPassword: string }>("/api/admin/admins", body(p));
export const patchAdmin = (id: string, p: { name?: string; role?: AdminRole; disabled?: boolean; resetPassword?: boolean; resetTotp?: boolean }) =>
  adminRequest<AdminUser & { initialPassword?: string }>(`/api/admin/admins/${id}`, body(p, "PATCH"));

// ---------------------------------------------------------------------------
// 概览与企业
// ---------------------------------------------------------------------------

export interface Dashboard {
  tenants: { total: number; byStatus: Record<string, number> };
  accounts: number;
  revenueMonthCents: number;
  creditsConsumedToday: number;
  tokensToday: number;
  pending: { invoices: number; transfers: number; verifications: number };
  trend: { date: string; credits: number; revenueCents: number }[];
}

export const getDashboard = () => adminRequest<Dashboard>("/api/admin/dashboard");

export interface AdminTenant {
  id: string;
  name: string;
  kind: "企业" | "个人";
  status: string;
  planCode: string;
  seats: number;
  seatsUsed: number | null;
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
  wallet: { balance: number; held: number; available?: number; totalRecharged?: number; totalConsumed?: number; expiringIn30Days?: number } | null;
}

export interface AdminTenantDetail extends AdminTenant {
  subscriptions: { planCode: string; startsAt: string; endsAt: string; status: string; orderId: string }[];
  storage: { bucket: string; objects?: number; bytes?: number; error?: string };
  supportGrant: { expiresAt: string; grantedBy: string } | null;
}

export const listTenants = (p: { q?: string; status?: string; verify?: string; kind?: string; page?: number }) =>
  adminRequest<Paged<AdminTenant>>(`/api/admin/tenants${qs({ ...p, size: 20 })}`);
export const createTenant = (p: {
  kind: "企业" | "个人";
  name: string;
  adminName: string;
  adminLogin: string;
  planCode: string;
  contactPhone: string;
  contactEmail: string;
}) =>
  adminRequest<{ id: string; adminLogin: string; initialPassword: string }>("/api/admin/tenants", body(p));
export const getTenant = (id: string) => adminRequest<AdminTenantDetail>(`/api/admin/tenants/${id}`);
export const patchTenant = (
  id: string,
  p: { name?: string; status?: string; planCode?: string; seats?: number; storageQuotaMb?: number; expiresAt?: string; features?: Record<string, boolean>; lowBalanceThreshold?: number },
) => adminRequest<AdminTenant>(`/api/admin/tenants/${id}`, body(p, "PATCH"));
export const reviewVerify = (id: string, approve: boolean, note: string) =>
  adminRequest<AdminTenant>(`/api/admin/tenants/${id}/verify`, body({ approve, note }));
export const tenantLicense = (id: string) => adminBlob(`/api/admin/tenants/${id}/license`);
export const deregisterTenant = (id: string, confirmName: string, dropData: boolean) =>
  adminRequest<Record<string, unknown>>(`/api/admin/tenants/${id}/deregister`, body({ confirmName, dropData }));

export interface TenantOrg {
  departments: { id: string; name: string; parentId: string | null; leaderId: string | null }[];
  users: {
    id: string;
    name: string;
    account: string;
    phone: string;
    role: string;
    customRole: string;
    departmentId: string | null;
    departmentName: string;
    disabled: boolean;
    monthlyCreditLimit: number | null;
    monthSpent: number;
    lastLoginAt: string;
    createdAt: string;
  }[];
}

export const getTenantOrg = (id: string) => adminRequest<TenantOrg>(`/api/admin/tenants/${id}/org`);
export const patchTenantUser = (tid: string, uid: string, p: { disabled?: boolean; role?: string; monthlyCreditLimit?: number; resetPassword?: boolean }) =>
  adminRequest<{ ok: boolean; initialPassword?: string }>(`/api/admin/tenants/${tid}/users/${uid}`, body(p, "PATCH"));

export interface TenantLibraries {
  stats: {
    knowledge: Record<string, { count: number; bytes: number }>;
    qualifications: number;
    productLibraries: number;
    productFeatures: number;
    projects: number;
    chatMessages: number;
  };
  supportGrant: { expiresAt: string; grantedBy: string } | null;
  detail: {
    knowledge: { id: string; title: string; scope: string; type: string; sizeBytes: number; createdAt: string }[];
    qualifications: { id: string; name: string; category: string; validUntil: string; reviewStatus: string }[];
    productLibraries: { id: string; name: string; category: string }[];
  } | null;
}

export const getTenantLibraries = (id: string) => adminRequest<TenantLibraries>(`/api/admin/tenants/${id}/libraries`);
export const getTenantStorage = (id: string) =>
  adminRequest<{ bucket: string; quotaMb: number; objects: number; bytes: number; prefixes: { prefix: string; objects: number; bytes: number }[] }>(
    `/api/admin/tenants/${id}/storage`,
  );
export const adjustCredits = (id: string, delta: number, note: string, expiresAt?: string) =>
  adminRequest<Record<string, number>>(`/api/admin/tenants/${id}/credits`, body({ delta, note, expiresAt: expiresAt || null }));
export const getUserCredits = (id: string) =>
  adminRequest<
    {
      userId: string;
      name: string;
      account: string;
      role: string;
      monthSpent: number;
      monthTokens: number;
      totalSpent: number;
      lastUsedAt: string;
      monthlyCreditLimit: number | null;
      disabled: boolean;
    }[]
  >(
    `/api/admin/tenants/${id}/user-credits`,
  );

// ---------------------------------------------------------------------------
// 积分、计费与套餐
// ---------------------------------------------------------------------------

export interface WalletRow {
  tenantId: string;
  tenantName: string;
  kind: "企业" | "个人";
  status: string;
  planCode: string;
  planName: string;
  expiresAt: string;
  seats: number;
  members: number | null;
  balance: number;
  held: number;
  available: number;
  lowBalance: boolean;
  totalRecharged: number;
  totalConsumed: number;
  paidCents: number;
  refundedCents: number;
  periodCredits: number;
  promptTokens: number;
  completionTokens: number;
  calls: number;
  activeUsers: number;
  lastUsedAt: string;
}

export interface WalletSummary {
  tenants: number;
  activeTenants: number;
  activeUsers: number;
  paidCents: number;
  refundedCents: number;
  periodCredits: number;
  promptTokens: number;
  completionTokens: number;
  available: number;
}

export type WalletSort = "spent" | "tokens" | "balance" | "paid" | "lastUsed";

export interface FeeQuery {
  q?: string;
  kind?: string;
  days?: number;
  sort?: string;
  page?: number;
}

export const listWallets = (p: FeeQuery) =>
  adminRequest<Paged<WalletRow> & { days: number; summary: WalletSummary }>(`/api/admin/wallets${qs({ ...p, size: 20 })}`);
export const exportWallets = (p: FeeQuery) => adminBlob(`/api/admin/wallets.csv${qs({ ...p, page: undefined })}`);

export interface PersonFeeRow {
  tenantId: string;
  tenantName: string;
  tenantKind: "企业" | "个人";
  userId: string;
  name: string;
  account: string;
  role: string;
  departmentName: string;
  monthlyCreditLimit: number | null;
  disabled: boolean;
  lastLoginAt: string;
  periodCredits: number;
  monthSpent: number;
  totalSpent: number;
  promptTokens: number;
  completionTokens: number;
  calls: number;
  lastUsedAt: string;
}

export interface PersonFeeSummary {
  users: number;
  activeUsers: number;
  periodCredits: number;
  promptTokens: number;
  completionTokens: number;
}

export type PersonSort = "spent" | "month" | "tokens" | "total" | "lastUsed";

export const listPeopleFees = (p: FeeQuery & { tenantId?: string; refresh?: boolean }) =>
  adminRequest<Paged<PersonFeeRow> & { days: number; summary: PersonFeeSummary }>(
    `/api/admin/users${qs({ ...p, refresh: p.refresh ? "true" : undefined, size: 20 })}`,
  );
export const exportPeopleFees = (p: FeeQuery & { tenantId?: string }) => adminBlob(`/api/admin/users.csv${qs({ ...p, page: undefined })}`);

export interface PersonUsage {
  days: number;
  byFeature: { feature: string; name: string; credits: number; promptTokens: number; completionTokens: number; calls: number }[];
  byModel: { model: string; promptTokens: number; completionTokens: number; calls: number; credits: number }[];
  trend: { date: string; credits: number; tokens: number }[];
}

export const getPersonUsage = (tenantId: string, userId: string, days: number) =>
  adminRequest<PersonUsage>(`/api/admin/users/${tenantId}/${userId}/usage${qs({ days })}`);
export const listPlatformLedger = (p: { tenantId?: string; kind?: string; page?: number }) =>
  adminRequest<Paged<LedgerRow & { tenantId: string; tenantName: string }>>(`/api/admin/ledger${qs({ ...p, size: 50 })}`);

export interface UsageGroup {
  key: string;
  name?: string;
  promptTokens: number;
  completionTokens: number;
  calls: number;
  credits: number;
}

export const getPlatformUsage = (days: number, tenantId = "") =>
  adminRequest<{ days: number; byTenant: UsageGroup[]; byModel: UsageGroup[]; byFeature: UsageGroup[] }>(`/api/admin/usage${qs({ days, tenantId })}`);

export interface AdminPriceRule {
  feature: string;
  name: string;
  mode: "per_1k_tokens" | "per_call" | "free";
  unitPrice: number;
  estimate: number;
  enabled: boolean;
}

export const listAdminPrices = () => adminRequest<AdminPriceRule[]>("/api/admin/prices");
export const updatePrice = (feature: string, p: Partial<Omit<AdminPriceRule, "feature">>) =>
  adminRequest<AdminPriceRule>(`/api/admin/prices/${encodeURIComponent(feature)}`, body(p, "PUT"));

export interface ModelRatio {
  key: string;
  name: string;
  apiModel: string;
  task: string;
  ratio: number;
  note: string;
}

export const listModelRatios = () => adminRequest<ModelRatio[]>("/api/admin/model-ratios");
export const setModelRatio = (key: string, ratio: number, note: string) =>
  adminRequest<{ key: string; ratio: number; note: string }>(`/api/admin/model-ratios/${encodeURIComponent(key)}`, body({ ratio, note }, "PUT"));

export type AdminPlan = Plan & { enabled: boolean; sortOrder: number };
export type PlanInput = Omit<AdminPlan, "code">;

export const listAdminPlans = () => adminRequest<AdminPlan[]>("/api/admin/plans");
export const savePlan = (code: string, p: PlanInput) => adminRequest<Plan>(`/api/admin/plans/${encodeURIComponent(code)}`, body(p, "PUT"));

// ---------------------------------------------------------------------------
// 订单、对公转账、对账、发票
// ---------------------------------------------------------------------------

export type AdminOrder = Order & { tenantId: string; tenantName: string };

export const listAdminOrders = (p: { status?: string; channel?: string; tenantId?: string; q?: string; page?: number }) =>
  adminRequest<Paged<AdminOrder>>(`/api/admin/orders${qs({ ...p, size: 20 })}`);
export const syncAdminOrder = (id: string) => adminRequest<Order>(`/api/admin/orders/${id}/sync`, { method: "POST" });
export const closeAdminOrder = (id: string, reason: string) => adminRequest<Order>(`/api/admin/orders/${id}/close`, body({ reason }));
export const markOrderPaid = (id: string, reason: string) => adminRequest<Order>(`/api/admin/orders/${id}/mark-paid`, body({ reason }));
export const refundOrder = (id: string, amountCents: number, reason: string) =>
  adminRequest<Order>(`/api/admin/orders/${id}/refund`, body({ amountCents, reason }));

export interface Transfer {
  id: string;
  orderId: string;
  tenantId: string;
  tenantName: string;
  payerName: string;
  payerAccount: string;
  amountCents: number;
  orderAmountCents: number | null;
  transferCode: string;
  bankSerial: string;
  hasReceipt: boolean;
  status: string;
  note: string;
  operator: string;
  confirmedAt: string;
  createdAt: string;
}

export const listTransfers = (status: string) => adminRequest<Transfer[]>(`/api/admin/transfers${qs({ status })}`);
export const transferReceipt = (id: string) => adminBlob(`/api/admin/transfers/${id}/receipt`);
export const confirmTransfer = (id: string, bankSerial: string, amountCents: number) =>
  adminRequest<Transfer>(`/api/admin/transfers/${id}/confirm`, body({ bankSerial, amountCents }));
export const rejectTransfer = (id: string, reason: string) => adminRequest<Transfer>(`/api/admin/transfers/${id}/reject`, body({ reason }));

export const getReconcile = (date: string) =>
  adminRequest<{
    date: string;
    summary: Record<string, { count: number; amountCents: number; refunded: number }>;
    orders: { id: string; channel: string; tradeNo: string; amountCents: number; status: string; paidAt: string }[];
  }>(`/api/admin/reconcile${qs({ date })}`);

export type AdminInvoice = Invoice & { tenantId: string; tenantName: string; operator: string };

export const listAdminInvoices = (p: { status?: string; tenantId?: string; page?: number }) =>
  adminRequest<Paged<AdminInvoice>>(`/api/admin/invoices${qs({ ...p, size: 20 })}`);
export const approveInvoice = (id: string) => adminRequest<Invoice>(`/api/admin/invoices/${id}/approve`, { method: "POST" });
export const rejectInvoice = (id: string, reason: string) => adminRequest<Invoice>(`/api/admin/invoices/${id}/reject`, body({ reason }));
export const redFlushInvoice = (id: string, reason: string) => adminRequest<Invoice>(`/api/admin/invoices/${id}/red-flush`, body({ reason }));
export function uploadInvoiceFile(id: string, invoiceNo: string, file: File) {
  const form = new FormData();
  form.append("invoiceNo", invoiceNo);
  form.append("file", file);
  return adminRequest<Invoice>(`/api/admin/invoices/${id}/upload`, { method: "POST", body: form });
}
export const invoiceFile = (id: string) => adminBlob(`/api/admin/invoices/${id}/file`);

// ---------------------------------------------------------------------------
// 系统环境、存储、公告、审计
// ---------------------------------------------------------------------------

export interface Probe {
  ok: boolean;
  latencyMs: number;
  detail: Record<string, unknown> | string;
}

export interface SystemEnv {
  app: Record<string, string | number | boolean>;
  database: Probe;
  redis: Probe;
  minio: Probe;
  celery: Probe;
  payments: { id: string; name: string; ready: boolean }[];
  checkedAt: string;
}

export const getSystemEnv = () => adminRequest<SystemEnv>("/api/admin/system/env");

export interface BucketRow {
  bucket: string;
  tenantId: string;
  tenantName: string;
  quotaMb: number | null;
  objects: number | null;
  bytes: number | null;
  createdAt: string;
  isDefault: boolean;
}

export const listBuckets = () => adminRequest<BucketRow[]>("/api/admin/storage/buckets");

export interface AdminAnnouncement {
  id: string;
  title: string;
  body: string;
  level: "info" | "warning";
  published: boolean;
  createdAt: string;
}

export type AnnouncementInput = Omit<AdminAnnouncement, "id" | "createdAt">;

export const listAdminAnnouncements = () => adminRequest<AdminAnnouncement[]>("/api/admin/announcements");
export const createAnnouncement = (p: AnnouncementInput) => adminRequest<AdminAnnouncement>("/api/admin/announcements", body(p));
export const updateAnnouncement = (id: string, p: AnnouncementInput) => adminRequest<AdminAnnouncement>(`/api/admin/announcements/${id}`, body(p, "PUT"));
export const deleteAnnouncement = (id: string) => adminRequest<{ ok: boolean }>(`/api/admin/announcements/${id}`, { method: "DELETE" });

export interface AuditRow {
  id: string;
  adminName: string;
  action: string;
  tenantId: string;
  target: string;
  detail: string;
  ip: string;
  createdAt: string;
}

export const listAudit = (p: { tenantId?: string; action?: string; page?: number }) =>
  adminRequest<Paged<AuditRow> & { actions: string[] }>(`/api/admin/audit${qs({ ...p, size: 50 })}`);

// ---------------------------------------------------------------------------
// 大模型接入（平台统一配置，企业端只读）
// ---------------------------------------------------------------------------

export const listLlmPresets = () => adminRequest<LlmPreset[]>("/api/admin/llm-presets");
export const listLlmProviders = () => adminRequest<LlmProvider[]>("/api/admin/llm-providers");
export const createLlmProvider = (p: { name: string; kind: LlmProviderKind; baseUrl?: string; apiKey?: string; note?: string }) =>
  adminRequest<LlmProvider>("/api/admin/llm-providers", body(p));
export const patchLlmProvider = (id: string, p: { name?: string; baseUrl?: string; apiKey?: string; enabled?: boolean; note?: string; clearKey?: boolean }) =>
  adminRequest<LlmProvider>(`/api/admin/llm-providers/${id}`, body(p, "PATCH"));
export const deleteLlmProvider = (id: string) => adminRequest<void>(`/api/admin/llm-providers/${id}`, { method: "DELETE" });
export const createLlmModel = (
  providerId: string,
  p: { name: string; apiModel: string; thinking?: boolean; enabled?: boolean; isDefault?: boolean; ctx?: string; speed?: string },
) => adminRequest<WriterLlmModel>(`/api/admin/llm-providers/${providerId}/models`, body(p));
export const patchLlmModel = (
  id: string,
  p: { name?: string; apiModel?: string; thinking?: boolean; enabled?: boolean; isDefault?: boolean; ctx?: string; speed?: string },
) => adminRequest<WriterLlmModel>(`/api/admin/llm-models/${id}`, body(p, "PATCH"));
export const deleteLlmModel = (id: string) => adminRequest<void>(`/api/admin/llm-models/${id}`, { method: "DELETE" });
export const testLlmModel = (id: string) => adminRequest<LlmTestResult>(`/api/admin/llm-models/${id}/test`, { method: "POST" });

export interface StandardCatalogRow {
  id: string;
  code: string;
  name: string;
  specialty: string;
  status: string;
  clauseCount: number;
  note: string;
}

export const listStandards = () => adminRequest<StandardCatalogRow[]>("/api/admin/standards");

export async function uploadStandard(file: File): Promise<{ id: string; status: string }> {
  const body = new FormData();
  body.append("file", file);
  return adminRequest("/api/admin/standards/upload", { method: "POST", body });
}
