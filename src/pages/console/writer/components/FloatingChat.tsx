import { useEffect, useRef, useState, type FormEvent } from "react";
import { useAuth } from "@/context/AuthContext";
import { ApiError, writerChat } from "@/lib/api";

interface ChatMessage {
  id: number;
  role: "assistant" | "user";
  content: string;
}

interface FloatingChatProps {
  projectName: string;
  draftId: string;
  chapterTitle?: string;
  chapterExcerpt?: string;
}

const suggestions = [
  "分析废标风险",
  "优化商务报价",
  "生成售后服务章节要点",
  "检查资格响应是否完整",
  "全局整理标书结构",
];

let msgId = 0;

export default function FloatingChat({ projectName, draftId, chapterTitle, chapterExcerpt }: FloatingChatProps) {
  const { token } = useAuth();
  const [open, setOpen] = useState(false);
  const [messages, setMessages] = useState<ChatMessage[]>([
    {
      id: 0,
      role: "assistant",
      content: `我是智标云撰写助手，当前项目「${projectName}」。可结合已解析的评分点与目录回答撰写问题。`,
    },
  ]);
  const [input, setInput] = useState("");
  const [typing, setTyping] = useState(false);
  const [hasChecklist, setHasChecklist] = useState(false);
  const scrollRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (scrollRef.current) {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
    }
  }, [messages, typing, open]);

  const handleSend = async (text: string) => {
    const value = text.trim();
    if (!value || typing) return;
    if (!token) {
      setMessages((prev) => [
        ...prev,
        { id: ++msgId, role: "user", content: value },
        { id: ++msgId, role: "assistant", content: "请先登录后再使用撰写助手。" },
      ]);
      return;
    }

    setInput("");
    const history = messages
      .filter((m) => m.id !== 0)
      .map((m) => ({ role: m.role, content: m.content }));
    setMessages((prev) => [...prev, { id: ++msgId, role: "user", content: value }]);
    setTyping(true);

    try {
      const result = await writerChat(token, draftId, {
        message: value,
        history,
        chapterTitle,
        chapterExcerpt,
      });
      setHasChecklist(result.hasChecklist);
      setMessages((prev) => [...prev, { id: ++msgId, role: "assistant", content: result.reply }]);
    } catch (err) {
      const msg = err instanceof ApiError ? err.message : "助手暂时无法回答，请稍后重试。";
      setMessages((prev) => [...prev, { id: ++msgId, role: "assistant", content: msg }]);
    } finally {
      setTyping(false);
    }
  };

  const onSubmit = (e: FormEvent) => {
    e.preventDefault();
    void handleSend(input);
  };

  if (!open) {
    return (
      <button
        type="button"
        onClick={() => setOpen(true)}
        className="fixed bottom-6 right-6 z-40 flex h-12 w-12 items-center justify-center rounded-full bg-gradient-to-br from-primary-500 to-primary-600 text-background-50 shadow-lg transition-transform hover:scale-105"
        title="AI 撰写助手"
      >
        <i className="ri-robot-2-line text-lg"></i>
      </button>
    );
  }

  return (
    <div className="fixed bottom-6 right-6 z-40 flex h-[480px] w-80 flex-col overflow-hidden rounded-xl border border-background-300 bg-background-100 shadow-2xl">
      <div className="flex items-center gap-2 border-b border-background-300 px-3 py-2.5">
        <span className="relative flex h-7 w-7 items-center justify-center rounded-md bg-gradient-to-br from-primary-400 to-primary-600 text-background-50">
          <i className="ri-robot-2-line text-sm"></i>
        </span>
        <div className="flex-1 min-w-0">
          <div className="text-sm font-semibold text-foreground-900">AI 撰写助手</div>
          <div className="flex items-center gap-1 text-[11px] text-foreground-500">
            <span className="relative flex h-1.5 w-1.5">
              <span className="absolute inline-flex h-full w-full rounded-full bg-primary-400 opacity-60 animate-ping" />
              <span className="relative inline-flex h-1.5 w-1.5 rounded-full bg-primary-500" />
            </span>
            {hasChecklist ? "已接入当前项目评分点" : "在线 · 按项目上下文回答"}
          </div>
        </div>
        <button
          type="button"
          onClick={() => setOpen(false)}
          className="flex h-6 w-6 cursor-pointer items-center justify-center rounded text-foreground-500 transition-colors hover:bg-background-200 hover:text-foreground-800"
          title="收起"
        >
          <i className="ri-close-line text-xs"></i>
        </button>
        <button
          type="button"
          className="flex h-6 w-6 cursor-pointer items-center justify-center rounded text-foreground-500 transition-colors hover:bg-background-200 hover:text-foreground-800"
          title="清空对话"
          onClick={() =>
            setMessages([
              { id: ++msgId, role: "assistant", content: "对话已清空，随时可以开始新的问题。" },
            ])
          }
        >
          <i className="ri-delete-bin-line text-xs"></i>
        </button>
      </div>

      <div ref={scrollRef} className="flex-1 space-y-2.5 overflow-y-auto px-3 py-3">
        {messages.map((message) => (
          <div key={message.id} className={`flex gap-2 ${message.role === "user" ? "flex-row-reverse" : ""}`}>
            {message.role === "assistant" ? (
              <span className="flex h-6 w-6 shrink-0 items-center justify-center rounded-md bg-primary-500 text-[10px] text-background-50">
                <i className="ri-robot-2-line text-xs"></i>
              </span>
            ) : (
              <span className="flex h-6 w-6 shrink-0 items-center justify-center rounded-md bg-secondary-100 text-[10px] font-medium text-secondary-700">
                我
              </span>
            )}
            <div
              className={`max-w-[85%] whitespace-pre-wrap rounded-lg px-3 py-2 text-[13px] leading-relaxed ${
                message.role === "assistant"
                  ? "rounded-tl-sm border border-background-300 bg-background-50 text-foreground-700"
                  : "rounded-tr-sm bg-primary-50 text-primary-700"
              }`}
            >
              {message.content}
            </div>
          </div>
        ))}
        {typing && (
          <div className="flex gap-2">
            <span className="flex h-6 w-6 shrink-0 items-center justify-center rounded-md bg-primary-500 text-[10px] text-background-50">
              <i className="ri-robot-2-line text-xs"></i>
            </span>
            <div className="flex items-center gap-1 rounded-lg rounded-tl-sm border border-background-300 bg-background-50 px-3 py-2">
              {[0, 1, 2].map((dot) => (
                <span
                  key={dot}
                  className="h-1 w-1 rounded-full bg-primary-400 animate-typing-dot"
                  style={{ animationDelay: `${dot * 0.15}s` }}
                />
              ))}
            </div>
          </div>
        )}
      </div>

      <div className="space-y-2 border-t border-background-300 px-3 py-2.5">
        <div className="flex flex-wrap gap-1">
          {suggestions.map((s) => (
            <button
              key={s}
              type="button"
              onClick={() => void handleSend(s)}
              className="cursor-pointer whitespace-nowrap rounded-full border border-background-300 bg-background-50 px-2 py-0.5 text-[11px] text-foreground-500 transition-colors hover:border-primary-200 hover:text-primary-600"
            >
              {s}
            </button>
          ))}
        </div>
        <form onSubmit={onSubmit} className="flex items-center gap-1.5">
          <button
            type="button"
            onClick={() =>
              setMessages((prev) => [
                ...prev,
                { id: ++msgId, role: "assistant", content: "本轮暂不支持附件解析，请直接描述问题或粘贴需要改写的段落。" },
              ])
            }
            className="flex h-8 w-8 shrink-0 cursor-pointer items-center justify-center rounded-md text-foreground-500 transition-colors hover:bg-background-200 hover:text-primary-600"
            title="上传文件（暂不支持）"
          >
            <i className="ri-attachment-2 text-sm"></i>
          </button>
          <input
            type="text"
            value={input}
            onChange={(e) => setInput(e.target.value)}
            placeholder="向 AI 提问，例如：优化报价…"
            className="h-8 flex-1 rounded-md border border-background-300 bg-background-50 px-2.5 text-sm text-foreground-900 outline-none transition-all focus:border-primary-400 focus:ring-1 focus:ring-primary-400/20 placeholder:text-foreground-500"
          />
          <button
            type="submit"
            disabled={typing || !input.trim()}
            className="flex h-8 w-8 shrink-0 cursor-pointer items-center justify-center rounded-md bg-gradient-to-r from-primary-500 to-primary-600 text-background-50 transition-all hover:from-primary-600 hover:to-primary-700 disabled:cursor-not-allowed disabled:opacity-50"
            aria-label="发送"
          >
            <i className="ri-send-plane-line text-sm"></i>
          </button>
        </form>
      </div>
    </div>
  );
}
