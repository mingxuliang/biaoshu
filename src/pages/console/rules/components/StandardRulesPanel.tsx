import { useEffect, useState } from "react";
import { useProjects } from "@/context/ProjectContext";
import { ApiError, getProjectStandardRules, type DrawingReviewRule, type ProjectStandardRules, type TenderLeafRule } from "@/lib/api";

type SourceKey = "all" | "tender" | "drawing";

const selectCls =
  "h-9 min-w-[240px] rounded-md border border-background-300 bg-background-50 px-3 text-sm text-foreground-900 outline-none transition-all focus:border-primary-400 focus:ring-1 focus:ring-primary-400/20";

function standardsOf(values: string[]) {
  return values.filter(Boolean);
}

function TenderCard({ rule, index }: { rule: TenderLeafRule; index: number }) {
  const standards = standardsOf(rule.standards);
  return (
    <article className="rounded-lg border border-background-300 bg-background-100 p-4">
      <div className="flex flex-wrap items-start justify-between gap-2">
        <div className="min-w-0">
          <div className="text-[11px] text-foreground-500">招标书规则 {index}</div>
          <h3 className="mt-0.5 text-sm font-semibold text-foreground-900">{rule.factor}</h3>
        </div>
        <div className="flex flex-wrap gap-1.5">
          {rule.axis ? (
            <span className="rounded bg-primary-50 px-1.5 py-0.5 text-[10px] text-primary-700">{rule.axis}</span>
          ) : null}
          {rule.chapter ? (
            <span className="rounded bg-background-200 px-1.5 py-0.5 text-[10px] text-foreground-600">{rule.chapter}</span>
          ) : null}
        </div>
      </div>
      {rule.score || rule.grades ? (
        <p className="mt-2 text-xs leading-relaxed text-foreground-700">
          {rule.score}
          {rule.score && rule.grades ? " · " : ""}
          {rule.grades}
        </p>
      ) : null}
      {rule.mustWrite ? <p className="mt-2 text-sm leading-relaxed text-foreground-800">{rule.mustWrite}</p> : null}
      {rule.parameters ? (
        <p className="mt-2 text-xs leading-relaxed text-foreground-600">参数：{rule.parameters}</p>
      ) : null}
      {standards.length > 0 ? (
        <div className="mt-2 flex flex-wrap gap-1.5">
          {standards.map((code) => (
            <span key={code} className="rounded bg-secondary-100 px-1.5 py-0.5 text-[10px] text-secondary-700">
              {code}
            </span>
          ))}
        </div>
      ) : null}
    </article>
  );
}

function DrawingCard({ rule, index }: { rule: DrawingReviewRule; index: number }) {
  const standards = standardsOf(rule.standards);
  return (
    <article className="rounded-lg border border-background-300 bg-background-100 p-4">
      <div className="flex flex-wrap items-start justify-between gap-2">
        <div className="min-w-0">
          <div className="text-[11px] text-foreground-500">
            图纸规则 {index}
            {rule.drawingNo ? ` · ${rule.drawingNo}` : ""}
          </div>
          <h3 className="mt-0.5 text-sm font-semibold text-foreground-900">{rule.title}</h3>
        </div>
        {rule.axis ? (
          <span className="rounded bg-primary-50 px-1.5 py-0.5 text-[10px] text-primary-700">{rule.axis}</span>
        ) : null}
      </div>
      {rule.parameters ? <p className="mt-2 text-sm leading-relaxed text-foreground-800">图面参数：{rule.parameters}</p> : null}
      {rule.notes ? <p className="mt-2 text-xs leading-relaxed text-foreground-600">施工说明：{rule.notes}</p> : null}
      {standards.length > 0 ? (
        <div className="mt-2 flex flex-wrap gap-1.5">
          {standards.map((code) => (
            <span key={code} className="rounded bg-secondary-100 px-1.5 py-0.5 text-[10px] text-secondary-700">
              {code}
            </span>
          ))}
        </div>
      ) : null}
    </article>
  );
}

