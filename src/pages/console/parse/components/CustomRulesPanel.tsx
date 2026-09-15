import { useEffect, useState } from "react";
import {
  ApiError,
  createCustomRule,
  deleteCustomRule,
  listCustomRules,
  updateCustomRule,
  type CustomRuleSeverity,
  type CustomRuleSource,
  type ProjectCustomRule,
} from "@/lib/api";
import { TENDER_KIND_SLOTS } from "@/lib/tenderPackage";

const SOURCE_OPTS: { value: CustomRuleSource; label: string; hint: string }[] = [
  { value: "tender", label: "招标文件", hint: "从招标正文、评标办法、合同条款里人工理解出的规则" },
  { value: "drawing", label: "图纸", hint: "从图纸设计说明或图面要求里人工理解出的规则" },
  { value: "mixed", label: "多种类型", hint: "跨招标文件、图纸、清单等多份材料综合得出的规则" },
];

const SEVERITY_OPTS: { value: CustomRuleSeverity; label: string }[] = [
  { value: "废标", label: "废标" },
  { value: "降档", label: "降档" },
  { value: "扣分", label: "扣分" },
  { value: "建议", label: "建议" },
];

const inputCls =
  "h-9 w-full rounded-md border border-background-300 bg-background-50 px-3 text-sm text-foreground-900 outline-none transition-all focus:border-primary-400 focus:ring-1 focus:ring-primary-400/20 placeholder:text-foreground-500";
const labelCls = "mb-1.5 block text-xs font-medium text-foreground-600";

function sourceLabel(source: CustomRuleSource, sources: string[]) {
  if (source === "tender") return "招标文件";
  if (source === "drawing") return "图纸";
  const names = TENDER_KIND_SLOTS.filter((s) => sources.includes(s.key)).map((s) => s.label);
  return names.length ? `多种类型 · ${names.join("、")}` : "多种类型";
}

interface CustomRulesPanelProps {
  projectId: string;
  onCountChange?: (n: number) => void;
  onToast: (message: string, type?: "success" | "error" | "info") => void;
}

