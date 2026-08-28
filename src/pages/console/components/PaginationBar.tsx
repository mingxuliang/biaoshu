interface PaginationBarProps {
  total: number;
  page: number;
  pageSize: number;
  onPageChange: (page: number) => void;
}

export default function PaginationBar({ total, page, pageSize, onPageChange }: PaginationBarProps) {
  const totalPages = Math.max(1, Math.ceil(total / pageSize));
  if (total === 0) return null;
  const safePage = Math.min(Math.max(1, page), totalPages);
  const start = (safePage - 1) * pageSize + 1;
  const end = Math.min(safePage * pageSize, total);

  const pages: number[] = [];
  const from = Math.max(1, safePage - 2);
  const to = Math.min(totalPages, from + 4);
  for (let i = from; i <= to; i += 1) pages.push(i);

  return (
    <div className="flex flex-wrap items-center justify-between gap-2 px-4 py-2.5">
      <span className="text-xs text-foreground-500">
        第 {start}–{end} 条，共 {total} 条
      </span>
      <div className="flex items-center gap-1">
        <button
          type="button"
          disabled={safePage <= 1}
          onClick={() => onPageChange(safePage - 1)}
          className="flex h-8 w-8 cursor-pointer items-center justify-center rounded-md border border-background-300 text-foreground-600 transition-colors hover:bg-background-200 disabled:cursor-not-allowed disabled:opacity-40"
          aria-label="上一页"
        >
          <i className="ri-arrow-left-s-line"></i>
        </button>
        {pages[0] > 1 && (
          <>
            <button
              type="button"
              onClick={() => onPageChange(1)}
              className="flex h-8 min-w-8 cursor-pointer items-center justify-center rounded-md border border-background-300 px-2 text-xs font-medium text-foreground-600 hover:bg-background-200"
            >
              1
            </button>
            {pages[0] > 2 && <span className="px-1 text-xs text-foreground-400">…</span>}
          </>
        )}
        {pages.map((n) => (
          <button
            key={n}
            type="button"
            onClick={() => onPageChange(n)}
            className={`flex h-8 min-w-8 cursor-pointer items-center justify-center rounded-md border px-2 text-xs font-medium transition-colors ${
              n === safePage
                ? "border-primary-200 bg-primary-50 text-primary-600"
                : "border-background-300 text-foreground-600 hover:bg-background-200"
            }`}
          >
            {n}
          </button>
        ))}
        {pages[pages.length - 1] < totalPages && (
          <>
            {pages[pages.length - 1] < totalPages - 1 && <span className="px-1 text-xs text-foreground-400">…</span>}
            <button
              type="button"
              onClick={() => onPageChange(totalPages)}
              className="flex h-8 min-w-8 cursor-pointer items-center justify-center rounded-md border border-background-300 px-2 text-xs font-medium text-foreground-600 hover:bg-background-200"
            >
              {totalPages}
            </button>
          </>
        )}
        <button
          type="button"
          disabled={safePage >= totalPages}
          onClick={() => onPageChange(safePage + 1)}
          className="flex h-8 w-8 cursor-pointer items-center justify-center rounded-md border border-background-300 text-foreground-600 transition-colors hover:bg-background-200 disabled:cursor-not-allowed disabled:opacity-40"
          aria-label="下一页"
        >
          <i className="ri-arrow-right-s-line"></i>
        </button>
      </div>
    </div>
  );
}
