import { useEffect, useState } from "react";
import PageHeader from "../components/PageHeader";
import Toast from "../components/Toast";
import Modal from "../components/Modal";
import {
  ApiError,
  activateWeightTemplate,
  createRulePackage,
  createWeightTemplate,
  createWordRule,
  listCatalogRules,
  listRulePackages,
  listThresholds,
  listVetoRules,
  listWeightTemplates,
  listWordRules,
  updateRulePackage,
  updateThreshold,
  updateWordRule,
  type CatalogRule,
  type FillerWordRule,
  type RulePackage,
  type ThresholdRule,
  type VetoRule,
  type WeightTemplate,
} from "@/lib/api";

type TabKey = "weight" | "veto" | "business" | "tech" | "word" | "dup" | "threshold" | "strategy" | "package";

const tabs: { key: TabKey; label: string; icon: string }[] = [
  { key: "weight", label: "五维权重", icon: "ri-focus-3-line" },
  { key: "veto", label: "一票否决", icon: "ri-alarm-warning-line" },
  { key: "business", label: "商务自查", icon: "ri-briefcase-4-line" },
  { key: "tech", label: "技术评分", icon: "ri-cpu-line" },
  { key: "word", label: "虚词表", icon: "ri-voiceprint-line" },
  { key: "dup", label: "专项检查", icon: "ri-shield-check-line" },
  { key: "threshold", label: "查重阈值", icon: "ri-scales-3-line" },
  { key: "strategy", label: "高分策略", icon: "ri-lightbulb-line" },
  { key: "package", label: "属地细则包", icon: "ri-map-2-line" },
];

