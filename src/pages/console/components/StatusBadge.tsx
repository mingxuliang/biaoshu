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
  用原文: "bg-secondary-100 text-secondary-700 border-secondary-200",
  生成中: "bg-accent-50 text-accent-600 border-accent-200",
  在线: "bg-primary-50 text-primary-600 border-primary-200",
  忙碌: "bg-accent-50 text-accent-600 border-accent-200",
  离线: "bg-secondary-100 text-secondary-500 border-secondary-200",
  推荐: "bg-primary-50 text-primary-600 border-primary-200",
  备选: "bg-accent-50 text-accent-600 border-accent-200",
  淘汰: "bg-secondary-100 text-secondary-500 border-secondary-200",
  通过: "bg-primary-50 text-primary-600 border-primary-200",
  阻断: "bg-accent-50 text-accent-600 border-accent-200",
  有效: "bg-primary-50 text-primary-600 border-primary-200",
  将到期: "bg-accent-50 text-accent-600 border-accent-200",
  已过期: "bg-secondary-100 text-secondary-600 border-secondary-200",
  启用: "bg-primary-50 text-primary-600 border-primary-200",
  已停用: "bg-secondary-100 text-secondary-500 border-secondary-200",
  待审核: "bg-accent-50 text-accent-600 border-accent-200",
  已入库: "bg-primary-50 text-primary-600 border-primary-200",
  解析中: "bg-accent-50 text-accent-600 border-accent-200",
  抽取失败: "bg-secondary-100 text-secondary-600 border-secondary-200",
  新增: "bg-secondary-100 text-secondary-700 border-secondary-200",
  并入已有: "bg-primary-50 text-primary-600 border-primary-200",
  疑似重复: "bg-accent-50 text-accent-600 border-accent-200",
  参数冲突: "bg-accent-50 text-accent-700 border-accent-200",
  信息冲突: "bg-accent-50 text-accent-700 border-accent-200",
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
  用原文: "bg-secondary-500",
  生成中: "bg-accent-500",
  在线: "bg-primary-500",
  忙碌: "bg-accent-500",
  离线: "bg-secondary-400",
  推荐: "bg-primary-500",
  备选: "bg-accent-500",
  淘汰: "bg-secondary-400",
  通过: "bg-primary-500",
  阻断: "bg-accent-500",
  有效: "bg-primary-500",
  将到期: "bg-accent-500",
  已过期: "bg-secondary-400",
  启用: "bg-primary-500",
  已停用: "bg-secondary-400",
  待审核: "bg-accent-500",
  已入库: "bg-primary-500",
  解析中: "bg-accent-500",
  抽取失败: "bg-secondary-500",
  新增: "bg-secondary-500",
  并入已有: "bg-primary-500",
  疑似重复: "bg-accent-500",
  参数冲突: "bg-accent-600",
  信息冲突: "bg-accent-600",
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