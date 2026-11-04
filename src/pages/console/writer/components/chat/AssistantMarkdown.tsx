import { useDeferredValue } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";

/** Qwen Paw Console 同款：流式阶段用 useDeferredValue 丢掉过期中间态，正文按 Markdown 渲染。 */
export function AssistantMarkdown({
  content,
  cursor,
}: {
  content: string;
  cursor: boolean;
}) {
  const deferred = useDeferredValue(content);
  const streaming = cursor || deferred !== content;
  const display = streaming ? content : deferred;
  if (!display && !cursor) return null;
  return (
    <div className="writer-md break-words text-[13px] leading-relaxed text-foreground-700">
      {display ? (
        <ReactMarkdown remarkPlugins={[remarkGfm]}>{display}</ReactMarkdown>
      ) : null}
      {cursor ? (
        <span className="ml-0.5 inline-block h-3.5 w-0.5 animate-pulse bg-primary-500 align-[-1px]" />
      ) : null}
    </div>
  );
}
