interface ProgressRingProps {
  value: number;
  size?: number;
  stroke?: number;
  color?: "primary" | "accent" | "secondary";
  label?: string;
}

const colorVars: Record<NonNullable<ProgressRingProps["color"]>, string> = {
  primary: "oklch(var(--primary-500))",
  accent: "oklch(var(--accent-500))",
  secondary: "oklch(var(--secondary-500))",
};

export default function ProgressRing({
  value,
  size = 56,
  stroke = 5,
  color = "primary",
  label,
}: ProgressRingProps) {
  const clamped = Math.max(0, Math.min(100, value));
  const ringColor = colorVars[color];
  const innerSize = size - stroke * 2;

  return (
    <div
      className="relative flex shrink-0 items-center justify-center rounded-full ring-1 ring-background-200"
      style={{
        width: size,
        height: size,
        background: `conic-gradient(${ringColor} ${clamped * 3.6}deg, oklch(var(--background-200)) ${clamped * 3.6}deg)`,
      }}
    >
      <div
        className="absolute rounded-full bg-background-100"
        style={{ width: innerSize, height: innerSize }}
      />
      <div className="relative flex flex-col items-center justify-center leading-none">
        <span className="font-heading text-gradient text-sm font-semibold" style={{ fontSize: size * 0.2 }}>
          {label || `${clamped}`}
          {label === undefined && <span className="ml-0.5 text-[0.55em] text-foreground-500">%</span>}
        </span>
      </div>
    </div>
  );
}