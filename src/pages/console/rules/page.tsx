import { useState } from "react";
import PageHeader from "../components/PageHeader";
import Toast from "../components/Toast";
import { weightTemplates, wordRules, thresholdRules, rulePackages } from "@/mocks/rules";

type TabKey = "weight" | "word" | "threshold" | "package";

const tabs: { key: TabKey; label: string; icon: string }[] = [
  { key: "weight", label: "五维权重", icon: "ri-focus-3-line" },
  { key: "word", label: "虚词表", icon: "ri-voiceprint-line" },
  { key: "threshold", label: "查重阈值", icon: "ri-scales-3-line" },
  { key: "package", label: "属地细则包", icon: "ri-map-2-line" },
];

const dimLabel = [
  { key: "completeness", label: "完整性" },
  { key: "relevance", label: "针对性" },
  { key: "compliance", label: "合规性" },
  { key: "feasibility", label: "可落地性" },
  { key: "standardization", label: "规范性" },
] as const;

interface ToastState {
  message: string;
  type: "success" | "error" | "info";
  visible: boolean;
}

export default function RulesPage() {
  const [activeTab, setActiveTab] = useState<TabKey>("weight");
  const [wordList, setWordList] = useState(wordRules);
  const [toast, setToast] = useState<ToastState>({ message: "", type: "success", visible: false });

  const showToast = (message: string, type: ToastState["type"] = "success") => {
    setToast({ message, type, visible: true });
    window.setTimeout(() => setToast((t) => ({ ...t, visible: false })), 3000);
  };

  const toggleWord = (id: string) => {
    setWordList((prev) => prev.map((w) => (w.id === id ? { ...w, enabled: !w.enabled } : w)));
    showToast("虚词规则已更新，版本号将进入下一份预审报告", "info");
  };

  return (
    <div>
      <PageHeader
        title="预审规则配置"
        description="把青天口径做成可配置规则包，随招标文件与属地政策更新，而不改代码。规则版本号将记录进每一份预审报告。"
        actions={
          <button
            type="button"
            onClick={() => showToast("已新建规则草稿并进入编辑模式", "info")}
            className="flex h-9 cursor-pointer items-center gap-1.5 whitespace-nowrap rounded-md bg-primary-500 px-4 text-sm font-medium text-background-50 transition-colors hover:bg-primary-600"
          >
            <i className="ri-add-line text-sm"></i>
            新增规则
          </button>
        }
      />

      {/* 选项卡 */}
      <div className="mb-4 flex rounded-md border border-background-300 bg-background-100 p-0.5">
        {tabs.map((tab) => (
          <button
            key={tab.key}
            type="button"
            onClick={() => setActiveTab(tab.key)}
            className={`font-label flex cursor-pointer items-center gap-1.5 whitespace-nowrap rounded-md px-4 py-2 text-sm font-medium transition-all ${
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

      {/* 五维权重 */}
      {activeTab === "weight" && (
        <div className="overflow-hidden rounded-lg border border-background-300 bg-background-100">
          <div className="border-b border-background-300 bg-background-50 px-4 py-3">
            <div className="flex items-center justify-between">
              <div className="flex items-center gap-2 text-sm font-medium text-foreground-800">
                <i className="ri-focus-3-line text-primary-500"></i>
                五维权重模板
              </div>
              <span className="font-label text-xs text-foreground-500">默认权重可在项目级被招标文件覆盖</span>
            </div>
          </div>
          <div className="overflow-x-auto">
            <table className="w-full min-w-[760px] text-left">
              <thead>
                <tr className="font-label border-b border-background-300 bg-background-50 text-xs text-foreground-500">
                  <th className="px-4 py-2.5 font-medium">模板名称</th>
                  {dimLabel.map((d) => (
                    <th key={d.key} className="px-3 py-2.5 font-medium">{d.label}</th>
                  ))}
                  <th className="px-3 py-2.5 font-medium">适用范围</th>
                  <th className="px-3 py-2.5 font-medium">状态</th>
                </tr>
              </thead>
              <tbody>
                {weightTemplates.map((t) => (
                  <tr key={t.id} className="group border-b border-background-200 transition-colors last:border-0 hover:bg-primary-50/30">
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
                      <span className={`inline-flex items-center whitespace-nowrap rounded-md border px-2 py-0.5 text-xs font-medium ${
                        t.active ? "bg-primary-50 text-primary-600 border-primary-200" : "bg-secondary-100 text-secondary-500 border-secondary-200"
                      }`}>
                        {t.active ? "启用中" : "停用"}
                      </span>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {/* 虚词表 */}
      {activeTab === "word" && (
        <div className="overflow-hidden rounded-lg border border-background-300 bg-background-100">
          <div className="border-b border-background-300 bg-background-50 px-4 py-3">
            <div className="flex items-center gap-2 text-sm font-medium text-foreground-800">
              <i className="ri-voiceprint-line text-primary-500"></i>
              虚词表（六类虚词 / 高危句式 / 改写对照）
            </div>
          </div>
          <div className="overflow-x-auto">
            <table className="w-full min-w-[860px] text-left">
              <thead>
                <tr className="font-label border-b border-background-300 bg-background-50 text-xs text-foreground-500">
                  <th className="px-4 py-2.5 font-medium">类别</th>
                  <th className="px-3 py-2.5 font-medium">虚词 / 句式</th>
                  <th className="px-3 py-2.5 font-medium">识别规则</th>
                  <th className="px-3 py-2.5 font-medium">改写建议</th>
                  <th className="px-3 py-2.5 text-center font-medium">启用</th>
                </tr>
              </thead>
              <tbody>
                {wordList.map((w) => (
                  <tr key={w.id} className="group border-b border-background-200 transition-colors last:border-0 hover:bg-primary-50/30">
                    <td className="px-4 py-3">
                      <span className="inline-flex items-center whitespace-nowrap rounded bg-secondary-100 px-1.5 py-0.5 text-[10px] text-secondary-700">{w.category}</span>
                    </td>
                    <td className="px-3 py-3">
                      <span className="text-sm font-medium text-foreground-900">{w.word}</span>
                    </td>
                    <td className="px-3 py-3">
                      <code className="rounded bg-background-200 px-1.5 py-0.5 font-label text-xs text-foreground-600">{w.pattern}</code>
                    </td>
                    <td className="max-w-[260px] px-3 py-3 text-xs text-foreground-600">{w.rewrite}</td>
                    <td className="px-3 py-3 text-center">
                      <button
                        type="button"
                        onClick={() => toggleWord(w.id)}
                        className={`relative h-5 w-9 cursor-pointer rounded-full transition-colors ${w.enabled ? "bg-primary-500" : "bg-background-300"}`}
                        aria-label="启用开关"
                      >
                        <span
                          className={`absolute top-0.5 h-4 w-4 rounded-full bg-background-50 shadow-sm transition-all ${w.enabled ? "left-[18px]" : "left-0.5"}`}
                        />
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {/* 查重阈值 */}
      {activeTab === "threshold" && (
        <div className="overflow-hidden rounded-lg border border-background-300 bg-background-100">
          <div className="border-b border-background-300 bg-background-50 px-4 py-3">
            <div className="flex items-center gap-2 text-sm font-medium text-foreground-800">
              <i className="ri-scales-3-line text-primary-500"></i>
              查重阈值配置
            </div>
          </div>
          <div className="overflow-x-auto">
            <table className="w-full min-w-[720px] text-left">
              <thead>
                <tr className="font-label border-b border-background-300 bg-background-50 text-xs text-foreground-500">
                  <th className="px-4 py-2.5 font-medium">规则</th>
                  <th className="px-3 py-2.5 font-medium">安全线</th>
                  <th className="px-3 py-2.5 font-medium">风险线</th>
                  <th className="px-3 py-2.5 font-medium">项目类型</th>
                </tr>
              </thead>
              <tbody>
                {thresholdRules.map((t) => (
                  <tr key={t.id} className="group border-b border-background-200 transition-colors last:border-0 hover:bg-primary-50/30">
                    <td className="px-4 py-3 text-sm font-medium text-foreground-900">{t.name}</td>
                    <td className="px-3 py-3">
                      <span className="inline-flex items-center gap-1.5 rounded-md bg-primary-50 px-2 py-1 text-sm font-semibold text-primary-600">
                        ≤ {t.safe}%
                      </span>
                    </td>
                    <td className="px-3 py-3">
                      <span className="inline-flex items-center gap-1.5 rounded-md bg-accent-50 px-2 py-1 text-sm font-semibold text-accent-600">
                        &gt; {t.risk}%
                      </span>
                    </td>
                    <td className="px-3 py-3">
                      <span className="whitespace-nowrap text-xs text-foreground-500">{t.projectType}</span>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {/* 属地细则包 */}
      {activeTab === "package" && (
        <div className="grid grid-cols-1 gap-3 md:grid-cols-2">
          {rulePackages.map((pkg) => (
            <div key={pkg.id} className="rounded-lg border border-background-300 bg-background-100 p-4 transition-all hover:border-primary-300/60">
              <div className="flex items-start gap-3">
                <span className="flex h-10 w-10 shrink-0 items-center justify-center rounded-lg bg-gradient-to-br from-secondary-400 to-secondary-500 text-background-50">
                  <i className="ri-map-2-line text-lg"></i>
                </span>
                <div className="min-w-0 flex-1">
                  <div className="flex items-center justify-between">
                    <div className="text-sm font-medium text-foreground-900">{pkg.name}</div>
                    <span className={`inline-flex items-center whitespace-nowrap rounded-md border px-2 py-0.5 text-xs font-medium ${
                      pkg.status === "启用" ? "bg-primary-50 text-primary-600 border-primary-200" : "bg-secondary-100 text-secondary-500 border-secondary-200"
                    }`}>
                      {pkg.status}
                    </span>
                  </div>
                  <div className="mt-0.5 text-[11px] text-foreground-500">适用地区：{pkg.region}</div>
                </div>
              </div>
              <div className="mt-3 flex flex-wrap gap-1.5">
                {pkg.items.map((item) => (
                  <span key={item} className="inline-flex items-center gap-1 rounded bg-secondary-100 px-1.5 py-0.5 text-[10px] text-secondary-700">
                    <i className="ri-checkbox-circle-line"></i>
                    {item}
                  </span>
                ))}
              </div>
            </div>
          ))}
        </div>
      )}

      <Toast message={toast.message} type={toast.type} visible={toast.visible} />
    </div>
  );
}