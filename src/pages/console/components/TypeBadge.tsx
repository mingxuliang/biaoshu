const typeStyles: Record<string, string> = {
  工程: "bg-secondary-100 text-secondary-700 border-secondary-200",
  政采: "bg-accent-50 text-accent-600 border-accent-200",
  医疗: "bg-primary-50 text-primary-600 border-primary-200",
  交通: "bg-secondary-100 text-secondary-700 border-secondary-200",
  IT: "bg-primary-50 text-primary-600 border-primary-200",
  能源: "bg-accent-50 text-accent-600 border-accent-200",
};

export default function TypeBadge({ type }: { type: string }) {
  return (
    <span
      className={`inline-flex items-center whitespace-nowrap rounded-md border px-2 py-0.5 text-xs font-medium ${typeStyles[type] || "bg-secondary-100 text-secondary-600 border-secondary-200"}`}
    >
      {type}
    </span>
  );
}