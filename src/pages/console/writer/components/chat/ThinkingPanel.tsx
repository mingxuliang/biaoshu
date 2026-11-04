import { useEffect, useState } from "react";
import { ChevronRight, Sparkles } from "lucide-react";

/** Qwen Paw Reasoning 面板：思考过程可折叠，完成后默认收起。 */
export function ThinkingPanel({
  text,
  streaming,
}: {
  text: string;
  streaming: boolean;
}) {
  const [open, setOpen] = useState(true);
  useEffect(() => {
    if (streaming) setOpen(true);
    else setOpen(false);
  }, [streaming]);
  if (!text && !streaming) return null;
  return (
    <details
      open={open}
      onToggle={(event) => setOpen(event.currentTarget.open)}
      className="overflow-hidden rounded-lg border border-primary-100 bg-primary-50/40"
    >
      <summary className="flex cursor-pointer list-none items-center gap-2 px-2.5 py-1.5 text-[12px] [&::-webkit-details-marker]:hidden">
        <ChevronRight className={`h-3.5 w-3.5 shrink-0 text-primary-500 transition-transform ${open ? "rotate-90" : ""}`} />
        <Sparkles className="h-3.5 w-3.5 shrink-0 text-primary-500" />
        <span className="font-medium text-primary-700">Thinking</span>
        {streaming ? <span className="text-[11px] text-primary-500">进行中</span> : <span className="text-[11px] text-foreground-400">已完成</span>}
      </summary>
      {text ? (
        <pre className="max-h-48 overflow-auto whitespace-pre-wrap break-words border-t border-primary-100 px-2.5 py-2 font-sans text-[12px] leading-relaxed text-foreground-600">
          {text}
          {streaming ? <span className="ml-0.5 inline-block h-3 w-0.5 animate-pulse bg-primary-400 align-[-1px]" /> : null}
        </pre>
      ) : streaming ? (
        <div className="border-t border-primary-100 px-2.5 py-2 text-[12px] text-primary-500">正在推理…</div>
      ) : null}
    </details>
  );
}
