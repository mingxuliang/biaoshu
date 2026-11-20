import { useCallback, useEffect, useState } from "react";
import { Link } from "react-router-dom";
import PageHeader from "@/pages/console/components/PageHeader";
import Modal from "@/pages/console/components/Modal";
import { formatBytes } from "@/lib/saasApi";
import {
  createAnnouncement,
  deleteAnnouncement,
  getSystemEnv,
  listAdminAnnouncements,
  listAudit,
  listBuckets,
  updateAnnouncement,
  type AdminAnnouncement,
  type AnnouncementInput,
  type AuditRow,
  type BucketRow,
  type Probe,
  type SystemEnv,
} from "../api";
import { useCan } from "../auth";
import { btnGhost, btnPrimary, Card, dangerLink, Empty, inputCls, linkBtn, num, PaginationBar, tdCls, theadCls, thCls, trCls, useUi } from "../ui";

const APP_LABELS: Record<string, string> = {
  env: "运行环境",
  python: "Python",
  os: "操作系统",
  publicBaseUrl: "公网地址（支付回调）",
  tenantSignup: "企业自助开通",
  personalRegister: "个人注册",
  trialCredits: "试用赠送积分",
  trialDays: "试用天数",
  creditsPerYuan: "1 元兑换积分",
  mockPayment: "模拟支付",
  verifyCodeChannel: "验证码通道",
  adminIpAllowlist: "后台 IP 白名单",
};

function show(v: unknown): string {
  if (typeof v === "boolean") return v ? "开启" : "关闭";
  if (v === "" || v == null) return "—";
  return String(v);
}

function ProbeCard({ title, probe }: { title: string; probe: Probe }) {
  const detail = typeof probe.detail === "string" ? { 错误: probe.detail } : probe.detail;
  return (
    <div className={`rounded-xl border p-4 ${probe.ok ? "border-background-300 bg-background-100" : "border-red-200 bg-red-50"}`}>
      <div className="flex items-center justify-between">
        <span className="text-sm font-semibold text-foreground-900">{title}</span>
        <span className={`text-xs ${probe.ok ? "text-emerald-600" : "text-red-600"}`}>
          <i className={probe.ok ? "ri-checkbox-circle-fill" : "ri-close-circle-fill"}></i> {probe.ok ? `正常 · ${probe.latencyMs} ms` : "异常"}
        </span>
      </div>
      <dl className="mt-2 space-y-0.5 text-xs">
        {Object.entries(detail).map(([k, v]) => (
          <div key={k} className="flex justify-between gap-3">
            <dt className="text-foreground-500">{k}</dt>
            <dd className="break-all text-right text-foreground-800">{k === "sizeBytes" ? formatBytes(Number(v)) : Array.isArray(v) ? v.join(", ") || "无" : show(v)}</dd>
          </div>
        ))}
      </dl>
    </div>
  );
}

export function SystemPage() {
  const { fail } = useUi();
  const [env, setEnv] = useState<SystemEnv | null>(null);
  const [loading, setLoading] = useState(false);

  const load = useCallback(() => {
    setLoading(true);
    getSystemEnv()
      .then(setEnv)
      .catch(fail)
      .finally(() => setLoading(false));
  }, [fail]);
  useEffect(load, [load]);

  return (
    <div>
      <PageHeader
        title="系统环境"
        description="依赖服务连通性与关键配置。秘钥类配置不在此显示，请在服务器 .env 中修改后重启。"
        actions={
          <button type="button" className={btnGhost} disabled={loading} onClick={load}>
            <i className="ri-refresh-line"></i>
            {loading ? "检测中…" : "重新检测"}
          </button>
        }
      />
      {env ? (
        <div className="space-y-4">
          <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-4">
            <ProbeCard title="数据库" probe={env.database} />
            <ProbeCard title="Redis" probe={env.redis} />
            <ProbeCard title="对象存储 MinIO" probe={env.minio} />
            <ProbeCard title="Celery Worker" probe={env.celery} />
          </div>
          <div className="grid gap-4 lg:grid-cols-2">
            <Card title="应用配置">
              <dl className="space-y-1 text-sm">
                {Object.entries(env.app).map(([k, v]) => (
                  <div key={k} className="flex justify-between gap-3 border-b border-background-200 py-1">
                    <dt className="text-foreground-500">{APP_LABELS[k] || k}</dt>
                    <dd className={`break-all text-right ${k === "mockPayment" && v && env.app.env === "production" ? "text-red-600" : "text-foreground-900"}`}>{show(v)}</dd>
                  </div>
                ))}
              </dl>
            </Card>
            <Card title="支付通道">
              <div className="space-y-2">
                {env.payments.map((p) => (
                  <div key={p.id} className="flex items-center justify-between rounded-lg border border-background-300 px-3 py-2 text-sm">
                    <span>{p.name}</span>
                    <span className={p.ready ? "text-emerald-600" : "text-foreground-500"}>{p.ready ? "已就绪" : "未配置"}</span>
                  </div>
                ))}
              </div>
              <p className="mt-3 text-xs text-foreground-500">
                回调地址：{show(env.app.publicBaseUrl)}/api/pay/notify/alipay 与 /api/pay/notify/wechat，需在支付宝开放平台和微信商户平台中配置。
              </p>
            </Card>
          </div>
          <p className="text-xs text-foreground-500">检测时间（UTC）：{env.checkedAt}</p>
        </div>
      ) : (
        <Empty text="检测中…" />
      )}
    </div>
  );
}