const dimLabel = [
  { key: "completeness", label: "完整性" },
  { key: "relevance", label: "针对性" },
  { key: "compliance", label: "合规性" },
  { key: "feasibility", label: "可落地性" },
  { key: "standardization", label: "规范性" },
] as const;

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
  const [activeTab, setActiveTab] = useState<TabKey>("weight");
  const [loading, setLoading] = useState(true);
  const [weightTemplates, setWeightTemplates] = useState<WeightTemplate[]>([]);
  const [wordList, setWordList] = useState<FillerWordRule[]>([]);
  const [thresholds, setThresholds] = useState<ThresholdRule[]>([]);
  const [packages, setPackages] = useState<RulePackage[]>([]);
  const [vetoRules, setVetoRules] = useState<VetoRule[]>([]);
  const [catalogRules, setCatalogRules] = useState<CatalogRule[]>([]);
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
    Promise.all([
      listWeightTemplates(),
      listWordRules(),
      listThresholds(),
      listRulePackages(),
      listVetoRules(),
      listCatalogRules(),
    ])
      .then(([weights, words, ths, pkgs, veto, catalog]) => {
        setWeightTemplates(weights);
        setWordList(words);
        setThresholds(ths);
        setPackages(pkgs);
        setVetoRules(veto);
        setCatalogRules(catalog);
      })
      .catch((err) => showToast(errMsg(err, "规则数据加载失败，请刷新重试"), "error"))
      .finally(() => setLoading(false));
  };

  useEffect(() => {
    loadAll();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const toggleWord = async (id: string, enabled: boolean) => {
    try {
      const updated = await updateWordRule(id, { enabled: !enabled });
      setWordList((prev) => prev.map((w) => (w.id === id ? updated : w)));
      showToast(updated.enabled ? "该虚词规则已启用" : "该虚词规则已停用，将不再进入预审判定");
    } catch (err) {
      showToast(errMsg(err, "更新失败，请稍后重试"), "error");
    }
  };

  const handleActivateWeight = async (id: string) => {
    try {
      const activated = await activateWeightTemplate(id);
      setWeightTemplates((prev) => prev.map((t) => (t.id === id ? activated : { ...t, active: false })));
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
      const updated = await updateThreshold(id, value);
      setThresholds((prev) => prev.map((t) => (t.id === id ? updated : t)));
      cancelEditThreshold(id);
      showToast(`「${updated.label}」已更新为 ${updated.value}${updated.unit}`);
    } catch (err) {
      showToast(errMsg(err, "更新失败，请稍后重试"), "error");
    }
  };

  const togglePackage = async (pkg: RulePackage) => {
    try {
      const updated = await updateRulePackage(pkg.id, { status: pkg.status === "启用" ? "停用" : "启用" });
      setPackages((prev) => prev.map((p) => (p.id === pkg.id ? updated : p)));
      showToast(updated.status === "启用" ? `已启用「${updated.name}」` : `已停用「${updated.name}」`);
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
    package: { label: "新增细则包", onClick: () => setPackageModalOpen(true) },
  };

  const catalogOf = (kind: CatalogRule["kind"]) => catalogRules.filter((r) => r.kind === kind);

  return (
    <div>
      <PageHeader
        title="预审规则配置"
        description="把青天口径做成可配置规则包，随招标文件与属地政策更新，而不改代码。规则调整会立即影响下一次预审的判定结果。"
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

      {/* 选项卡 */}
      <div className="mb-4 flex overflow-x-auto rounded-md border border-background-300 bg-background-100 p-0.5">
        {tabs.map((tab) => (
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
                    {weightTemplates.map((t) => (
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
                    {weightTemplates.length === 0 && (
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
              rules={vetoRules}
              icon="ri-alarm-warning-line"
              iconWrapClass="from-accent-400 to-accent-500"
              emptyText="暂无一票否决清单，请确认后端已完成规则入库"
              footer="清单来自青天一票否决口径，页面展示对照项与当前引擎接入状态。「接入判定」会进入废标结论；「部分接入」只覆盖部分子项。"
            />
          )}

          {/* 商务标打分自查项 */}
          {activeTab === "business" && (
            <CatalogGrid
              rules={catalogOf("business")}
              icon="ri-briefcase-4-line"
              iconWrapClass="from-secondary-400 to-secondary-500"
              emptyText="暂无商务自查清单，请确认后端已完成规则入库"
              footer="青天第二层「商务标 AI 打分自查项」。业绩四件套、资产负债率、报价偏离由商务核验（L2）部分接入；荣誉、本地化、人员、设备、信用仍为人工对照，不联网查询外部平台。"
            />
          )}

          {/* 技术标核心 AI 评分点 */}
          {activeTab === "tech" && (
            <CatalogGrid
              rules={catalogOf("tech")}
              icon="ri-cpu-line"
              iconWrapClass="from-primary-400 to-primary-600"
              emptyText="暂无技术评分模块，请确认后端已完成规则入库"
              footer="青天第三层「技术标核心 AI 评分点」。八个模块写入五维语义引擎（L3）Prompt，作为完整性/针对性/合规性/可落地性/规范性的判分参考，不按模块单独出分。"
            />
          )}

          {/* 虚词表 */}
          {activeTab === "word" && (
            <div className="overflow-hidden rounded-lg border border-background-300 bg-background-100">
              <div className="border-b border-background-300 bg-background-50 px-4 py-3">
                <div className="flex items-center gap-2 text-sm font-medium text-foreground-800">
                  <i className="ri-voiceprint-line text-primary-500"></i>
                  虚词表（六类虚词 / 改写对照，驱动 AI 预审 L4 虚词密度检测）
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
                    {wordList.map((w) => (
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
                    {wordList.length === 0 && (
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
              footer="青天第四层「AI 查重/防废标专项检查」。虚词密度、高危词句由 L4 接入判定；全文/专项查重比对内置模板库与本企业历史标书。跨项目阈值驱动本企业查重，不比对其他投标人。"
            />
          )}

          {/* 查重阈值 */}
          {activeTab === "threshold" && (
            <div className="overflow-hidden rounded-lg border border-background-300 bg-background-100">
              <div className="border-b border-background-300 bg-background-50 px-4 py-3">
                <div className="flex items-center gap-2 text-sm font-medium text-foreground-800">
                  <i className="ri-scales-3-line text-primary-500"></i>
                  查重与数值阈值（虚词密度、全文/专项查重、本企业跨项目查重、报价偏离、资产负债率）
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
                    {thresholds.map((t) => {
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
                                  onChange={(e) =>
                                    setThresholdEdits((prev) => ({ ...prev, [t.id]: e.target.value }))
                                  }
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
                                  onClick={() => cancelEditThreshold(t.id)}
                                  className="cursor-pointer whitespace-nowrap rounded-md border border-background-300 px-2.5 py-1 text-xs text-foreground-600 transition-colors hover:bg-background-200"
                                >
                                  取消
                                </button>
                                <button
                                  type="button"
                                  onClick={() => saveThreshold(t.id)}
                                  className="cursor-pointer whitespace-nowrap rounded-md bg-primary-500 px-2.5 py-1 text-xs font-medium text-background-50 transition-colors hover:bg-primary-600"
                                >
                                  保存
                                </button>
                              </div>
                            ) : (
                              <button
                                type="button"
                                onClick={() => startEditThreshold(t)}
                                className="cursor-pointer whitespace-nowrap rounded-md border border-background-300 px-2.5 py-1 text-xs text-foreground-600 transition-colors hover:bg-background-200"
                              >
                                编辑
                              </button>
                            )}
                          </td>
                        </tr>
                      );
                    })}
                    {thresholds.length === 0 && (
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
          )}

          {/* 高分编制策略建议 */}
          {activeTab === "strategy" && (
            <CatalogGrid
              rules={catalogOf("strategy")}
              icon="ri-lightbulb-line"
              iconWrapClass="from-primary-500 to-primary-600"
              emptyText="暂无高分策略清单，请确认后端已完成规则入库"
              footer="青天高分编制十条。部分条目已进入预审 Prompt 或版式/虚词引擎；数据链交叉验算、废止规范库仍为人工对照，不会虚构加分。"
            />
          )}

          {/* 属地细则包 */}
          {activeTab === "package" && (
            <div className="grid grid-cols-1 gap-3 md:grid-cols-2">
              {packages.map((pkg) => (
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
              {packages.length === 0 && (
                <div className="col-span-full rounded-lg border border-dashed border-background-300 bg-background-100/60 p-10 text-center text-sm text-foreground-500">
                  暂无属地细则包，点击右上角「新增细则包」创建
                </div>
              )}
              <div className="col-span-full rounded-md border border-dashed border-secondary-300 bg-secondary-50/40 px-4 py-2.5 text-xs text-secondary-700">
                启用中的属地细则由商务核验（L2）在正文已写到对应主题时检查量化要求，例如临边 1.2m、扫地杆距地 ≤20cm、扬尘六个 100%。停用后不再进入预审判定。
              </div>
            </div>
          )}
        </>
      )}

      {/* 新增权重模板 */}
      <AddWeightTemplateModal
        open={weightModalOpen}
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
        onClose={() => setWordModalOpen(false)}
        onCreated={(w) => {
          setWordList((prev) => [...prev, w]);
          setWordModalOpen(false);
          showToast(`已新增虚词规则「${w.word}」`);
        }}
        onError={(msg) => showToast(msg, "error")}
      />

      {/* 新增细则包 */}
      <AddRulePackageModal
        open={packageModalOpen}
        onClose={() => setPackageModalOpen(false)}
        onCreated={(p) => {
          setPackages((prev) => [...prev, p]);
          setPackageModalOpen(false);
          showToast(`已新增属地细则包「${p.name}」`);
        }}
        onError={(msg) => showToast(msg, "error")}
      />

      <Toast message={toast.message} type={toast.type} visible={toast.visible} />
    </div>
  );
}

function wiredBadgeClass(wired: VetoRule["wired"]) {
  if (wired === "接入判定") return "border-primary-200 bg-primary-50 text-primary-600";
  if (wired === "部分接入") return "border-amber-200 bg-amber-50 text-amber-700";
  return "border-secondary-200 bg-secondary-100 text-secondary-500";
}

function CatalogGrid({
  rules,
  icon,
  iconWrapClass,
  emptyText,
  footer,
}: {
  rules: VetoRule[];
  icon: string;
  iconWrapClass: string;
  emptyText: string;
  footer: string;
}) {
  return (
    <div className="grid grid-cols-1 gap-3 md:grid-cols-2">
      {rules.map((rule) => (
        <div
          key={rule.id}
          className="rounded-lg border border-background-300 bg-background-100 p-4 transition-all hover:border-primary-300/60"
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
                <span
                  className={`inline-flex shrink-0 items-center whitespace-nowrap rounded-md border px-2 py-0.5 text-xs font-medium ${wiredBadgeClass(rule.wired)}`}
                >
                  {rule.wired}
                </span>
              </div>
              <div className="mt-0.5 text-[11px] leading-5 text-foreground-500">{rule.point}</div>
            </div>
          </div>
          <div className="mt-3 flex flex-wrap gap-1.5">
            {rule.items.map((item) => (
              <span
                key={item}
                className="inline-flex items-center gap-1 rounded bg-secondary-100 px-1.5 py-0.5 text-[10px] text-secondary-700"
              >
                <i className="ri-checkbox-circle-line"></i>
                {item}
              </span>
            ))}
          </div>
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
  onClose,
  onCreated,
  onError,
}: {
  open: boolean;
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
      const created = await createWeightTemplate(form);
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
  onClose,
  onCreated,
  onError,
}: {
  open: boolean;
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
      const created = await createWordRule(form);
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
  onClose,
  onCreated,
  onError,
}: {
  open: boolean;
  onClose: () => void;
  onCreated: (p: RulePackage) => void;
  onError: (msg: string) => void;
}) {
  const [form, setForm] = useState({ name: "", region: "全国", itemsText: "" });
  const [submitting, setSubmitting] = useState(false);

  useEffect(() => {
    if (open) setForm({ name: "", region: "全国", itemsText: "" });
  }, [open]);

  const handleSubmit = async () => {
    if (!form.name.trim()) {
      onError("请填写细则包名称");
      return;
    }
    const items = form.itemsText
      .split("\n")
      .map((s) => s.trim())
      .filter(Boolean);
    setSubmitting(true);
    try {
      const created = await createRulePackage({ name: form.name, region: form.region, items });
      onCreated(created);
    } catch (err) {
      onError(err instanceof ApiError ? err.message : "新增失败，请稍后重试");
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <Modal open={open} onClose={onClose} title="新增属地细则包" subtitle="启用后由商务核验在对应主题出现时检查量化要求">
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
