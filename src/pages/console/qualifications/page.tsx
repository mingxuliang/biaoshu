import { useMemo, useState, type FormEvent } from "react";
import PageHeader from "../components/PageHeader";
import Modal from "../components/Modal";
import Toast from "../components/Toast";
import StatusBadge from "../components/StatusBadge";
import { qualifications, qualificationTabs, type Qualification } from "@/mocks/qualifications";

type TabKey = (typeof qualificationTabs)[number]["key"];

const kindLabel: Record<Qualification["kind"], string> = {
  cert: "企业证照",
  people: "人员证书",
  achievement: "业绩",
  equipment: "设备机具",
  credit: "信用材料",
};

const statCards = [
  { key: "total", label: "证照总数", icon: "ri-vip-crown-line", gradient: "from-primary-400 to-primary-600", bar: "from-primary-500 to-primary-400" },
  { key: "expiring", label: "即将到期", icon: "ri-time-line", gradient: "from-accent-400 to-accent-500", bar: "from-accent-500 to-accent-400" },
  { key: "people", label: "人员证书", icon: "ri-id-card-line", gradient: "from-secondary-400 to-secondary-500", bar: "from-secondary-400 to-secondary-300" },
  { key: "achievement", label: "有效业绩", icon: "ri-trophy-line", gradient: "from-primary-400 to-primary-600", bar: "from-primary-500 to-primary-400" },
];

interface ToastState {
  message: string;
  type: "success" | "error" | "info";
  visible: boolean;
}