export function StoragePage() {
  const { fail } = useUi();
  const [rows, setRows] = useState<BucketRow[] | null>(null);

  useEffect(() => {
    listBuckets().then(setRows).catch(fail);
  }, [fail]);

  const total = (rows || []).reduce((s, r) => s + (r.bytes || 0), 0);

  return (
    <div>
      <PageHeader title="对象存储" description={`每个企业一个独立 bucket，平台文件（发票、转账回单）单独存放。合计 ${formatBytes(total)}。`} />
      <Card>
        {rows ? (
          rows.length ? (
            <table className="w-full">
              <thead className={theadCls}>
                <tr>
                  <th className={thCls}>Bucket</th>
                  <th className={thCls}>所属</th>
                  <th className={`${thCls} text-right`}>对象数</th>
                  <th className={`${thCls} text-right`}>已用</th>
                  <th className={`${thCls} text-right`}>配额</th>
                  <th className={thCls}>使用率</th>
                </tr>
              </thead>
              <tbody>
                {rows.map((r) => {
                  const quota = r.quotaMb ? r.quotaMb * 1024 * 1024 : 0;
                  const pct = quota && r.bytes != null ? Math.min(100, (r.bytes / quota) * 100) : 0;
                  return (
                    <tr key={r.bucket} className={trCls}>
                      <td className={`${tdCls} font-mono text-xs`}>{r.bucket}</td>
                      <td className={tdCls}>
                        {r.tenantId && r.tenantId !== "platform" ? (
                          <Link to={`/tenants/${r.tenantId}?tab=storage`} className="text-primary-700 hover:underline">
                            {r.tenantName}
                          </Link>
                        ) : (
                          <span className={r.tenantId ? "" : "text-amber-700"}>{r.tenantName}</span>
                        )}
                        {r.isDefault && <span className="ml-1 text-[11px] text-foreground-500">（默认企业）</span>}
                      </td>
                      <td className={`${tdCls} text-right`}>{num(r.objects)}</td>
                      <td className={`${tdCls} text-right`}>{formatBytes(r.bytes)}</td>
                      <td className={`${tdCls} text-right`}>{quota ? formatBytes(quota) : "不限"}</td>
                      <td className={tdCls}>
                        {quota > 0 && (
                          <div className="h-1.5 w-28 rounded-full bg-background-200">
                            <div className={`h-full rounded-full ${pct >= 90 ? "bg-red-500" : "bg-primary-500"}`} style={{ width: `${Math.max(2, pct)}%` }} />
                          </div>
                        )}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          ) : (
            <Empty text="没有 bucket" />
          )
        ) : (
          <Empty text="统计中…（需要遍历全部对象，可能较慢）" />
        )}
      </Card>
    </div>
  );
}

const EMPTY_ANN: AnnouncementInput = { title: "", body: "", level: "info", published: false };

export function AnnouncementsPage() {
  const { notify, fail, ask } = useUi();
  const can = useCan();
  const [rows, setRows] = useState<AdminAnnouncement[]>([]);
  const [editing, setEditing] = useState<(AnnouncementInput & { id?: string }) | null>(null);

  const load = useCallback(() => {
    listAdminAnnouncements().then(setRows).catch(fail);
  }, [fail]);
  useEffect(load, [load]);

  const save = async () => {
    if (!editing) return;
    const { id, ...payload } = editing;
    try {
      if (id) await updateAnnouncement(id, payload);
      else await createAnnouncement(payload);
      setEditing(null);
      notify("公告已保存");
      load();
    } catch (e) {
      fail(e);
    }
  };

  const remove = async (a: AdminAnnouncement) => {
    if ((await ask({ title: "删除公告", message: `删除「${a.title}」？`, required: false, danger: true })) === null) return;
    deleteAnnouncement(a.id).then(load).catch(fail);
  };

  return (
    <div>
      <PageHeader
        title="公告"
        description="发布后所有企业用户在工作台可见，适合维护通知、价格调整等。"
        actions={
          can.ops && (
            <button type="button" className={btnPrimary} onClick={() => setEditing({ ...EMPTY_ANN })}>
              <i className="ri-add-line"></i>新建公告
            </button>
          )
        }
      />
      <Card>
        {rows.length ? (
          <div className="divide-y divide-background-300">
            {rows.map((a) => (
              <div key={a.id} className="flex items-start gap-3 py-3">
                <i className={`${a.level === "warning" ? "ri-alarm-warning-line text-amber-600" : "ri-information-line text-sky-600"} mt-0.5 text-lg`}></i>
                <div className="min-w-0 flex-1">
                  <div className="flex items-center gap-2">
                    <span className="font-medium text-foreground-900">{a.title}</span>
                    <span className={`rounded px-1.5 text-[11px] ${a.published ? "bg-emerald-50 text-emerald-700" : "bg-background-200 text-foreground-500"}`}>{a.published ? "已发布" : "草稿"}</span>
                    <span className="text-xs text-foreground-500">{a.createdAt}</span>
                  </div>
                  <p className="mt-1 whitespace-pre-line text-sm text-foreground-600">{a.body}</p>
                </div>
                {can.ops && (
                  <div className="space-x-2 whitespace-nowrap">
                    <button type="button" className={linkBtn} onClick={() => setEditing({ id: a.id, title: a.title, body: a.body, level: a.level, published: a.published })}>
                      编辑
                    </button>
                    <button type="button" className={dangerLink} onClick={() => remove(a)}>
                      删除
                    </button>
                  </div>
                )}
              </div>
            ))}
          </div>
        ) : (
          <Empty text="暂无公告" />
        )}
      </Card>

      {editing && (
        <Modal open onClose={() => setEditing(null)} title={editing.id ? "编辑公告" : "新建公告"}>
          <div className="space-y-3">
            <input className={inputCls} placeholder="标题" value={editing.title} onChange={(e) => setEditing({ ...editing, title: e.target.value })} />
            <textarea
              className={`${inputCls} h-36 py-2`}
              placeholder="正文"
              value={editing.body}
              onChange={(e) => setEditing({ ...editing, body: e.target.value })}
            />
            <div className="flex items-center gap-4 text-sm">
              <label className="flex items-center gap-1.5">
                <input type="radio" checked={editing.level === "info"} onChange={() => setEditing({ ...editing, level: "info" })} />
                普通
              </label>
              <label className="flex items-center gap-1.5">
                <input type="radio" checked={editing.level === "warning"} onChange={() => setEditing({ ...editing, level: "warning" })} />
                重要
              </label>
              <label className="ml-auto flex items-center gap-1.5">
                <input type="checkbox" checked={editing.published} onChange={(e) => setEditing({ ...editing, published: e.target.checked })} />
                立即发布
              </label>
            </div>
            <div className="flex justify-end gap-2">
              <button type="button" className={btnGhost} onClick={() => setEditing(null)}>
                取消
              </button>
              <button type="button" className={btnPrimary} disabled={!editing.title.trim()} onClick={save}>
                保存
              </button>
            </div>
          </div>
        </Modal>
      )}
    </div>
  );
}

export function AuditPage() {
  const { fail } = useUi();
  const [tenantId, setTenantId] = useState("");
  const [action, setAction] = useState("");
  const [page, setPage] = useState(1);
  const [data, setData] = useState<{ total: number; items: AuditRow[]; actions: string[] }>({ total: 0, items: [], actions: [] });

  useEffect(() => {
    const t = window.setTimeout(() => listAudit({ tenantId: tenantId.trim(), action, page }).then(setData).catch(fail), 250);
    return () => window.clearTimeout(t);
  }, [tenantId, action, page, fail]);

  return (
    <div>
      <PageHeader title="平台审计" description="后台的每一次登录、修改和查看企业资料都会记录在此，不可删除。" />
      <Card>
        <div className="mb-3 flex flex-wrap gap-3">
          <input className={`${inputCls} max-w-[220px]`} placeholder="企业编号" value={tenantId} onChange={(e) => { setTenantId(e.target.value); setPage(1); }} />
          <select className={`${inputCls} max-w-[200px]`} value={action} onChange={(e) => { setAction(e.target.value); setPage(1); }}>
            <option value="">全部操作</option>
            {data.actions.map((a) => (
              <option key={a}>{a}</option>
            ))}
          </select>
        </div>
        {data.items.length ? (
          <>
            <table className="w-full">
              <thead className={theadCls}>
                <tr>
                  <th className={thCls}>时间</th>
                  <th className={thCls}>操作人</th>
                  <th className={thCls}>操作</th>
                  <th className={thCls}>企业</th>
                  <th className={thCls}>对象</th>
                  <th className={thCls}>详情</th>
                  <th className={thCls}>IP</th>
                </tr>
              </thead>
              <tbody>
                {data.items.map((r) => (
                  <tr key={r.id} className={`${trCls} align-top`}>
                    <td className={`${tdCls} whitespace-nowrap text-xs`}>{r.createdAt}</td>
                    <td className={tdCls}>{r.adminName}</td>
                    <td className={tdCls}>{r.action}</td>
                    <td className={`${tdCls} font-mono text-xs`}>{r.tenantId ? <Link to={`/tenants/${r.tenantId}`} className="hover:underline">{r.tenantId}</Link> : "—"}</td>
                    <td className={`${tdCls} text-xs`}>{r.target || "—"}</td>
                    <td className={`${tdCls} max-w-md break-all text-xs text-foreground-600`}>{r.detail || "—"}</td>
                    <td className={`${tdCls} font-mono text-xs`}>{r.ip}</td>
                  </tr>
                ))}
              </tbody>
            </table>
            <PaginationBar page={page} pageSize={50} total={data.total} onPageChange={setPage} />
          </>
        ) : (
          <Empty text="暂无审计记录" />
        )}
      </Card>
    </div>
  );
}