export default function CustomRulesPanel({ projectId, onCountChange, onToast }: CustomRulesPanelProps) {
  const [rules, setRules] = useState<ProjectCustomRule[]>([]);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [source, setSource] = useState<CustomRuleSource>("tender");
  const [slots, setSlots] = useState<string[]>([]);
  const [title, setTitle] = useState("");
  const [content, setContent] = useState("");
  const [severity, setSeverity] = useState<CustomRuleSeverity>("扣分");

  const load = () => {
    setLoading(true);
    listCustomRules(projectId)
      .then((rows) => {
        setRules(rows);
        onCountChange?.(rows.length);
      })
      .catch((err) => onToast(err instanceof ApiError ? err.message : "自定义规则加载失败", "error"))
      .finally(() => setLoading(false));
  };

  useEffect(() => {
    load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [projectId]);

  const resetForm = () => {
    setTitle("");
    setContent("");
    setSource("tender");
    setSlots([]);
    setSeverity("扣分");
  };

  const addRule = async () => {
    const text = content.trim();
    if (text.length < 2) {
      onToast("请填写规则内容", "error");
      return;
    }
    setSaving(true);
    try {
      const row = await createCustomRule(projectId, {
        source,
        sources: source === "mixed" ? slots : [],
        title: title.trim(),
        content: text,
        severity,
        enabled: true,
      });
      setRules((prev) => {
        const next = [row, ...prev];
        onCountChange?.(next.length);
        return next;
      });
      resetForm();
      onToast("已加入自定义规则，下次 AI 预审会检查投标书是否响应");
    } catch (err) {
      onToast(err instanceof ApiError ? err.message : "添加失败", "error");
    } finally {
      setSaving(false);
    }
  };

  const toggleEnabled = async (rule: ProjectCustomRule) => {
    try {
      const next = await updateCustomRule(projectId, rule.id, { enabled: !rule.enabled });
      setRules((prev) => prev.map((r) => (r.id === next.id ? next : r)));
    } catch (err) {
      onToast(err instanceof ApiError ? err.message : "更新失败", "error");
    }
  };

  const remove = async (rule: ProjectCustomRule) => {
    try {
      await deleteCustomRule(projectId, rule.id);
      const next = rules.filter((r) => r.id !== rule.id);
      setRules(next);
      onCountChange?.(next.length);
      onToast("已删除该自定义规则");
    } catch (err) {
      onToast(err instanceof ApiError ? err.message : "删除失败", "error");
    }
  };

  const toggleSlot = (key: string) => {
    setSlots((prev) => (prev.includes(key) ? prev.filter((k) => k !== key) : [...prev, key]));
  };

  return (
    <div className="space-y-4">
      <p className="text-[12px] leading-5 text-foreground-600">
        把招标文件、图纸或多种材料里人工理解出的条款写在这里。不限句式，只要是你认为投标书必须响应的规则都可以添加。启用中的规则会进入
        <strong> AI 预审</strong>，检查投标文件是否覆盖。
      </p>

      <div className="rounded-lg border border-background-200 bg-background-50 p-3">
        <div className="grid gap-3 sm:grid-cols-2">
          <div>
            <label className={labelCls}>来源类型</label>
            <select className={inputCls} value={source} onChange={(e) => setSource(e.target.value as CustomRuleSource)}>
              {SOURCE_OPTS.map((opt) => (
                <option key={opt.value} value={opt.value}>
                  {opt.label}
                </option>
              ))}
            </select>
            <p className="mt-1 text-[11px] text-foreground-400">{SOURCE_OPTS.find((o) => o.value === source)?.hint}</p>
          </div>
          <div>
            <label className={labelCls}>预审处理</label>
            <select
              className={inputCls}
              value={severity}
              onChange={(e) => setSeverity(e.target.value as CustomRuleSeverity)}
            >
              {SEVERITY_OPTS.map((opt) => (
                <option key={opt.value} value={opt.value}>
                  {opt.label}
                </option>
              ))}
            </select>
          </div>
        </div>
        {source === "mixed" && (
          <div className="mt-3">
            <span className={labelCls}>涉及的文件类型</span>
            <div className="flex flex-wrap gap-1.5">
              {TENDER_KIND_SLOTS.map((slot) => {
                const on = slots.includes(slot.key);
                return (
                  <button
                    key={slot.key}
                    type="button"
                    onClick={() => toggleSlot(slot.key)}
                    className={`cursor-pointer rounded-full px-2.5 py-1 text-[11px] ${
                      on
                        ? "bg-primary-50 text-primary-700 ring-1 ring-primary-200"
                        : "bg-background-100 text-foreground-600 ring-1 ring-background-300"
                    }`}
                  >
                    {slot.label}
                  </button>
                );
              })}
            </div>
          </div>
        )}
        <div className="mt-3">
          <label className={labelCls}>规则标题（可选）</label>
          <input className={inputCls} value={title} onChange={(e) => setTitle(e.target.value)} placeholder="例如：进度计划须 7 日内报监理确认" />
        </div>
        <div className="mt-3">
          <label className={labelCls}>规则内容</label>
          <textarea
            className="min-h-[88px] w-full rounded-md border border-background-300 bg-background-50 px-3 py-2 text-sm text-foreground-900 outline-none focus:border-primary-400 focus:ring-1 focus:ring-primary-400/20 placeholder:text-foreground-500"
            value={content}
            onChange={(e) => setContent(e.target.value)}
            placeholder="任意人工理解的规则原文或归纳，例如：专用合同条款 4.12，承包人须在监理确认后 3 日内提交修订进度计划。"
          />
        </div>
        <div className="mt-3 flex justify-end">
          <button
            type="button"
            disabled={saving}
            onClick={addRule}
            className="flex h-8 cursor-pointer items-center rounded-md bg-primary-500 px-4 text-xs font-medium text-background-50 hover:bg-primary-600 disabled:opacity-60"
          >
            {saving ? "添加中…" : "添加规则"}
          </button>
        </div>
      </div>

      <div>
        <div className="mb-2 text-xs font-medium text-foreground-700">已添加 {rules.length} 条</div>
        {loading ? (
          <div className="py-6 text-center text-sm text-foreground-400">加载中…</div>
        ) : rules.length === 0 ? (
          <div className="rounded-md border border-dashed border-background-300 px-3 py-8 text-center text-[13px] text-foreground-400">
            还没有自定义规则
          </div>
        ) : (
          <ul className="space-y-2">
            {rules.map((rule) => (
              <li key={rule.id} className="rounded-md border border-background-200 bg-background-100 px-3 py-2.5">
                <div className="flex items-start justify-between gap-2">
                  <div className="min-w-0">
                    <div className="flex flex-wrap items-center gap-1.5">
                      <span className="rounded bg-primary-50 px-1.5 py-0.5 text-[10px] font-medium text-primary-700">
                        {sourceLabel(rule.source, rule.sources)}
                      </span>
                      <span className="rounded bg-background-200 px-1.5 py-0.5 text-[10px] text-foreground-600">
                        {rule.severity}
                      </span>
                      {!rule.enabled && (
                        <span className="rounded bg-background-200 px-1.5 py-0.5 text-[10px] text-foreground-400">已停用</span>
                      )}
                    </div>
                    {rule.title ? (
                      <div className="mt-1 text-sm font-medium text-foreground-900">{rule.title}</div>
                    ) : null}
                    <div className="mt-1 whitespace-pre-wrap text-[13px] text-foreground-700">{rule.content}</div>
                  </div>
                  <div className="flex shrink-0 items-center gap-1">
                    <button
                      type="button"
                      onClick={() => toggleEnabled(rule)}
                      className="cursor-pointer rounded-md px-2 py-1 text-[11px] text-foreground-600 hover:bg-background-200"
                    >
                      {rule.enabled ? "停用" : "启用"}
                    </button>
                    <button
                      type="button"
                      onClick={() => remove(rule)}
                      className="cursor-pointer rounded-md px-2 py-1 text-[11px] text-accent-600 hover:bg-accent-50"
                    >
                      删除
                    </button>
                  </div>
                </div>
              </li>
            ))}
          </ul>
        )}
      </div>
    </div>
  );
}
