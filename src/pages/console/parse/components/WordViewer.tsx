import { useMemo, useState } from "react";

interface WordViewerProps {
  projectName: string;
  projectCode: string;
}

const zoomOptions = [75, 90, 100, 125, 150];

/* 招标文件连续文档（章节 + 段落），参照闭环修改页的 Word 式结构 */
interface TenderSection {
  id: string;
  level: 1 | 2 | 3;
  heading: string;
  paragraphs: Array<{
    id: string;
    text: string;
    list?: boolean;
    table?: { headers: string[]; rows: string[][] };
    empty?: boolean;
  }>;
}

const tenderSections: TenderSection[] = [
  {
    id: "title",
    level: 1,
    heading: "贝恩医疗设备（广州）有限公司企业培训管理系统建设项目",
    paragraphs: [
      { id: "t1", text: "招标文件", empty: true },
      { id: "t2", text: "招标编号：BM-PX202605001" },
      { id: "t3", text: "招标单位：贝恩医疗设备（广州）有限公司" },
      { id: "t4", text: "日期：2026年05月" },
    ],
  },
  {
    id: "s1",
    level: 1,
    heading: "第一章 招标公告",
    paragraphs: [
      { id: "1.1", text: "1. 招标条件" },
      { id: "1.2", text: "本招标项目贝恩医疗设备（广州）有限公司企业培训管理系统建设项目已由公司管理层批准建设，项目资金来自企业自筹，招标人为贝恩医疗设备（广州）有限公司。项目已具备招标条件，现对该项目的软件开发与实施服务进行公开招标。" },
      { id: "1.3", text: "2. 项目概况与招标范围" },
      { id: "1.4", text: "2.1 项目名称：企业培训管理系统建设项目" },
      { id: "1.5", text: "2.2 项目编号：BM-PX202605001" },
      { id: "1.6", text: "2.3 建设地点：广州市黄埔区科学城创新大道168号贝恩医疗总部大楼" },
      { id: "1.7", text: "2.4 招标范围：企业培训管理系统软件的设计、开发、部署、培训、验收及三年运维服务。具体包括：" },
      { id: "1.8", text: "在线学习平台（PC端、移动端APP、微信小程序）", list: true },
      { id: "1.9", text: "考试与测评系统（含防作弊机制）", list: true },
      { id: "1.10", text: "培训计划与资源管理系统", list: true },
      { id: "1.11", text: "学员档案与证书管理系统", list: true },
      { id: "1.12", text: "数据分析与报表系统", list: true },
      { id: "1.13", text: "系统集成（OA、企业微信、人事系统、访客系统）", list: true },
      { id: "1.14", text: "2.5 计划工期：合同签订后180日历天内完成系统上线交付；上线后提供不少于90日历天的试运行及调优期。" },
      { id: "1.15", text: "2.6 质量标准：满足招标文件技术需求书中全部功能需求，通过招标人组织的验收测试。" },
    ],
  },
  {
    id: "s2",
    level: 1,
    heading: "第二章 投标人须知",
    paragraphs: [
      { id: "2.1", text: "1. 投标人资格要求" },
      { id: "2.2", text: "1.1 投标人须为在中华人民共和国境内依法注册、具有独立法人资格的企业，注册资本不低于人民币500万元（含）。" },
      { id: "2.3", text: "1.2 投标人须具备有效的软件企业认定证书或高新技术企业证书。" },
      { id: "2.4", text: "1.3 投标人近三年（2023年1月1日至今）须承担过至少2个单项合同金额不低于人民币200万元的企业培训管理系统或E-Learning平台建设项目，并提供合同复印件及验收证明。" },
      { id: "2.5", text: "1.4 投标人拟派项目经理须具备PMP认证或信息系统项目管理师（高级）资格，且近三年担任过至少1个同类项目的项目经理。" },
      { id: "2.6", text: "1.5 投标人须通过ISO 9001质量管理体系认证和ISO 27001信息安全管理体系认证，且认证证书在有效期内。" },
      { id: "2.7", text: "1.6 投标人未被列入失信被执行人、重大税收违法失信主体名单，须提供信用中国查询截图。" },
      { id: "2.8", text: "2. 投标文件的组成" },
      { id: "2.9", text: "2.1 商务标部分：投标函、法定代表人授权书、开标一览表、分项报价表、商务条款响应表、资格证明文件。" },
      { id: "2.10", text: "2.2 技术标部分：技术方案书、项目实施计划、项目团队配置表、售后服务承诺书、培训方案、演示方案。" },
      { id: "2.11", text: "2.3 暗标评审要求：技术标部分不得出现任何可识别投标人身份的信息（包括但不限于公司名称、LOGO、水印、特殊标记）。出现上述情形按废标处理。" },
    ],
  },
  {
    id: "s3",
    level: 1,
    heading: "第三章 评标办法（综合评分法）",
    paragraphs: [
      { id: "3.1", text: "本次评标采用综合评分法，满分100分。评标委员会由5名专家组成，其中技术专家3名、商务专家2名。" },
      { id: "3.2", text: "1. 评分标准" },
      {
        id: "3.3",
        table: {
          headers: ["评审维度", "分值", "评审内容"],
          rows: [
            ["技术方案", "35", "系统架构设计、功能响应完整性、技术先进性与可行性"],
            ["项目团队", "15", "项目经理资质、核心技术人员经验、团队稳定性"],
            ["商务报价", "25", "报价合理性、性价比、付款方式接受度"],
            ["实施与售后", "15", "实施计划可行性、培训方案、售后服务承诺"],
            ["演示答辩", "10", "现场系统演示、答辩表现、问题响应能力"],
          ],
        },
      },
      { id: "3.4", text: "2. 废标条款" },
      { id: "3.5", text: "2.1 投标报价超过预算上限（人民币480万元）的，按废标处理。" },
      { id: "3.6", text: "2.2 技术标出现可识别投标人身份标记的，按废标处理。" },
      { id: "3.7", text: "2.3 未按要求提供全部资格证明文件的，按废标处理。" },
      { id: "3.8", text: "2.4 投标有效期少于90日历天的，按废标处理。" },
    ],
  },
  {
    id: "s4",
    level: 1,
    heading: "第四章 技术与功能需求",
    paragraphs: [
      { id: "4.1", text: "F-01 组织与账号管理" },
      { id: "4.2", text: "系统须支持多级组织架构管理（集团-事业部-部门-科室-小组），支持批量导入/导出组织架构；支持账号生命周期管理（创建、启用、禁用、注销、冻结）；支持单点登录（SSO）与企业微信、钉钉等第三方身份源对接。" },
      { id: "4.3", text: "F-02 角色与权限管理" },
      { id: "4.4", text: "系统须支持RBAC权限模型，至少包含超级管理员、培训管理员、部门管理员、讲师、学员五类角色；支持自定义角色及细粒度权限配置（菜单级、按钮级、数据级）；支持权限继承与委托授权。" },
      { id: "4.5", text: "F-03 培训计划管理" },
      { id: "4.6", text: "支持年度/季度/月度培训计划编制与审批流转；支持培训计划自动分解至部门/个人；支持培训计划执行进度跟踪与预警；支持培训计划与实际完成情况的对比分析。" },
      { id: "4.7", text: "F-04 课程资源管理" },
      { id: "4.8", text: "支持多种课程形式（视频、文档、SCORM课件、H5课件、直播、线下课）；支持课程分类标签体系；支持课程版本管理；支持课程评价与反馈收集。" },
      { id: "4.9", text: "F-05 在线学习与进度跟踪" },
      { id: "4.10", text: "支持PC端、iOS、Android、微信小程序多端学习；支持学习进度实时同步；支持断点续播；支持学习笔记与收藏；支持学习提醒与催办。" },
    ],
  },
];

