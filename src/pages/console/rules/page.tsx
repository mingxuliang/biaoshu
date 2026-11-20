import { useEffect, useState } from "react";
import PageHeader from "../components/PageHeader";
import Toast from "../components/Toast";
import Modal from "../components/Modal";
import StandardRulesPanel from "./components/StandardRulesPanel";
import {
  ApiError,
  activateWeightTemplate,
  createRulePackage,
  createSwRulePackage,
  createWeightTemplate,
  createSwWordRule,
  createWordRule,
  listCatalogRules,
  listRulePackages,
  listSwCatalogRules,
  listSwRulePackages,
  listSwVetoRules,
  listSwThresholds,
  listSwWordRules,
  listThresholds,
  listVetoRules,
  listWeightTemplates,
  listWordRules,
  updateCatalogRule,
  updateRulePackage,
  updateSwCatalogRule,
  updateSwRulePackage,
  updateSwVetoRule,
  updateSwThreshold,
  updateSwWordRule,
  updateThreshold,
  updateVetoRule,
  updateWordRule,
  type CatalogRule,
  type FillerWordRule,
  type RulePackage,
  type RulePackagePayload,
  type ThresholdRule,
  type VetoRule,
  type WeightTemplate,
} from "@/lib/api";

type TabKey = "weight" | "veto" | "business" | "tech" | "word" | "dup" | "threshold" | "strategy" | "anon" | "package" | "standard";

// 标书类别只认用户在新建/编辑项目时的选择（工程类 / 软件服务类），与 src/mocks/projects.ts
// 的 isEngineeringCategory 同一套字面值约定。下面这五个 tab 的规则目录彻底按类别分两套独立
// 数据（工程类走 /api/rules/*，软件服务类走 /api/rules/sw/*），不是同一份数据加过滤。
type RuleView = "工程类" | "软件服务类";
const ENGINEERING_TABS: TabKey[] = ["weight", "veto", "business", "tech", "word", "dup", "threshold", "strategy", "anon", "package", "standard"];
const SOFTWARE_TABS: TabKey[] = ["weight", "veto", "business", "tech", "word", "dup", "threshold", "strategy", "anon", "package"];

const tabs: { key: TabKey; label: string; icon: string }[] = [
  { key: "weight", label: "五维权重", icon: "ri-focus-3-line" },
  { key: "veto", label: "一票否决", icon: "ri-alarm-warning-line" },
  { key: "business", label: "商务自查", icon: "ri-briefcase-4-line" },
  { key: "tech", label: "技术评分", icon: "ri-cpu-line" },
  { key: "word", label: "虚词表", icon: "ri-voiceprint-line" },
  { key: "dup", label: "专项检查", icon: "ri-shield-check-line" },
  { key: "threshold", label: "查重阈值", icon: "ri-scales-3-line" },
  { key: "strategy", label: "高分策略", icon: "ri-lightbulb-line" },
  { key: "anon", label: "暗标规则", icon: "ri-eye-off-line" },
  { key: "package", label: "属地细则包", icon: "ri-map-2-line" },
  { key: "standard", label: "规范对标", icon: "ri-ruler-line" },
];

const dimLabel = [
  { key: "completeness", label: "完整性" },
  { key: "relevance", label: "针对性" },
  { key: "compliance", label: "合规性" },
  { key: "feasibility", label: "可落地性" },
  { key: "standardization", label: "规范性" },
] as const;

const DUP_CARD_THRESHOLD_KEYS: Record<string, string[]> = {
  filler_density: ["filler_density_safe"],
  price_deviation: ["price_deviation_ok", "price_deviation_warn", "price_deviation_malicious"],
  asset_liability: ["asset_liability_ratio_max"],
};

const SIM_CARD_THRESHOLD_KEYS: Record<string, string[]> = {
  full_text_sim: ["full_text_similarity_safe", "full_text_similarity_risk"],
  key_section_sim: ["key_section_similarity_safe", "key_section_similarity_risk"],
  cross_bidder: ["cross_bidder_paragraph_risk", "cross_bidder_whole_risk"],
};

const TECH_CARD_THRESHOLD_KEYS: Record<string, string[]> = {
  qty_logic: ["qty_deviation_ok", "qty_material_mismatch", "excavator_m3_per_shift"],
};

const WORD_CATEGORIES = [
  "一类：万能动词",
  "二类：空洞形容词",
  "三类：承诺套话",
  "四类：无量化副词",
  "五类：连接废话与模板句",
  "六类：口号标语类",
];

interface ToastState {
  message: string;
  type: "success" | "error" | "info";
  visible: boolean;
}

const inputCls =
  "h-9 w-full rounded-md border border-background-300 bg-background-50 px-3 text-sm text-foreground-900 outline-none transition-all focus:border-primary-400 focus:ring-1 focus:ring-primary-400/20 placeholder:text-foreground-500";
const labelCls = "mb-1.5 block text-xs font-medium text-foreground-600";

