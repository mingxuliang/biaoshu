import type { WriterChatTraceStep } from "@/lib/api";
import { AssistantMarkdown } from "./AssistantMarkdown";
import { BubbleSpin, ToolCardShell } from "./ToolCardShell";
import { ThinkingPanel } from "./ThinkingPanel";

function splitDetail(detail: string) {
  const argsMatch = detail.match(/参数\n([\s\S]*?)(?:\n\n结果\n|$)/);
  const resultMatch = detail.match(/结果\n([\s\S]*)$/);
  return {
    args: argsMatch?.[1]?.trim() || "",
    result: resultMatch?.[1]?.trim() || "",
  };
}

function toolPayload(step: WriterChatTraceStep) {
  const parsed = splitDetail(step.detail || "");
  return {
    args: step.args || parsed.args,
    result: step.result || parsed.result,
  };
}

function ToolCards({
  tools,
  pending,
}: {
  tools: WriterChatTraceStep[];
  pending: boolean;
}) {
  if (tools.length === 0) return null;
  const cards = tools.map((step, index) => {
    const parsed = toolPayload(step);
    const running = Boolean(pending && index === tools.length - 1 && !parsed.result && step.status !== "done");
    return (
      <ToolCardShell
        key={step.id || `${step.title}-${index}`}
        title={step.title}
        running={running}
        failed={step.status === "error"}
        args={parsed.args}
        result={parsed.result}
        defaultExpanded={running}
      />
    );
  });
  if (pending || tools.length === 1) {
    return <div className="space-y-1.5">{cards}</div>;
  }
  return (
    <details className="overflow-hidden rounded-lg border border-background-300 bg-background-50">
      <summary className="flex cursor-pointer list-none items-center gap-2 px-2.5 py-1.5 text-[12px] text-foreground-700 [&::-webkit-details-marker]:hidden">
        <span className="font-medium">{tools.length} 步</span>
        <span className="text-foreground-400">工具调用已完成</span>
      </summary>
      <div className="space-y-1.5 border-t border-background-200 px-2 py-2">{cards}</div>
    </details>
  );
}

/** Qwen Paw HostBubbles：思考折叠、工具卡片、正文 Markdown 分卡流式合并。 */
export function HostBubbles({
  steps,
  content,
  pending,
}: {
  steps: WriterChatTraceStep[];
  content: string;
  pending: boolean;
}) {
  const thinkingText = steps
    .filter((step) => step.kind === "thinking")
    .map((step) => step.detail || "")
    .filter(Boolean)
    .join("\n\n");
  const tools = steps.filter((step) => step.kind === "tool");
  const limited = steps.some((step) => step.kind === "limit");
  const reply =
    content ||
    [...steps]
      .reverse()
      .find((step) => step.kind === "reply")?.detail ||
    "";
  const lastTool = tools[tools.length - 1];
  const lastToolRunning = Boolean(
    pending && lastTool && !toolPayload(lastTool).result && lastTool.status !== "done",
  );
  const thinkingActive = Boolean(pending && thinkingText && !lastToolRunning && !reply);
  const generatingEmpty = pending && !thinkingText && tools.length === 0 && !reply;
  const showReply = Boolean(reply) || (pending && !thinkingActive && !lastToolRunning && !generatingEmpty);

  if (generatingEmpty) return <BubbleSpin />;

  return (
    <div className="space-y-2">
      {thinkingText || thinkingActive ? (
        <ThinkingPanel text={thinkingText} streaming={thinkingActive || (pending && !reply && tools.length === 0)} />
      ) : null}
      <ToolCards tools={tools} pending={pending} />
      {limited ? (
        <div className="rounded-lg border border-amber-200 bg-amber-50 px-2.5 py-1.5 text-[12px] text-amber-800">
          达到推理轮次上限
        </div>
      ) : null}
      {showReply ? <AssistantMarkdown content={reply} cursor={pending && !lastToolRunning} /> : null}
    </div>
  );
}
