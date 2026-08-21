import { useEffect, type ReactNode } from "react";

interface ModalProps {
  open: boolean;
  title: string;
  subtitle?: string;
  onClose: () => void;
  children: ReactNode;
  width?: string;
}

export default function Modal({ open, title, subtitle, onClose, children, width = "max-w-lg" }: ModalProps) {
  useEffect(() => {
    if (!open) return;
    const handleKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    window.addEventListener("keydown", handleKey);
    document.body.style.overflow = "hidden";
    return () => {
      window.removeEventListener("keydown", handleKey);
      document.body.style.overflow = "";
    };
  }, [open, onClose]);

  if (!open) return null;

  return (
    <div className="fixed inset-0 z-[80] flex items-center justify-center p-4">
      <div
        className="absolute inset-0 bg-foreground-950/40 animate-fade-in"
        onClick={onClose}
      />
      <div
        className={`relative w-full ${width} max-h-[88vh] overflow-y-auto rounded-xl border border-background-300 bg-background-100 animate-pop-in`}
      >
        <div className="sticky top-0 z-10 flex items-start justify-between gap-4 border-b border-background-300 bg-background-100 px-5 py-4">
          <div>
            <h3 className="text-base font-semibold text-foreground-950">{title}</h3>
            {subtitle && <p className="mt-0.5 text-xs text-foreground-500">{subtitle}</p>}
          </div>
          <button
            type="button"
            onClick={onClose}
            className="flex h-7 w-7 shrink-0 cursor-pointer items-center justify-center rounded-md text-foreground-500 transition-colors hover:bg-background-200 hover:text-foreground-800"
            aria-label="关闭"
          >
            <i className="ri-close-line text-lg"></i>
          </button>
        </div>
        <div className="px-5 py-4">{children}</div>
      </div>
    </div>
  );
}