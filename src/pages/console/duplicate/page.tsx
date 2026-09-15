import { useRef, useState, type RefObject } from "react";
import { useNavigate } from "react-router-dom";
import PageHeader from "../components/PageHeader";
import { clearDuplicateReport } from "./session";

const ACCEPT = ".docx,.pdf,application/pdf,application/vnd.openxmlformats-officedocument.wordprocessingml.document";

interface SlotFile {
  file: File;
  name: string;
  size: string;
}

function formatSize(bytes: number): string {
  if (!bytes) return "—";
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

function isAllowed(file: File): boolean {
  return /\.(docx|pdf)$/i.test(file.name);
}

export default function DuplicatePage() {
  const navigate = useNavigate();
  const [fileA, setFileA] = useState<SlotFile | null>(null);
  const [fileB, setFileB] = useState<SlotFile | null>(null);
  const [errA, setErrA] = useState("");
  const [errB, setErrB] = useState("");
  const inputA = useRef<HTMLInputElement>(null);
  const inputB = useRef<HTMLInputElement>(null);

  const pick = (slot: "a" | "b", file: File) => {
    if (!isAllowed(file)) {
      const msg = "仅支持技术标 .docx 或 .pdf";
      if (slot === "a") setErrA(msg);
      else setErrB(msg);
      return;
    }
    const picked: SlotFile = { file, name: file.name, size: formatSize(file.size) };
    if (slot === "a") {
      setErrA("");
      setFileA(picked);
    } else {
      setErrB("");
      setFileB(picked);
    }
  };

  const goAnalyze = () => {
    if (!fileA || !fileB) return;
    clearDuplicateReport();
    navigate("/console/duplicate/result", { state: { fileA: fileA.file, fileB: fileB.file } });
  };

  const ready = !!(fileA && fileB);

  return (
    <div>
      <PageHeader
        title="查重分析"
        description="上传两份技术标后进入结果页，系统通读抽出的全部正文再对照规则页查重阈值。暂不支持商务标。"
        actions={
          ready ? (
            <button
              type="button"
              onClick={goAnalyze}
              className="flex h-9 cursor-pointer items-center gap-1.5 whitespace-nowrap rounded-md bg-primary-500 px-4 text-sm font-medium text-background-50 transition-colors hover:bg-primary-600"
            >
              <i className="ri-file-search-line text-sm"></i>
              开始查重
            </button>
          ) : undefined
        }
      />

      <div className="overflow-hidden rounded-lg border border-background-300 bg-background-100">
        <div className="flex items-center gap-2.5 border-b border-background-300 bg-background-50 px-5 py-4">
          <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg bg-gradient-to-br from-accent-400 to-accent-500 text-background-50">
            <i className="ri-upload-cloud-2-line text-lg"></i>
          </span>
          <div>
            <div className="font-label text-sm font-semibold text-foreground-900">上传两份技术标</div>
            <div className="text-xs text-foreground-500">不绑定项目。请上传本企业两份施工组织设计 / 技术方案 Word 或 PDF。</div>
          </div>
        </div>
        <div className="grid grid-cols-1 gap-3 p-5 lg:grid-cols-2">
          <FileSlot
            label="技术标甲"
            hint="对照文件一"
            icon="ri-file-word-2-line"
            slot={fileA}
            error={errA}
            inputRef={inputA}
            onPick={(f) => pick("a", f)}
            onClear={() => setFileA(null)}
          />
          <FileSlot
            label="技术标乙"
            hint="对照文件二"
            icon="ri-file-copy-2-line"
            slot={fileB}
            error={errB}
            inputRef={inputB}
            onPick={(f) => pick("b", f)}
            onClear={() => setFileB(null)}
          />
        </div>
        <div className="flex flex-col gap-2 border-t border-background-300 bg-background-50 px-5 py-3 sm:flex-row sm:items-center sm:justify-between">
          <div className="text-xs text-foreground-500">
            {ready ? "两份技术标已就绪，将进入独立的分析结果页。" : "请分别上传技术标甲和技术标乙。"}
          </div>
          <button
            type="button"
            disabled={!ready}
            onClick={goAnalyze}
            className="flex h-9 shrink-0 cursor-pointer items-center justify-center gap-1.5 whitespace-nowrap rounded-md bg-gradient-to-r from-primary-500 to-primary-600 px-5 text-sm font-semibold text-background-50 transition-all hover:from-primary-600 hover:to-primary-700 disabled:cursor-not-allowed disabled:opacity-50"
          >
            <i className="ri-arrow-right-line text-sm"></i>
            进入查重分析
          </button>
        </div>
      </div>
    </div>
  );
}

function FileSlot({
  label,
  hint,
  icon,
  slot,
  error,
  inputRef,
  onPick,
  onClear,
}: {
  label: string;
  hint: string;
  icon: string;
  slot: SlotFile | null;
  error: string;
  inputRef: RefObject<HTMLInputElement | null>;
  onPick: (file: File) => void;
  onClear: () => void;
}) {
  return (
    <div className="flex flex-col overflow-hidden rounded-lg border border-background-300 bg-background-50">
      <div className="flex items-center gap-2 border-b border-background-300 bg-background-100 px-4 py-2.5">
        <span className="flex h-6 w-6 items-center justify-center rounded-md bg-primary-50 text-primary-600">
          <i className={`${icon} text-sm`}></i>
        </span>
        <div className="min-w-0">
          <div className="text-sm font-medium text-foreground-800">{label}</div>
          <div className="text-[11px] text-foreground-500">{hint}</div>
        </div>
        {slot && (
          <button type="button" onClick={onClear} className="ml-auto cursor-pointer text-[11px] text-foreground-500 hover:text-accent-600">
            清除
          </button>
        )}
      </div>
      <div className="flex flex-1 flex-col gap-3 p-3">
        <button
          type="button"
          onClick={() => inputRef.current?.click()}
          className={`flex cursor-pointer flex-col items-center justify-center gap-1 rounded-lg border-2 border-dashed px-3 py-8 text-center transition-colors ${
            slot ? "border-primary-300 bg-primary-50/50" : "border-background-300 hover:border-primary-300 hover:bg-background-100"
          }`}
        >
          <i className={`${slot ? "ri-file-word-2-line" : "ri-upload-cloud-2-line"} text-xl text-primary-500`}></i>
          <span className="text-xs font-medium text-foreground-700">{slot ? slot.name : `上传${label}`}</span>
          <span className="text-[11px] text-foreground-500">{slot ? slot.size : ".docx / .pdf"}</span>
        </button>
        <input
          ref={inputRef}
          type="file"
          accept={ACCEPT}
          className="hidden"
          onChange={(e) => {
            const file = e.target.files?.[0];
            if (file) onPick(file);
            e.target.value = "";
          }}
        />
        {error && <p className="text-[11px] text-accent-600">{error}</p>}
        {!slot && !error && <p className="text-[11px] text-accent-600">请上传{label}</p>}
      </div>
    </div>
  );
}
