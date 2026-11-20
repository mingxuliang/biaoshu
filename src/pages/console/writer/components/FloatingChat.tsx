import { useEffect, useRef, useState, type ClipboardEvent, type DragEvent, type FormEvent, type UIEvent } from "react";
import AuthImage from "../../components/AuthImage";
import { useAuth } from "@/context/AuthContext";
import {
  ApiError,
  clearWriterChatMessages,
  listWriterChatMessages,
  uploadWriterChatFile,
  writerChat,
  type WriterChatEdit,
  type WriterChatFileInfo,
  type WriterChatTraceStep,
} from "@/lib/api";
import { HostBubbles } from "./chat/HostBubbles";

interface ChatAttach extends WriterChatFileInfo {
  previewUrl?: string;
}

interface ChatMessage {
  id: number;
  role: "assistant" | "user";
  content: string;
  trace?: WriterChatTraceStep[];
  files?: ChatAttach[];
  pending?: boolean;
}

interface FloatingChatProps {
  projectName: string;
  draftId: string;
  chapterId?: string;
  onApplied?: (edits: WriterChatEdit[]) => void;
  /** 底部有操作栏时把悬浮球抬高，避免挡住「目录确认」等按钮 */
  lift?: boolean;
}

const suggestions = [
  "把当前章节标题改短",
  "按编写思路重写本章正文",
  "调整相邻目录的顺序说明",
  "检查资格响应是否完整",
];

const IMAGE_EXT_RE = /\.(png|jpe?g|gif|webp)$/i;
const IMAGE_MIME: Record<string, string> = {
  "image/png": "png",
  "image/jpeg": "jpg",
  "image/jpg": "jpg",
  "image/webp": "webp",
  "image/gif": "gif",
};

let msgId = 0;

function isImageFile(file: { name?: string; type?: string; kind?: string }) {
  if (file.kind === "image") return true;
  if (file.type?.startsWith("image/")) return true;
  return IMAGE_EXT_RE.test(file.name || "");
}

function normalizeChatFile(file: File): File {
  if (file.name && IMAGE_EXT_RE.test(file.name)) return file;
  const ext = IMAGE_MIME[file.type] || (file.type.startsWith("image/") ? "png" : "");
  if (!ext) return file;
  const stamp = new Date().toISOString().replace(/\D/g, "").slice(0, 14);
  return new File([file], `粘贴图片-${stamp}.${ext}`, { type: file.type || "image/png" });
}

function clipboardImages(event: ClipboardEvent): File[] {
  const out: File[] = [];
  const items = event.clipboardData?.items;
  if (items) {
    for (const item of Array.from(items)) {
      if (!item.type.startsWith("image/")) continue;
      const file = item.getAsFile();
      if (file) out.push(normalizeChatFile(file));
    }
  }
  if (out.length === 0 && event.clipboardData?.files) {
    for (const file of Array.from(event.clipboardData.files)) {
      if (file.type.startsWith("image/") || IMAGE_EXT_RE.test(file.name)) out.push(normalizeChatFile(file));
    }
  }
  return out;
}

function defaultPrompt(files: ChatAttach[]) {
  if (files.length === 0) return "";
  return files.every(isImageFile) ? "请查看图片，并说明要如何修改当前标书" : "请阅读附件，并说明要如何修改当前标书";
}

