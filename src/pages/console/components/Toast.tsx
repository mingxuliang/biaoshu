interface ToastProps {
  message: string;
  type?: "success" | "error" | "info";
  visible: boolean;
}

const typeStyles = {
  success: "border-primary-200 bg-primary-50 text-primary-700",
  error: "border-red-200 bg-red-50 text-red-700",
  info: "bg-background-100 border-background-300 text-foreground-700",
};

const iconMap = {
  success: "ri-check-line",
  error: "ri-error-warning-line",
  info: "ri-information-line",
};

export default function Toast({ message, type = "success", visible }: ToastProps) {
  if (!visible) return null;

  return (
    <div className="fixed bottom-6 right-6 z-[90] animate-slide-up">
      <div className={`flex items-center gap-2 rounded-lg border px-4 py-2.5 text-sm font-medium ${typeStyles[type]}`}>
        <i className={`${iconMap[type]} text-base`}></i>
        {message}
      </div>
    </div>
  );
}