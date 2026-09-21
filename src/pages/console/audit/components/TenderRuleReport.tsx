import type { TenderRuleReport } from "@/lib/api";

interface TenderRuleReportProps {
  projectName: string;
  projectCode: string;
  round: number;
  data?: TenderRuleReport | null;
}

const statusStyle: Record<string, string> = {
  优: "bg-primary-50 text-primary-600 border-primary-200",
  良: "bg-primary-50 text-primary-600 border-primary-200",
  一般: "bg-secondary-100 text-secondary-600 border-secondary-200",
  未响应: "bg-accent-50 text-accent-600 border-accent-200",
  已评分: "bg-primary-50 text-primary-600 border-primary-200",
  部分响应: "bg-secondary-100 text-secondary-600 border-secondary-200",
  基本响应: "bg-primary-50 text-primary-600 border-primary-200",
  公式项: "bg-background-200 text-foreground-600 border-background-300",
  未能评审: "bg-accent-50 text-accent-600 border-accent-200",
};

export default function TenderRuleReportView({ projectName, projectCode, round, data }: TenderRuleReportProps) {
  const groups = data?.groups ?? [];
  const empty = !data || groups.length === 0;

  return (
    <div className="mx-auto max-w-4xl overflow-hidden rounded-lg border border-background-300 bg-background-100">
      <div className="border-b border-background-300 bg-background-50 px-5 py-5 md:px-8">
        <div className="flex items-center gap-2.5">
          <span className="flex h-9 w-9 items-center justify-center rounded-lg bg-gradient-to-br from-accent-400 to-accent-500 text-background-50">
            <i className="ri-auction-line text-lg"></i>
          </span>
          <div>
            <h3 className="font-heading text-base font-semibold tracking-wide text-foreground-950">招标规则预审报告</h3>
            <p className="text-xs text-foreground-500">
              模拟评委按本项目招标规则原文逐条赋分，仅供自查，不是评标委员会得分 · 第 {round} 轮
            </p>
          </div>
        </div>
        <div className="mt-3 flex flex-wrap items-center gap-x-5 gap-y-1 text-xs text-foreground-500">
          <span>
            项目名称：<span className="text-foreground-700">{projectName}</span>
          </span>
          <span>
            招标编号：<span className="text-foreground-700">{projectCode}</span>
          </span>
          <span>
            评分依据：<span className="text-foreground-700">招标解析抽出的评标办法原文</span>
          </span>
        </div>
      </div>

      <div className="px-5 py-5 md:px-8">
        {!empty && !data?.judgeMode ? (
          <div className="mb-4 rounded-lg border border-accent-200 bg-accent-50/60 px-3 py-2 text-xs text-foreground-700">
            当前还是旧版对照结果，不是按本项目招标规则逐条赋分。请点击右上角「发起全量预审」，系统会对照招标评分要求重新评审。
          </div>
        ) : null}
        {empty ? (
          <div className="rounded-lg border border-dashed border-background-300 bg-background-50 px-4 py-12 text-center">
            <i className="ri-file-search-line text-3xl text-foreground-400"></i>
            <p className="mt-2 text-sm font-medium text-foreground-800">暂无招标评分规则</p>
            <p className="mt-1 text-xs text-foreground-500">
              请先在「招标解析」完成本项目评标办法抽取。每份招标书规则不同，本页不会套用其他项目或青天固定模块。
            </p>
          </div>
        ) : (
          <>
            <h4 className="mb-2.5 flex items-center gap-1.5 text-sm font-semibold text-foreground-900">
              <i className="ri-radio-button-line text-accent-500 text-sm"></i>
              一、模拟评委得分（不含报价公式项）
            </h4>
            <div className="grid grid-cols-1 gap-3 lg:grid-cols-3">
              <div className="flex items-center gap-3 rounded-lg border border-accent-200 bg-accent-50/40 p-3.5">
                <span className="font-heading text-gradient text-3xl font-bold">{data.totalScore}</span>
                <div className="text-xs text-foreground-500">
                  <div className="font-medium text-foreground-700">模拟评标得分（非评标委员会）</div>
                  <div className="mt-0.5">满分 {data.totalMax} · 折合 {data.percent}%</div>
                </div>
              </div>
              <div className="rounded-lg border border-background-300 bg-background-50 p-3.5 lg:col-span-2">
                <div className="mb-2 text-xs font-medium text-foreground-700">分信封汇总</div>
                <div className="grid grid-cols-1 gap-2 sm:grid-cols-3">
                  {groups.map((g) => (
                    <div key={g.key} className="rounded-md border border-background-200 bg-background-100 px-3 py-2">
                      <div className="text-[11px] text-foreground-500">{g.label}</div>
                      <div className="font-heading text-sm font-bold text-foreground-900">
                        {g.score} <span className="text-[11px] font-normal text-foreground-500">/ {g.maxScore}</span>
                      </div>
                    </div>
                  ))}
                </div>
              </div>
            </div>

            {groups.map((group, gi) => (
              <div key={group.key}>
                <h4 className="mb-2.5 mt-6 flex items-center gap-1.5 text-sm font-semibold text-foreground-900">
                  <i className="ri-list-check-3 text-accent-500 text-sm"></i>
                  {["二", "三", "四", "五"][gi] || gi + 2}、{group.label}
                </h4>
                <div className="space-y-3">
                  {group.items.map((item) => (
                    <div key={item.id} className="overflow-hidden rounded-lg border border-background-200">
                      <div className="flex flex-wrap items-center gap-2 border-b border-background-200 bg-background-50 px-3 py-2">
                        <span className="text-sm font-medium text-foreground-900">{item.name}</span>
                        <span className={`inline-flex items-center whitespace-nowrap rounded-md border px-1.5 py-0.5 text-[10px] font-medium ${statusStyle[item.status] || statusStyle["部分响应"]}`}>
                          {item.status}
                        </span>
                        <span className="font-label ml-auto text-xs text-foreground-600">
                          {item.status === "公式项" ? "不估算报价分" : `${item.score} / 满分 ${item.maxScore || "—"}`}
                        </span>
                      </div>
                      <div className="grid grid-cols-1 gap-3 p-3 sm:grid-cols-2">
                        <div className="rounded-md border border-primary-200 bg-primary-50/40 p-3">
                          <div className="mb-1.5 text-[11px] font-medium text-primary-600">招标评分规则原文</div>
                          <p className="text-sm leading-relaxed text-foreground-800">{item.rule}</p>
                        </div>
                        <div className="rounded-md border border-accent-200 bg-accent-50/40 p-3">
                          <div className="mb-1.5 text-[11px] font-medium text-accent-600">模拟评委评分理由</div>
                          <p className="text-sm leading-relaxed text-foreground-800">{item.reason}</p>
                          {item.evidence ? (
                            <p className="mt-2 text-xs leading-relaxed text-foreground-500">投标原文依据：「{item.evidence}」</p>
                          ) : null}
                        </div>
                      </div>
                      <div className="border-t border-background-200 bg-background-50 px-3 py-2 text-xs text-foreground-600">
                        <div>
                          <span className="font-medium text-foreground-800">修改建议：</span>
                          {item.suggestion}
                        </div>
                        {item.strategies.length > 0 && (
                          <div className="mt-2">
                            <div className="font-medium text-foreground-800">使用的高分规则条款：</div>
                            <ul className="mt-1 space-y-1">
                              {item.strategies.map((s) => (
                                <li key={s.key}>
                                  <span className="text-primary-600">{s.category}</span>
                                  <span className="text-foreground-500"> · {s.point}</span>
                                  {s.clauses.length > 0 && (
                                    <span className="text-foreground-500">（{s.clauses.join("；")}）</span>
                                  )}
                                </li>
                              ))}
                            </ul>
                          </div>
                        )}
                      </div>
                    </div>
                  ))}
                </div>
              </div>
            ))}

            <p className="mt-6 text-xs leading-relaxed text-foreground-500">{data.note}</p>
          </>
        )}
      </div>
    </div>
  );
}