export default function FloatingChat({ projectName, draftId, chapterId, onApplied, lift = false }: FloatingChatProps) {
  const { token } = useAuth();
  const [open, setOpen] = useState(false);
  const [messages, setMessages] = useState<ChatMessage[]>([
    {
      id: 0,
      role: "assistant",
      content: `我是慧投标撰写助手，当前项目「${projectName}」。可结合已解析的评分点与目录回答撰写问题。可上传或直接粘贴图片。`,
    },
  ]);
  const [input, setInput] = useState("");
  const [typing, setTyping] = useState(false);
  const [hasChecklist, setHasChecklist] = useState(false);
  const [files, setFiles] = useState<ChatAttach[]>([]);
  const [uploading, setUploading] = useState(false);
  const [dragging, setDragging] = useState(false);
  const scrollRef = useRef<HTMLDivElement>(null);
  const stickRef = useRef(true);
  const fileRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    if (!token || !open) return;
    let cancelled = false;
    listWriterChatMessages(token, draftId)
      .then((rows) => {
        if (cancelled || rows.length === 0) return;
        msgId = Math.max(msgId, rows.length);
        setMessages(
          rows.map((row, index) => ({
            id: index + 1,
            role: row.role,
            content: row.content,
            trace: row.trace || [],
            files: row.files || [],
          })),
        );
      })
      .catch(() => {
        /* 历史加载失败时仍可发送新消息 */
      });
    return () => {
      cancelled = true;
    };
  }, [token, draftId, open]);

  useEffect(() => {
    const el = scrollRef.current;
    if (el && stickRef.current) {
      el.scrollTop = el.scrollHeight;
    }
  }, [messages, typing, open]);

  const onTranscriptScroll = (event: UIEvent<HTMLDivElement>) => {
    const el = event.currentTarget;
    stickRef.current = el.scrollHeight - el.scrollTop - el.clientHeight < 96;
  };

  const removeFile = (id: string) => {
    setFiles((prev) => {
      const target = prev.find((item) => item.id === id);
      if (target?.previewUrl?.startsWith("blob:")) URL.revokeObjectURL(target.previewUrl);
      return prev.filter((item) => item.id !== id);
    });
  };

  const addFiles = async (list: ArrayLike<File> | null) => {
    if (!list || Array.from(list).length === 0) return;
    if (!token) {
      setMessages((prev) => [...prev, { id: ++msgId, role: "assistant", content: "请先登录后再上传或粘贴图片。" }]);
      return;
    }
    const incoming = Array.from(list).map(normalizeChatFile);
    const room = 3 - files.length;
    if (room <= 0) {
      setMessages((prev) => [...prev, { id: ++msgId, role: "assistant", content: "一次最多附带 3 个文件。" }]);
      return;
    }
    setUploading(true);
    try {
      for (const file of incoming.slice(0, room)) {
        const previewUrl = isImageFile(file) ? URL.createObjectURL(file) : undefined;
        try {
          const saved = await uploadWriterChatFile(token, draftId, file);
          setFiles((prev) =>
            prev.length >= 3
              ? prev
              : [
                  ...prev,
                  {
                    ...saved,
                    kind: saved.kind || (isImageFile(file) ? "image" : "file"),
                    previewUrl,
                  },
                ],
          );
        } catch (err) {
          if (previewUrl) URL.revokeObjectURL(previewUrl);
          const msg = err instanceof ApiError ? err.message : "附件上传失败，请稍后重试。";
          setMessages((prev) => [...prev, { id: ++msgId, role: "assistant", content: msg }]);
        }
      }
    } finally {
      setUploading(false);
      if (fileRef.current) fileRef.current.value = "";
    }
  };

  const handleSend = async (text: string) => {
    const pending = files;
    const value = text.trim() || defaultPrompt(pending);
    if (!value || typing || uploading) return;
    if (!token) {
      setMessages((prev) => [
        ...prev,
        { id: ++msgId, role: "user", content: value, files: pending },
        { id: ++msgId, role: "assistant", content: "请先登录后再使用撰写助手。" },
      ]);
      return;
    }

    const liveId = ++msgId;
    setInput("");
    setFiles([]);
    setMessages((prev) => [
      ...prev,
      { id: ++msgId, role: "user", content: value, files: pending },
      { id: liveId, role: "assistant", content: "", trace: [], pending: true },
    ]);
    setTyping(true);

    try {
      const result = await writerChat(
        token,
        draftId,
        {
          message: value,
          chapterId,
          fileIds: pending.map((item) => item.id),
        },
        (job) => {
          const trace = job.result?.trace || [];
          const reply =
            job.result?.reply ||
            [...trace].reverse().find((step) => step.kind === "reply")?.detail ||
            "";
          if (trace.length === 0 && !reply && job.status === "queued") return;
          setMessages((prev) =>
            prev.map((item) =>
              item.id === liveId
                ? { ...item, trace, content: reply, pending: job.status !== "done" && job.status !== "failed" }
                : item,
            ),
          );
        },
      );
      pending.forEach((item) => {
        if (item.previewUrl?.startsWith("blob:")) URL.revokeObjectURL(item.previewUrl);
      });
      setHasChecklist(result.hasChecklist);
      setMessages((prev) =>
        prev.map((item) =>
          item.id === liveId ? { ...item, content: result.reply, trace: result.trace, pending: false } : item,
        ),
      );
      try {
        if (result.edits.length > 0) onApplied?.(result.edits);
      } catch {
        /* 目录刷新失败不影响已经生成的回复 */
      }
    } catch (err) {
      const msg =
        err instanceof ApiError
          ? err.message
          : err instanceof Error && err.message
            ? err.message
            : "助手暂时无法回答，请稍后重试。";
      setMessages((prev) =>
        prev.map((item) => (item.id === liveId ? { ...item, content: msg, pending: false } : item)),
      );
    } finally {
      setTyping(false);
    }
  };

  const onPaste = (event: ClipboardEvent) => {
    const images = clipboardImages(event);
    if (images.length === 0) return;
    event.preventDefault();
    void addFiles(images);
  };

  const onDrop = (event: DragEvent<HTMLDivElement>) => {
    event.preventDefault();
    setDragging(false);
    const dropped = Array.from(event.dataTransfer.files || []);
    if (dropped.length) void addFiles(dropped);
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
        className={`fixed z-40 flex h-12 w-12 items-center justify-center rounded-full bg-gradient-to-br from-primary-500 to-primary-600 text-background-50 shadow-lg transition-transform hover:scale-105 ${
          lift ? "bottom-24 right-6" : "bottom-6 right-6"
        }`}
        title="AI 撰写助手"
      >
        <i className="ri-robot-2-line text-lg"></i>
      </button>
    );
  }

  return (
    <div
      className={`fixed bottom-4 right-4 z-40 flex h-[min(820px,calc(100vh-2rem))] w-[min(640px,calc(100vw-1.5rem))] flex-col overflow-hidden rounded-xl border bg-background-100 shadow-2xl ${
        dragging ? "border-primary-400 ring-2 ring-primary-200" : "border-background-300"
      }`}
      onPaste={onPaste}
      onDragOver={(event) => {
        event.preventDefault();
        setDragging(true);
      }}
      onDragLeave={() => setDragging(false)}
      onDrop={onDrop}
    >
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
            AgentScope{hasChecklist ? " · 已接入当前项目评分点" : " · 可粘贴或上传图片"}
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
          onClick={() => {
            const cleared = [
              { id: ++msgId, role: "assistant" as const, content: "对话已清空，随时可以开始新的问题。" },
            ];
            setMessages(cleared);
            if (token) {
              void clearWriterChatMessages(token, draftId).catch(() => {
                setMessages((prev) => [
                  ...prev,
                  { id: ++msgId, role: "assistant", content: "清空失败，请稍后重试。" },
                ]);
              });
            }
          }}
        >
          <i className="ri-delete-bin-line text-xs"></i>
        </button>
      </div>

      <div ref={scrollRef} onScroll={onTranscriptScroll} className="flex-1 space-y-3 overflow-y-auto px-3 py-3">
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
            {message.role === "assistant" ? (
              <div className="min-w-0 max-w-[92%] flex-1">
                <HostBubbles steps={message.trace || []} content={message.content} pending={Boolean(message.pending)} />
              </div>
            ) : (
              <div className="max-w-[92%] rounded-lg rounded-tr-sm bg-primary-50 px-3 py-2 text-[13px] leading-relaxed text-primary-700">
                {message.files && message.files.length > 0 ? (
                  <div className="mb-1.5 flex flex-wrap gap-1.5">
                    {message.files.map((file) =>
                      isImageFile(file) ? (
                        <AuthImage
                          key={file.id}
                          src={file.previewUrl || file.url}
                          alt={file.filename}
                          eager
                          className="max-h-40 max-w-[220px] rounded-md object-contain"
                        />
                      ) : (
                        <span key={file.id} className="rounded-full bg-primary-100 px-2 py-0.5 text-[11px]">
                          {file.filename}
                        </span>
                      ),
                    )}
                  </div>
                ) : null}
                {message.content ? <div className="whitespace-pre-wrap">{message.content}</div> : null}
              </div>
            )}
          </div>
        ))}
        {typing && !messages.some((item) => item.pending) && (
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
        {dragging ? (
          <div className="rounded-md border border-dashed border-primary-300 bg-primary-50 px-2 py-1.5 text-center text-[11px] text-primary-700">
            松开即可放入聊天
          </div>
        ) : null}
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
        {files.length > 0 && (
          <div className="flex flex-wrap gap-1.5">
            {files.map((file) =>
              isImageFile(file) ? (
                <span key={file.id} className="relative h-16 w-16 overflow-hidden rounded-md border border-primary-100">
                  <AuthImage
                    src={file.previewUrl || file.url}
                    alt={file.filename}
                    eager
                    className="h-full w-full object-cover"
                  />
                  <button
                    type="button"
                    className="absolute right-0.5 top-0.5 flex h-4 w-4 cursor-pointer items-center justify-center rounded-full bg-foreground-900/70 text-[10px] text-background-50"
                    onClick={() => removeFile(file.id)}
                    aria-label="移除图片"
                  >
                    ×
                  </button>
                </span>
              ) : (
                <span
                  key={file.id}
                  className="inline-flex max-w-full items-center gap-1 rounded-full bg-primary-50 px-2 py-0.5 text-[11px] text-primary-700"
                >
                  <span className="truncate">{file.filename}</span>
                  <button
                    type="button"
                    className="cursor-pointer text-primary-500"
                    onClick={() => removeFile(file.id)}
                    aria-label="移除附件"
                  >
                    ×
                  </button>
                </span>
              ),
            )}
          </div>
        )}
        <form onSubmit={onSubmit} className="flex items-center gap-1.5">
          <input
            ref={fileRef}
            type="file"
            accept=".docx,.pdf,.txt,.md,.png,.jpg,.jpeg,.webp,.gif,application/pdf,text/plain,text/markdown,image/png,image/jpeg,image/webp,image/gif"
            multiple
            className="hidden"
            onChange={(e) => void addFiles(e.target.files)}
          />
          <button
            type="button"
            onClick={() => fileRef.current?.click()}
            disabled={uploading || files.length >= 3}
            className="flex h-8 w-8 shrink-0 cursor-pointer items-center justify-center rounded-md text-foreground-500 transition-colors hover:bg-background-200 hover:text-primary-600 disabled:cursor-not-allowed disabled:opacity-50"
            title="上传图片、Word、PDF、TXT 或 Markdown，也可直接粘贴图片"
          >
            <i className="ri-image-add-line text-sm"></i>
          </button>
          <input
            type="text"
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onPaste={onPaste}
            placeholder={uploading ? "正在上传图片…" : "可粘贴图片，或直接说要改的目录或正文…"}
            className="h-8 flex-1 rounded-md border border-background-300 bg-background-50 px-2.5 text-sm text-foreground-900 outline-none transition-all focus:border-primary-400 focus:ring-1 focus:ring-primary-400/20 placeholder:text-foreground-500"
          />
          <button
            type="submit"
            disabled={typing || uploading || (!input.trim() && files.length === 0)}
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
