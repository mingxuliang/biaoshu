import { useCallback, useState, type ReactNode, type SyntheticEvent } from "react";
import { Check, ChevronRight, Loader2, Wrench, X } from "lucide-react";

/** Qwen Paw ToolCardShell：一行图标+名称，运行中转圈，展开后才挂载参数/结果。流式参数不当 JSON 解析。 */
export function ToolCardShell({
  title,
  running,
  args,
  result,
  defaultExpanded = false,
  failed = false,
}: {
  title: string;
  running: boolean;
  failed?: boolean;
  args?: string;
  result?: string;
  defaultExpanded?: boolean;
}) {
  const [expanded, setExpanded] = useState(defaultExpanded);
  const [mounted, setMounted] = useState(defaultExpanded);
  const onToggle = useCallback((event: SyntheticEvent<HTMLDetailsElement>) => {
    const open = event.currentTarget.open;
    setExpanded(open);
    if (open) setMounted(true);
  }, []);
  const preview = running && args ? `${args.length} 字符` : null;
  return (
    <details
      open={expanded}
      onToggle={onToggle}
      className="overflow-hidden rounded-lg border border-background-300 bg-background-50"
    >
      <summary className="flex cursor-pointer list-none items-center gap-2 px-2.5 py-1.5 text-[12px] [&::-webkit-details-marker]:hidden">
        <ChevronRight className={`h-3.5 w-3.5 shrink-0 text-foreground-400 transition-transform ${expanded ? "rotate-90" : ""}`} />
        {running ? (
          <Loader2 className="h-3.5 w-3.5 shrink-0 animate-spin text-primary-500" />
        ) : (
          <span className="relative flex h-3.5 w-3.5 shrink-0 items-center justify-center text-primary-600">
            <Wrench className="h-3.5 w-3.5" />
            {failed ? (
              <X className="absolute -bottom-0.5 -right-0.5 h-2.5 w-2.5 rounded-full bg-background-50 text-red-600" />
            ) : (
              <Check className="absolute -bottom-0.5 -right-0.5 h-2.5 w-2.5 rounded-full bg-background-50 text-emerald-600" />
            )}
          </span>
        )}
        <span className="min-w-0 flex-1 truncate font-medium text-foreground-800">{title}</span>
        {running ? <span className="shrink-0 text-[11px] text-primary-600">运行中</span> : null}
        {failed && !running ? <span className="shrink-0 text-[11px] text-red-600">失败</span> : null}
        {preview ? <span className="shrink-0 text-[11px] text-foreground-400">{preview}</span> : null}
      </summary>
      {mounted ? (
        <div className="space-y-2 border-t border-background-200 px-2.5 py-2">
          {args ? (
            <div>
              <div className="text-[10px] font-medium uppercase tracking-wide text-foreground-400">参数</div>
              <pre className="mt-1 max-h-40 overflow-auto whitespace-pre-wrap break-words font-mono text-[11px] text-foreground-600">
                {args}
              </pre>
            </div>
          ) : null}
          {result ? (
            <div>
              <div className="text-[10px] font-medium uppercase tracking-wide text-foreground-400">结果</div>
              <pre className="mt-1 max-h-52 overflow-auto whitespace-pre-wrap break-words font-mono text-[11px] text-foreground-600">
                {result}
              </pre>
            </div>
          ) : running ? (
            <div className="text-[11px] text-foreground-500">工具正在执行…</div>
          ) : null}
        </div>
      ) : null}
    </details>
  );
}

export function BubbleSpin() {
  return (
    <div className="flex items-center gap-1.5 py-1 text-[12px] text-foreground-500">
      <Loader2 className="h-3.5 w-3.5 animate-spin text-primary-500" />
      正在思考
    </div>
  );
}

export function StepCount({ children }: { children: ReactNode }) {
  return (
    <div className="rounded-lg border border-dashed border-background-300 bg-background-100/80 px-2 py-1 text-[11px] text-foreground-500">
      {children}
    </div>
  );
}
