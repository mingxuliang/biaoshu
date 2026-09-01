import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { getLatestChecklist, type Checklist } from "@/lib/api";
import type { InterpretSource } from "@/mocks/writerSteps";

interface BidInterpretProps {
  projectId: string;
  source: InterpretSource;
  onSourceChange: (s: InterpretSource) => void;
  onConfirm: () => void;
  onBack: () => void;
}

interface OverviewItem {
  key: string;
  label: string;
  count: number;
}

export default function BidInterpret({ projectId, source, onSourceChange, onConfirm, onBack }: BidInterpretProps) {
  const [checklist, setChecklist] = useState<Checklist | null>(null);
  const [loading, setLoading] = useState(true);
  const [notFound, setNotFound] = useState(false);
  const [reused, setReused] = useState(false);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setNotFound(false);
    getLatestChecklist(projectId)
      .then((data) => {
        if (cancelled) return;
        setChecklist(data);
      })
      .catch(() => {
        if (cancelled) return;
        setChecklist(null);
        setNotFound(true);
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [projectId]);

  const overview: OverviewItem[] = checklist
    ? [
        { key: "scoreRules", label: "评分规则", count: checklist.scoreRules.length },
        { key: "mustRespond", label: "星号/废标条款", count: checklist.mustRespond.length },
        { key: "qualification", label: "资格要求", count: checklist.qualification.length },
        { key: "formatRequirements", label: "格式要求", count: checklist.formatRequirements.length },
      ]
    : [];
  const totalItems = overview.reduce((sum, d) => sum + d.count, 0);
  const ready = !!checklist && checklist.status === "done";
  const canReuse = ready && totalItems > 0;
  const canNext = source === "reuse" ? reused && canReuse : reused;

  const sourceCls = (active: boolean) =>
    `flex cursor-pointer flex-col gap-3 rounded-lg border p-4 text-left transition-all ${
      active ? "border-primary-400 bg-primary-50/70 ring-1 ring-primary-200" : "border-background-300 bg-background-50 hover:border-primary-200"
    }`;

  return (
    <div className="flex min-h-0 flex-1 flex-col overflow-hidden rounded-lg border border-background-300 bg-background-100">
      {/* 头部 */}
      <div className="flex shrink-0 items-center gap-2.5 border-b border-background-300 px-4 py-3">
        <span className="flex h-8 w-8 items-center justify-center rounded-md bg-gradient-to-br from-primary-400 to-primary-600 text-background-50">
          <i className="ri-file-settings-line text-base"></i>
        </span>
        <div>
          <div className="font-heading text-sm font-semibold tracking-wide text-foreground-900">第二步 · 标书解读</div>
          <div className="text-xs text-foreground-500">引用招标解析的既有结果，或上传招标文件重新解析，为目录与正文生成提供评分依据</div>
        </div>
        {reused && (
          <span className="ml-auto flex items-center gap-1 rounded-md bg-secondary-100 px-2 py-1 text-[11px] font-medium text-secondary-700">
            <i className="ri-check-double-line"></i>
            已确认解读来源
          </span>
        )}
      </div>

      {/* 内容区 */}
      <div className="min-h-0 flex-1 overflow-y-auto px-4 py-4">
        <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
          {/* 来源 A：复用已解析结果 */}
          <div className={`${sourceCls(source === "reuse")}`} onClick={() => onSourceChange("reuse")}>
            <div className="flex items-center gap-2.5">
              <span className={`flex h-7 w-7 items-center justify-center rounded-md ${source === "reuse" ? "bg-primary-500 text-background-50" : "bg-secondary-100 text-secondary-600"}`}>
                <i className="ri-database-2-line text-sm"></i>
              </span>
              <div>
                <div className="text-sm font-semibold text-foreground-900">复用招标解析结果</div>
                <div className="text-[11px] text-foreground-500">引用本项目最新一次已完成的招标解析（不必锁定；预审同样使用最新解析）</div>
              </div>
              <span className={`ml-auto flex h-5 w-5 items-center justify-center rounded-full border ${source === "reuse" ? "border-primary-500 bg-primary-500 text-background-50" : "border-background-300 text-transparent"}`}>
                <i className="ri-check-line text-[10px]"></i>
              </span>
            </div>

            {loading && (
              <div className="flex items-center justify-center rounded-lg border border-background-200 bg-background-100 p-6 text-xs text-foreground-500">
                <i className="ri-loader-4-line mr-1.5 animate-spin"></i>
                正在加载评标尺子…
              </div>
            )}

            {!loading && notFound && (
              <div className="flex flex-col items-center gap-2 rounded-lg border border-dashed border-background-300 bg-background-100 p-5 text-center">
                <i className="ri-file-warning-line text-2xl text-accent-500"></i>
                <p className="text-xs text-foreground-600">该项目暂无招标解析记录，请先完成招标文件解析（完成即可，不必锁定）</p>
                <Link
                  to={`/console/parse?project=${projectId}`}
                  className="mt-1 flex h-8 items-center gap-1 rounded-md bg-primary-500 px-3 text-xs font-medium text-background-50 transition-colors hover:bg-primary-600"
                >
                  <i className="ri-arrow-right-line text-xs"></i>
                  前往招标解析
                </Link>
              </div>
            )}

            {!loading && checklist && (
              <div className="rounded-lg border border-background-200 bg-background-100 p-3">
                <div className="mb-2 flex items-center justify-between">
                  <span className="text-xs font-medium text-foreground-700">已解析结果概览</span>
                  <span
                    className={`font-label text-xs font-semibold ${
                      checklist.status === "done" ? "text-primary-600" : "text-accent-600"
                    }`}
                  >
                    {checklist.status === "done" ? `v${checklist.version} 已完成` : `v${checklist.version} ${checklist.status}`}
                  </span>
                </div>
                <div className="grid grid-cols-2 gap-1.5 sm:grid-cols-4">
                  {overview.map((dim) => (
                    <span
                      key={dim.key}
                      className="flex items-center gap-1 rounded-md bg-background-50 px-2 py-1.5 text-[11px] text-foreground-600"
                    >
                      <i className="ri-checkbox-circle-fill text-primary-500 text-xs"></i>
                      {dim.label}
                      <span className="ml-auto text-[10px] text-foreground-400">{dim.count}</span>
                    </span>
                  ))}
                </div>
                <div className="mt-2 flex flex-wrap items-center gap-1.5 border-t border-background-200 pt-2 text-[11px] text-foreground-500">
                  <span className="rounded bg-secondary-100 px-1.5 py-0.5 text-secondary-700">共 {totalItems} 条评标要素</span>
                  <span
                    className={`rounded px-1.5 py-0.5 ${
                      checklist.locked ? "bg-secondary-100 text-secondary-700" : "bg-accent-100 text-accent-700"
                    }`}
                  >
                    {checklist.locked ? "评标尺子已锁定" : "未锁定也可用于写标与预审"}
                  </span>
                </div>
              </div>
            )}

            <button
              type="button"
              disabled={!canReuse}
              onClick={() => {
                onSourceChange("reuse");
                setReused(true);
              }}
              className="flex h-9 w-full cursor-pointer items-center justify-center gap-1.5 whitespace-nowrap rounded-md bg-primary-500 px-4 text-sm font-medium text-background-50 transition-colors hover:bg-primary-600 disabled:cursor-not-allowed disabled:opacity-50"
            >
              <i className="ri-check-double-line text-sm"></i>
              确认引用该解析结果
            </button>
          </div>

          {/* 来源 B：上传重新解析 */}
          <div className={`${sourceCls(source === "upload")}`} onClick={() => onSourceChange("upload")}>
            <div className="flex items-center gap-2.5">
              <span className={`flex h-7 w-7 items-center justify-center rounded-md ${source === "upload" ? "bg-primary-500 text-background-50" : "bg-secondary-100 text-secondary-600"}`}>
                <i className="ri-upload-cloud-2-line text-sm"></i>
              </span>
              <div>
                <div className="text-sm font-semibold text-foreground-900">上传文件重新解析</div>
                <div className="text-[11px] text-foreground-500">如需用新的招标文件重新解析，请前往「招标文件解析」模块上传</div>
              </div>
              <span className={`ml-auto flex h-5 w-5 items-center justify-center rounded-full border ${source === "upload" ? "border-primary-500 bg-primary-500 text-background-50" : "border-background-300 text-transparent"}`}>
                <i className="ri-check-line text-[10px]"></i>
              </span>
            </div>

            <div className="flex flex-col items-center justify-center gap-2 rounded-lg border border-dashed border-background-300 bg-background-100 px-4 py-6 text-center">
              <i className="ri-upload-cloud-2-line text-3xl text-primary-500"></i>
              <p className="text-sm text-foreground-700">重新解析请统一在招标解析模块完成</p>
              <p className="text-xs text-foreground-500">解析完成后回到本页选择「复用招标解析结果」即可，锁定不是写标的前置条件</p>
              <Link
                to={`/console/parse?project=${projectId}`}
                className="mt-1 flex h-8 cursor-pointer items-center gap-1.5 whitespace-nowrap rounded-md bg-primary-500 px-3 text-xs font-medium text-background-50 transition-colors hover:bg-primary-600"
              >
                <i className="ri-external-link-line"></i>
                前往招标解析模块
              </Link>
            </div>
          </div>
        </div>
      </div>

      {/* 底部操作 */}
      <div className="flex shrink-0 items-center justify-between border-t border-background-300 bg-background-50 px-4 py-3">
        <div className="flex items-center gap-2">
          <button
            type="button"
            onClick={onBack}
            className="flex h-9 cursor-pointer items-center gap-1.5 whitespace-nowrap rounded-md border border-background-300 bg-background-50 px-4 text-sm font-medium text-foreground-600 transition-colors hover:bg-background-200"
          >
            <i className="ri-arrow-left-s-line text-base"></i>
            上一步
          </button>
          <span className="hidden text-[11px] text-foreground-500 sm:block">
            <i className="ri-information-line mr-1 text-primary-500"></i>
            解读结果将用于下一步目录的评分点绑定与章节权重
          </span>
        </div>
        <button
          type="button"
          onClick={onConfirm}
          disabled={!canNext}
          className="flex h-9 cursor-pointer items-center gap-1.5 whitespace-nowrap rounded-md bg-primary-500 px-4 text-sm font-medium text-background-50 transition-colors hover:bg-primary-600 disabled:cursor-not-allowed disabled:opacity-50"
        >
          确认解读，进入下一步
          <i className="ri-arrow-right-s-line text-base"></i>
        </button>
      </div>
    </div>
  );
}