const headingClass: Record<number, string> = {
  1: "editor-heading-h1",
  2: "editor-heading-h2",
  3: "editor-heading-h3",
};

export default function WordViewer({ projectName, projectCode }: WordViewerProps) {
  const [zoom, setZoom] = useState(100);
  const [searchQuery, setSearchQuery] = useState("");
  const [focusSection, setFocusSection] = useState<string | null>(null);

  /* 统计总字数（用于底部状态栏） */
  const totalWords = useMemo(
    () =>
      tenderSections.reduce(
        (sum, s) =>
          sum +
          s.paragraphs.reduce(
            (acc, p) => acc + (p.text ? p.text.length : (p.table ? p.table.rows.reduce((t, r) => t + r.join("").length, 0) : 0)),
            0,
          ),
        0,
      ),
    [],
  );

  const iconBtn =
    "flex h-8 w-8 cursor-pointer items-center justify-center rounded-md text-sm text-foreground-600 transition-colors hover:bg-background-200 hover:text-foreground-900";
  const disabledBtn = "flex h-8 w-8 cursor-not-allowed items-center justify-center rounded-md text-sm text-foreground-400";

  /* 标题锚点 */
  const jumpTo = (id: string) => {
    setFocusSection(id);
    window.setTimeout(() => setFocusSection(null), 1600);
    document.getElementById(`tender-sec-${id}`)?.scrollIntoView({ behavior: "smooth", block: "start" });
  };

  return (
    <div className="flex h-full flex-col overflow-hidden rounded-lg border border-background-300 bg-background-100">
      {/* 顶部工具栏（参照 Word 式工具栏） */}
      <div className="flex flex-wrap items-center gap-1 border-b border-background-300 bg-background-100 px-2.5 py-1.5">
        <button type="button" title="撤销" className={iconBtn}><i className="ri-arrow-go-back-line"></i></button>
        <button type="button" title="重做" className={disabledBtn}><i className="ri-arrow-go-forward-line"></i></button>
        <span className="mx-1 h-4 w-px bg-background-300" />
        <select
          value={zoom}
          onChange={(e) => setZoom(Number(e.target.value))}
          className="h-8 cursor-pointer rounded border border-background-300 bg-background-50 px-1.5 text-xs text-foreground-700 outline-none"
        >
          {zoomOptions.map((z) => (
            <option key={z} value={z}>{z}%</option>
          ))}
        </select>
        <span className="mx-1 h-4 w-px bg-background-300" />
        <button type="button" title="正文" className={disabledBtn}>正文</button>
        <button type="button" title="一级标题" className={disabledBtn}>H1</button>
        <button type="button" title="二级标题" className={disabledBtn}>H2</button>
        <button type="button" title="三级标题" className={disabledBtn}>H3</button>
        <span className="mx-1 h-4 w-px bg-background-300" />
        <button type="button" title="加粗" className={`${iconBtn} font-bold`}>B</button>
        <button type="button" title="斜体" className={`${iconBtn} italic`}>I</button>
        <button type="button" title="下划线" className={`${iconBtn} underline`}>U</button>
        <button type="button" title="删除线" className={`${iconBtn} line-through`}>S</button>
        <span className="mx-1 h-4 w-px bg-background-300" />
        <button type="button" title="无序列表" className={iconBtn}><i className="ri-list-unordered"></i></button>
        <button type="button" title="有序列表" className={iconBtn}><i className="ri-list-ordered"></i></button>
        <button type="button" title="左对齐" className={iconBtn}><i className="ri-align-left"></i></button>
        <button type="button" title="居中" className={iconBtn}><i className="ri-align-center"></i></button>
        <button type="button" title="右对齐" className={iconBtn}><i className="ri-align-right"></i></button>
        <button type="button" title="两端对齐" className={iconBtn}><i className="ri-align-justify"></i></button>
        <span className="mx-1 h-4 w-px bg-background-300" />
        <button type="button" title="插入链接" className={iconBtn}><i className="ri-link"></i></button>
        <button type="button" title="插入表格" className={iconBtn}><i className="ri-table-2"></i></button>
        <div className="ml-auto flex items-center gap-2">
          <div className="relative">
            <i className="ri-search-line absolute left-2.5 top-1/2 -translate-y-1/2 text-xs text-foreground-400"></i>
            <input
              type="text"
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              placeholder="搜索文档内容…"
              className="h-8 w-44 rounded-md border border-background-300 bg-background-50 pl-8 pr-3 text-xs text-foreground-700 outline-none transition-all focus:w-56 focus:border-primary-400 focus:ring-1 focus:ring-primary-400/20 placeholder:text-foreground-400"
            />
          </div>
          <span className="flex items-center gap-1 text-[11px] text-primary-600">
            <i className="ri-lock-2-line"></i>只读预览
          </span>
        </div>
      </div>

      {/* 文档内容区：连续纸张（参照闭环 Word 纸面） */}
      <div className="flex-1 overflow-auto bg-background-200/50 px-4 py-5 md:px-6">
        <div
          className="word-sheet mx-auto w-full max-w-[820px] px-8 py-10 md:px-12"
          style={{ transform: `scale(${zoom / 100})`, transformOrigin: "top center" }}
        >
          <div className="lex-editor">
            {tenderSections.map((section) => {
              const isTitle = section.id === "title";
              return (
                <section
                  key={section.id}
                  id={`tender-sec-${section.id}`}
                  className={`transition-all duration-500 ${focusSection === section.id ? "bg-primary-100/50 ring-1 ring-primary-300/60" : ""}`}
                >
                  <h1
                    className={`${headingClass[section.level]} ${
                      isTitle ? "!text-[24px] !text-center" : ""
                    }`}
                  >
                    {section.heading}
                  </h1>
                  <div className="space-y-0.5">
                    {section.paragraphs.map((para) => {
                      if (para.table) {
                        return (
                          <table key={para.id} className="my-3">
                            <thead>
                              <tr>
                                {para.table.headers.map((h) => (
                                  <th key={h}>{h}</th>
                                ))}
                              </tr>
                            </thead>
                            <tbody>
                              {para.table.rows.map((row, ri) => (
                                <tr key={ri}>
                                  {row.map((cell, ci) => (
                                    <td key={ci}>{cell}</td>
                                  ))}
                                </tr>
                              ))}
                            </tbody>
                          </table>
                        );
                      }
                      if (para.empty) {
                        return (
                          <p key={para.id} className="editor-paragraph !mb-0 text-center text-[22px] font-bold text-foreground-950">
                            {para.text}
                          </p>
                        );
                      }
                      if (para.list) {
                        return (
                          <p key={para.id} className="editor-paragraph flex items-start gap-1.5 pl-1">
                            <span className="mt-[9px] h-1.5 w-1.5 shrink-0 rounded-full bg-primary-500" />
                            <span className="flex-1">{para.text}</span>
                          </p>
                        );
                      }
                      const isBold = /^[0-9]/.test(para.text) && para.text.length <= 8;
                      return (
                        <p key={para.id} className={`editor-paragraph ${isBold ? "font-semibold text-foreground-900" : ""}`}>
                          {para.text}
                        </p>
                      );
                    })}
                  </div>
                </section>
              );
            })}
          </div>
        </div>
      </div>

      {/* 底部状态栏 */}
      <div className="flex items-center justify-between border-t border-background-300 bg-background-100 px-4 py-1.5 text-[11px] text-foreground-500">
        <span className="flex items-center gap-1">
          <i className="ri-file-word-2-line text-primary-500"></i>
          招标文件 · {projectName || projectCode}
        </span>
        <span className="flex items-center gap-3">
          <button
            type="button"
            onClick={() => jumpTo("s1")}
            className="hidden cursor-pointer items-center gap-0.5 hover:text-primary-600 sm:flex"
          >
            <i className="ri-bookmark-3-line text-xs"></i>第一章
          </button>
          <button
            type="button"
            onClick={() => jumpTo("s3")}
            className="hidden cursor-pointer items-center gap-0.5 hover:text-primary-600 sm:flex"
          >
            <i className="ri-list-check-2 text-xs"></i>评标办法
          </button>
          <span>字数 {totalWords}</span>
          <span>共 {tenderSections.length} 章</span>
        </span>
      </div>
    </div>
  );
}