export default function StandardRulesPanel() {
  const { projects, loading: projectsLoading } = useProjects();
  const [projectId, setProjectId] = useState("");
  const [source, setSource] = useState<SourceKey>("all");
  const [data, setData] = useState<ProjectStandardRules | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    if (projectId || projects.length === 0) return;
    setProjectId(projects[0].id);
  }, [projectId, projects]);

  useEffect(() => {
    if (!projectId) return;
    let cancelled = false;
    setLoading(true);
    setError("");
    getProjectStandardRules(projectId)
      .then((result) => {
        if (!cancelled) setData(result);
      })
      .catch((err: unknown) => {
        if (cancelled) return;
        setData(null);
        setError(err instanceof ApiError ? err.message : "规范对标规则加载失败");
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [projectId]);

  const tenderCount = data?.tenderRules.length ?? 0;
  const drawingCount = data?.drawingRules.length ?? 0;
  const sources: { key: SourceKey; label: string; count: number }[] = [
    { key: "all", label: "全部", count: tenderCount + drawingCount },
    { key: "tender", label: "招标书规则", count: tenderCount },
    { key: "drawing", label: "图纸规则", count: drawingCount },
  ];

  return (
    <div>
      <div className="mb-4 flex flex-wrap items-center gap-3">
        <label className="text-xs font-medium text-foreground-600" htmlFor="standard-rule-project">
          项目
        </label>
        <select
          id="standard-rule-project"
          className={selectCls}
          value={projectId}
          disabled={projectsLoading || projects.length === 0}
          onChange={(event) => setProjectId(event.target.value)}
        >
          {projects.length === 0 ? <option value="">暂无项目</option> : null}
          {projects.map((project) => (
            <option key={project.id} value={project.id}>
              {project.name}
              {project.code ? `（${project.code}）` : ""}
            </option>
          ))}
        </select>
        <div className="flex rounded-md border border-background-300 bg-background-100 p-0.5">
          {sources.map((item) => (
            <button
              key={item.key}
              type="button"
              onClick={() => setSource(item.key)}
              className={`cursor-pointer rounded px-3 py-1.5 text-xs font-medium ${
                source === item.key ? "bg-primary-500 text-background-50" : "text-foreground-600 hover:text-foreground-900"
              }`}
            >
              {item.label} {item.count}
            </button>
          ))}
        </div>
      </div>

      {data?.note ? <p className="mb-4 text-xs leading-relaxed text-foreground-500">{data.note}</p> : null}

      {projectsLoading || loading ? (
        <div className="flex items-center justify-center rounded-lg border border-background-300 bg-background-100 p-16">
          <span className="h-8 w-8 animate-spin rounded-full border-2 border-primary-200 border-t-primary-500" />
        </div>
      ) : error ? (
        <div className="rounded-lg border border-dashed border-accent-200 bg-accent-50/50 p-10 text-center text-sm text-accent-700">{error}</div>
      ) : projects.length === 0 ? (
        <div className="rounded-lg border border-dashed border-background-300 bg-background-100/60 p-10 text-center text-sm text-foreground-500">
          还没有项目。创建项目并完成招标解析后，这里按项目显示规范对标规则。
        </div>
      ) : (
        <div className="space-y-6">
          {source !== "drawing" ? (
            <section>
              <h2 className="mb-3 text-sm font-semibold text-foreground-800">招标书规则 {tenderCount}</h2>
              {tenderCount === 0 ? (
                <p className="rounded-lg border border-dashed border-background-300 bg-background-100/60 p-8 text-center text-sm text-foreground-500">
                  这个项目还没有招标书规则。
                </p>
              ) : (
                <div className="grid grid-cols-1 gap-3 xl:grid-cols-2">
                  {data?.tenderRules.map((rule, index) => (
                    <TenderCard key={`${rule.factor}-${index}`} rule={rule} index={index + 1} />
                  ))}
                </div>
              )}
            </section>
          ) : null}
          {source !== "tender" ? (
            <section>
              <h2 className="mb-3 text-sm font-semibold text-foreground-800">图纸规则 {drawingCount}</h2>
              {drawingCount === 0 ? (
                <p className="rounded-lg border border-dashed border-background-300 bg-background-100/60 p-8 text-center text-sm text-foreground-500">
                  这个项目还没有图纸规则。
                </p>
              ) : (
                <div className="grid grid-cols-1 gap-3 xl:grid-cols-2">
                  {data?.drawingRules.map((rule, index) => (
                    <DrawingCard key={`${rule.drawingNo}-${rule.title}-${index}`} rule={rule} index={index + 1} />
                  ))}
                </div>
              )}
            </section>
          ) : null}
        </div>
      )}
    </div>
  );
}
