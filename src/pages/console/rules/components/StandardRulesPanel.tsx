import { useEffect, useState } from "react";
import { useProjects } from "@/context/ProjectContext";
import { ApiError, getProjectStandardRules, type DrawingFact, type DrawingReviewRule, type ProjectRule, type ProjectStandardRules, type TenderLeafRule } from "@/lib/api";
import { isEngineeringCategory } from "@/mocks/projects";

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

function ProjectRuleCard({ rule }: { rule: ProjectRule }) {
  return (
    <article className="rounded-lg border border-background-300 bg-background-100 p-4">
      <div className="text-[11px] text-foreground-500">{rule.source || "规则"} · {rule.checkType || "必须有"} · {rule.severity || "扣分"}</div>
      <h3 className="mt-0.5 text-sm font-semibold text-foreground-900">{rule.title}</h3>
      <p className="mt-2 text-sm leading-relaxed text-foreground-800">{rule.requirement}</p>
      {rule.evidence ? <p className="mt-2 text-xs text-foreground-500">依据：{rule.evidence}</p> : null}
      {rule.enabled === false ? <p className="mt-1 text-xs text-warning-600">已停用</p> : null}
    </article>
  );
}

function FactLine({ fact }: { fact: DrawingFact }) {
  return <li>{fact.drawingNo} {fact.field} {fact.value} · {fact.evidence}</li>;
}

export default function StandardRulesPanel() {
  const { projects: allProjects, loading: projectsLoading } = useProjects();
  const projects = allProjects.filter((project) => isEngineeringCategory(project.category));
  const [projectId, setProjectId] = useState("");
  const [source, setSource] = useState<SourceKey>("all");
  const [data, setData] = useState<ProjectStandardRules | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    if (projects.length === 0) return;
    if (projects.some((project) => project.id === projectId)) return;
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

  const selected = projects.find((project) => project.id === projectId);
  const engineering = isEngineeringCategory(selected?.category);
  const tenderCount = data?.tenderRules.length ?? 0;
  const drawingCount = engineering ? data?.drawingRules.length ?? 0 : 0;
  const sources: { key: SourceKey; label: string; count: number }[] = [
    { key: "all", label: "全部", count: tenderCount + drawingCount },
    { key: "tender", label: "招标书规则", count: tenderCount },
    ...(engineering ? [{ key: "drawing" as const, label: "图纸规则", count: drawingCount }] : []),
  ];

  useEffect(() => {
    if (!engineering && source === "drawing") setSource("all");
  }, [engineering, source]);

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
          还没有工程类项目。规范对标只服务工程标，创建工程类项目并完成招标解析后，这里按项目显示。
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
          {engineering && source !== "tender" ? (
            <section>
              <h2 className="mb-3 text-sm font-semibold text-foreground-800">本项目规则 {data?.projectRules?.length ?? 0}</h2>
              {(data?.projectRules?.length ?? 0) === 0 ? (
                <p className="rounded-lg border border-dashed border-background-300 bg-background-100/60 p-8 text-center text-sm text-foreground-500">
                  重新解析后，这里会列出招标、清单、图纸和水利规则池合成的规则。
                </p>
              ) : (
                <div className="grid grid-cols-1 gap-3 xl:grid-cols-2">
                  {data?.projectRules?.map((rule) => (
                    <ProjectRuleCard key={rule.id || rule.title} rule={rule} />
                  ))}
                </div>
              )}
              {(data?.drawingFacts?.length ?? 0) > 0 ? (
                <div className="mt-4">
                  <h3 className="mb-2 text-xs font-semibold text-foreground-700">图纸特征</h3>
                  <ul className="space-y-1 text-xs text-foreground-700">
                    {data?.drawingFacts?.map((fact, index) => (
                      <FactLine key={`${fact.drawingNo}-${index}`} fact={fact} />
                    ))}
                  </ul>
                </div>
              ) : null}
            </section>
          ) : null}
          {engineering && source !== "tender" ? (
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
