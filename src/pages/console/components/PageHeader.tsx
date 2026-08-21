import type { ReactNode } from "react";

interface PageHeaderProps {
  title: string;
  description?: string;
  actions?: ReactNode;
}

export default function PageHeader({ title, description, actions }: PageHeaderProps) {
  return (
    <div className="mb-5 flex flex-col gap-3 sm:flex-row sm:items-end sm:justify-between">
      <div>
        <h2 className="font-heading text-lg font-semibold tracking-wide text-foreground-950">{title}</h2>
        <div className="mt-1.5 h-[2px] w-10 rounded-full bg-gradient-to-r from-primary-500 to-primary-300" />
        {description && <p className="mt-2 max-w-2xl text-sm text-foreground-500">{description}</p>}
      </div>
      {actions && <div className="flex shrink-0 items-center gap-2">{actions}</div>}
    </div>
  );
}