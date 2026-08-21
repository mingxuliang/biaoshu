import { useState } from "react";
import type { ScoreRule, MustRespond } from "@/mocks/parse";

interface ReportPreviewProps {
  project: { name: string; code: string; type: string; budget?: string; deadline?: string; owner?: string; createdAt?: string };
  rules: ScoreRule[];
  mustRespond: MustRespond[];
  onToast: (msg: string, type?: "success" | "error" | "info") => void;
}

interface QualificationItem {
  title: string;
  desc: string;
  source: string;
  level: "星号" | "废标";
}

interface FormatItem {
  title: string;
  desc: string;
  level: "废标" | "建议" | "强制";
}

const qualificationItems: QualificationItem[] = [
  { title: "资质等级要求", desc: "投标人须具备市政公用工程施工总承包一级及以上资质", source: "第二章 投标人须知 1.4.1", level: "星号" },
  { title: "拟派项目经理", desc: "须持市政一级建造师注册证书，且不得在其他项目担任在建职务", source: "第二章 投标人须知 1.4.2", level: "废标" },
  { title: "同类业绩要求", desc: "近三年承担过单项合同额 ≥5000 万元的同类市政工程至少 1 项", source: "第二章 投标人须知 1.4.3", level: "星号" },
  { title: "财务能力要求", desc: "提交近三年经审计财务报表，资产负债率不高于 85%", source: "第三章 评标办法 2.1.2", level: "星号" },
  { title: "信誉要求", desc: "未被列入失信被执行人、重大税收违法失信主体名单", source: "第二章 投标人须知 1.4.4", level: "建议" },
];

const formatItems: FormatItem[] = [
  { title: "暗标评审", desc: "投标文件不得出现任何可识别投标人身份的标记、章印、水印或符号", source: "第二章 投标人须知 5.2", level: "废标" },
  { title: "装订格式", desc: "左侧装订、统一封面模板，A4 打印，正本 1 份、副本 5 份", source: "第二章 投标人须知 5.1", level: "强制" },
  { title: "字体版式", desc: "正文宋体小四、行距 1.5 倍，各级标题用黑体并按规范字号排版", source: "第二章 投标人须知 5.3", level: "强制" },
  { title: "页码目录", desc: "全文连续页码，目录自动生成并须与正文页码一致", source: "第二章 投标人须知 5.4", level: "建议" },
  { title: "电子标书", desc: "提交加密 U 盘，内含 docx 与加密 PDF 双格式电子标书", source: "第二章 投标人须知 6.1", level: "强制" },
  { title: "封装要求", desc: "密封袋外层不得标注投标人名称，仅标招标编号与项目名称", source: "第二章 投标人须知 6.2", level: "废标" },
];

const riskItems = [
  { icon: "ri-scan-line", level: "高", text: "《答疑澄清（第1号）》含图片扫描页，OCR 识别存在缺字风险，建议人工逐页核对原文后再引用。" },
  { icon: "ri-calculator-line", level: "中", text: "商务标报价组成（维度3）尚未覆盖，需在撰写阶段补齐报价组成完整性与成本控制措施。" },
  { icon: "ri-eye-off-line", level: "高", text: "本项目为暗标评审，导出前须执行去标识校验，杜绝任何可识别投标人身份的痕迹。" },
  { icon: "ri-time-line", level: "中", text: "投标有效期 90 日历天条款状态为待响应，须在商务标中明确承诺并置于醒目位置。" },
];

const zooms = [75, 90, 100, 125, 150];

const levelStyle: Record<string, string> = {
  星号: "bg-accent-50 text-accent-600 border-accent-200",
  废标: "bg-red-50 text-red-500 border-red-200",
  强制: "bg-secondary-100 text-secondary-600 border-secondary-200",
  建议: "bg-primary-50 text-primary-600 border-primary-200",
  高: "bg-red-50 text-red-500 border-red-200",
  中: "bg-accent-50 text-accent-600 border-accent-200",
};

