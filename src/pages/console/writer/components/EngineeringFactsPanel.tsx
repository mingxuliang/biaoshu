import { useEffect, useState } from "react";
import { saveEngineeringFacts, type EngineeringFacts } from "@/lib/api";

interface EngineeringFactsPanelProps {
  draftId: string;
  facts: EngineeringFacts;
  onSaved: (facts: EngineeringFacts) => void;
  onError: (message: string) => void;
  water?: boolean;
}

type TitledRow = { title: string; text?: string };

const SCALAR_FIELDS: { key: keyof EngineeringFacts; label: string; wide?: boolean }[] = [
  { key: "projectName", label: "工程名称", wide: true },
  { key: "location", label: "建设地点" },
  { key: "duration", label: "计划工期" },
  { key: "quality", label: "质量目标" },
  { key: "milestones", label: "节点工期" },
  { key: "scale", label: "建设规模", wide: true },
  { key: "scope", label: "招标范围", wide: true },
  { key: "civilization", label: "安全文明施工目标", wide: true },
  { key: "greenBuilding", label: "绿色施工 / 绿色建筑要求", wide: true },
  { key: "smartSite", label: "智慧工地要求", wide: true },
];

function rowsToText(rows: TitledRow[] | undefined): string {
  return (rows || []).map((r) => (r.text ? `${r.title}：${r.text}` : r.title)).join("\n");
}

function pipeText(rows: Record<string, string | undefined>[] | undefined, keys: string[]): string {
  return (rows || [])
    .map((row) => keys.map((key) => row[key] || "").join("｜"))
    .filter((line) => line.replace(/｜/g, "").trim())
    .join("\n");
}

function pipeRows<T extends Record<string, string>>(text: string, keys: readonly (keyof T & string)[]): T[] {
  return text
    .split("\n")
    .map((line) => line.trim())
    .filter(Boolean)
    .map((line) => {
      const parts = line.split(/[|｜]/);
      const row = {} as T;
      keys.forEach((key, index) => {
        row[key] = (parts[index] || "").trim() as T[typeof key];
      });
      return row;
    })
    .filter((row) => row[keys[0]]);
}

function hasWaterLedger(facts: EngineeringFacts): boolean {
  const grade = facts.projectGrade || {};
  const site = facts.siteSurvey || {};
  return Boolean(
    facts.regionTotalLength ||
      facts.regions?.length ||
      facts.structures?.length ||
      facts.controlNodes?.length ||
      facts.standardsRefs?.length ||
      grade.projectLevel ||
      grade.structureLevel ||
      grade.floodStandard ||
      site.boundaries ||
      site.access ||
      site.crsNote ||
      site.sensitivePoints?.length ||
      facts.floodSeason?.spansFlood,
  );
}

function textToRows(text: string): TitledRow[] {
  return text
    .split("\n")
    .map((line) => line.trim())
    .filter(Boolean)
    .map((line) => {
      const m = /^([^：:]{1,40})[：:](.*)$/.exec(line);
      return m ? { title: m[1].trim(), text: m[2].trim() } : { title: line };
    });
}

