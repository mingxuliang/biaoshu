import { useCallback, useEffect, useState } from "react";
import PageHeader from "@/pages/console/components/PageHeader";
import Modal from "@/pages/console/components/Modal";
import { saveBlob, yuan } from "@/lib/saasApi";
import {
  approveInvoice,
  invoiceFile,
  listAdminInvoices,
  redFlushInvoice,
  rejectInvoice,
  uploadInvoiceFile,
  type AdminInvoice,
  type Paged,
} from "../api";
import { useCan } from "../auth";
import { btnGhost, btnPrimary, Card, dangerLink, Empty, Filter, inputCls, linkBtn, PaginationBar, StatusTag, tdCls, theadCls, thCls, trCls, useUi } from "../ui";

const STATUS = [
  { id: "待审核", label: "待审核" },
  { id: "开具中", label: "开具中" },
  { id: "已开具", label: "已开具" },
  { id: "已驳回", label: "已驳回" },
  { id: "已红冲", label: "已红冲" },
  { id: "", label: "全部" },
] as const;

const TITLE_FIELDS: [string, string][] = [
  ["title", "抬头"],
  ["taxNo", "税号"],
  ["address", "地址"],
  ["phone", "电话"],
  ["bankName", "开户行"],
  ["bankAccount", "账号"],
  ["email", "接收邮箱"],
];

