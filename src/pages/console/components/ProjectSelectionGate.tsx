import { useProjects } from "@/context/ProjectContext";
import PageHeader from "./PageHeader";
import StatusBadge from "./StatusBadge";
import TypeBadge from "./TypeBadge";

interface ProjectSelectionGateProps {
  title: string;
  description: string;
  stepLabel: string;
  stepHint: string;
  icon: string;
  accentClass: string;
  onSelect: (id: string) => void;
}

export default function ProjectSelectionGate({
  title,
  description,
  stepLabel,
  stepHint,
  icon,
  accentClass,
  onSelect,
}: ProjectSelectionGateProps) {
  const { projects } = useProjects();

  return (
    <div>
      <PageHeader title={title} description={description} />
      <div className="overflow-hidden rounded-lg border border-background-300 bg-background-100">
        <div className="flex flex-wrap items-center gap-2.5 border-b border-background-300 bg-background-50 px-5 py-4 sm:justify-between">
          <div className="flex items-center gap-2.5">
            <span
              className={`flex h-9 w-9 items-center justify-center rounded-lg bg-gradient-to-br ${accentClass} text-background-50`}
            >
              <i className={`${icon} text-lg`}></i>
            </span>
            <div>
              <div className="font-label text-sm font-semibold text-foreground-900">{stepLabel}</div>
              <div className="text-xs text-foreground-500">{stepHint}</div>
            </div>
          </div>
          <select
            value=""
            onChange={(e) => e.target.value && onSelect(e.target.value)}
            className="h-9 w-full cursor-pointer rounded-md border border-background-300 bg-background-100 px-2.5 text-xs text-foreground-600 outline-none focus:border-primary-400 sm:w-auto sm:max-w-[280px]"
          >
            <option value="">快速选择项目…</option>
            {projects.map((p) => (
              <option key={p.id} value={p.id}>
                {p.name}
              </option>
            ))}
          </select>
        </div>
        <div className="grid grid-cols-1 gap-3 p-5 sm:grid-cols-2 lg:grid-cols-3">
          {projects.map((p) => (
            <button
              key={p.id}
              type="button"
              onClick={() => onSelect(p.id)}
              className="group flex cursor-pointer flex-col gap-2.5 rounded-lg border border-background-300 bg-background-50 p-4 text-left transition-all duration-300 hover:border-primary-300/70 hover:bg-primary-50/40"
            >
              <div className="flex items-start justify-between gap-2">
                <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg bg-secondary-100 text-secondary-600">
                  <i className="ri-folder-open-line text-lg"></i>
                </span>
                <span className="text-xs text-foreground-400 transition-colors group-hover:text-primary-500">进入工作台 →</span>
              </div>
              <div>
                <div className="truncate text-sm font-medium text-foreground-900 group-hover:text-primary-600">{p.name}</div>
                <div className="mt-0.5 text-xs text-foreground-500">编号 {p.code}</div>
              </div>
              <div className="flex flex-wrap items-center gap-1.5">
                <TypeBadge type={p.type} />
                <StatusBadge status={p.status} />
                <span className="text-[11px] text-foreground-500">截止 {p.deadline}</span>
              </div>
            </button>
          ))}
        </div>
      </div>
    </div>
  );
}