export default function QualificationsPage() {
  const [activeTab, setActiveTab] = useState<TabKey>("all");
  const [keyword, setKeyword] = useState("");
  const [createOpen, setCreateOpen] = useState(false);
  const [toast, setToast] = useState<ToastState>({ message: "", type: "success", visible: false });

  const showToast = (message: string, type: ToastState["type"] = "success") => {
    setToast({ message, type, visible: true });
    window.setTimeout(() => setToast((t) => ({ ...t, visible: false })), 3000);
  };

  const stats = useMemo(
    () => ({
      total: qualifications.length,
      expiring: qualifications.filter((q) => q.status === "将到期").length,
      people: qualifications.filter((q) => q.kind === "people").length,
      achievement: qualifications.filter((q) => q.kind === "achievement" && q.status === "有效").length,
    }),
    [],
  );

  const filtered = useMemo(() => {
    let list = qualifications;
    if (activeTab !== "all") list = list.filter((q) => q.kind === activeTab);
    if (keyword.trim()) {
      list = list.filter(
        (q) => q.name.toLowerCase().includes(keyword.toLowerCase()) || (q.number || "").toLowerCase().includes(keyword.toLowerCase()),
      );
    }
    return list;
  }, [activeTab, keyword]);

  const handleCreate = (e: FormEvent) => {
    e.preventDefault();
    setCreateOpen(false);
    showToast("证照已录入并进入 OCR 识别队列（演示）", "info");
  };

  const inputCls =
    "h-9 w-full rounded-md border border-background-300 bg-background-50 px-3 text-sm text-foreground-900 outline-none transition-all focus:border-primary-400 focus:ring-1 focus:ring-primary-400/20 placeholder:text-foreground-500";
  const labelCls = "mb-1.5 block text-xs font-medium text-foreground-600";

  return (
    <div>
      <PageHeader
        title="企业资质与证照库"
        description="集中管理企业证照、人员、业绩与设备，供资格文件与商务标一键引用，并在预审时做有效期与匹配度核验。"
        actions={
          <button
            type="button"
            onClick={() => setCreateOpen(true)}
            className="flex h-9 cursor-pointer items-center gap-1.5 whitespace-nowrap rounded-md bg-primary-500 px-4 text-sm font-medium text-background-50 transition-colors hover:bg-primary-600"
          >
            <i className="ri-add-line text-sm"></i>
            上传证照
          </button>
        }
      />

      {/* 统计卡片 */}
      <div className="mb-5 grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-4">
        {statCards.map((card) => (
          <div
            key={card.key}
            className="group relative flex items-center gap-3 overflow-hidden rounded-lg border border-background-300 bg-background-100 p-3.5 transition-all duration-300 hover:border-primary-300/60"
          >
            <span className={`flex h-10 w-10 shrink-0 items-center justify-center rounded-lg bg-gradient-to-br ${card.gradient} text-background-50`}>
              <i className={`${card.icon} text-lg`}></i>
            </span>
            <div className="min-w-0 flex-1">
              <div className="font-label text-[11px] text-foreground-500">{card.label}</div>
              <div className="font-heading text-gradient mt-0.5 text-xl font-bold tracking-wide">
                {card.key === "total" && stats.total}
                {card.key === "expiring" && stats.expiring}
                {card.key === "people" && stats.people}
                {card.key === "achievement" && stats.achievement}
              </div>
            </div>
            <div className={`absolute bottom-0 left-0 right-0 h-[2px] bg-gradient-to-r ${card.bar} opacity-0 transition-opacity duration-300 group-hover:opacity-100`} />
          </div>
        ))}
      </div>

      {/* 到期预警条 */}
      <div className="mb-4 flex flex-wrap items-center gap-2 rounded-lg border border-accent-200 bg-accent-50/50 px-4 py-2.5 text-sm text-accent-800">
        <i className="ri-error-warning-line text-base"></i>
        <span className="font-medium">有效期预警：</span>
        <span>市政工程施工总承包一级将于 25 天后到期</span>
        <button
          type="button"
          onClick={() => showToast("已加入证照续期提醒任务", "info")}
          className="ml-auto flex h-7 cursor-pointer items-center gap-1 whitespace-nowrap rounded-md bg-accent-500 px-2.5 text-xs font-medium text-background-50 transition-colors hover:bg-accent-600"
        >
          添加续期提醒
        </button>
      </div>

      {/* 筛选工具栏 */}
      <div className="mb-4 flex flex-col gap-3 rounded-lg border border-background-300 bg-background-100 p-3.5 lg:flex-row lg:items-center">
        <div className="flex flex-wrap items-center gap-1.5">
          {qualificationTabs.map((tab) => (
            <button
              key={tab.key}
              type="button"
              onClick={() => setActiveTab(tab.key)}
              className={`flex cursor-pointer items-center gap-1 whitespace-nowrap rounded-md border px-3 py-1.5 text-xs font-medium transition-all ${
                activeTab === tab.key
                  ? "border-primary-200 bg-primary-50 text-primary-600"
                  : "border-background-300 bg-transparent text-foreground-600 hover:border-background-400 hover:text-foreground-700"
              }`}
            >
              <i className={`${tab.icon} text-sm`}></i>
              {tab.label}
            </button>
          ))}
        </div>
        <div className="relative flex-1 lg:max-w-xs lg:ml-auto">
          <i className="ri-search-line absolute left-3 top-1/2 -translate-y-1/2 text-xs text-foreground-500"></i>
          <input
            type="text"
            value={keyword}
            onChange={(e) => setKeyword(e.target.value)}
            placeholder="搜索证照 / 证书编号 / 姓名…"
            className={`${inputCls} pl-9`}
          />
        </div>
      </div>

      {/* 证照列表 */}
      <div className="grid grid-cols-1 gap-3 md:grid-cols-2 xl:grid-cols-3">
        {filtered.map((item) => (
          <div key={item.id} className="group rounded-lg border border-background-300 bg-background-100 p-4 transition-all hover:border-primary-300/60">
            <div className="flex items-start gap-3">
              <span
                className={`flex h-10 w-10 shrink-0 items-center justify-center rounded-lg bg-gradient-to-br text-background-50 ${
                  item.kind === "cert" || item.kind === "credit"
                    ? "from-primary-400 to-primary-600"
                    : item.kind === "people"
                      ? "from-accent-400 to-accent-500"
                      : "from-secondary-400 to-secondary-500"
                }`}
              >
                <i className={kindIcon(item.kind)}></i>
              </span>
              <div className="min-w-0 flex-1">
                <div className="truncate text-sm font-medium text-foreground-900">{item.name}</div>
                <div className="mt-0.5 text-xs text-foreground-500">
                  {kindLabel[item.kind]} · {item.number || item.level}
                </div>
              </div>
              <StatusBadge status={item.status} pulse={item.status === "将到期"} />
            </div>
            <p className="mt-3 line-clamp-2 text-xs leading-relaxed text-foreground-600">{item.detail}</p>
            <div className="mt-3 flex flex-wrap items-center gap-1.5">
              {item.owner && (
                <span className="inline-flex items-center gap-1 rounded bg-secondary-100 px-1.5 py-0.5 text-[10px] text-secondary-700">
                  <i className="ri-user-line"></i>
                  {item.owner}
                </span>
              )}
              {item.attachments?.map((att) => (
                <span key={att} className="inline-flex items-center gap-1 rounded bg-primary-50 px-1.5 py-0.5 text-[10px] text-primary-600">
                  <i className="ri-attachment-line"></i>
                  {att}
                </span>
              ))}
              {item.warnDays && (
                <span className="inline-flex items-center gap-1 rounded bg-accent-50 px-1.5 py-0.5 text-[10px] text-accent-600">
                  <i className="ri-time-line"></i>
                  {item.warnDays} 天后到期
                </span>
              )}
            </div>
            <div className="mt-3 flex items-center justify-between border-t border-background-200 pt-3">
              <span className="text-[11px] text-foreground-500">
                {item.validUntil === "长期" ? "长期有效" : `有效期至 ${item.validUntil}`}
              </span>
              <div className="flex items-center gap-1">
                <button
                  type="button"
                  title="引用到项目"
                  onClick={() => showToast("已勾选可引用到本项目（专业/等级匹配校验通过）")}
                  className="flex h-7 w-7 cursor-pointer items-center justify-center rounded-md text-foreground-500 transition-all hover:scale-110 hover:bg-primary-50 hover:text-primary-600"
                >
                  <i className="ri-link-m text-sm"></i>
                </button>
                <button
                  type="button"
                  title="查看扫描件"
                  onClick={() => showToast("已打开证照扫描件预览（演示）", "info")}
                  className="flex h-7 w-7 cursor-pointer items-center justify-center rounded-md text-foreground-500 transition-all hover:scale-110 hover:bg-background-200 hover:text-foreground-800"
                >
                  <i className="ri-eye-line text-sm"></i>
                </button>
              </div>
            </div>
          </div>
        ))}
        {filtered.length === 0 && (
          <div className="col-span-full rounded-lg border border-background-300 bg-background-100 py-16 text-center">
            <i className="ri-inbox-line text-3xl text-foreground-400"></i>
            <p className="mt-3 text-sm text-foreground-500">没有找到匹配的证照，试试调整筛选条件</p>
          </div>
        )}
      </div>

      {/* 上传弹窗 */}
      <Modal open={createOpen} onClose={() => setCreateOpen(false)} title="上传证照 / 业绩材料" subtitle="支持 PDF/JPG/PNG，系统将自动 OCR 提取证号、等级与有效期">
        <form onSubmit={handleCreate} className="space-y-4">
          <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
            <div>
              <label className={labelCls} htmlFor="q-kind">
                材料类型
              </label>
              <select id="q-kind" className={`${inputCls} cursor-pointer`}>
                <option>企业证照</option>
                <option>人员证书</option>
                <option>业绩四件套</option>
                <option>设备机具</option>
                <option>信用材料</option>
              </select>
            </div>
            <div>
              <label className={labelCls} htmlFor="q-name">
                名称
              </label>
              <input id="q-name" type="text" placeholder="例如：营业执照" className={inputCls} />
            </div>
          </div>
          <div className="flex flex-col items-center justify-center gap-2 rounded-lg border border-dashed border-background-300 bg-background-50 px-4 py-6 text-center">
            <i className="ri-upload-cloud-2-line text-2xl text-primary-500"></i>
            <p className="text-xs text-foreground-500">点击上传扫描件，单文件不超过 50MB</p>
            <button
              type="button"
              className="mt-1 flex h-8 cursor-pointer items-center gap-1.5 whitespace-nowrap rounded-md bg-primary-500 px-3 text-xs font-medium text-background-50 transition-colors hover:bg-primary-600"
            >
              <i className="ri-folder-add-line"></i>
              选择文件
            </button>
          </div>
          <div className="flex items-center justify-end gap-2 pt-2">
            <button
              type="button"
              onClick={() => setCreateOpen(false)}
              className="h-9 cursor-pointer whitespace-nowrap rounded-md border border-background-300 px-4 text-sm font-medium text-foreground-600 transition-colors hover:bg-background-200"
            >
              取消
            </button>
            <button
              type="submit"
              className="flex h-9 cursor-pointer items-center gap-1.5 whitespace-nowrap rounded-md bg-primary-500 px-4 text-sm font-medium text-background-50 transition-colors hover:bg-primary-600"
            >
              <i className="ri-sparkling-2-line text-sm"></i>
              上传并识别
            </button>
          </div>
        </form>
      </Modal>

      <Toast message={toast.message} type={toast.type} visible={toast.visible} />
    </div>
  );
}

function kindIcon(kind: Qualification["kind"]): string {
  switch (kind) {
    case "cert":
      return "ri-vip-crown-line text-lg";
    case "people":
      return "ri-id-card-line text-lg";
    case "achievement":
      return "ri-trophy-line text-lg";
    case "equipment":
      return "ri-truck-line text-lg";
    case "credit":
      return "ri-shield-star-line text-lg";
  }
}