export default function EngineeringFactsPanel({ draftId, facts, onSaved, onError, water = false }: EngineeringFactsPanelProps) {
  const [open, setOpen] = useState(false);
  const [saving, setSaving] = useState(false);
  const [form, setForm] = useState<EngineeringFacts>(facts);
  const [scoreText, setScoreText] = useState("");
  const [diffText, setDiffText] = useState("");
  const [extraText, setExtraText] = useState("");
  const [hazardText, setHazardText] = useState("");
  const [regionText, setRegionText] = useState("");
  const [nodeText, setNodeText] = useState("");
  const [structureText, setStructureText] = useState("");
  const [pointText, setPointText] = useState("");
  const [standardText, setStandardText] = useState("");

  useEffect(() => {
    setForm(facts);
    setScoreText((facts.scoreItems || []).map((s) => s.title).join("\n"));
    setDiffText(rowsToText(facts.difficulties));
    setExtraText(rowsToText(facts.extraDifficulties));
    setHazardText(rowsToText((facts.hazards || []).map((h) => ({ title: h.name, text: h.text }))));
    setRegionText(pipeText(facts.regions, ["name", "length", "mainQuantities"]));
    setNodeText(pipeText(facts.controlNodes, ["name", "window", "note"]));
    setStructureText(pipeText(facts.structures, ["name", "count", "spec"]));
    setPointText(pipeText(facts.siteSurvey?.sensitivePoints, ["name", "kind", "note"]));
    setStandardText((facts.standardsRefs || []).join("\n"));
  }, [facts]);

  const save = async () => {
    const previousScores = new Map((facts.scoreItems || []).map((s) => [s.title, s]));
    const payload: EngineeringFacts = {
      ...form,
      scoreItems: scoreText
        .split("\n")
        .map((t) => t.trim())
        .filter(Boolean)
        .map((title) => previousScores.get(title) ?? { title }),
      difficulties: textToRows(diffText),
      extraDifficulties: textToRows(extraText),
      hazards: textToRows(hazardText).map((r) => ({ name: r.title, text: r.text })),
      regions: pipeRows(regionText, ["name", "length", "mainQuantities"]),
      controlNodes: pipeRows(nodeText, ["name", "window", "note"]),
      structures: pipeRows(structureText, ["name", "count", "spec"]),
      standardsRefs: standardText
        .split("\n")
        .map((line) => line.trim())
        .filter(Boolean),
      siteSurvey: {
        ...(form.siteSurvey || {}),
        sensitivePoints: pipeRows(pointText, ["name", "kind", "note"]),
      },
    };
    setSaving(true);
    try {
      const draft = await saveEngineeringFacts(draftId, payload);
      onSaved((draft.settings?.engFacts as EngineeringFacts | undefined) ?? payload);
    } catch (err) {
      onError(err instanceof Error ? err.message : "工程事实保存失败");
    } finally {
      setSaving(false);
    }
  };

  const inputCls =
    "h-8 w-full rounded-md border border-background-300 bg-background-50 px-2.5 text-xs text-foreground-900 outline-none focus:border-primary-400 focus:ring-1 focus:ring-primary-400/20";
  const areaCls =
    "w-full resize-y rounded-md border border-background-300 bg-background-50 px-2.5 py-2 text-xs leading-relaxed text-foreground-900 outline-none focus:border-primary-400 focus:ring-1 focus:ring-primary-400/20";

  return (
    <div className="rounded-lg border border-accent-200/70 bg-accent-50/30">
      <button
        type="button"
        onClick={() => setOpen(!open)}
        className="flex w-full cursor-pointer items-center gap-2 px-4 py-3 text-left"
      >
        <i className="ri-building-2-line text-sm text-accent-600"></i>
        <span className="text-sm font-semibold text-foreground-900">工程事实</span>
        <span className="text-[11px] text-foreground-500">
          从招标文件提取，目录和正文都按这里写。工期 {facts.duration || "未识别"} · 质量 {facts.quality || "未识别"} ·
          重难点 {(facts.difficulties || []).length} 条
          {facts.edited ? " · 已人工修订" : ""}
        </span>
        <i className={`ml-auto text-base text-foreground-500 ${open ? "ri-arrow-up-s-line" : "ri-arrow-down-s-line"}`}></i>
      </button>
      {open && (
        <div className="space-y-3 border-t border-accent-200/60 px-4 py-3">
          <div className="grid grid-cols-1 gap-2.5 sm:grid-cols-2">
            {SCALAR_FIELDS.map((f) => (
              <label key={f.key} className={f.wide ? "sm:col-span-2" : ""}>
                <span className="mb-1 block text-[11px] font-medium text-foreground-600">{f.label}</span>
                <input
                  value={String(form[f.key] ?? "")}
                  onChange={(e) => setForm({ ...form, [f.key]: e.target.value })}
                  className={inputCls}
                />
              </label>
            ))}
            <label>
              <span className="mb-1 block text-[11px] font-medium text-foreground-600">技术标页数上限（0 为不限）</span>
              <input
                type="number"
                min={0}
                value={form.pageLimit ?? 0}
                onChange={(e) => setForm({ ...form, pageLimit: Math.max(0, Number(e.target.value) || 0) })}
                className={inputCls}
              />
            </label>
          </div>
          <label className="block">
            <span className="mb-1 block text-[11px] font-medium text-foreground-600">技术评分项（每行一项，每项成一章，标题照抄评分办法）</span>
            <textarea value={scoreText} onChange={(e) => setScoreText(e.target.value)} rows={4} className={areaCls} />
          </label>
          <label className="block">
            <span className="mb-1 block text-[11px] font-medium text-foreground-600">
              招标点名的重点难点（每行一条，「标题：说明」，每条单独成节并分析与措施两部分）
            </span>
            <textarea value={diffText} onChange={(e) => setDiffText(e.target.value)} rows={5} className={areaCls} />
          </label>
          <label className="block">
            <span className="mb-1 block text-[11px] font-medium text-foreground-600">补充重难点（招标未点名、按工程特点补充，最多 4 条）</span>
            <textarea value={extraText} onChange={(e) => setExtraText(e.target.value)} rows={3} className={areaCls} />
          </label>
          <label className="block">
            <span className="mb-1 block text-[11px] font-medium text-foreground-600">危大工程（每行一项，「名称：说明」）</span>
            <textarea value={hazardText} onChange={(e) => setHazardText(e.target.value)} rows={3} className={areaCls} />
          </label>
          {(water || hasWaterLedger(facts)) && (
            <div className="space-y-2.5 rounded-md border border-accent-200/80 bg-background-50/70 p-3">
              <div className="text-xs font-semibold text-foreground-800">水利事实账</div>
              <p className="text-[11px] leading-relaxed text-foreground-500">
                只填招标或设计文件里有的数。没有的留空，正文会标成待核实或待补，不会自行补坐标和等别。
              </p>
              <div className="grid grid-cols-1 gap-2.5 sm:grid-cols-2">
                <label>
                  <span className="mb-1 block text-[11px] font-medium text-foreground-600">治理总长</span>
                  <input
                    value={form.regionTotalLength || ""}
                    onChange={(e) => setForm({ ...form, regionTotalLength: e.target.value })}
                    className={inputCls}
                  />
                </label>
                <label className="flex items-end gap-2 pb-1 text-xs text-foreground-700">
                  <input
                    type="checkbox"
                    checked={Boolean(form.floodSeason?.spansFlood)}
                    onChange={(e) =>
                      setForm({ ...form, floodSeason: { ...(form.floodSeason || {}), spansFlood: e.target.checked } })
                    }
                  />
                  工期跨汛
                </label>
                {(
                  [
                    ["projectLevel", "工程等别"],
                    ["structureLevel", "建筑物级别"],
                    ["floodStandard", "设计洪水标准"],
                  ] as const
                ).map(([key, label]) => (
                  <label key={key}>
                    <span className="mb-1 block text-[11px] font-medium text-foreground-600">{label}</span>
                    <input
                      value={form.projectGrade?.[key] || ""}
                      onChange={(e) =>
                        setForm({ ...form, projectGrade: { ...(form.projectGrade || {}), [key]: e.target.value } })
                      }
                      className={inputCls}
                    />
                  </label>
                ))}
                <label>
                  <span className="mb-1 block text-[11px] font-medium text-foreground-600">导流方式</span>
                  <input
                    value={form.floodSeason?.diversionMethod || ""}
                    onChange={(e) =>
                      setForm({ ...form, floodSeason: { ...(form.floodSeason || {}), diversionMethod: e.target.value } })
                    }
                    className={inputCls}
                  />
                </label>
                <label>
                  <span className="mb-1 block text-[11px] font-medium text-foreground-600">停工撤离标准</span>
                  <input
                    value={form.floodSeason?.stopWorkRule || ""}
                    onChange={(e) =>
                      setForm({ ...form, floodSeason: { ...(form.floodSeason || {}), stopWorkRule: e.target.value } })
                    }
                    className={inputCls}
                  />
                </label>
                {(
                  [
                    ["boundaries", "工程四至"],
                    ["access", "对外交通"],
                    ["crsNote", "坐标系与高程系"],
                  ] as const
                ).map(([key, label]) => (
                  <label key={key} className="sm:col-span-2">
                    <span className="mb-1 block text-[11px] font-medium text-foreground-600">{label}</span>
                    <input
                      value={form.siteSurvey?.[key] || ""}
                      onChange={(e) =>
                        setForm({ ...form, siteSurvey: { ...(form.siteSurvey || {}), [key]: e.target.value } })
                      }
                      className={inputCls}
                    />
                  </label>
                ))}
              </div>
              {(
                [
                  [regionText, setRegionText, "治理区段（每行：名称｜长度｜主要工程量）"],
                  [nodeText, setNodeText, "控制性节点（每行：名称｜时间窗口｜约束）"],
                  [structureText, setStructureText, "构筑物（每行：名称｜座数｜规格，如 新建泵站｜2｜）"],
                  [pointText, setPointText, "敏感点（每行：名称｜类别｜说明，没有就留空）"],
                  [standardText, setStandardText, "招标写出的规范编号（每行一个）"],
                ] as const
              ).map(([value, setter, label]) => (
                <label key={label} className="block">
                  <span className="mb-1 block text-[11px] font-medium text-foreground-600">{label}</span>
                  <textarea value={value} onChange={(e) => setter(e.target.value)} rows={3} className={areaCls} />
                </label>
              ))}
            </div>
          )}
          <div className="flex items-center justify-between">
            <span className="text-[11px] text-foreground-500">保存后重新生成技术标目录生效；已生成的正文不会自动改写。</span>
            <button
              type="button"
              onClick={save}
              disabled={saving}
              className="flex h-8 cursor-pointer items-center gap-1.5 whitespace-nowrap rounded-md bg-primary-500 px-3 text-xs font-medium text-background-50 transition-colors hover:bg-primary-600 disabled:cursor-not-allowed disabled:opacity-60"
            >
              <i className={`${saving ? "ri-loader-4-line animate-spin" : "ri-save-line"} text-xs`}></i>
              保存工程事实
            </button>
          </div>
        </div>
      )}
    </div>
  );
}