export default function InvoicesPage() {
  const { notify, fail, ask } = useUi();
  const can = useCan();
  const [status, setStatus] = useState<(typeof STATUS)[number]["id"]>("待审核");
  const [page, setPage] = useState(1);
  const [data, setData] = useState<Paged<AdminInvoice>>({ total: 0, items: [] });
  const [uploading, setUploading] = useState<AdminInvoice | null>(null);
  const [upload, setUpload] = useState<{ invoiceNo: string; file: File | null }>({ invoiceNo: "", file: null });
  const [viewing, setViewing] = useState<AdminInvoice | null>(null);

  const load = useCallback(() => {
    listAdminInvoices({ status, page }).then(setData).catch(fail);
  }, [status, page, fail]);
  useEffect(load, [load]);

  const run = async (fn: () => Promise<unknown>, done: string) => {
    try {
      await fn();
      notify(done);
      load();
    } catch (e) {
      fail(e);
    }
  };

  const withReason = async (title: string, fn: (r: string) => Promise<unknown>, done: string) => {
    const reason = await ask({ title, placeholder: "原因（企业可见）", danger: true });
    if (reason) run(() => fn(reason), done);
  };

  const submitUpload = async () => {
    if (!uploading || !upload.file) return;
    await run(() => uploadInvoiceFile(uploading.id, upload.invoiceNo.trim(), upload.file as File), "发票已上传，企业可下载");
    setUploading(null);
  };

  return (
    <div>
      <PageHeader title="发票" description="企业申请后：审核 → 在税务数字账户开具数电票 → 上传 PDF/OFD/XML 并填写发票号码。红冲后对应订单金额可重新开票。" />
      <Card>
        <div className="mb-3">
          <Filter options={STATUS} value={status} onChange={(v) => { setStatus(v); setPage(1); }} />
        </div>
        {data.items.length ? (
          <>
            <table className="w-full">
              <thead className={theadCls}>
                <tr>
                  <th className={thCls}>申请时间</th>
                  <th className={thCls}>企业</th>
                  <th className={thCls}>抬头 / 税号</th>
                  <th className={thCls}>类型</th>
                  <th className={`${thCls} text-right`}>金额</th>
                  <th className={thCls}>状态</th>
                  <th className={thCls}>发票号码</th>
                  <th className={thCls}></th>
                </tr>
              </thead>
              <tbody>
                {data.items.map((inv) => (
                  <tr key={inv.id} className={trCls}>
                    <td className={`${tdCls} text-xs`}>{inv.createdAt}</td>
                    <td className={tdCls}>
                      {inv.tenantName}
                      <div className="text-[11px] text-foreground-500">{inv.applicantName}</div>
                    </td>
                    <td className={tdCls}>
                      <button type="button" className="cursor-pointer text-left hover:underline" onClick={() => setViewing(inv)}>
                        {inv.title.title}
                      </button>
                      <div className="font-mono text-[11px] text-foreground-500">{inv.title.taxNo}</div>
                    </td>
                    <td className={tdCls}>{inv.kind}</td>
                    <td className={`${tdCls} text-right font-medium`}>{yuan(inv.amountCents)}</td>
                    <td className={tdCls}>
                      <StatusTag status={inv.status} />
                      {inv.rejectReason && <div className="text-[11px] text-red-600">{inv.rejectReason}</div>}
                    </td>
                    <td className={`${tdCls} font-mono text-xs`}>{inv.invoiceNo || "—"}</td>
                    <td className={`${tdCls} space-x-2 whitespace-nowrap text-right`}>
                      {inv.hasFile && (
                        <button type="button" className={linkBtn} onClick={() => invoiceFile(inv.id).then((b) => saveBlob(b, inv.fileName || `${inv.invoiceNo}.pdf`)).catch(fail)}>
                          下载
                        </button>
                      )}
                      {can.finance && inv.status === "待审核" && (
                        <button type="button" className={linkBtn} onClick={() => run(() => approveInvoice(inv.id), "已通过，进入开具中")}>
                          通过
                        </button>
                      )}
                      {can.finance && (inv.status === "待审核" || inv.status === "开具中") && (
                        <button type="button" className={dangerLink} onClick={() => withReason("驳回开票申请", (r) => rejectInvoice(inv.id, r), "已驳回，订单可重新申请")}>
                          驳回
                        </button>
                      )}
                      {can.finance && (inv.status === "开具中" || inv.status === "待审核") && (
                        <button
                          type="button"
                          className={linkBtn}
                          onClick={() => {
                            setUpload({ invoiceNo: "", file: null });
                            setUploading(inv);
                          }}
                        >
                          上传发票
                        </button>
                      )}
                      {can.finance && inv.status === "已开具" && (
                        <button type="button" className={dangerLink} onClick={() => withReason("红冲发票", (r) => redFlushInvoice(inv.id, r), "已红冲")}>
                          红冲
                        </button>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
            <PaginationBar page={page} pageSize={20} total={data.total} onPageChange={setPage} />
          </>
        ) : (
          <Empty text="没有符合条件的开票申请" />
        )}
      </Card>

      {viewing && (
        <Modal open onClose={() => setViewing(null)} title="开票信息" subtitle={`${viewing.tenantName} · ${viewing.kind} · ${yuan(viewing.amountCents)}`}>
          <dl className="grid grid-cols-[80px_1fr] gap-y-1.5 text-sm">
            {TITLE_FIELDS.map(([k, label]) => (
              <div key={k} className="contents">
                <dt className="text-foreground-500">{label}</dt>
                <dd className="break-all text-foreground-900">{viewing.title[k] || "—"}</dd>
              </div>
            ))}
            <dt className="text-foreground-500">关联订单</dt>
            <dd className="font-mono text-xs">{viewing.orderIds.join("、")}</dd>
          </dl>
        </Modal>
      )}

      {uploading && (
        <Modal open onClose={() => setUploading(null)} title="上传数电发票" subtitle={`${uploading.title.title} · ${yuan(uploading.amountCents)}`}>
          <div className="space-y-3">
            <input className={inputCls} placeholder="发票号码（20 位数电票号码）" value={upload.invoiceNo} onChange={(e) => setUpload({ ...upload, invoiceNo: e.target.value.trim() })} />
            <label className="flex cursor-pointer items-center gap-2 rounded-lg border border-dashed border-background-300 px-3 py-3 text-sm text-foreground-600">
              <i className="ri-upload-2-line"></i>
              {upload.file ? upload.file.name : "选择 PDF / OFD / XML 文件"}
              <input type="file" accept=".pdf,.ofd,.xml" className="hidden" onChange={(e) => setUpload({ ...upload, file: e.target.files?.[0] || null })} />
            </label>
            <div className="flex justify-end gap-2">
              <button type="button" className={btnGhost} onClick={() => setUploading(null)}>
                取消
              </button>
              <button type="button" className={btnPrimary} disabled={!upload.invoiceNo || !upload.file} onClick={submitUpload}>
                上传并通知企业
              </button>
            </div>
          </div>
        </Modal>
      )}
    </div>
  );
}
