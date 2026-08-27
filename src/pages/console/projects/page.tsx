import { useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import PageHeader from "../components/PageHeader";
import StatusBadge from "../components/StatusBadge";
import TypeBadge from "../components/TypeBadge";
import Toast from "../components/Toast";
import MonitorPanel from "./components/MonitorPanel";
import AssignMembersModal from "./components/AssignMembersModal";
import ProjectFilesModal from "./components/ProjectFilesModal";
import ProjectFormModal, { type ProjectFormValues } from "./components/ProjectFormModal";
import DeleteProjectModal from "./components/DeleteProjectModal";
import { projectTypes, projectStatuses, type Project } from "@/mocks/projects";
import { useProjects } from "@/context/ProjectContext";
import { useAuth } from "@/context/AuthContext";
import { hasPerm } from "@/lib/permissions";

interface ToastState {
  message: string;
  type: "success" | "error" | "info";
  visible: boolean;
}

const statCards = [
  { key: "total", label: "全部项目", icon: "ri-folder-2-line", gradient: "from-primary-400 to-primary-600", bar: "from-primary-500 to-primary-400" },
  { key: "active", label: "进行中", icon: "ri-loader-4-line", gradient: "from-accent-400 to-accent-500", bar: "from-accent-500 to-accent-400" },
  { key: "progress", label: "平均进度", icon: "ri-percent-line", gradient: "from-secondary-400 to-secondary-500", bar: "from-secondary-400 to-secondary-300" },
  { key: "score", label: "平均预测得分", icon: "ri-focus-3-line", gradient: "from-primary-400 to-primary-600", bar: "from-primary-500 to-primary-400" },
];

export default function ProjectsPage() {
  const navigate = useNavigate();
  const { projects, addProject, updateProject, deleteProject } = useProjects();
  const { user } = useAuth();
  const canEditProject = hasPerm(user?.role, "project_edit");
  const [keyword, setKeyword] = useState("");
  const [typeFilter, setTypeFilter] = useState<string>("全部");
  const [statusFilter, setStatusFilter] = useState<string>("全部");
  const [sortBy, setSortBy] = useState<string>("created");
  const [createOpen, setCreateOpen] = useState(false);
  const [editOpen, setEditOpen] = useState(false);
  const [editTarget, setEditTarget] = useState<Project | null>(null);
  const [toast, setToast] = useState<ToastState>({ message: "", type: "success", visible: false });

  const [assignTarget, setAssignTarget] = useState<{ projectId: string; selected: string[] } | null>(null);
  const [filesTarget, setFilesTarget] = useState<string | null>(null);
  const [deleteTarget, setDeleteTarget] = useState<Project | null>(null);

  const showToast = (message: string, type: ToastState["type"] = "success") => {
    setToast({ message, type, visible: true });
    window.setTimeout(() => setToast((t) => ({ ...t, visible: false })), 3000);
  };

  const stats = useMemo(() => {
    const active = projects.filter((p) => p.status === "撰写中" || p.status === "评标中").length;
    const scored = projects.filter((p) => p.score > 0);
    const avgProgress = Math.round(projects.reduce((s, p) => s + p.progress, 0) / Math.max(projects.length, 1));
    const avgScore = scored.length ? (scored.reduce((s, p) => s + p.score, 0) / scored.length).toFixed(1) : "—";
    return { total: projects.length, active, avgProgress, avgScore };
  }, [projects]);

  const filtered = useMemo(() => {
    let list = projects.filter((p) => {
      const matchKeyword = p.name.toLowerCase().includes(keyword.toLowerCase()) || p.code.toLowerCase().includes(keyword.toLowerCase());
      const matchType = typeFilter === "全部" || p.type === typeFilter;
      const matchStatus = statusFilter === "全部" || p.status === statusFilter;
      return matchKeyword && matchType && matchStatus;
    });
    if (sortBy === "deadline") {
      list = [...list].sort((a, b) => a.deadline.localeCompare(b.deadline));
    } else if (sortBy === "score") {
      list = [...list].sort((a, b) => b.score - a.score);
    } else {
      list = [...list].sort((a, b) => b.createdAt.localeCompare(a.createdAt));
    }
    return list;
  }, [projects, keyword, typeFilter, statusFilter, sortBy]);

  const handleSubmit = async (values: ProjectFormValues) => {
    if (!values.name.trim() || !values.code.trim()) {
      showToast("请填写项目名称与招标编号", "error");
      return;
    }
    if (editOpen && editTarget) {
      try {
        await updateProject(
          editTarget.id,
          {
            code: values.code.trim(),
            name: values.name.trim(),
            type: values.type,
            owner: values.owner,
            budget: values.budget ? `¥ ${values.budget} 万` : "待定",
            deadline: values.deadline || "2026-12-31",
          },
          { tenderFile: values.tenderFile, memberIds: values.memberIds },
        );
        setEditOpen(false);
        setEditTarget(null);
        showToast(
          values.tenderFile
            ? `已更新「${values.name.trim()}」项目信息（招标文件：${values.tenderFile.name}）`
            : `已更新「${values.name.trim()}」项目信息（分配 ${values.memberIds.length} 人）`,
        );
      } catch (err) {
        showToast(err instanceof Error ? err.message : "更新项目失败，请稍后重试", "error");
      }
      return;
    }
    try {
      const newProject = await addProject({
        code: values.code.trim(),
        name: values.name.trim(),
        type: values.type,
        owner: values.owner,
        budget: values.budget,
        deadline: values.deadline || "2026-12-31",
        tenderFile: values.tenderFile,
        memberIds: values.memberIds,
      });
      setCreateOpen(false);
      showToast(
        values.memberIds.length > 0
          ? `项目创建成功，已分配 ${values.memberIds.length} 人，正在进入招标解析…`
          : "项目创建成功，正在进入招标解析…",
      );
      window.setTimeout(() => navigate(`/console/parse?project=${newProject.id}`), 600);
    } catch (err) {
      showToast(err instanceof Error ? err.message : "创建项目失败，请稍后重试", "error");
    }
  };

  const openEdit = (project: Project) => {
    setEditTarget(project);
    setEditOpen(true);
  };

  const closeForm = () => {
    setCreateOpen(false);
    setEditOpen(false);
    setEditTarget(null);
  };

  const openAssign = (project: Project) => {
    setAssignTarget({ projectId: project.id, selected: (project.team ?? []).map((m) => m.id) });
  };

  const saveAssign = async (memberIds: string[]) => {
    if (!assignTarget) return;
    try {
      await updateProject(assignTarget.projectId, {}, { memberIds });
      const project = projects.find((p) => p.id === assignTarget.projectId);
      showToast(`已更新「${project?.name ?? ""}」项目人员分配（${memberIds.length} 人）`);
      setAssignTarget(null);
    } catch (err) {
      showToast(err instanceof Error ? err.message : "保存分配失败，请稍后重试", "error");
    }
  };

  const assignProject = projects.find((p) => p.id === assignTarget?.projectId) ?? null;
  const filesProject = projects.find((p) => p.id === filesTarget) ?? null;

  const inputCls =
    "h-9 w-full rounded-md border border-background-300 bg-background-50 px-3 text-sm text-foreground-900 outline-none transition-all focus:border-primary-400 focus:ring-1 focus:ring-primary-400/20 placeholder:text-foreground-500";

  return (
    <div>
      <PageHeader
        title="标书项目管理中心"
        description="统一监控投标项目整体进程：跟踪撰写进度、AI 预测得分、人员分配与文件归档。"
        actions={
          canEditProject ? (
          <button
            type="button"
            onClick={() => setCreateOpen(true)}
            className="flex h-9 cursor-pointer items-center gap-1.5 whitespace-nowrap rounded-md bg-primary-500 px-4 text-sm font-medium text-background-50 transition-colors hover:bg-primary-600"
          >
            <i className="ri-add-line text-sm"></i>
            新建项目
          </button>
          ) : undefined
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
                {card.key === "active" && stats.active}
                {card.key === "progress" && `${stats.avgProgress}%`}
                {card.key === "score" && stats.avgScore}
              </div>
            </div>
            <div className={`absolute bottom-0 left-0 right-0 h-[2px] bg-gradient-to-r ${card.bar} opacity-0 transition-opacity duration-300 group-hover:opacity-100`} />
          </div>
        ))}
      </div>

      {/* 整体进程监控 + AI 评分分析 + 状态分布 + 风险 */}
      <MonitorPanel projects={projects} />

      {/* 筛选工具栏 */}
      <div className="mb-4 flex flex-col gap-3 rounded-lg border border-background-300 bg-background-100 p-3.5 lg:flex-row lg:items-center">
        <div className="relative flex-1">
          <i className="ri-search-line absolute left-3 top-1/2 -translate-y-1/2 text-xs text-foreground-500"></i>
          <input
            type="text"
            value={keyword}
            onChange={(e) => setKeyword(e.target.value)}
            placeholder="搜索项目名称或招标编号…"
            className={`${inputCls} pl-9`}
          />
        </div>
        <div className="flex flex-wrap items-center gap-1.5">
          {["全部", ...projectTypes].map((t) => (
            <button
              key={t}
              type="button"
              onClick={() => setTypeFilter(t)}
              className={`cursor-pointer whitespace-nowrap rounded-full border px-2.5 py-1 text-xs font-medium transition-all ${
                typeFilter === t
                  ? "border-primary-200 bg-primary-50 text-primary-600"
                  : "border-background-300 bg-transparent text-foreground-600 hover:border-background-400 hover:text-foreground-700"
              }`}
            >
              {t}
            </button>
          ))}
        </div>
        <div className="flex items-center gap-2">
          <select
            value={statusFilter}
            onChange={(e) => setStatusFilter(e.target.value)}
            className={`${inputCls} w-28 cursor-pointer`}
          >
            <option value="全部">全部状态</option>
            {projectStatuses.map((s) => (
              <option key={s} value={s}>
                {s}
              </option>
            ))}
          </select>
          <select
            value={sortBy}
            onChange={(e) => setSortBy(e.target.value)}
            className={`${inputCls} w-28 cursor-pointer`}
          >
            <option value="created">最近更新</option>
            <option value="deadline">截止时间</option>
            <option value="score">预测得分</option>
          </select>
        </div>
      </div>

      {/* 项目表格 */}
      <div className="overflow-hidden rounded-lg border border-background-300 bg-background-100">
        <div className="overflow-x-auto">
          <table className="w-full min-w-[960px] text-left">
            <thead>
              <tr className="font-label border-b border-background-300 bg-background-50 text-xs text-foreground-500">
                <th className="px-4 py-3 font-medium">项目名称</th>
                <th className="px-3 py-3 font-medium">类型</th>
                <th className="px-3 py-3 font-medium">负责人</th>
                <th className="px-3 py-3 font-medium">项目团队</th>
                <th className="px-3 py-3 font-medium">撰写进度</th>
                <th className="px-3 py-3 font-medium">预测得分</th>
                <th className="px-3 py-3 font-medium">截止日期</th>
                <th className="px-3 py-3 font-medium">状态</th>
                <th className="px-3 py-3 text-right font-medium">操作</th>
              </tr>
            </thead>
            <tbody>
              {filtered.map((project) => {
                const teamMembers = project.team ?? [];
                const shown = teamMembers.slice(0, 3);
                const rest = Math.max(teamMembers.length - 3, 0);
                return (
                  <tr
                    key={project.id}
                    onClick={() => navigate(`/console/projects/${project.id}`)}
                    className="group cursor-pointer border-b border-background-200 transition-colors last:border-0 hover:bg-primary-50/30"
                  >
                    <td className="px-4 py-3.5">
                      <div className="font-medium text-sm text-foreground-900 transition-colors group-hover:text-primary-600">
                        {project.name}
                      </div>
                      <div className="mt-0.5 text-xs text-foreground-500">编号 {project.code}</div>
                    </td>
                    <td className="px-3 py-3.5">
                      <TypeBadge type={project.type} />
                    </td>
                    <td className="px-3 py-3.5">
                      <span className="flex items-center gap-2 whitespace-nowrap text-sm text-foreground-700">
                        <span className="flex h-6 w-6 items-center justify-center rounded-full bg-secondary-100 text-xs font-medium text-secondary-700">
                          {project.owner.charAt(0)}
                        </span>
                        {project.owner}
                      </span>
                    </td>
                    <td className="px-3 py-3.5">
                      {shown.length > 0 ? (
                        <div className="flex items-center">
                          <div className="flex -space-x-1.5">
                            {shown.map((m) => (
                              <span
                                key={m.id}
                                title={m.name}
                                className="flex h-6 w-6 items-center justify-center rounded-full border-2 border-background-100 bg-secondary-100 text-[10px] font-medium text-secondary-700"
                              >
                                {m.name.charAt(0)}
                              </span>
                            ))}
                          </div>
                          {rest > 0 && (
                            <span className="ml-1.5 text-xs text-foreground-500">+{rest}</span>
                          )}
                        </div>
                      ) : (
                        <span className="text-xs text-foreground-500">未分配</span>
                      )}
                    </td>
                    <td className="px-3 py-3.5">
                      <div className="flex items-center gap-2">
                        <div className="h-1.5 w-16 overflow-hidden rounded-full bg-background-200">
                          <div
                            className="h-full rounded-full bg-gradient-to-r from-primary-500 to-primary-400 transition-all"
                            style={{ width: `${project.progress}%` }}
                          />
                        </div>
                        <span className="font-label w-8 text-xs text-foreground-500">{project.progress}%</span>
                      </div>
                    </td>
                    <td className="px-3 py-3.5">
                      {project.score > 0 ? (
                        <span className="font-heading text-gradient text-sm font-bold">{project.score}</span>
                      ) : (
                        <span className="text-sm text-foreground-500">—</span>
                      )}
                    </td>
                    <td className="px-3 py-3.5">
                      <span className="whitespace-nowrap text-sm text-foreground-500">{project.deadline}</span>
                    </td>
                    <td className="px-3 py-3.5">
                      <StatusBadge status={project.status} pulse={project.status === "评标中"} />
                    </td>
                    <td className="px-3 py-3.5">
                      <div className="flex items-center justify-end gap-0.5">
                        {canEditProject && (
                        <button
                          type="button"
                          title="编辑项目信息"
                          onClick={(e) => {
                            e.stopPropagation();
                            openEdit(project);
                          }}
                          className="flex h-7 w-7 cursor-pointer items-center justify-center rounded-md text-foreground-500 transition-all hover:scale-110 hover:bg-primary-50 hover:text-primary-600"
                        >
                          <i className="ri-edit-2-line text-sm"></i>
                        </button>
                        )}
                        {canEditProject && (
                        <button
                          type="button"
                          title="分配项目人员"
                          onClick={(e) => {
                            e.stopPropagation();
                            openAssign(project);
                          }}
                          className="flex h-7 w-7 cursor-pointer items-center justify-center rounded-md text-foreground-500 transition-all hover:scale-110 hover:bg-secondary-100 hover:text-secondary-700"
                        >
                          <i className="ri-team-line text-sm"></i>
                        </button>
                        )}
                        <button
                          type="button"
                          title="项目文件下载"
                          onClick={(e) => {
                            e.stopPropagation();
                            setFilesTarget(project.id);
                          }}
                          className="flex h-7 w-7 cursor-pointer items-center justify-center rounded-md text-foreground-500 transition-all hover:scale-110 hover:bg-primary-50 hover:text-primary-600"
                        >
                          <i className="ri-folder-download-line text-sm"></i>
                        </button>
                        {canEditProject && (
                        <button
                          type="button"
                          title="删除项目"
                          onClick={(e) => {
                            e.stopPropagation();
                            setDeleteTarget(project);
                          }}
                          className="flex h-7 w-7 cursor-pointer items-center justify-center rounded-md text-foreground-500 transition-all hover:scale-110 hover:bg-secondary-100 hover:text-secondary-700"
                        >
                          <i className="ri-delete-bin-6-line text-sm"></i>
                        </button>
                        )}
                      </div>
                    </td>
                  </tr>
                );
              })}
              {filtered.length === 0 && (
                <tr>
                  <td colSpan={9} className="px-4 py-16 text-center">
                    <i className="ri-inbox-line text-3xl text-foreground-400"></i>
                    <p className="mt-3 text-sm text-foreground-500">
                      {projects.length === 0 ? "暂无项目，请新建后开始投标工作" : "没有找到匹配的项目，试试调整筛选条件"}
                    </p>
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      </div>

      {/* 新建 / 编辑项目弹窗 */}
      <ProjectFormModal
        open={createOpen || editOpen}
        mode={editOpen ? "edit" : "create"}
        initial={editTarget}
        initialMemberIds={editTarget ? (editTarget.team ?? []).map((m) => m.id) : []}
        onClose={closeForm}
        onSubmit={handleSubmit}
      />

      {/* 分配项目人员弹窗 */}
      <AssignMembersModal
        open={!!assignTarget}
        project={assignProject}
        selected={assignTarget?.selected ?? []}
        onClose={() => setAssignTarget(null)}
        onSave={saveAssign}
      />

      {/* 项目文件下载弹窗 */}
      <ProjectFilesModal
        open={!!filesTarget}
        project={filesProject}
        onClose={() => setFilesTarget(null)}
        onToast={(msg, type) => showToast(msg, type ?? "success")}
      />

      {/* 删除项目确认弹窗 */}
      <DeleteProjectModal
        open={!!deleteTarget}
        project={deleteTarget}
        onClose={() => setDeleteTarget(null)}
        onConfirm={async () => {
          if (!deleteTarget) return;
          try {
            await deleteProject(deleteTarget.id);
            showToast(`已删除项目「${deleteTarget.name}」及其全部文件`);
          } catch (err) {
            showToast(err instanceof Error ? err.message : "删除项目失败，请稍后重试", "error");
          } finally {
            setDeleteTarget(null);
          }
        }}
      />

      <Toast message={toast.message} type={toast.type} visible={toast.visible} />
    </div>
  );
}