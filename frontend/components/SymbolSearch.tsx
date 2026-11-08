"use client";

import { useState, useRef, useEffect } from "react";
import { useRouter } from "next/navigation";
import { Search } from "lucide-react";
import clsx from "clsx";

const TOP_PICKS = [
  "NIFTY", "BANKNIFTY", "FINNIFTY", "RELIANCE", "TCS", "INFY", "HDFCBANK",
  "ICICIBANK", "SBIN", "AXISBANK", "BAJFINANCE", "BHARTIARTL", "MARUTI",
  "TATAMOTORS", "M&M", "HCLTECH", "WIPRO", "ASIANPAINT", "SUNPHARMA",
  "ULTRACEMCO", "NTPC", "POWERGRID", "ONGC", "ADANIENT", "ADANIPORTS",
  "JSWSTEEL", "TATASTEEL", "COALINDIA", "INDUSINDBK", "HDFCLIFE",
  "SBILIFE", "TITAN", "NESTLEIND", "BRITANNIA", "ITC", "HINDUNILVR",
  "LT", "KOTAKBANK", "TECHM", "EICHERMOT",
];

export function SymbolSearch({ className, autoFocus = false }:
                              { className?: string; autoFocus?: boolean }) {
  const router = useRouter();
  const [q, setQ] = useState("");
  const [open, setOpen] = useState(false);
  const [active, setActive] = useState(0);
  const inputRef = useRef<HTMLInputElement>(null);
  const containerRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (autoFocus && inputRef.current) inputRef.current.focus();
  }, [autoFocus]);

  useEffect(() => {
    function onClick(e: MouseEvent) {
      if (!containerRef.current?.contains(e.target as Node)) setOpen(false);
    }
    document.addEventListener("mousedown", onClick);
    return () => document.removeEventListener("mousedown", onClick);
  }, []);

  const filtered = q.trim().length === 0
    ? TOP_PICKS.slice(0, 8)
    : TOP_PICKS.filter((s) => s.includes(q.toUpperCase().trim())).slice(0, 10);

  function go(sym: string) {
    setOpen(false);
    setQ("");
    router.push(`/symbol/${sym.toUpperCase()}`);
  }

  function onKey(e: React.KeyboardEvent) {
    if (e.key === "ArrowDown") {
      e.preventDefault();
      setActive((a) => Math.min(filtered.length - 1, a + 1));
    } else if (e.key === "ArrowUp") {
      e.preventDefault();
      setActive((a) => Math.max(0, a - 1));
    } else if (e.key === "Enter") {
      e.preventDefault();
      const target = filtered[active] || q.toUpperCase().trim();
      if (target) go(target);
    } else if (e.key === "Escape") {
      setOpen(false);
    }
  }

  return (
    <div ref={containerRef} className={clsx("relative", className)}>
      <div className="flex items-center bg-bg-base border border-bg-line rounded
                      focus-within:border-accent-amber/60 focus-within:bg-bg-panel transition-colors">
        <Search className="w-4 h-4 ml-3 text-text-muted" />
        <input
          ref={inputRef}
          value={q}
          onChange={(e) => { setQ(e.target.value); setOpen(true); setActive(0); }}
          onFocus={() => setOpen(true)}
          onKeyDown={onKey}
          placeholder="Search stock — NIFTY, RELIANCE, TCS…"
          className="flex-1 bg-transparent px-3 py-2 text-sm font-mono outline-none"
        />
        <kbd className="text-[9px] text-text-muted px-2">Enter</kbd>
      </div>

      {open && filtered.length > 0 && (
        <div className="absolute top-full left-0 right-0 mt-1 bg-bg-panel border border-bg-line
                        rounded shadow-xl z-50 max-h-80 overflow-auto">
          {q.trim().length === 0 && (
            <div className="text-[10px] uppercase text-text-muted px-3 py-1.5 border-b border-bg-line">
              Top picks
            </div>
          )}
          {filtered.map((s, i) => (
            <button key={s} onClick={() => go(s)}
              onMouseEnter={() => setActive(i)}
              className={clsx("w-full text-left px-3 py-2 text-sm font-mono flex justify-between",
                i === active ? "bg-bg-line text-accent-amber" : "text-text-secondary hover:bg-bg-line/50")}>
              <span>{s}</span>
              <span className="text-[10px] text-text-muted">view detail →</span>
            </button>
          ))}
          {q.trim().length > 0 && !filtered.includes(q.toUpperCase().trim()) && (
            <button onClick={() => go(q.toUpperCase().trim())}
              className="w-full text-left px-3 py-2 text-sm font-mono text-accent-amber border-t border-bg-line">
              Open "{q.toUpperCase().trim()}" →
            </button>
          )}
        </div>
      )}
    </div>
  );
}