export default function RulesPage() {
  const [ruleView, setRuleView] = useState<RuleView>("工程类");
  const [activeTab, setActiveTab] = useState<TabKey>("veto");
  const [ruleSpecialty, setRuleSpecialty] = useState("全部");
  const [loading, setLoading] = useState(true);
  const [swLoadError, setSwLoadError] = useState("");
  const [weightTemplates, setWeightTemplates] = useState<WeightTemplate[]>([]);
  const [wordList, setWordList] = useState<FillerWordRule[]>([]);
  const [swWordList, setSwWordList] = useState<FillerWordRule[]>([]);
  const [thresholds, setThresholds] = useState<ThresholdRule[]>([]);
  const [swThresholds, setSwThresholds] = useState<ThresholdRule[]>([]);
  const [packages, setPackages] = useState<RulePackage[]>([]);
  const [vetoRules, setVetoRules] = useState<VetoRule[]>([]);
  const [catalogRules, setCatalogRules] = useState<CatalogRule[]>([]);
  // 软件服务类标书专属规则目录，彻底独立于上面工程类四组 state，不混用。
  const [swPackages, setSwPackages] = useState<RulePackage[]>([]);
  const [swVetoRules, setSwVetoRules] = useState<VetoRule[]>([]);
  const [swCatalogRules, setSwCatalogRules] = useState<CatalogRule[]>([]);
  const [toast, setToast] = useState<ToastState>({ message: "", type: "success", visible: false });

  const [weightModalOpen, setWeightModalOpen] = useState(false);
  const [wordModalOpen, setWordModalOpen] = useState(false);
  const [packageModalOpen, setPackageModalOpen] = useState(false);
  const [thresholdEdits, setThresholdEdits] = useState<Record<string, string>>({});

  const showToast = (message: string, type: ToastState["type"] = "success") => {
    setToast({ message, type, visible: true });
    window.setTimeout(() => setToast((t) => ({ ...t, visible: false })), 3000);
  };

  const errMsg = (err: unknown, fallback: string) => (err instanceof ApiError ? err.message : fallback);

  const loadAll = () => {
    setLoading(true);
    // 目录（含暗标）单独落地。权重、虚词失败时，不能把已经返回的暗标、商务、技术规则一起丢掉。
    const engineeringJobs: Array<[Promise<unknown>, (value: never) => void, string]> = [
      [listWeightTemplates(), setWeightTemplates as (value: never) => void, "五维权重"],
      [listWordRules(), setWordList as (value: never) => void, "虚词表"],
      [listThresholds(), setThresholds as (value: never) => void, "查重阈值"],
      [listRulePackages(), setPackages as (value: never) => void, "属地细则包"],
      [listVetoRules(), setVetoRules as (value: never) => void, "一票否决"],
      [listCatalogRules(), setCatalogRules as (value: never) => void, "规则目录"],
    ];
    const engineering = (async () => {
      const failed: string[] = [];
      await Promise.all(
        engineeringJobs.map(async ([request, apply, label]) => {
          try {
            apply((await request) as never);
          } catch (err) {
            failed.push(`${label}：${errMsg(err, "加载失败")}`);
          }
        }),
      );
      if (failed.length) showToast(failed.join("；"), "error");
    })();
    // 五个接口各自落地。虚词、专项检查、查重阈值不因一票否决或目录 404 被一起清空。
    const software = (async () => {
      const jobs: Array<[Promise<unknown>, (value: never) => void, string]> = [
        [listSwRulePackages(), setSwPackages as (value: never) => void, "行业合规包"],
        [listSwVetoRules(), setSwVetoRules as (value: never) => void, "一票否决"],
        [listSwCatalogRules(), setSwCatalogRules as (value: never) => void, "规则目录"],
        [listSwWordRules(), setSwWordList as (value: never) => void, "虚词表"],
        [listSwThresholds(), setSwThresholds as (value: never) => void, "查重阈值"],
      ];
      const failed: string[] = [];
      await Promise.all(
        jobs.map(async ([request, apply, label]) => {
          try {
            apply((await request) as never);
          } catch (err) {
            failed.push(`${label}：${errMsg(err, "加载失败")}`);
          }
        }),
      );
      setSwLoadError(failed.length ? failed.join("；") : "");
    })();
    Promise.all([engineering, software]).finally(() => setLoading(false));
  };

  useEffect(() => {
    loadAll();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    const allowed = ruleView === "工程类" ? ENGINEERING_TABS : SOFTWARE_TABS;
    if (!allowed.includes(activeTab)) setActiveTab("veto");
  }, [ruleView, activeTab]);

  const toggleWord = async (id: string, enabled: boolean) => {
    const isSw = ruleView === "软件服务类";
    try {
      const updated = isSw ? await updateSwWordRule(id, { enabled: !enabled }) : await updateWordRule(id, { enabled: !enabled });
      const setter = isSw ? setSwWordList : setWordList;
      setter((prev) => prev.map((w) => (w.id === id ? updated : w)));
      showToast(updated.enabled ? "该虚词规则已启用" : "该虚词规则已停用，将不再进入预审判定");
    } catch (err) {
      showToast(errMsg(err, "更新失败，请稍后重试"), "error");
    }
  };

  const handleActivateWeight = async (id: string) => {
    try {
      const activated = await activateWeightTemplate(id);
      setWeightTemplates((prev) =>
        prev.map((t) => (t.id === id ? activated : (t.category || "工程类") === (activated.category || "工程类") ? { ...t, active: false } : t)),
      );
      showToast(`已启用「${activated.name}」，下一份预审报告将使用该权重`);
    } catch (err) {
      showToast(errMsg(err, "启用失败，请稍后重试"), "error");
    }
  };

  const startEditThreshold = (t: ThresholdRule) => {
    setThresholdEdits((prev) => ({ ...prev, [t.id]: String(t.value) }));
  };

  const cancelEditThreshold = (id: string) => {
    setThresholdEdits((prev) => {
      const next = { ...prev };
      delete next[id];
      return next;
    });
  };

  const saveThreshold = async (id: string) => {
    const raw = thresholdEdits[id];
    const value = Number(raw);
    if (!raw || Number.isNaN(value)) {
      showToast("请输入合法的数值", "error");
      return;
    }
    try {
      const updated = ruleView === "软件服务类" ? await updateSwThreshold(id, value) : await updateThreshold(id, value);
      const setter = ruleView === "软件服务类" ? setSwThresholds : setThresholds;
      setter((prev) => prev.map((t) => (t.id === id ? updated : t)));
      cancelEditThreshold(id);
      showToast(`「${updated.label}」已更新为 ${updated.value}${updated.unit}`);
    } catch (err) {
      showToast(errMsg(err, "更新失败，请稍后重试"), "error");
    }
  };

  const togglePackage = async (pkg: RulePackage) => {
    const isSw = ruleView === "软件服务类";
    try {
      const updated = isSw
        ? await updateSwRulePackage(pkg.id, { status: pkg.status === "启用" ? "停用" : "启用" })
        : await updateRulePackage(pkg.id, { status: pkg.status === "启用" ? "停用" : "启用" });
      const setter = isSw ? setSwPackages : setPackages;
      setter((prev) => prev.map((p) => (p.id === pkg.id ? updated : p)));
      showToast(updated.status === "启用" ? `已启用「${updated.name}」` : `已停用「${updated.name}」`);
    } catch (err) {
      showToast(errMsg(err, "更新失败，请稍后重试"), "error");
    }
  };

  const toggleVeto = async (rule: VetoRule) => {
    const isSw = ruleView === "软件服务类";
    try {
      const updated = isSw
        ? await updateSwVetoRule(rule.id, { enabled: !rule.enabled })
        : await updateVetoRule(rule.id, { enabled: !rule.enabled });
      const setter = isSw ? setSwVetoRules : setVetoRules;
      setter((prev) => prev.map((r) => (r.id === rule.id ? updated : r)));
      showToast(updated.enabled ? `已启用「${updated.category}」` : `已停用「${updated.category}」，引擎将跳过该项检查`);
    } catch (err) {
      showToast(errMsg(err, "更新失败，请稍后重试"), "error");
    }
  };

  const toggleCatalog = async (rule: CatalogRule) => {
    const isSw = ruleView === "软件服务类";
    try {
      const updated = isSw
        ? await updateSwCatalogRule(rule.id, { enabled: !rule.enabled })
        : await updateCatalogRule(rule.id, { enabled: !rule.enabled });
      const setter = isSw ? setSwCatalogRules : setCatalogRules;
      setter((prev) => prev.map((r) => (r.id === rule.id ? updated : r)));
      showToast(updated.enabled ? `已启用「${updated.category}」` : `已停用「${updated.category}」，引擎将跳过该项检查`);
    } catch (err) {
      showToast(errMsg(err, "更新失败，请稍后重试"), "error");
    }
  };

  const addButtonMeta: Record<TabKey, { label: string; onClick: () => void } | null> = {
    weight: { label: "新增权重模板", onClick: () => setWeightModalOpen(true) },
    veto: null,
    business: null,
    tech: null,
    word: { label: "新增虚词规则", onClick: () => setWordModalOpen(true) },
    dup: null,
    threshold: null,
    strategy: null,
    anon: null,
    package: { label: ruleView === "软件服务类" ? "新增行业合规包" : "新增细则包", onClick: () => setPackageModalOpen(true) },
    standard: null,
  };

  const isSwCategory = ruleView === "软件服务类";
  const viewWeightTemplates = weightTemplates.filter((t) => (t.category || "工程类") === ruleView);
  const selectRuleView = (view: RuleView) => {
    setRuleView(view);
    setActiveTab("veto");
  };
  const categoryTabs = ruleView === "工程类" ? ENGINEERING_TABS : SOFTWARE_TABS;
  const visibleTabs = tabs.filter((tab) => categoryTabs.includes(tab.key)).map((tab) => {
    if (tab.key !== "package") return tab;
    return { ...tab, label: isSwCategory ? "行业合规包" : "属地细则包" };
  });
  const activeVetoRules = isSwCategory ? swVetoRules : vetoRules;
  const activeCatalogRules = isSwCategory ? swCatalogRules : catalogRules;
  const activePackages = isSwCategory ? swPackages : packages;
  const activeWordList = isSwCategory ? swWordList : wordList;
  const activeThresholds = isSwCategory ? swThresholds : thresholds;
  const matchesSpecialty = (rule: { specialties?: string[] }) => {
    if (ruleSpecialty === "全部") return true;
    const list = rule.specialties?.length ? rule.specialties : ["通用"];
    return list.includes("通用") || list.includes(ruleSpecialty);
  };
  const catalogOf = (kind: CatalogRule["kind"]) => activeCatalogRules.filter((r) => r.kind === kind && matchesSpecialty(r));

  return (
    <div>
      <PageHeader
        title="预审规则配置"
        description={
          ruleView === "工程类"
            ? "当前只展示工程标预审规则，含五维权重、虚词、专项检查、查重阈值和规范对标。软件服务标有自己的一份，不会出现在这一页。"
            : "当前只展示软件服务标预审规则，含五维权重、虚词、专项检查和查重阈值。五维权重与工程标分开配置；不含规范对标和工程量等工程标专项内容。"
        }
        actions={
          addButtonMeta[activeTab] && (
            <button
              type="button"
              onClick={addButtonMeta[activeTab]!.onClick}
              className="flex h-9 cursor-pointer items-center gap-1.5 whitespace-nowrap rounded-md bg-primary-500 px-4 text-sm font-medium text-background-50 transition-colors hover:bg-primary-600"
            >
              <i className="ri-add-line text-sm"></i>
              {addButtonMeta[activeTab]!.label}
            </button>
          )
        }
      />

      {ruleView === "工程类" ? (
        <div className="mb-3 flex items-center gap-2 text-xs text-foreground-600">
          <span>适用专业</span>
          <select value={ruleSpecialty} onChange={(e) => setRuleSpecialty(e.target.value)} className="h-8 rounded-md border border-background-300 bg-background-50 px-2">
            {["全部", "水利", "房建", "市政", "公路"].map((item) => (
              <option key={item} value={item}>{item}</option>
            ))}
          </select>
        </div>
      ) : null}
      <div className="mb-4 flex flex-wrap gap-2">
        {(
          [
            ["工程类", "工程标预审规则"],
            ["软件服务类", "软件服务标预审规则"],
          ] as [RuleView, string][]
        ).map(([view, label]) => (
          <button
            key={view}
            type="button"
            onClick={() => selectRuleView(view)}
            className={`font-label cursor-pointer whitespace-nowrap rounded-md px-4 py-2 text-sm font-medium transition-all ${
              ruleView === view
                ? "bg-gradient-to-r from-primary-500 to-primary-600 text-background-50"
                : "border border-background-300 bg-background-100 text-foreground-600 hover:text-foreground-900"
            }`}
          >
            {label}
          </button>
        ))}
      </div>

      {/* 选项卡：工程标与软件服务标各自列出本类目录，虚词、专项检查、查重阈值也分表 */}
      <div className="mb-4 flex overflow-x-auto rounded-md border border-background-300 bg-background-100 p-0.5">
        {visibleTabs.map((tab) => (
          <button
            key={tab.key}
            type="button"
            onClick={() => setActiveTab(tab.key)}
            className={`font-label flex cursor-pointer items-center gap-1.5 whitespace-nowrap rounded-md px-3 py-2 text-sm font-medium transition-all ${
              activeTab === tab.key
                ? "bg-gradient-to-r from-primary-500 to-primary-600 text-background-50"
                : "text-foreground-600 hover:text-foreground-900"
            }`}
          >
            <i className={`${tab.icon} text-sm`}></i>
            {tab.label}
          </button>
        ))}
      </div>

      {ruleView === "软件服务类" && swLoadError && (
        <div className="mb-4 rounded-md border border-accent-200 bg-accent-50 px-4 py-2.5 text-xs text-accent-700">
          有的软件服务标规则没有读到（{swLoadError}）。已经读到的仍会显示，不会改用工程标规则。
        </div>
      )}

      {loading ? (
        <div className="flex items-center justify-center rounded-lg border border-background-300 bg-background-100 p-16">
          <span className="h-8 w-8 animate-spin rounded-full border-2 border-primary-200 border-t-primary-500" />
        </div>
      ) : (
        <>
          {/* 五维权重 */}
          {activeTab === "weight" && (
            <div className="overflow-hidden rounded-lg border border-background-300 bg-background-100">
              <div className="border-b border-background-300 bg-background-50 px-4 py-3">
                <div className="flex items-center justify-between">
                  <div className="flex items-center gap-2 text-sm font-medium text-foreground-800">
                    <i className="ri-focus-3-line text-primary-500"></i>
                    五维权重模板
                  </div>
                  <span className="font-label text-xs text-foreground-500">
                    当前启用模板将用于下一次预审的 L3 加权计算
                  </span>
                </div>
              </div>
              <div className="overflow-x-auto">
                <table className="w-full min-w-[820px] text-left">
                  <thead>
                    <tr className="font-label border-b border-background-300 bg-background-50 text-xs text-foreground-500">
                      <th className="px-4 py-2.5 font-medium">模板名称</th>
                      {dimLabel.map((d) => (
                        <th key={d.key} className="px-3 py-2.5 font-medium">
                          {d.label}
                        </th>
                      ))}
                      <th className="px-3 py-2.5 font-medium">适用范围</th>
                      <th className="px-3 py-2.5 font-medium">状态</th>
                      <th className="px-3 py-2.5 text-right font-medium">操作</th>
                    </tr>
                  </thead>
                  <tbody>
                    {viewWeightTemplates.map((t) => (
                      <tr
                        key={t.id}
                        className="group border-b border-background-200 transition-colors last:border-0 hover:bg-primary-50/30"
                      >
                        <td className="px-4 py-3">
                          <div className="flex items-center gap-2 text-sm font-medium text-foreground-900">
                            <i className="ri-settings-3-line text-primary-500"></i>
                            {t.name}
                          </div>
                        </td>
                        {dimLabel.map((d) => (
                          <td key={d.key} className="px-3 py-3">
                            <span className="font-heading text-gradient text-sm font-bold">{t[d.key]}%</span>
                          </td>
                        ))}
                        <td className="px-3 py-3">
                          <span className="whitespace-nowrap text-xs text-foreground-500">{t.scope}</span>
                        </td>
                        <td className="px-3 py-3">
                          <span
                            className={`inline-flex items-center whitespace-nowrap rounded-md border px-2 py-0.5 text-xs font-medium ${
                              t.active
                                ? "bg-primary-50 text-primary-600 border-primary-200"
                                : "bg-secondary-100 text-secondary-500 border-secondary-200"
                            }`}
                          >
                            {t.active ? "启用中" : "停用"}
                          </span>
                        </td>
                        <td className="px-3 py-3 text-right">
                          {!t.active && (
                            <button
                              type="button"
                              onClick={() => handleActivateWeight(t.id)}
                              className="cursor-pointer whitespace-nowrap rounded-md border border-primary-200 bg-primary-50 px-2.5 py-1 text-xs font-medium text-primary-600 transition-colors hover:bg-primary-100"
                            >
                              启用此模板
                            </button>
                          )}
                        </td>
                      </tr>
                    ))}
                    {viewWeightTemplates.length === 0 && (
                      <tr>
                        <td colSpan={8} className="px-4 py-10 text-center text-sm text-foreground-500">
                          暂无权重模板
                        </td>
                      </tr>
                    )}
                  </tbody>
                </table>
              </div>
            </div>
          )}

          {/* 一票否决 */}
          {activeTab === "veto" && (
            <CatalogGrid
              rules={activeVetoRules.filter(matchesSpecialty)}
              specialty={ruleSpecialty}
              icon="ri-alarm-warning-line"
              iconWrapClass="from-accent-400 to-accent-500"
              emptyText="暂无一票否决清单，请确认后端已完成规则入库"
              footer={
                isSwCategory
                  ? "软件服务类标书版一票否决清单，彻底独立于工程类表，不含安全生产许可证/建造师等施工专属条目。关闭开关后引擎跳过该项。蓝色为已接线的自动核验；灰色仍须人工（如社保联网）。"
                  : "关闭开关后引擎跳过该项。蓝色为已接线的自动核验；灰色仍须人工（如社保联网）。串标痕迹核验本企业历史标书 MD5 与长句，不比对其他投标人未公开文件。"
              }
              onToggle={toggleVeto}
            />
          )}

          {/* 商务标打分自查项 */}
          {activeTab === "business" && (
            <CatalogGrid
              specialty={ruleSpecialty}
              rules={catalogOf("business")}
              icon="ri-briefcase-4-line"
              iconWrapClass="from-secondary-400 to-secondary-500"
              emptyText="暂无商务自查清单，请确认后端已完成规则入库"
              footer={
                isSwCategory
                  ? "青天第二层「商务标 AI 打分自查项」软件服务类版本，不含设备机械等施工专属条目，研发运行环境替代设备机械。蓝色标签为已接入商务核验（L2）的子项，灰色为仍需人工对照。关闭开关后引擎将跳过该项检查。"
                  : "青天第二层「商务标 AI 打分自查项」。蓝色标签为已接入商务核验（L2）的子项，灰色为仍需人工对照（如专业对口、联网查失信）。关闭开关后引擎将跳过该项检查。"
              }
              onToggle={toggleCatalog}
            />
          )}

          {/* 技术标核心 AI 评分点 */}
          {activeTab === "tech" && (
            <CatalogGrid
              specialty={ruleSpecialty}
              rules={catalogOf("tech")}
              icon="ri-cpu-line"
              iconWrapClass="from-primary-400 to-primary-600"
              emptyText="暂无技术评分模块，请确认后端已完成规则入库"
              footer={
                isSwCategory
                  ? "青天第三层「技术标核心 AI 评分点」软件服务类版本。八个模块写入五维语义引擎（L3）Prompt，并做确定性核验，不含施工/工程量内容。关闭开关后该模块退出 Prompt 与核验。"
                  : "青天第三层「技术标核心 AI 评分点」。九个模块写入五维语义引擎（L3）Prompt，并做确定性核验；「工程量逻辑匹配」由 e_qty_logic 比对清单与标书数字。关闭开关后该模块退出 Prompt 与核验。"
              }
              onToggle={toggleCatalog}
              thresholds={activeThresholds}
              thresholdKeysByRule={isSwCategory ? undefined : TECH_CARD_THRESHOLD_KEYS}
              thresholdEdits={thresholdEdits}
              onStartEditThreshold={startEditThreshold}
              onCancelEditThreshold={cancelEditThreshold}
              onSaveThreshold={saveThreshold}
              onEditThresholdValue={(id, value) => setThresholdEdits((prev) => ({ ...prev, [id]: value }))}
            />
          )}

          {/* 虚词表 */}
          {activeTab === "word" && (
            <div className="overflow-hidden rounded-lg border border-background-300 bg-background-100">
              <div className="border-b border-background-300 bg-background-50 px-4 py-3">
                <div className="flex items-center gap-2 text-sm font-medium text-foreground-800">
                  <i className="ri-voiceprint-line text-primary-500"></i>
                  虚词表（六类空话口径 / 改写对照，仅供大模型虚词语义分析参考）
                </div>
              </div>
              <div className="overflow-x-auto">
                <table className="w-full min-w-[760px] text-left">
                  <thead>
                    <tr className="font-label border-b border-background-300 bg-background-50 text-xs text-foreground-500">
                      <th className="px-4 py-2.5 font-medium">类别</th>
                      <th className="px-3 py-2.5 font-medium">虚词 / 句式</th>
                      <th className="px-3 py-2.5 font-medium">危险等级</th>
                      <th className="px-3 py-2.5 font-medium">改写建议</th>
                      <th className="px-3 py-2.5 text-center font-medium">启用</th>
                    </tr>
                  </thead>
                  <tbody>
                    {activeWordList.map((w) => (
                      <tr
                        key={w.id}
                        className="group border-b border-background-200 transition-colors last:border-0 hover:bg-primary-50/30"
                      >
                        <td className="px-4 py-3">
                          <span className="inline-flex items-center whitespace-nowrap rounded bg-secondary-100 px-1.5 py-0.5 text-[10px] text-secondary-700">
                            {w.category}
                          </span>
                        </td>
                        <td className="px-3 py-3">
                          <span className="text-sm font-medium text-foreground-900">{w.word}</span>
                        </td>
                        <td className="px-3 py-3">
                          <span
                            className={`inline-flex items-center whitespace-nowrap rounded px-1.5 py-0.5 text-[10px] font-medium ${
                              w.level === "高危"
                                ? "bg-accent-50 text-accent-600"
                                : w.level === "低危"
                                  ? "bg-background-200 text-foreground-600"
                                  : "bg-secondary-100 text-secondary-700"
                            }`}
                          >
                            {w.level}
                          </span>
                        </td>
                        <td className="max-w-[260px] px-3 py-3 text-xs text-foreground-600">{w.rewrite || "—"}</td>
                        <td className="px-3 py-3 text-center">
                          <button
                            type="button"
                            onClick={() => toggleWord(w.id, w.enabled)}
                            className={`relative h-5 w-9 cursor-pointer rounded-full transition-colors ${
                              w.enabled ? "bg-primary-500" : "bg-background-300"
                            }`}
                            aria-label="启用开关"
                          >
                            <span
                              className={`absolute top-0.5 h-4 w-4 rounded-full bg-background-50 shadow-sm transition-all ${
                                w.enabled ? "left-[18px]" : "left-0.5"
                              }`}
                            />
                          </button>
                        </td>
                      </tr>
                    ))}
                    {activeWordList.length === 0 && (
                      <tr>
                        <td colSpan={5} className="px-4 py-10 text-center text-sm text-foreground-500">
                          暂无虚词规则
                        </td>
                      </tr>
                    )}
                  </tbody>
                </table>
              </div>
            </div>
          )}

          {/* AI 查重 / 防废标专项检查 */}
          {activeTab === "dup" && (
            <CatalogGrid
              rules={catalogOf("dup_check")}
              icon="ri-shield-check-line"
              iconWrapClass="from-amber-400 to-amber-500"
              emptyText="暂无专项检查清单，请确认后端已完成规则入库"
              footer="青天第四层专项检查。虚词由大模型阅读原文判定；报价偏离、资产负债率数值写在对应卡片内。关闭开关后引擎将跳过该项。"
              onToggle={toggleCatalog}
              thresholds={activeThresholds}
              thresholdKeysByRule={DUP_CARD_THRESHOLD_KEYS}
              thresholdEdits={thresholdEdits}
              onStartEditThreshold={startEditThreshold}
              onCancelEditThreshold={cancelEditThreshold}
              onSaveThreshold={saveThreshold}
              onEditThresholdValue={(id, value) => setThresholdEdits((prev) => ({ ...prev, [id]: value }))}
            />
          )}

          {/* 查重阈值 */}
          {activeTab === "threshold" && (
            <CatalogGrid
              rules={catalogOf("dup_sim")}
              icon="ri-scales-3-line"
              iconWrapClass="from-primary-500 to-primary-600"
              emptyText="暂无查重规则，请确认后端已完成规则入库"
              footer="这三项只用于「查重分析」比对两份技术标，不进入 AI 预审。卡片内数字可改；关闭开关后该项不参与点灯。"
              onToggle={toggleCatalog}
              thresholds={activeThresholds}
              thresholdKeysByRule={SIM_CARD_THRESHOLD_KEYS}
              thresholdEdits={thresholdEdits}
              onStartEditThreshold={startEditThreshold}
              onCancelEditThreshold={cancelEditThreshold}
              onSaveThreshold={saveThreshold}
              onEditThresholdValue={(id, value) => setThresholdEdits((prev) => ({ ...prev, [id]: value }))}
            />
          )}

          {/* 高分编制策略建议 */}
          {activeTab === "strategy" && (
            <CatalogGrid
              rules={catalogOf("strategy")}
              icon="ri-lightbulb-line"
              iconWrapClass="from-primary-500 to-primary-600"
              emptyText="暂无高分策略清单，请确认后端已完成规则入库"
              footer={
                isSwCategory
                  ? "青天高分编制十条软件服务类版本，「数据链逻辑闭环」替换为「接口与数据链路一致性」，不含塔吊/临建内容。蓝色为已进入预审引擎的子项，灰色为尚未自动核验、需人工对照的子项。关闭开关后引擎将跳过该项检查。"
                  : "青天高分编制十条。蓝色为已进入预审引擎的子项，灰色为尚未自动核验、需人工对照的子项。关闭开关后引擎将跳过该项检查。"
              }
              onToggle={toggleCatalog}
            />
          )}

          {activeTab === "anon" && (
            <CatalogGrid
              rules={catalogOf("anon")}
              icon="ri-eye-off-line"
              iconWrapClass="from-primary-500 to-primary-600"
              emptyText="暂无暗标规则，请确认后端已完成规则入库"
              footer={
                isSwCategory
                  ? "只在招标解析标明暗标或盲评时，单位名称、联系电话和文档作者才会判为问题。加粗只给建议。商务分册里的资质、业绩、人员证书和软著不算暗标违规。行距、页边距以招标文件为准，不自动废标。"
                  : "只在招标解析标明暗标或盲评时，单位名称和文档作者才会判为问题。加粗只给建议。行距、页边距以招标文件为准，不自动废标。"
              }
              onToggle={toggleCatalog}
            />
          )}

          {activeTab === "standard" && <StandardRulesPanel />}

          {/* 属地细则包 */}
          {activeTab === "package" && (
            <div className="grid grid-cols-1 gap-3 md:grid-cols-2">
              {activePackages.map((pkg) => (
                <div
                  key={pkg.id}
                  className="rounded-lg border border-background-300 bg-background-100 p-4 transition-all hover:border-primary-300/60"
                >
                  <div className="flex items-start gap-3">
                    <span className="flex h-10 w-10 shrink-0 items-center justify-center rounded-lg bg-gradient-to-br from-secondary-400 to-secondary-500 text-background-50">
                      <i className="ri-map-2-line text-lg"></i>
                    </span>
                    <div className="min-w-0 flex-1">
                      <div className="flex items-center justify-between gap-2">
                        <div className="text-sm font-medium text-foreground-900">{pkg.name}</div>
                        <button
                          type="button"
                          onClick={() => togglePackage(pkg)}
                          className={`inline-flex shrink-0 cursor-pointer items-center whitespace-nowrap rounded-md border px-2 py-0.5 text-xs font-medium transition-colors ${
                            pkg.status === "启用"
                              ? "bg-primary-50 text-primary-600 border-primary-200 hover:bg-primary-100"
                              : "bg-secondary-100 text-secondary-500 border-secondary-200 hover:bg-secondary-200"
                          }`}
                        >
                          {pkg.status}
                        </button>
                      </div>
                      <div className="mt-0.5 text-[11px] text-foreground-500">适用地区：{pkg.region}</div>
                    </div>
                  </div>
                  <div className="mt-3 flex flex-wrap gap-1.5">
                    {pkg.items.map((item) => (
                      <span
                        key={item}
                        className="inline-flex items-center gap-1 rounded bg-secondary-100 px-1.5 py-0.5 text-[10px] text-secondary-700"
                      >
                        <i className="ri-checkbox-circle-line"></i>
                        {item}
                      </span>
                    ))}
                  </div>
                </div>
              ))}
              {activePackages.length === 0 && (
                <div className="col-span-full rounded-lg border border-dashed border-background-300 bg-background-100/60 p-10 text-center text-sm text-foreground-500">
                  暂无{isSwCategory ? "行业合规包" : "属地细则包"}，点击右上角「新增细则包」创建
                </div>
              )}
              <div className="col-span-full rounded-md border border-dashed border-secondary-300 bg-secondary-50/40 px-4 py-2.5 text-xs text-secondary-700">
                {isSwCategory
                  ? "启用中的行业合规条目由商务核验（L2）在正文已写到对应主题时检查量化要求，例如等保测评报告编号、信创适配测试报告、数据出境安全评估。停用后不再进入预审判定。"
                  : "启用中的属地细则由商务核验（L2）在正文已写到对应主题时检查量化要求，例如临边 1.2m、扫地杆距地 ≤20cm、扬尘六个 100%。水利项目预审会自动去掉扬尘和临边，改核安全度汛。停用后不再进入预审判定。"}
              </div>
            </div>
          )}
        </>
      )}

      {/* 新增权重模板 */}
      <AddWeightTemplateModal
        open={weightModalOpen}
        category={ruleView}
        onClose={() => setWeightModalOpen(false)}
        onCreated={(t) => {
          setWeightTemplates((prev) => [...prev, t]);
          setWeightModalOpen(false);
          showToast(`已新增权重模板「${t.name}」`);
        }}
        onError={(msg) => showToast(msg, "error")}
      />

      {/* 新增虚词规则 */}
      <AddWordRuleModal
        open={wordModalOpen}
        isSw={isSwCategory}
        onClose={() => setWordModalOpen(false)}
        onCreated={(w) => {
          const setter = isSwCategory ? setSwWordList : setWordList;
          setter((prev) => [...prev, w]);
          setWordModalOpen(false);
          showToast(`已新增虚词规则「${w.word}」`);
        }}
        onError={(msg) => showToast(msg, "error")}
      />

      {/* 新增细则包：按当前选中的标书类别写入工程类或软件服务类独立表 */}
      <AddRulePackageModal
        open={packageModalOpen}
        isSw={isSwCategory}
        onClose={() => setPackageModalOpen(false)}
        onCreated={(p) => {
          const setter = isSwCategory ? setSwPackages : setPackages;
          setter((prev) => [...prev, p]);
          setPackageModalOpen(false);
          showToast(`已新增${isSwCategory ? "行业合规包" : "属地细则包"}「${p.name}」`);
        }}
        onError={(msg) => showToast(msg, "error")}
      />

      <Toast message={toast.message} type={toast.type} visible={toast.visible} />
    </div>
  );
}

