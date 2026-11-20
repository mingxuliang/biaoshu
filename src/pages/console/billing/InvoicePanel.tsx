import { useCallback, useEffect, useState } from "react";
import Modal from "../components/Modal";
import {
  applyInvoice,
  createInvoiceTitle,
  deleteInvoiceTitle,
  downloadInvoice,
  listInvoices,
  listInvoiceTitles,
  listOrders,
  saveBlob,
  updateInvoiceTitle,
  yuan,
  type Invoice,
  type InvoiceTitle,
  type InvoiceTitleInput,
  type Order,
} from "@/lib/saasApi";
import { btnGhost, btnPrimary, Card, Empty, inputCls, StatusTag } from "./ui";

const EMPTY_TITLE: InvoiceTitleInput = { kind: "普票", title: "", taxNo: "", address: "", phone: "", bankName: "", bankAccount: "", email: "", isDefault: false };

interface Props {
  canManage: boolean;
  personal?: boolean;
  notify: (msg: string, type?: "success" | "error") => void;
}

export default function InvoicePanel({ canManage, personal = false, notify }: Props) {
  const [titles, setTitles] = useState<InvoiceTitle[]>([]);
  const [invoices, setInvoices] = useState<Invoice[]>([]);
  const [orders, setOrders] = useState<Order[]>([]);
  const [editing, setEditing] = useState<{ id: string | null; data: InvoiceTitleInput } | null>(null);
  const [applying, setApplying] = useState(false);
  const [picked, setPicked] = useState<string[]>([]);
  const [titleId, setTitleId] = useState("");
  const [busy, setBusy] = useState(false);

  const fail = useCallback((e: unknown) => notify(e instanceof Error ? e.message : "操作失败", "error"), [notify]);

  const load = useCallback(() => {
    Promise.all([listInvoiceTitles(), listInvoices(), listOrders(1)])
      .then(([t, i, o]) => {
        setTitles(t);
        setInvoices(i);
        setOrders(o.items);
      })
      .catch(fail);
  }, [fail]);

  useEffect(load, [load]);

  const invoiceable = orders.filter((o) => o.status === "已支付" && o.invoicedCents < o.amountCents);
  const pickedTotal = invoiceable.filter((o) => picked.includes(o.id)).reduce((s, o) => s + o.amountCents, 0);

  const saveTitle = async () => {
    if (!editing) return;
    setBusy(true);
    try {
      if (editing.id) await updateInvoiceTitle(editing.id, editing.data);
      else await createInvoiceTitle(editing.data);
      setEditing(null);
      notify("发票抬头已保存");
      load();
    } catch (e) {
      fail(e);
    } finally {
      setBusy(false);
    }
  };

  const submitApply = async () => {
    setBusy(true);
    try {
      await applyInvoice(titleId, picked);
      setApplying(false);
      setPicked([]);
      notify("开票申请已提交，财务审核后开具数电发票");
      load();
    } catch (e) {
      fail(e);
    } finally {
      setBusy(false);
    }
  };

  const openApply = () => {
    setTitleId(titles.find((t) => t.isDefault)?.id || titles[0]?.id || "");
    setPicked([]);
    setApplying(true);
  };

  const field = (key: keyof InvoiceTitleInput, label: string, required = false) =>
    editing && (
      <label className="block">
        <span className="mb-1 block text-xs text-foreground-500">
          {label}
          {required && <span className="text-red-500"> *</span>}
        </span>
        <input className={inputCls} value={String(editing.data[key] ?? "")} onChange={(e) => setEditing({ ...editing, data: { ...editing.data, [key]: e.target.value } })} />
      </label>
    );
  const special = editing?.data.kind === "专票";

  return (
    <div className="space-y-4">
      <Card
        title="开票记录"
        extra={
          canManage && (
            <button type="button" className={btnPrimary} onClick={openApply} disabled={!titles.length}>
              申请开票
            </button>
          )
        }
      >
        {!titles.length && canManage && <p className="mb-3 text-xs text-amber-700">请先在下方添加发票抬头。</p>}
        {invoices.length ? (
          <table className="w-full text-sm">
            <thead className="text-left text-xs text-foreground-500">
              <tr>
                <th className="py-2 font-normal">申请时间</th>
                <th className="py-2 font-normal">抬头</th>
                <th className="py-2 font-normal">类型</th>
                <th className="py-2 text-right font-normal">金额</th>
                <th className="py-2 font-normal">状态</th>
                <th className="py-2 font-normal">发票号码</th>
                <th className="py-2"></th>
              </tr>
            </thead>
            <tbody>
              {invoices.map((inv) => (
                <tr key={inv.id} className="border-t border-background-300">
                  <td className="py-2 text-foreground-600">{inv.createdAt.slice(0, 16).replace("T", " ")}</td>
                  <td className="py-2 text-foreground-800">{inv.title.title}</td>
                  <td className="py-2 text-foreground-600">{inv.kind}</td>
                  <td className="py-2 text-right text-foreground-900">{yuan(inv.amountCents)}</td>
                  <td className="py-2">
                    <StatusTag status={inv.status} />
                    {inv.rejectReason && <div className="mt-0.5 text-[11px] text-red-600">{inv.rejectReason}</div>}
                  </td>
                  <td className="py-2 font-mono text-xs text-foreground-700">{inv.invoiceNo || "—"}</td>
                  <td className="py-2 text-right">
                    {inv.hasFile && (
                      <button
                        type="button"
                        className="cursor-pointer text-xs text-primary-600 hover:underline"
                        onClick={() => downloadInvoice(inv.id).then((b) => saveBlob(b, inv.fileName || `发票-${inv.invoiceNo}.pdf`)).catch(fail)}
                      >
                        下载
                      </button>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        ) : (
          <Empty text="暂无开票记录" />
        )}
      </Card>

      <Card
        title="发票抬头"
        extra={
          canManage && (
            <button type="button" className={btnGhost} onClick={() => setEditing({ id: null, data: { ...EMPTY_TITLE, isDefault: !titles.length } })}>
              <i className="ri-add-line"></i>添加抬头
            </button>
          )
        }
      >
        {titles.length ? (
          <div className="grid gap-3 sm:grid-cols-2">
            {titles.map((t) => (
              <div key={t.id} className="rounded-lg border border-background-300 bg-background-50 p-3 text-sm">
                <div className="flex items-center gap-2">
                  <span className="font-medium text-foreground-900">{t.title}</span>
                  <span className="rounded bg-background-200 px-1.5 text-[11px] text-foreground-600">{t.kind}</span>
                  {t.isDefault && <span className="rounded bg-primary-100 px-1.5 text-[11px] text-primary-700">默认</span>}
                </div>
                <div className="mt-1 text-xs text-foreground-500">税号 {t.taxNo || "—"}</div>
                {canManage && (
                  <div className="mt-2 flex gap-3 text-xs">
                    <button type="button" className="cursor-pointer text-primary-600 hover:underline" onClick={() => setEditing({ id: t.id, data: { ...t } })}>
                      编辑
                    </button>
                    <button
                      type="button"
                      className="cursor-pointer text-red-600 hover:underline"
                      onClick={() => window.confirm(`删除抬头「${t.title}」？`) && deleteInvoiceTitle(t.id).then(load).catch(fail)}
                    >
                      删除
                    </button>
                  </div>
                )}
              </div>
            ))}
          </div>
        ) : (
          <Empty text="暂无发票抬头" />
        )}
      </Card>

      {editing && (
        <Modal open onClose={() => setEditing(null)} title={editing.id ? "编辑发票抬头" : "添加发票抬头"}>
          <div className="space-y-3">
            {personal ? (
              <p className="rounded-lg bg-background-50 px-3 py-2 text-xs text-foreground-600">个人账号开具增值税普通发票（个人抬头），升级为企业后可开专票。</p>
            ) : (
              <div className="flex gap-4 text-sm">
                {(["普票", "专票"] as const).map((k) => (
                  <label key={k} className="flex cursor-pointer items-center gap-1.5">
                    <input type="radio" checked={editing.data.kind === k} onChange={() => setEditing({ ...editing, data: { ...editing.data, kind: k } })} />
                    {k === "普票" ? "增值税普通发票" : "增值税专用发票"}
                  </label>
                ))}
              </div>
            )}
            {field("title", personal ? "发票抬头（个人姓名）" : "发票抬头（单位全称）", true)}
            {field("taxNo", personal ? "纳税人识别号（个人可不填）" : "纳税人识别号", !personal)}
            {!personal && (
              <>
                {field("address", "注册地址", special)}
                {field("phone", "注册电话", special)}
                {field("bankName", "开户银行", special)}
                {field("bankAccount", "银行账号", special)}
              </>
            )}
            {field("email", "接收邮箱")}
            <label className="flex cursor-pointer items-center gap-2 text-sm text-foreground-700">
              <input type="checkbox" checked={editing.data.isDefault} onChange={(e) => setEditing({ ...editing, data: { ...editing.data, isDefault: e.target.checked } })} />
              设为默认抬头
            </label>
            <div className="flex justify-end gap-2 pt-2">
              <button type="button" className={btnGhost} onClick={() => setEditing(null)}>
                取消
              </button>
              <button type="button" className={btnPrimary} disabled={busy || !editing.data.title.trim()} onClick={saveTitle}>
                保存
              </button>
            </div>
          </div>
        </Modal>
      )}

      {applying && (
        <Modal open onClose={() => setApplying(false)} title="申请开票" subtitle="可合并多笔已支付订单开具一张发票" width="max-w-xl">
          <div className="space-y-3 text-sm">
            <label className="block">
              <span className="mb-1 block text-xs text-foreground-500">发票抬头</span>
              <select className={inputCls} value={titleId} onChange={(e) => setTitleId(e.target.value)}>
                {titles.map((t) => (
                  <option key={t.id} value={t.id}>
                    {t.title}（{t.kind}）
                  </option>
                ))}
              </select>
            </label>
            <div>
              <div className="mb-1 text-xs text-foreground-500">选择订单</div>
              {invoiceable.length ? (
                <div className="max-h-64 space-y-1 overflow-y-auto">
                  {invoiceable.map((o) => (
                    <label key={o.id} className="flex cursor-pointer items-center gap-2 rounded-lg border border-background-300 px-3 py-2">
                      <input
                        type="checkbox"
                        checked={picked.includes(o.id)}
                        onChange={(e) => setPicked(e.target.checked ? [...picked, o.id] : picked.filter((x) => x !== o.id))}
                      />
                      <span className="flex-1 text-foreground-800">{o.subject}</span>
                      <span className="text-xs text-foreground-500">{o.paidAt.slice(0, 10)}</span>
                      <span className="w-24 text-right text-foreground-900">{yuan(o.amountCents)}</span>
                    </label>
                  ))}
                </div>
              ) : (
                <Empty text="没有可开票的已支付订单" />
              )}
            </div>
            <div className="flex items-center justify-between border-t border-background-300 pt-3">
              <span className="text-foreground-600">
                开票金额 <b className="text-foreground-950">{yuan(pickedTotal)}</b>
              </span>
              <button type="button" className={btnPrimary} disabled={busy || !titleId || !picked.length} onClick={submitApply}>
                提交申请
              </button>
            </div>
          </div>
        </Modal>
      )}
    </div>
  );
}
