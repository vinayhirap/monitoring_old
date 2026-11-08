import clsx from "clsx";
import { ReactNode } from "react";

export function Panel({
  title,
  right,
  children,
  className,
  noPad,
}: {
  title?: string;
  right?: ReactNode;
  children: ReactNode;
  className?: string;
  noPad?: boolean;
}) {
  return (
    <div className={clsx(
      "bg-card border border-bg-line rounded-md shadow-card",
      "hover:border-bg-lineHi transition-colors",
      className
    )}>
      {title && (
        <div className="px-3.5 py-2 border-b border-bg-line flex items-center justify-between">
          <h3 className="text-[10.5px] font-bold uppercase tracking-[0.08em] text-accent-amber">
            {title}
          </h3>
          {right}
        </div>
      )}
      <div className={noPad ? "" : "p-3.5"}>{children}</div>
    </div>
  );
}

export function Stat({
  label, value, sub, color,
}: { label: string; value: string | number; sub?: string; color?: string }) {
  return (
    <div>
      <div className="text-[9.5px] uppercase text-text-muted tracking-wider font-semibold">{label}</div>
      <div className={clsx("text-lg tabular font-bold leading-tight mt-0.5",
                            color || "text-text-primary")}>
        {value}
      </div>
      {sub && <div className="text-[10px] text-text-muted mt-0.5">{sub}</div>}
    </div>
  );
}
