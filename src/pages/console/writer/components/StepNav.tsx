interface StepDef {
  key: number;
  title: string;
  desc: string;
  icon: string;
}

const steps: StepDef[] = [
  { key: 1, title: "标书设置", desc: "模型与知识库", icon: "ri-settings-3-line" },
  { key: 2, title: "标书解读", desc: "解析与对标", icon: "ri-file-settings-line" },
  { key: 3, title: "目录生成", desc: "大纲与编写思路", icon: "ri-list-check-3" },
  { key: 4, title: "正文生成", desc: "撰写与精修", icon: "ri-edit-2-line" },
];

interface StepNavProps {
  current: number;
  completed: Record<number, boolean>;
  onStepClick: (step: number) => void;
}

export default function StepNav({ current, completed, onStepClick }: StepNavProps) {
  return (
    <div className="rounded-lg border border-background-300 bg-background-100 px-3 py-2.5">
      <div className="flex items-center gap-1 sm:gap-2">
        {steps.map((step, idx) => {
          const isDone = completed[step.key];
          const isCurrent = step.key === current;
          const reachable = isDone || isCurrent;
          return (
            <div key={step.key} className="flex min-w-0 flex-1 items-center gap-1 sm:gap-2">
              <button
                type="button"
                onClick={() => reachable && onStepClick(step.key)}
                disabled={!reachable}
                className={`group flex min-w-0 flex-1 cursor-pointer items-center gap-2 rounded-lg px-2 py-1.5 text-left transition-all sm:px-3 ${
                  isCurrent ? "bg-primary-50 ring-1 ring-primary-200/70" : isDone ? "hover:bg-background-50" : "opacity-60"
                } ${reachable ? "" : "cursor-not-allowed"}`}
              >
                <span
                  className={`flex h-6 w-6 shrink-0 items-center justify-center rounded-full text-[11px] transition-colors sm:h-7 sm:w-7 ${
                    isCurrent
                      ? "bg-gradient-to-br from-primary-400 to-primary-600 text-background-50"
                      : isDone
                        ? "bg-primary-500 text-background-50"
                        : "border border-background-300 bg-background-50 text-foreground-500"
                  }`}
                >
                  {isDone && !isCurrent ? <i className="ri-check-line"></i> : step.key}
                </span>
                <span className="hidden min-w-0 items-center gap-1.5 sm:flex">
                  <i className={`${step.icon} text-sm ${isCurrent ? "text-primary-500" : isDone ? "text-foreground-400" : "text-foreground-400"}`}></i>
                  <span className="min-w-0">
                    <span className={`block truncate text-xs font-semibold ${isCurrent ? "text-primary-700" : "text-foreground-800"}`}>
                      {step.title}
                    </span>
                    <span className="block truncate text-[10px] text-foreground-500">{step.desc}</span>
                  </span>
                </span>
              </button>
              {idx < steps.length - 1 && (
                <span className={`h-px w-2 shrink-0 sm:w-4 ${completed[step.key] ? "bg-primary-400" : "bg-background-300"}`}></span>
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
}