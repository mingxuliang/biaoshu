import { Link, useNavigate, useParams } from "react-router-dom";
import PageHeader from "../components/PageHeader";
import StatusBadge from "../components/StatusBadge";
import TypeBadge from "../components/TypeBadge";
import ProgressRing from "../components/ProgressRing";
import ProjectDocuments from "./components/ProjectDocuments";
import { useProjects } from "@/context/ProjectContext";
import { timelineStages, type StageStatus } from "@/mocks/projectDetail";
import { members } from "@/mocks/members";

const stageDot: Record<StageStatus, string> = {
  已完成: "bg-primary-500 border-primary-300",
  进行中: "bg-accent-500 border-accent-300",
  待开始: "bg-background-400 border-background-300",
};

export default function ProjectDetailPage() {
  const { id } = useParams();
  const navigate = useNavigate();
  const { getProject, loading } = useProjects();
  const project = getProject(id);

  if (loading) {
    return (
      <div className="flex items-center justify-center rounded-lg border border-background-300 bg-background-100 p-16">
        <span className="h-8 w-8 animate-spin rounded-full border-2 border-primary-200 border-t-primary-500" />
      </div>
    );
  }

  if (!project) {
    return (
      <div>
        <PageHeader title="项目不存在" />
        <div className="rounded-lg border border-background-300 bg-background-100 p-16 text-center">
          <i className="ri-folder-close-line text-3xl text-foreground-400"></i>
          <p className="mt-3 text-sm text-foreground-500">未找到该项目，可能已被删除或链接有误</p>
          <Link
            to="/console/projects"
            className="mt-5 inline-flex h-9 items-center gap-1.5 rounded-md bg-primary-500 px-4 text-sm font-medium text-background-50 transition-colors hover:bg-primary-600"
          >
            <i className="ri-arrow-left-s-line text-sm"></i>
            返回项目中心
          </Link>
        </div>
      </div>
    );
  }

  const teamMembers = members.slice(0, 5);

  const infoRows = [
    { label: "招标编号", value: project.code },
    { label: "项目类型", value: project.type },
    { label: "预算金额", value: project.budget },
    { label: "投标截止", value: project.deadline },
    { label: "负责人", value: project.owner },
    { label: "创建时间", value: project.createdAt },
  ];

  return (
    <div>
      <Link
        to="/console/projects"
        className="mb-4 inline-flex cursor-pointer items-center gap-1 text-sm text-foreground-500 transition-colors hover:text-primary-600"
      >
        <i className="ri-arrow-left-s-line text-base"></i>
        返回项目中心
      </Link>

      {/* 项目头部 */}
      <div className="mb-5 overflow-hidden rounded-lg border border-background-300 bg-background-100">
        <div className="border-b border-background-300 bg-background-50 px-5 py-4">
          <div className="flex flex-col gap-4 md:flex-row md:items-center md:justify-between">
            <div className="min-w-0">
              <div className="flex flex-wrap items-center gap-2">
                <StatusBadge status={project.status} pulse={project.status === "评标中"} />
                <TypeBadge type={project.type} />
                <span className="text-xs text-foreground-500">编号 {project.code}</span>
              </div>
              <h2 className="mt-2 text-lg font-semibold text-foreground-950">
                {project.name}
              </h2>
              <p className="mt-1 text-sm text-foreground-500">
                负责人 {project.owner} · 预算 {project.budget} · 截止 {project.deadline}
              </p>
            </div>
            <div className="flex shrink-0 items-center gap-4">
              <ProgressRing value={project.progress} size={64} stroke={6} label={`${project.progress}%`} color="primary" />
              <div>
                <div className="text-[11px] text-foreground-500">AI 预测得分</div>
                <div className="font-heading text-gradient mt-0.5 text-2xl font-bold tracking-wide">
                  {project.score > 0 ? project.score : "—"}
                </div>
                <div className="text-[11px] text-foreground-500">撰写进度 {project.progress}%</div>
              </div>
            </div>
          </div>
        </div>
        <div className="flex flex-col gap-2 px-5 py-3 sm:flex-row sm:items-center sm:justify-between">
          <p className="text-xs text-foreground-500">
            {project.status === "撰写中" && "标书正在 AI 撰写与人工修订阶段，当前进度 " + project.progress + "%"}
            {project.status === "评标中" && "标书已提交评标环节，等待招标方开标与评审结果"}
            {project.status === "已提交" && "标书已递交，等待开标评标结果"}
            {project.status === "已中标" && "恭喜中标！本项目已成功中标，可归档复盘"}
            {project.status === "未中标" && "本项目未能中标，可查看评标分析优化下次投标策略"}
          </p>
          <div className="flex flex-wrap items-center gap-2">
            <Link
              to={`/console/parse?project=${project.id}`}
              className="flex h-8 cursor-pointer items-center gap-1.5 whitespace-nowrap rounded-md border border-background-300 bg-background-50 px-3.5 text-xs font-medium text-foreground-700 transition-colors hover:bg-background-200"
            >
              <i className="ri-file-settings-line text-sm"></i>
              招标解析
            </Link>
            <Link
              to={`/console/writer?project=${project.id}`}
              className="flex h-8 cursor-pointer items-center gap-1.5 whitespace-nowrap rounded-md bg-primary-500 px-3.5 text-xs font-medium text-background-50 transition-colors hover:bg-primary-600"
            >
              <i className="ri-edit-2-line text-sm"></i>
              进入撰写工作台
            </Link>
            <Link
              to={`/console/audit?project=${project.id}`}
              className="flex h-8 cursor-pointer items-center gap-1.5 whitespace-nowrap rounded-md border border-background-300 bg-background-50 px-3.5 text-xs font-medium text-foreground-700 transition-colors hover:bg-background-200"
            >
              <i className="ri-shield-check-line text-sm"></i>
              AI 预审
            </Link>
            <Link
              to={`/console/review?project=${project.id}`}
              className="flex h-8 cursor-pointer items-center gap-1.5 whitespace-nowrap rounded-md border border-accent-200 bg-accent-50 px-3.5 text-xs font-medium text-accent-600 transition-colors hover:bg-accent-100"
            >
              <i className="ri-loop-left-line text-sm"></i>
              修改闭环
            </Link>
          </div>
        </div>
      </div>

      <div className="grid grid-cols-1 gap-5 lg:grid-cols-3">
        {/* 左栏 */}
        <div className="space-y-5 lg:col-span-2">
          {/* 项目概览 */}
          <div className="rounded-lg border border-background-300 bg-background-100 p-5">
            <h3 className="mb-3 flex items-center gap-1.5 text-sm font-semibold text-foreground-900">
              <i className="ri-information-line text-primary-500 text-sm"></i>
              项目概览
            </h3>
            <div className="grid grid-cols-2 gap-x-5 gap-y-3 sm:grid-cols-3">
              {infoRows.map((row) => (
                <div key={row.label}>
                  <div className="font-label text-xs text-foreground-500">{row.label}</div>
                  <div className="mt-0.5 text-sm font-medium text-foreground-800">{row.value}</div>
                </div>
              ))}
            </div>
            <div className="mt-5">
              <div className="mb-1.5 flex items-center justify-between text-xs">
                <span className="text-foreground-500">撰写进度</span>
                <span className="font-medium text-primary-600">{project.progress}%</span>
              </div>
              <div className="h-2 overflow-hidden rounded-full bg-background-200">
                <div
                  className="h-full rounded-full bg-gradient-to-r from-primary-500 to-primary-400"
                  style={{ width: `${project.progress}%` }}
                />
              </div>
            </div>
          </div>

          {/* 进度时间线 */}
          <div className="rounded-lg border border-background-300 bg-background-100 p-5">
            <h3 className="mb-4 flex items-center gap-1.5 text-sm font-semibold text-foreground-900">
              <i className="ri-time-line text-primary-500 text-sm"></i>
              投标进度时间线
            </h3>
            <ol className="relative space-y-0">
              {timelineStages.map((stage, index) => (
                <li key={stage.id} className="relative flex gap-4 pb-5 last:pb-0">
                  {index < timelineStages.length - 1 && (
                    <span className="absolute left-[6px] top-3.5 h-full w-px bg-background-300" />
                  )}
                  <span
                    className={`relative z-10 mt-0.5 flex h-[13px] w-[13px] shrink-0 items-center justify-center rounded-full border-2 ${stageDot[stage.status]}`}
                  >
                    {stage.status === "已完成" && <i className="ri-check-line text-[8px] text-background-50"></i>}
                    {stage.status === "进行中" && (
                      <span className="relative flex h-1 w-1">
                        <span className="absolute inline-flex h-full w-full rounded-full bg-accent-400 opacity-60 animate-ping" />
                        <span className="relative inline-flex h-1 w-1 rounded-full bg-accent-500" />
                      </span>
                    )}
                  </span>
                  <div className="flex-1">
                    <div className="flex flex-wrap items-center gap-2">
                      <span
                        className={`text-sm font-medium ${
                          stage.status === "待开始" ? "text-foreground-500" : "text-foreground-900"
                        }`}
                      >
                        {stage.label}
                      </span>
                      <span className="text-xs text-foreground-500">{stage.date}</span>
                      {stage.status !== "待开始" && (
                        <span className="ml-auto text-[11px] text-foreground-500">{stage.desc}</span>
                      )}
                    </div>
                  </div>
                </li>
              ))}
            </ol>
          </div>
        </div>

        {/* 右栏 */}
        <div className="space-y-5">
          {/* 团队成员 */}
          <div className="rounded-lg border border-background-300 bg-background-100 p-5">
            <h3 className="mb-3 flex items-center justify-between text-sm font-semibold text-foreground-900">
              <span className="flex items-center gap-1.5">
                <i className="ri-team-line text-primary-500 text-sm"></i>
                项目团队
              </span>
              <Link to="/console/team" className="text-xs text-foreground-500 transition-colors hover:text-primary-600">
                管理团队
              </Link>
            </h3>
            <div className="space-y-2.5">
              {teamMembers.map((member) => (
                <div key={member.id} className="flex items-center gap-2.5">
                  <span className="relative flex h-8 w-8 items-center justify-center rounded-full bg-secondary-100 text-sm font-medium text-secondary-700">
                    {member.name.charAt(0)}
                    <span
                      className={`absolute -right-0.5 -top-0.5 h-2 w-2 rounded-full border-2 border-background-100 ${
                        member.status === "在线" ? "bg-primary-500 animate-pulse" : member.status === "忙碌" ? "bg-accent-500" : "bg-foreground-400"
                      }`}
                    />
                  </span>
                  <div className="min-w-0 flex-1">
                    <div className="text-sm font-medium text-foreground-900">{member.name}</div>
                    <div className="text-xs text-foreground-500">{member.role}</div>
                  </div>
                </div>
              ))}
            </div>
          </div>
        </div>
      </div>

      {/* 全部文档：招标文件 / 招标解析 / 技术标 / 商务标 */}
      <div className="mt-5">
        <ProjectDocuments />
      </div>

      <div className="mt-5 flex justify-end">
        <button
          type="button"
          onClick={() => navigate("/console/projects")}
          className="cursor-pointer text-sm text-foreground-500 transition-colors hover:text-primary-600"
        >
          ← 返回项目列表
        </button>
      </div>
    </div>
  );
}