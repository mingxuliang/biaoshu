interface StatusBadgeProps {
  status: string;
  pulse?: boolean;
}

const statusStyles: Record<string, string> = {
  撰写中: "bg-primary-50 text-primary-600 border-primary-200",
  评标中: "bg-accent-50 text-accent-600 border-accent-200",
  已提交: "bg-secondary-100 text-secondary-700 border-secondary-200",
  已中标: "bg-primary-50 text-primary-600 border-primary-200",
  未中标: "bg-secondary-100 text-secondary-600 border-secondary-200",
  已完成: "bg-primary-50 text-primary-600 border-primary-200",
  修订中: "bg-accent-50 text-accent-600 border-accent-200",
  进行中: "bg-primary-50 text-primary-600 border-primary-200",
  待开始: "bg-secondary-100 text-secondary-500 border-secondary-200",
  待生成: "bg-secondary-100 text-secondary-500 border-secondary-200",
  生成中: "bg-accent-50 text-accent-600 border-accent-200",
  在线: "bg-primary-50 text-primary-600 border-primary-200",
  忙碌: "bg-accent-50 text-accent-600 border-accent-200",
  离线: "bg-secondary-100 text-secondary-500 border-secondary-200",
  推荐: "bg-primary-50 text-primary-600 border-primary-200",
  备选: "bg-accent-50 text-accent-600 border-accent-200",
  淘汰: "bg-secondary-100 text-secondary-500 border-secondary-200",
};

const dotStyles: Record<string, string> = {
  撰写中: "bg-primary-500",
  评标中: "bg-accent-500",
  已提交: "bg-secondary-500",
  已中标: "bg-primary-500",
  未中标: "bg-secondary-500",
  已完成: "bg-primary-500",
  修订中: "bg-accent-500",
  进行中: "bg-primary-500",
  待开始: "bg-secondary-400",
  待生成: "bg-secondary-400",
  生成中: "bg-accent-500",
  在线: "bg-primary-500",
  忙碌: "bg-accent-500",
  离线: "bg-secondary-400",
  推荐: "bg-primary-500",
  备选: "bg-accent-500",
  淘汰: "bg-secondary-400",
};

export default function StatusBadge({ status, pulse = false }: StatusBadgeProps) {
  return (
    <span
      className={`inline-flex items-center gap-1.5 whitespace-nowrap rounded-md border px-2 py-0.5 text-xs font-medium ${statusStyles[status] || statusStyles["待开始"]}`}
    >
      <span className="relative flex h-1.5 w-1.5">
        {pulse && (
          <span className={`absolute inline-flex h-full w-full rounded-full ${dotStyles[status] || "bg-secondary-400"} opacity-50 animate-ping`} />
        )}
        <span className={`relative inline-flex h-1.5 w-1.5 rounded-full ${dotStyles[status] || "bg-secondary-400"}`} />
      </span>
      {status}
    </span>
  );
}