export default function ReportPreview({ project, rules, mustRespond, onToast }: ReportPreviewProps) {
  const [currentPage, setCurrentPage] = useState(0);
  const [zoom, setZoom] = useState(100);

  const totalPages = 4;
  const covered = rules.filter((r) => r.responseStatus === "已覆盖").length;
  const essentialCount = rules.filter((r) => r.isEssential).length;

  const pages: React.ReactNode[] = [
    /* 封面页 */
    <div key="p1" className="flex h-full flex-col">
      <div className="mb-8 flex items-center justify-between">
        <span className="font-label text-[11px] uppercase tracking-widest text-foreground-400">Doc No. {project.code}-REP-01</span>
        <span className="font-label text-[11px] text-foreground-400">版本 V1.0 · 内部</span>
      </div>
      <div className="mt-6 text-center">
        <div className="font-label text-xs uppercase tracking-[0.3em] text-primary-500">Tender Document Analysis Report</div>
        <h2 className="font-heading mt-3 text-[32px] font-bold leading-tight text-foreground-950">招标文件解析报告</h2>
        <p className="mt-2 text-sm text-foreground-500">招标编号：{project.code}</p>
      </div>
      <div className="my-8 border-t border-background-200" />
      <div className="mb-3 font-label text-xs font-semibold uppercase tracking-wider text-foreground-500">项目基本信息</div>
      <table className="w-full border-collapse text-sm">
        <tbody>
          {[
            ["项目名称", project.name],
            ["招标编号", project.code],
            ["项目类型", project.type],
            ["预算金额", project.budget || "—"],
            ["投标截止", project.deadline || "—"],
            ["项目负责人", project.owner || "—"],
          ].map(([k, v]) => (
            <tr key={k}>
              <td className="w-32 border border-background-200 bg-background-100 px-3 py-2 font-medium text-foreground-600">{k}</td>
              <td className="border border-background-200 px-3 py-2 text-foreground-900">{v}</td>
            </tr>
          ))}
        </tbody>
      </table>
      <div className="mt-6 rounded-md border border-background-200 bg-background-100/60 p-3.5 text-sm leading-relaxed text-foreground-600">
        <span className="font-medium text-foreground-800">报告摘要：</span>
        本报告由 AI 解析引擎基于本项目招标文件、评标办法及答疑澄清自动生成，共抽取评分规则 {rules.length} 条（其中必响应 {essentialCount} 条）、实质性条款与否决项 {mustRespond.length} 条、资格要求 {qualificationItems.length} 项、格式与暗标要求 {formatItems.length} 项。请项目经理逐项校对并确认后锁定「本项目尺子」。
      </div>
      <div className="mt-auto flex items-center justify-between border-t border-background-200 pt-4">
        <span className="font-label text-[11px] text-foreground-400">生成：2026-08-17 14:32</span>
        <span className="font-label text-[11px] text-foreground-400">文档状态：待人工校对确认</span>
      </div>
    </div>,

    /* 评分办法对标清单 */
    <div key="p2" className="flex h-full flex-col">
      <div className="mb-4 flex items-center gap-2">
        <span className="flex h-7 w-7 items-center justify-center rounded-md bg-primary-500 text-sm font-semibold text-background-50">一</span>
        <h3 className="font-heading text-lg font-semibold text-foreground-950">评分办法对标清单</h3>
      </div>
      <p className="mb-4 text-sm leading-relaxed text-foreground-600">
        综合评分法总分 100 分。以下清单已按评分维度自动对标，标注「必响应」的维度在撰写阶段必须逐项覆盖，作为本项目的评标尺子。
      </p>
      <table className="w-full border-collapse text-[13px]">
        <thead>
          <tr className="bg-background-100 text-foreground-600">
            <th className="border border-background-200 px-2.5 py-2 text-left font-medium">评分维度</th>
            <th className="w-14 border border-background-200 px-2 py-2 text-center font-medium">分值</th>
            <th className="border border-background-200 px-2.5 py-2 text-left font-medium">评分细则</th>
            <th className="w-24 border border-background-200 px-2 py-2 text-center font-medium">状态</th>
          </tr>
        </thead>
        <tbody>
          {rules.map((r) => (
            <tr key={r.id} className="align-top">
              <td className="border border-background-200 px-2.5 py-2">
                <div className="font-medium text-foreground-900">{r.dimension}</div>
                {r.isEssential && <span className="font-label mt-0.5 inline-block rounded bg-accent-50 px-1.5 py-0.5 text-[10px] text-accent-600">必响应</span>}
              </td>
              <td className="border border-background-200 px-2 py-2 text-center font-semibold text-primary-600">{r.weight}</td>
              <td className="border border-background-200 px-2.5 py-2 text-foreground-700">{r.detail}</td>
              <td className="border border-background-200 px-2 py-2 text-center text-foreground-600">{r.responseStatus}</td>
            </tr>
          ))}
        </tbody>
        <tfoot>
          <tr>
            <td colSpan={4} className="border border-background-200 bg-background-100/60 px-2.5 py-1.5 text-[12px] text-foreground-500">
              合计 100 分 · 已覆盖 {covered} 条，未完全覆盖 {rules.length - covered} 条
            </td>
          </tr>
        </tfoot>
      </table>
    </div>,

    /* 实质性条款 + 资格要求 */
    <div key="p3" className="flex h-full flex-col">
      <div className="mb-4 flex items-center gap-2">
        <span className="flex h-7 w-7 items-center justify-center rounded-md bg-primary-500 text-sm font-semibold text-background-50">二</span>
        <h3 className="font-heading text-lg font-semibold text-foreground-950">实质性条款与否决项清单</h3>
      </div>
      <ul className="mb-5 space-y-2">
        {mustRespond.map((m) => (
          <li key={m.id} className="flex items-start gap-2.5 rounded-md border border-background-200 px-3 py-2">
            <span className={`font-label mt-0.5 shrink-0 whitespace-nowrap rounded border px-1.5 py-0.5 text-[10px] font-medium ${levelStyle[m.type === "星号条款" ? "星号" : "废标"]}`}>
              {m.type}
            </span>
            <div className="min-w-0 flex-1">
              <div className="text-[13px] text-foreground-800">{m.clause}</div>
              <div className="text-[11px] text-foreground-400">原文位置：{m.original}</div>
            </div>
          </li>
        ))}
      </ul>
      <div className="mb-4 flex items-center gap-2">
        <span className="flex h-7 w-7 items-center justify-center rounded-md bg-primary-500 text-sm font-semibold text-background-50">三</span>
        <h3 className="font-heading text-lg font-semibold text-foreground-950">资格要求清单</h3>
      </div>
      <table className="w-full border-collapse text-[13px]">
        <tbody>
          {qualificationItems.map((q) => (
            <tr key={q.title} className="align-top">
              <td className="w-32 border border-background-200 px-2.5 py-2">
                <div className="font-medium text-foreground-900">{q.title}</div>
                <span className={`font-label mt-0.5 inline-block rounded border px-1.5 py-0.5 text-[10px] font-medium ${levelStyle[q.level]}`}>{q.level}</span>
              </td>
              <td className="border border-background-200 px-2.5 py-2 text-foreground-700">
                <div>{q.desc}</div>
                <div className="mt-0.5 text-[11px] text-foreground-400">原文位置：{q.source}</div>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>,

    /* 格式暗标 + 风险提示 + 结论 */
    <div key="p4" className="flex h-full flex-col">
      <div className="mb-4 flex items-center gap-2">
        <span className="flex h-7 w-7 items-center justify-center rounded-md bg-primary-500 text-sm font-semibold text-background-50">四</span>
        <h3 className="font-heading text-lg font-semibold text-foreground-950">格式与暗标要求</h3>
      </div>
      <ul className="mb-5 space-y-2">
        {formatItems.map((f) => (
          <li key={f.title} className="flex items-start gap-2.5 rounded-md border border-background-200 px-3 py-2">
            <span className={`font-label mt-0.5 shrink-0 whitespace-nowrap rounded border px-1.5 py-0.5 text-[10px] font-medium ${levelStyle[f.level]}`}>{f.level}</span>
            <div className="min-w-0 flex-1">
              <div className="text-[13px] text-foreground-800">
                <span className="font-medium">{f.title}：</span>
                {f.desc}
              </div>
              <div className="text-[11px] text-foreground-400">原文位置：{f.source}</div>
            </div>
          </li>
        ))}
      </ul>
      <div className="mb-4 flex items-center gap-2">
        <span className="flex h-7 w-7 items-center justify-center rounded-md bg-primary-500 text-sm font-semibold text-background-50">五</span>
        <h3 className="font-heading text-lg font-semibold text-foreground-950">风险提示与待办</h3>
      </div>
      <ul className="mb-5 space-y-2">
        {riskItems.map((r) => (
          <li key={r.text} className="flex items-start gap-2.5 rounded-md border border-background-200 px-3 py-2">
            <i className={`${r.icon} mt-0.5 text-sm text-foreground-400`}></i>
            <span className={`font-label mt-0.5 shrink-0 rounded border px-1.5 py-0.5 text-[10px] font-medium ${levelStyle[r.level]}`}>{r.level}</span>
            <span className="text-[13px] text-foreground-700">{r.text}</span>
          </li>
        ))}
      </ul>
      <div className="mt-auto rounded-md border border-background-200 bg-background-100/60 px-3.5 py-3 text-sm leading-relaxed text-foreground-600">
        <span className="font-medium text-foreground-800">结论与建议：</span>
        本项目为暗标综合评分法。评分维度已全部抽取，其中 {rules.length - covered} 项尚未完全覆盖，建议按「本项目尺子」在撰写阶段逐项补齐；星号条款与废标条款已识别，请在撰写大纲中置顶并在投标前逐条勾稽确认。
      </div>
      <div className="mt-4 flex items-center justify-between border-t border-background-200 pt-4">
        <span className="font-label text-[11px] text-foreground-400">解析引擎 v2.4 · 校对人：______</span>
        <span className="font-label text-[11px] text-foreground-400">批准人：______</span>
      </div>
    </div>,
  ];

  return (
    <div className="overflow-hidden rounded-lg border border-background-300 bg-background-100">
      {/* Word 风格工具栏 */}
      <div className="flex flex-wrap items-center gap-2 border-b border-background-300 bg-background-50 px-3 py-2">
        <div className="flex min-w-0 items-center gap-2">
          <span className="flex h-8 w-8 shrink-0 items-center justify-center rounded-md bg-gradient-to-br from-primary-400 to-primary-600 text-background-50">
            <i className="ri-file-word-2-line text-base"></i>
          </span>
          <div className="min-w-0">
            <div className="truncate text-sm font-medium text-foreground-900">招标文件解析报告</div>
            <div className="font-label text-[11px] text-foreground-500">{project.code} · {project.name}</div>
          </div>
        </div>
        <div className="ml-auto flex flex-wrap items-center gap-1.5">
          <div className="flex items-center rounded-md border border-background-300 bg-background-100 p-0.5">
            <button type="button" onClick={() => setCurrentPage((p) => Math.max(0, p - 1))} disabled={currentPage === 0} className="flex h-7 w-7 cursor-pointer items-center justify-center rounded-md text-foreground-600 transition-colors hover:bg-background-200 disabled:cursor-not-allowed disabled:opacity-40">
              <i className="ri-arrow-left-s-line text-base"></i>
            </button>
            <span className="font-label mx-1 whitespace-nowrap text-xs text-foreground-600">{currentPage + 1} / {totalPages} 页</span>
            <button type="button" onClick={() => setCurrentPage((p) => Math.min(totalPages - 1, p + 1))} disabled={currentPage === totalPages - 1} className="flex h-7 w-7 cursor-pointer items-center justify-center rounded-md text-foreground-600 transition-colors hover:bg-background-200 disabled:cursor-not-allowed disabled:opacity-40">
              <i className="ri-arrow-right-s-line text-base"></i>
            </button>
          </div>
          <div className="flex items-center gap-1 rounded-md border border-background-300 bg-background-100 px-1.5 py-0.5">
            <i className="ri-zoom-out-line text-xs text-foreground-500"></i>
            <select value={zoom} onChange={(e) => setZoom(Number(e.target.value))} className="cursor-pointer bg-transparent text-xs text-foreground-600 outline-none">
              {zooms.map((z) => (
                <option key={z} value={z}>{z}%</option>
              ))}
            </select>
            <i className="ri-zoom-in-line text-xs text-foreground-500"></i>
          </div>
          <button type="button" onClick={() => onToast("报告已重新生成（演示）", "info")} className="flex h-8 cursor-pointer items-center gap-1.5 whitespace-nowrap rounded-md border border-background-300 px-2.5 text-xs text-foreground-600 transition-colors hover:bg-background-200">
            <i className="ri-refresh-line text-sm"></i>
            重新生成
          </button>
          <button type="button" onClick={() => onToast("正在导出 Word 文档…", "info")} className="flex h-8 cursor-pointer items-center gap-1.5 whitespace-nowrap rounded-md bg-primary-500 px-3 text-xs font-medium text-background-50 transition-colors hover:bg-primary-600">
            <i className="ri-download-2-line text-sm"></i>
            导出 Word
          </button>
        </div>
      </div>

      {/* 纸张区域 */}
      <div className="flex h-[660px] items-start justify-center overflow-auto bg-background-200/50 px-6 py-8">
        <div
          className="flex h-[990px] w-[700px] shrink-0 flex-col rounded-md border border-background-300 bg-background-50 p-12 transition-transform duration-200"
          style={{ transform: `scale(${zoom / 100})`, transformOrigin: "top center" }}
        >
          {pages[currentPage]}
          <div className="mt-4 flex items-center justify-center gap-1 font-label text-[11px] text-foreground-400">
            <i className="ri-file-word-2-line text-xs"></i>
            {project.code} 招标文件解析报告 · 第 {currentPage + 1} 页 / 共 {totalPages} 页
          </div>
        </div>
      </div>
    </div>
  );
}