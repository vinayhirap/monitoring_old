export const fmt = {
  num: (v: number | null | undefined, d = 2) =>
    v === null || v === undefined || Number.isNaN(v) ? "—" : Number(v).toFixed(d),
  pct: (v: number | null | undefined, d = 2) =>
    v === null || v === undefined ? "—" : `${Number(v).toFixed(d)}%`,
  inr: (v: number | null | undefined) =>
    v === null || v === undefined ? "—" : new Intl.NumberFormat("en-IN", { maximumFractionDigits: 2 }).format(v),
};

export function signalColor(signal: string): string {
  switch (signal) {
    case "STRONG_BUY":  return "text-accent-green glow-amber";
    case "BUY":         return "text-accent-green";
    case "STRONG_SELL": return "text-accent-red glow-amber";
    case "SELL":        return "text-accent-red";
    default:            return "text-text-secondary";
  }
}

export function biasColor(bias: string): string {
  switch (bias) {
    case "BULLISH": return "text-accent-green";
    case "BEARISH": return "text-accent-red";
    default:        return "text-text-secondary";
  }
}
