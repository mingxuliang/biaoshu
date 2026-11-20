import { createContext, useCallback, useContext, useRef, useState, type ReactNode } from "react";
import Modal from "@/pages/console/components/Modal";
import Toast from "@/pages/console/components/Toast";
import { btnGhost, btnPrimary, inputCls } from "@/pages/console/billing/ui";

export { btnGhost, btnPrimary, inputCls, Card, Empty, Stat, StatusTag, CHANNEL_LABEL } from "@/pages/console/billing/ui";
export { default as PaginationBar } from "@/pages/console/components/PaginationBar";

// 与企业工作台团队管理页的表格同一套样式
export const theadCls = "border-b border-background-300 bg-background-50";
export const thCls = "font-label px-3 py-3 text-left text-xs font-medium text-foreground-500";
export const tdCls = "px-3 py-3 text-sm text-foreground-800";
export const trCls = "border-b border-background-200 transition-colors last:border-0 hover:bg-primary-50/30";
export const tableWrap = "overflow-x-auto rounded-lg border border-background-300 bg-background-100";
export const linkBtn = "cursor-pointer text-xs text-primary-600 hover:underline disabled:cursor-not-allowed disabled:opacity-50";
export const dangerLink = "cursor-pointer text-xs text-red-600 hover:underline";

export const errMsg = (e: unknown) => (e instanceof Error ? e.message : "操作失败");

interface AskOptions {
  title: string;
  message?: string;
  placeholder?: string;
  initial?: string;
  required?: boolean;
  confirmText?: string;
  danger?: boolean;
  inputType?: "text" | "number";
}

interface UiContextValue {
  notify: (msg: string, type?: "success" | "error" | "info") => void;
  fail: (e: unknown) => void;
  /** 弹窗输入，取消返回 null。不需要输入框时把 placeholder 留空并设 required=false。 */
  ask: (opts: AskOptions) => Promise<string | null>;
}

const UiContext = createContext<UiContextValue | null>(null);

export function UiProvider({ children }: { children: ReactNode }) {
  const [toast, setToast] = useState<{ message: string; type: "success" | "error" | "info"; visible: boolean }>({ message: "", type: "success", visible: false });
  const [askState, setAskState] = useState<(AskOptions & { value: string }) | null>(null);
  const resolver = useRef<((v: string | null) => void) | null>(null);

  const notify = useCallback((message: string, type: "success" | "error" | "info" = "success") => {
    setToast({ message, type, visible: true });
    window.setTimeout(() => setToast((t) => ({ ...t, visible: false })), 3200);
  }, []);
  const fail = useCallback((e: unknown) => notify(errMsg(e), "error"), [notify]);

  const ask = useCallback((opts: AskOptions) => {
    setAskState({ required: true, ...opts, value: opts.initial ?? "" });
    return new Promise<string | null>((resolve) => {
      resolver.current = resolve;
    });
  }, []);

  const finish = (value: string | null) => {
    resolver.current?.(value);
    resolver.current = null;
    setAskState(null);
  };

  const showInput = !!askState && (askState.placeholder !== undefined || askState.initial !== undefined);

  return (
    <UiContext.Provider value={{ notify, fail, ask }}>
      {children}
      {askState && (
        <Modal open onClose={() => finish(null)} title={askState.title} width="max-w-md">
          <form
            className="space-y-3"
            onSubmit={(e) => {
              e.preventDefault();
              if (showInput && askState.required && !askState.value.trim()) return;
              finish(askState.value.trim());
            }}
          >
            {askState.message && <p className="whitespace-pre-line text-sm text-foreground-700">{askState.message}</p>}
            {showInput && (
              <input
                autoFocus
                type={askState.inputType || "text"}
                className={inputCls}
                placeholder={askState.placeholder}
                value={askState.value}
                onChange={(e) => setAskState({ ...askState, value: e.target.value })}
              />
            )}
            <div className="flex justify-end gap-2 pt-1">
              <button type="button" className={btnGhost} onClick={() => finish(null)}>
                取消
              </button>
              <button
                type="submit"
                className={askState.danger ? `${btnPrimary} bg-red-600 hover:bg-red-700` : btnPrimary}
                disabled={showInput && askState.required && !askState.value.trim()}
              >
                {askState.confirmText || "确定"}
              </button>
            </div>
          </form>
        </Modal>
      )}
      <Toast message={toast.message} type={toast.type} visible={toast.visible} />
    </UiContext.Provider>
  );
}

