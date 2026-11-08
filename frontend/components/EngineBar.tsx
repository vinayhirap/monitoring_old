import clsx from "clsx";

export function EngineBar({
  label, score, bias,
}: { label: string; score: number; bias: string }) {
  const pct = Math.max(0, Math.min(100, score));
  const color = bias === "BULLISH" ? "bg-accent-green"
              : bias === "BEARISH" ? "bg-accent-red"
              : "bg-accent-amber";
  return (
    <div>
      <div className="flex items-center justify-between text-[11px] mb-1">
        <span className="uppercase text-text-secondary tracking-wider">{label}</span>
        <span className={clsx(
          "tabular font-semibold",
          bias === "BULLISH" ? "text-accent-green"
            : bias === "BEARISH" ? "text-accent-red"
            : "text-text-secondary"
        )}>
          {pct.toFixed(0)} <span className="text-text-muted">/ {bias}</span>
        </span>
      </div>
      <div className="h-1.5 bg-bg-line rounded overflow-hidden">
        <div className={clsx("h-full transition-all", color)} style={{ width: `${pct}%` }} />
      </div>
    </div>
  );
}
