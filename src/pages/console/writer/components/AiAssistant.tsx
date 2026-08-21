import { useEffect, useRef, useState, type FormEvent } from "react";

interface ChatMessage {
  id: number;
  role: "bot" | "user";
  content: string;
}

const suggestions = ["分析废标风险", "优化商务报价", "生成售后服务章节", "检查资质文件完整度"];

const replies: { match: string[]; reply: string }[] = [
  {
    match: ["风险", "废标"],
    reply: "已完成风险扫描，发现以下潜在废标风险：\n\n1. 商务标报价明细中 2 处分项报价未包含安装调试费，与招标文件 B 章第 6 条不一致；\n2. 资格文件中「近三年同类业绩」缺少验收报告复印件；\n3. 技术标中第 3 章进度计划未体现关键节点的监理报验环节。\n\n建议优先处理第 1 项（属于形式审查硬性条款），需要我自动修复吗？",
  },
  {
    match: ["报价", "商务"],
    reply: "根据 42 项评分点分析，本项目商务报价权重 30%。建议报价策略：\n\n- 分项报价与招标控制价偏差控制在 ±5% 以内；\n- 优先保留高权重维度的成本投入（技术方案 40%）；\n- 对设备清单采用「基准价 + 可选配置」结构，避免被判定为不平衡报价。\n\n已生成优化后的报价框架，可切换到「商务报价与成本分析」章节查看。",
  },
  {
    match: ["售后", "服务", "章节"],
    reply: "已完成「售后服务与质量保障」章节的撰写，包含服务承诺、响应机制、质量体系、培训计划与应急预案五个小节，全文约 1200 字。\n\n重点覆盖了招标文件中的服务响应时限要求，并补充了本行业常见的加分项：备品备件库承诺与季度应急演练计划。",
  },
  {
    match: ["资质", "资格", "检查"],
    reply: "资质文件完整度检查完成：\n\n- 企业法人营业执照 ✓\n- 机电安装一级资质（有效期至 2027-03）✓\n- 质量管理体系认证 ISO 9001 ✓\n- 近三年同类业绩证明：缺 1 份验收报告，其余 4 份完整\n- 拟派项目经理注册证书 ✓\n\n缺失项请尽快补充，截止日前系统会自动复核。",
  },
  {
    match: ["你好", "hi", "hello"],
    reply: "你好！我是智标云 AI 撰写助手，可以帮你生成标书内容、分析废标风险、优化报价策略。告诉我你想处理哪个章节或问题吧。",
  },
];

const defaultReply = "收到，我已理解你的需求。结合当前项目招标文件的评分点，我正在整理相关素材…\n\n建议你可以先让我「分析废标风险」或「优化商务报价」，这两个维度对中标率影响最大。也可以直接告诉我需要生成的具体章节内容。";

let msgId = 0;

export default function AiAssistant({ projectName }: { projectName: string }) {
  const [messages, setMessages] = useState<ChatMessage[]>([
    {
      id: 0,
      role: "bot",
      content: `我是智标云 AI 撰写助手，已接入「${projectName}」的招标文件与评分点。可以帮你生成章节内容、分析废标风险、优化报价策略，随时开口~`,
    },
  ]);
  const [input, setInput] = useState("");
  const [typing, setTyping] = useState(false);
  const scrollRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (scrollRef.current) {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
    }
  }, [messages, typing]);

  const pushUserMessage = (text: string) => {
    setMessages((prev) => [...prev, { id: ++msgId, role: "user", content: text }]);
  };

  const handleSend = (text: string) => {
    const value = text.trim();
    if (!value || typing) return;
    setInput("");
    pushUserMessage(value);
    setTyping(true);
    window.setTimeout(() => {
      const matched = replies.find((r) => r.match.some((k) => value.includes(k)));
      setMessages((prev) => [...prev, { id: ++msgId, role: "bot", content: matched ? matched.reply : defaultReply }]);
      setTyping(false);
    }, 1100);
  };

  const onSubmit = (e: FormEvent) => {
    e.preventDefault();
    handleSend(input);
  };

  return (
    <div className="flex w-72 shrink-0 flex-col rounded-lg border border-background-300 bg-background-100 lg:w-72">
      <div className="flex items-center gap-2 border-b border-background-300 px-3 py-3">
        <span className="relative flex h-7 w-7 items-center justify-center rounded-md bg-gradient-to-br from-primary-400 to-primary-600 text-background-50">
          <i className="ri-robot-2-line text-sm"></i>
        </span>
        <div className="flex-1">
          <div className="font-heading text-sm font-semibold tracking-wide text-foreground-900">AI 撰写助手</div>
          <div className="font-label flex items-center gap-1 text-[11px] text-foreground-500">
            <span className="relative flex h-1.5 w-1.5">
              <span className="absolute inline-flex h-full w-full rounded-full bg-primary-400 opacity-60 animate-ping" />
              <span className="relative inline-flex h-1.5 w-1.5 rounded-full bg-primary-500" />
            </span>
            在线 · 已读取招标文件
          </div>
        </div>
        <button
          type="button"
          className="flex h-6 w-6 cursor-pointer items-center justify-center rounded text-foreground-500 transition-colors hover:bg-background-200 hover:text-foreground-800"
          title="清空对话"
          onClick={() =>
            setMessages([
              { id: ++msgId, role: "bot", content: "对话已清空，随时可以开始新的任务。" },
            ])
          }
        >
          <i className="ri-delete-bin-line text-xs"></i>
        </button>
      </div>

      <div ref={scrollRef} className="flex-1 space-y-2.5 overflow-y-auto px-3 py-3">
        {messages.map((message) => (
          <div key={message.id} className={`flex gap-2 ${message.role === "user" ? "flex-row-reverse" : ""}`}>
            {message.role === "bot" ? (
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
                message.role === "bot"
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
              onClick={() => handleSend(s)}
              className="font-label cursor-pointer whitespace-nowrap rounded-full border border-background-300 bg-background-50 px-2 py-0.5 text-[11px] text-foreground-500 transition-colors hover:border-primary-200 hover:text-primary-600"
            >
              {s}
            </button>
          ))}
        </div>
        <form onSubmit={onSubmit} className="flex items-center gap-1.5">
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