function ThresholdTable({
  title,
  rows,
  thresholdEdits,
  onStartEdit,
  onCancelEdit,
  onSave,
  onEditValue,
}: {
  title: string;
  rows: ThresholdRule[];
  thresholdEdits: Record<string, string>;
  onStartEdit: (t: ThresholdRule) => void;
  onCancelEdit: (id: string) => void;
  onSave: (id: string) => void;
  onEditValue: (id: string, value: string) => void;
}) {
  return (
    <div className="overflow-hidden rounded-lg border border-background-300 bg-background-100">
      <div className="border-b border-background-300 bg-background-50 px-4 py-3">
        <div className="flex items-center gap-2 text-sm font-medium text-foreground-800">
          <i className="ri-scales-3-line text-primary-500"></i>
          {title}
        </div>
      </div>
      <div className="overflow-x-auto">
        <table className="w-full min-w-[680px] text-left">
          <thead>
            <tr className="font-label border-b border-background-300 bg-background-50 text-xs text-foreground-500">
              <th className="px-4 py-2.5 font-medium">规则</th>
              <th className="px-3 py-2.5 font-medium">说明</th>
              <th className="px-3 py-2.5 font-medium">当前值</th>
              <th className="px-3 py-2.5 text-right font-medium">操作</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((t) => {
              const editing = t.id in thresholdEdits;
              return (
                <tr
                  key={t.id}
                  className="group border-b border-background-200 transition-colors last:border-0 hover:bg-primary-50/30"
                >
                  <td className="px-4 py-3 text-sm font-medium text-foreground-900">{t.label}</td>
                  <td className="max-w-[320px] px-3 py-3 text-xs text-foreground-500">{t.description}</td>
                  <td className="px-3 py-3">
                    {editing ? (
                      <div className="flex items-center gap-1">
                        <input
                          type="number"
                          value={thresholdEdits[t.id]}
                          onChange={(e) => onEditValue(t.id, e.target.value)}
                          className="h-8 w-20 rounded-md border border-primary-300 bg-background-50 px-2 text-sm text-foreground-900 outline-none focus:ring-1 focus:ring-primary-400/30"
                        />
                        <span className="text-xs text-foreground-500">{t.unit}</span>
                      </div>
                    ) : (
                      <span className="inline-flex items-center gap-1.5 rounded-md bg-primary-50 px-2 py-1 text-sm font-semibold text-primary-600">
                        {t.value}
                        {t.unit}
                      </span>
                    )}
                  </td>
                  <td className="px-3 py-3 text-right">
                    {editing ? (
                      <div className="flex items-center justify-end gap-1.5">
                        <button
                          type="button"
                          onClick={() => onCancelEdit(t.id)}
                          className="cursor-pointer whitespace-nowrap rounded-md border border-background-300 px-2.5 py-1 text-xs text-foreground-600 transition-colors hover:bg-background-200"
                        >
                          取消
                        </button>
                        <button
                          type="button"
                          onClick={() => onSave(t.id)}
                          className="cursor-pointer whitespace-nowrap rounded-md bg-primary-500 px-2.5 py-1 text-xs font-medium text-background-50 transition-colors hover:bg-primary-600"
                        >
                          保存
                        </button>
                      </div>
                    ) : (
                      <button
                        type="button"
                        onClick={() => onStartEdit(t)}
                        className="cursor-pointer whitespace-nowrap rounded-md border border-background-300 px-2.5 py-1 text-xs text-foreground-600 transition-colors hover:bg-background-200"
                      >
                        编辑
                      </button>
                    )}
                  </td>
                </tr>
              );
            })}
            {rows.length === 0 && (
              <tr>
                <td colSpan={4} className="px-4 py-10 text-center text-sm text-foreground-500">
                  暂无阈值配置
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
}

function ThresholdInline({
  rows,
  thresholdEdits,
  onStartEdit,
  onCancelEdit,
  onSave,
  onEditValue,
}: {
  rows: ThresholdRule[];
  thresholdEdits: Record<string, string>;
  onStartEdit?: (t: ThresholdRule) => void;
  onCancelEdit?: (id: string) => void;
  onSave?: (id: string) => void;
  onEditValue?: (id: string, value: string) => void;
}) {
  if (rows.length === 0) return null;
  return (
    <div className="mt-3 space-y-2 border-t border-background-200 pt-3">
      {rows.map((t) => {
        const editing = t.id in thresholdEdits;
        return (
          <div key={t.id} className="flex items-center justify-between gap-2">
            <div className="min-w-0 text-xs font-medium text-foreground-800">{t.label}</div>
            <div className="flex shrink-0 items-center gap-1.5">
              {editing ? (
                <>
                  <input
                    type="number"
                    value={thresholdEdits[t.id]}
                    onChange={(e) => onEditValue?.(t.id, e.target.value)}
                    className="h-7 w-[4.5rem] rounded-md border border-primary-300 bg-background-50 px-2 text-sm text-foreground-900 outline-none focus:ring-1 focus:ring-primary-400/30"
                  />
                  <span className="text-[11px] text-foreground-500">{t.unit}</span>
                  <button
                    type="button"
                    onClick={() => onCancelEdit?.(t.id)}
                    className="cursor-pointer whitespace-nowrap rounded-md border border-background-300 px-2 py-0.5 text-[11px] text-foreground-600 transition-colors hover:bg-background-200"
                  >
                    取消
                  </button>
                  <button
                    type="button"
                    onClick={() => onSave?.(t.id)}
                    className="cursor-pointer whitespace-nowrap rounded-md bg-primary-500 px-2 py-0.5 text-[11px] font-medium text-background-50 transition-colors hover:bg-primary-600"
                  >
                    保存
                  </button>
                </>
              ) : (
                <>
                  <span className="inline-flex items-center gap-1 rounded-md bg-primary-50 px-2 py-0.5 text-sm font-semibold text-primary-600">
                    {t.value}
                    {t.unit}
                  </span>
                  <button
                    type="button"
                    onClick={() => onStartEdit?.(t)}
                    className="cursor-pointer whitespace-nowrap rounded-md border border-background-300 px-2 py-0.5 text-[11px] text-foreground-600 transition-colors hover:bg-background-200"
                  >
                    编辑
                  </button>
                </>
              )}
            </div>
          </div>
        );
      })}
    </div>
  );
}

function wiredBadgeClass(wired: VetoRule["wired"]) {
  if (wired === "接入判定") return "border-primary-200 bg-primary-50 text-primary-600";
  if (wired === "部分接入") return "border-amber-200 bg-amber-50 text-amber-700";
  return "border-secondary-200 bg-secondary-100 text-secondary-500";
}

function itemIsWired(rule: VetoRule, item: string): boolean {
  if (Array.isArray(rule.wiredItems)) {
    return rule.wiredItems.includes(item);
  }
  return rule.wired === "接入判定";
}

function CatalogGrid<T extends VetoRule>({
  rules,
  icon,
  iconWrapClass,
  emptyText,
  footer,
  onToggle,
  thresholds = [],
  thresholdKeysByRule,
  thresholdEdits = {},
  onStartEditThreshold,
  onCancelEditThreshold,
  onSaveThreshold,
  onEditThresholdValue,
  specialty = "全部",
}: {
  rules: T[];
  specialty?: string;
  icon: string;
  iconWrapClass: string;
  emptyText: string;
  footer: string;
  onToggle: (rule: T) => void;
  thresholds?: ThresholdRule[];
  thresholdKeysByRule?: Record<string, string[]>;
  thresholdEdits?: Record<string, string>;
  onStartEditThreshold?: (t: ThresholdRule) => void;
  onCancelEditThreshold?: (id: string) => void;
  onSaveThreshold?: (id: string) => void;
  onEditThresholdValue?: (id: string, value: string) => void;
}) {
  return (
    <div className="grid grid-cols-1 gap-3 md:grid-cols-2">
      {rules.map((rule) => (
        <div
          key={rule.id}
          className={`rounded-lg border border-background-300 bg-background-100 p-4 transition-all hover:border-primary-300/60 ${
            rule.enabled === false ? "opacity-60" : ""
          }`}
        >
          <div className="flex items-start gap-3">
            <span
              className={`flex h-10 w-10 shrink-0 items-center justify-center rounded-lg bg-gradient-to-br text-background-50 ${iconWrapClass}`}
            >
              <i className={`${icon} text-lg`}></i>
            </span>
            <div className="min-w-0 flex-1">
              <div className="flex items-center justify-between gap-2">
                <div className="text-sm font-medium text-foreground-900">{rule.category}</div>
                <div className="flex shrink-0 items-center gap-1.5">
                  <span
                    className={`inline-flex items-center whitespace-nowrap rounded-md border px-2 py-0.5 text-xs font-medium ${wiredBadgeClass(rule.wired)}`}
                  >
                    {rule.wired}
                  </span>
                  <button
                    type="button"
                    onClick={() => onToggle(rule)}
                    className={`relative h-5 w-9 cursor-pointer rounded-full transition-colors ${
                      rule.enabled !== false ? "bg-primary-500" : "bg-background-300"
                    }`}
                    aria-label="启用开关"
                    title={rule.enabled !== false ? "点击停用该规则" : "点击启用该规则"}
                  >
                    <span
                      className={`absolute top-0.5 h-4 w-4 rounded-full bg-background-50 shadow-sm transition-all ${
                        rule.enabled !== false ? "left-[18px]" : "left-0.5"
                      }`}
                    />
                  </button>
                </div>
              </div>
              <div className="mt-0.5 text-[11px] leading-5 text-foreground-500">{rule.point}</div>
              <div className="mt-1 text-[10px] text-foreground-400">适用：{(rule.specialties || ["通用"]).join("、")}</div>
            </div>
          </div>
          <div className="mt-3 flex flex-wrap gap-1.5">
            {rule.items.filter((item) => {
              const limit = rule.itemSpecialties?.[item];
              return !limit || specialty === "全部" || limit.includes(specialty);
            }).map((item) => {
              const wired = itemIsWired(rule, item);
              return (
                <span
                  key={item}
                  title={wired ? "已接入自动核验" : "尚未接入，需人工对照"}
                  className={
                    wired
                      ? "inline-flex items-center gap-1 rounded bg-primary-500 px-1.5 py-0.5 text-[10px] text-white"
                      : "inline-flex items-center gap-1 rounded bg-secondary-100 px-1.5 py-0.5 text-[10px] text-secondary-700"
                  }
                >
                  <i className={wired ? "ri-checkbox-circle-fill" : "ri-checkbox-blank-circle-line"}></i>
                  {item}
                </span>
              );
            })}
          </div>
          {thresholdKeysByRule && (
            <ThresholdInline
              rows={(thresholdKeysByRule[rule.key] || [])
                .map((key) => thresholds.find((t) => t.key === key))
                .filter((t): t is ThresholdRule => Boolean(t))}
              thresholdEdits={thresholdEdits}
              onStartEdit={onStartEditThreshold}
              onCancelEdit={onCancelEditThreshold}
              onSave={onSaveThreshold}
              onEditValue={onEditThresholdValue}
            />
          )}
          {rule.wired === "部分接入" && (
            <div className="mt-2 flex flex-wrap items-center gap-3 text-[10px] text-foreground-500">
              <span className="inline-flex items-center gap-1">
                <span className="h-2 w-2 rounded-sm bg-primary-500" />
                已接入
              </span>
              <span className="inline-flex items-center gap-1">
                <span className="h-2 w-2 rounded-sm bg-secondary-200" />
                未接入
              </span>
            </div>
          )}
          {rule.wiredNote && (
            <div className="mt-3 text-[11px] leading-5 text-foreground-500">{rule.wiredNote}</div>
          )}
        </div>
      ))}
      {rules.length === 0 && (
        <div className="col-span-full rounded-lg border border-dashed border-background-300 bg-background-100/60 p-10 text-center text-sm text-foreground-500">
          {emptyText}
        </div>
      )}
      <div className="col-span-full rounded-md border border-dashed border-secondary-300 bg-secondary-50/40 px-4 py-2.5 text-xs text-secondary-700">
        {footer}
      </div>
    </div>
  );
}

function AddWeightTemplateModal({
  open,
  category,
  onClose,
  onCreated,
  onError,
}: {
  open: boolean;
  category: "工程类" | "软件服务类";
  onClose: () => void;
  onCreated: (t: WeightTemplate) => void;
  onError: (msg: string) => void;
}) {
  const [form, setForm] = useState({
    name: "",
    scope: "按项目类型",
    completeness: 30,
    relevance: 25,
    compliance: 20,
    feasibility: 15,
    standardization: 10,
  });
  const [submitting, setSubmitting] = useState(false);

  useEffect(() => {
    if (open) {
      setForm({ name: "", scope: "按项目类型", completeness: 30, relevance: 25, compliance: 20, feasibility: 15, standardization: 10 });
    }
  }, [open]);

  const total = form.completeness + form.relevance + form.compliance + form.feasibility + form.standardization;

  const numField = (key: keyof typeof form) => (
    <input
      type="number"
      value={form[key] as number}
      onChange={(e) => setForm((f) => ({ ...f, [key]: Number(e.target.value) }))}
      className={inputCls}
    />
  );

  const handleSubmit = async () => {
    if (!form.name.trim()) {
      onError("请填写模板名称");
      return;
    }
    if (total !== 100) {
      onError(`五维权重之和必须为 100，当前为 ${total}`);
      return;
    }
    setSubmitting(true);
    try {
      const created = await createWeightTemplate({ ...form, category });
      onCreated(created);
    } catch (err) {
      onError(err instanceof ApiError ? err.message : "新增失败，请稍后重试");
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <Modal open={open} onClose={onClose} title="新增权重模板" subtitle="五维权重之和必须为 100">
      <div className="space-y-3">
        <div>
          <label className={labelCls}>模板名称</label>
          <input
            type="text"
            value={form.name}
            onChange={(e) => setForm((f) => ({ ...f, name: e.target.value }))}
            placeholder="例如：EPC 总承包"
            className={inputCls}
          />
        </div>
        <div>
          <label className={labelCls}>适用范围</label>
          <input
            type="text"
            value={form.scope}
            onChange={(e) => setForm((f) => ({ ...f, scope: e.target.value }))}
            className={inputCls}
          />
        </div>
        <div className="grid grid-cols-2 gap-3 sm:grid-cols-3">
          {dimLabel.map((d) => (
            <div key={d.key}>
              <label className={labelCls}>
                {d.label}（%）
              </label>
              {numField(d.key)}
            </div>
          ))}
        </div>
        <p className={`text-xs ${total === 100 ? "text-foreground-500" : "text-accent-600"}`}>
          当前合计：{total}%{total !== 100 && "（须调整为 100）"}
        </p>
        <div className="flex items-center justify-end gap-2 pt-2">
          <button
            type="button"
            onClick={onClose}
            className="h-9 cursor-pointer whitespace-nowrap rounded-md border border-background-300 px-4 text-sm font-medium text-foreground-600 transition-colors hover:bg-background-200"
          >
            取消
          </button>
          <button
            type="button"
            disabled={submitting}
            onClick={handleSubmit}
            className="flex h-9 cursor-pointer items-center gap-1.5 whitespace-nowrap rounded-md bg-primary-500 px-4 text-sm font-medium text-background-50 transition-colors hover:bg-primary-600 disabled:opacity-60"
          >
            {submitting ? "提交中…" : "创建模板"}
          </button>
        </div>
      </div>
    </Modal>
  );
}

function AddWordRuleModal({
  open,
  isSw = false,
  onClose,
  onCreated,
  onError,
}: {
  open: boolean;
  isSw?: boolean;
  onClose: () => void;
  onCreated: (w: FillerWordRule) => void;
  onError: (msg: string) => void;
}) {
  const [form, setForm] = useState({ category: WORD_CATEGORIES[0], level: "中危" as "高危" | "中危" | "低危", word: "", rewrite: "" });
  const [submitting, setSubmitting] = useState(false);

  useEffect(() => {
    if (open) setForm({ category: WORD_CATEGORIES[0], level: "中危", word: "", rewrite: "" });
  }, [open]);

  const handleSubmit = async () => {
    if (!form.word.trim()) {
      onError("请填写虚词/句式内容");
      return;
    }
    setSubmitting(true);
    try {
      const created = isSw ? await createSwWordRule(form) : await createWordRule(form);
      onCreated(created);
    } catch (err) {
      onError(err instanceof ApiError ? err.message : "新增失败，请稍后重试");
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <Modal open={open} onClose={onClose} title="新增虚词规则">
      <div className="space-y-3">
        <div>
          <label className={labelCls}>分类</label>
          <select
            value={form.category}
            onChange={(e) => setForm((f) => ({ ...f, category: e.target.value }))}
            className={`${inputCls} cursor-pointer`}
          >
            {WORD_CATEGORIES.map((c) => (
              <option key={c} value={c}>
                {c}
              </option>
            ))}
          </select>
        </div>
        <div>
          <label className={labelCls}>危险等级</label>
          <select
            value={form.level}
            onChange={(e) => setForm((f) => ({ ...f, level: e.target.value as "高危" | "中危" | "低危" }))}
            className={`${inputCls} cursor-pointer`}
          >
            <option value="高危">高危</option>
            <option value="中危">中危</option>
            <option value="低危">低危</option>
          </select>
        </div>
        <div>
          <label className={labelCls}>虚词 / 句式</label>
          <input
            type="text"
            value={form.word}
            onChange={(e) => setForm((f) => ({ ...f, word: e.target.value }))}
            placeholder="例如：确保"
            className={inputCls}
          />
        </div>
        <div>
          <label className={labelCls}>改写建议（高危命中时写入预审建议）</label>
          <input
            type="text"
            value={form.rewrite}
            onChange={(e) => setForm((f) => ({ ...f, rewrite: e.target.value }))}
            placeholder="例如：一次验收合格率≥99%"
            className={inputCls}
          />
        </div>
        <div className="flex items-center justify-end gap-2 pt-2">
          <button
            type="button"
            onClick={onClose}
            className="h-9 cursor-pointer whitespace-nowrap rounded-md border border-background-300 px-4 text-sm font-medium text-foreground-600 transition-colors hover:bg-background-200"
          >
            取消
          </button>
          <button
            type="button"
            disabled={submitting}
            onClick={handleSubmit}
            className="flex h-9 cursor-pointer items-center gap-1.5 whitespace-nowrap rounded-md bg-primary-500 px-4 text-sm font-medium text-background-50 transition-colors hover:bg-primary-600 disabled:opacity-60"
          >
            {submitting ? "提交中…" : "新增"}
          </button>
        </div>
      </div>
    </Modal>
  );
}

function AddRulePackageModal({
  open,
  isSw = false,
  onClose,
  onCreated,
  onError,
}: {
  open: boolean;
  isSw?: boolean;
  onClose: () => void;
  onCreated: (p: RulePackage) => void;
  onError: (msg: string) => void;
}) {
  const [form, setForm] = useState({ name: "", region: isSw ? "行业通用" : "全国", itemsText: "" });
  const [submitting, setSubmitting] = useState(false);

  useEffect(() => {
    if (open) setForm({ name: "", region: isSw ? "行业通用" : "全国", itemsText: "" });
  }, [open, isSw]);

  const handleSubmit = async () => {
    if (!form.name.trim()) {
      onError("请填写细则包名称");
      return;
    }
    const items = form.itemsText
      .split("\n")
      .map((s) => s.trim())
      .filter(Boolean);
    const payload: RulePackagePayload = { name: form.name, region: form.region, items };
    setSubmitting(true);
    try {
      const created = isSw ? await createSwRulePackage(payload) : await createRulePackage(payload);
      onCreated(created);
    } catch (err) {
      onError(err instanceof ApiError ? err.message : "新增失败，请稍后重试");
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <Modal
      open={open}
      onClose={onClose}
      title={isSw ? "新增行业合规包" : "新增属地细则包"}
      subtitle="启用后由商务核验在对应主题出现时检查量化要求"
    >
      <div className="space-y-3">
        <div>
          <label className={labelCls}>细则包名称</label>
          <input
            type="text"
            value={form.name}
            onChange={(e) => setForm((f) => ({ ...f, name: e.target.value }))}
            placeholder="例如：夜间施工噪音管控细则包"
            className={inputCls}
          />
        </div>
        <div>
          <label className={labelCls}>适用地区</label>
          <input
            type="text"
            value={form.region}
            onChange={(e) => setForm((f) => ({ ...f, region: e.target.value }))}
            className={inputCls}
          />
        </div>
        <div>
          <label className={labelCls}>条目（每行一条）</label>
          <textarea
            value={form.itemsText}
            onChange={(e) => setForm((f) => ({ ...f, itemsText: e.target.value }))}
            rows={4}
            placeholder={"例如：\n噪音监测点位覆盖率 100%\n夜间作业审批留档"}
            className="w-full resize-none rounded-md border border-background-300 bg-background-50 px-3 py-2 text-sm text-foreground-900 outline-none transition-all focus:border-primary-400 focus:ring-1 focus:ring-primary-400/20 placeholder:text-foreground-500"
          />
        </div>
        <div className="flex items-center justify-end gap-2 pt-2">
          <button
            type="button"
            onClick={onClose}
            className="h-9 cursor-pointer whitespace-nowrap rounded-md border border-background-300 px-4 text-sm font-medium text-foreground-600 transition-colors hover:bg-background-200"
          >
            取消
          </button>
          <button
            type="button"
            disabled={submitting}
            onClick={handleSubmit}
            className="flex h-9 cursor-pointer items-center gap-1.5 whitespace-nowrap rounded-md bg-primary-500 px-4 text-sm font-medium text-background-50 transition-colors hover:bg-primary-600 disabled:opacity-60"
          >
            {submitting ? "提交中…" : "创建细则包"}
          </button>
        </div>
      </div>
    </Modal>
  );
}