export function useUi() {
  const ctx = useContext(UiContext);
  if (!ctx) throw new Error("useUi 必须在 UiProvider 内使用");
  return ctx;
}

export function Tabs<T extends string>({ tabs, value, onChange }: { tabs: readonly { id: T; label: string }[]; value: T; onChange: (id: T) => void }) {
  return (
    <div className="mb-4 flex gap-1 overflow-x-auto border-b border-background-300">
      {tabs.map((t) => (
        <button
          key={t.id}
          type="button"
          onClick={() => onChange(t.id)}
          className={`-mb-px cursor-pointer whitespace-nowrap border-b-2 px-4 py-2 text-sm transition-colors ${value === t.id ? "border-primary-500 font-medium text-primary-600" : "border-transparent text-foreground-600 hover:text-foreground-900"}`}
        >
          {t.label}
        </button>
      ))}
    </div>
  );
}

export function Filter<T extends string>({ options, value, onChange }: { options: readonly { id: T; label: string }[]; value: T; onChange: (v: T) => void }) {
  return (
    <div className="flex flex-wrap gap-1">
      {options.map((o) => (
        <button
          key={o.id || "all"}
          type="button"
          onClick={() => onChange(o.id)}
          className={`cursor-pointer rounded-md px-2.5 py-1 text-xs ${value === o.id ? "bg-primary-100 text-primary-700" : "text-foreground-600 hover:bg-background-200"}`}
        >
          {o.label}
        </button>
      ))}
    </div>
  );
}

export const num = (n: number | null | undefined) => (n == null ? "—" : n.toLocaleString("zh-CN"));

/** Token 数缩写：12,345 → 1.2 万，3.4 亿。 */
export function tokens(n: number | null | undefined) {
  if (!n) return "0";
  if (n >= 1e8) return `${(n / 1e8).toFixed(n >= 1e9 ? 0 : 1)} 亿`;
  if (n >= 1e4) return `${(n / 1e4).toFixed(n >= 1e5 ? 0 : 1)} 万`;
  return n.toLocaleString("zh-CN");
}

export const ACCOUNT_KINDS = [
  { id: "", label: "企业和个人" },
  { id: "企业", label: "企业" },
  { id: "个人", label: "个人" },
] as const;
export type AccountKindFilter = (typeof ACCOUNT_KINDS)[number]["id"];

export const PERIODS = [
  { id: "7", label: "近 7 天" },
  { id: "30", label: "近 30 天" },
  { id: "90", label: "近 90 天" },
  { id: "0", label: "全部" },
] as const;
export type PeriodId = (typeof PERIODS)[number]["id"];
export const periodLabel = (days: PeriodId) => PERIODS.find((p) => p.id === days)?.label || "";

export function KindTag({ kind }: { kind: string }) {
  return (
    <span
      className={`ml-1.5 inline-flex rounded px-1 text-[11px] ${kind === "个人" ? "bg-secondary-100 text-secondary-700" : "bg-primary-50 text-primary-700"}`}
    >
      {kind === "个人" ? "个人" : "企业"}
    </span>
  );
}

export function SortTh<T extends string>({ id, label, sort, onSort, className = "" }: { id: T; label: string; sort: T; onSort: (s: T) => void; className?: string }) {
  return (
    <th className={`${thCls} text-right ${className}`}>
      <button type="button" onClick={() => onSort(id)} className={`inline-flex cursor-pointer items-center gap-0.5 ${sort === id ? "text-primary-700" : "hover:text-foreground-800"}`}>
        {label}
        <i className={sort === id ? "ri-arrow-down-s-fill" : "ri-arrow-up-down-line text-[11px] opacity-50"} />
      </button>
    </th>
  );
}

export function openBlob(blob: Blob) {
  const url = URL.createObjectURL(blob);
  window.open(url, "_blank", "noopener");
  window.setTimeout(() => URL.revokeObjectURL(url), 60_000);
}
