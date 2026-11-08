"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import useSWR from "swr";
import { fetcher } from "@/lib/api";
import { AnimatedNumber, ChangeBadge } from "@/components/animated";
import { Plus, X, Star, TrendingUp, TrendingDown } from "lucide-react";
import clsx from "clsx";

const STORAGE_KEY = "marketlens.watchlist.v1";
const DEFAULT_WATCHLIST = ["NIFTY", "BANKNIFTY", "RELIANCE", "TCS", "ICICIBANK", "HDFCBANK", "INFY", "SBIN"];

function loadWatchlist(): string[] {
  if (typeof window === "undefined") return DEFAULT_WATCHLIST;
  try {
    const raw = window.localStorage.getItem(STORAGE_KEY);
    if (raw) return JSON.parse(raw);
  } catch {}
  return DEFAULT_WATCHLIST;
}

function saveWatchlist(symbols: string[]) {
  if (typeof window === "undefined") return;
  try {
    window.localStorage.setItem(STORAGE_KEY, JSON.stringify(symbols));
  } catch {}
}

export function Watchlist() {
  const router = useRouter();
  const [symbols, setSymbols] = useState<string[]>(DEFAULT_WATCHLIST);
  const [adding, setAdding] = useState(false);
  const [newSym, setNewSym] = useState("");

  // Hydrate from localStorage on mount (avoid SSR mismatch)
  useEffect(() => { setSymbols(loadWatchlist()); }, []);

  function remove(sym: string) {
    const next = symbols.filter((s) => s !== sym);
    setSymbols(next);
    saveWatchlist(next);
  }
  function add() {
    const s = newSym.trim().toUpperCase();
    if (!s || symbols.includes(s)) { setAdding(false); setNewSym(""); return; }
    const next = [...symbols, s];
    setSymbols(next);
    saveWatchlist(next);
    setAdding(false);
    setNewSym("");
  }

  return (
    <div className="bg-card border border-bg-line rounded-md">
      <div className="flex items-center justify-between px-3 py-2 border-b border-bg-line">
        <div className="flex items-center gap-2">
          <Star className="w-3.5 h-3.5 text-accent-amber" />
          <span className="text-[10.5px] font-bold uppercase tracking-wider text-accent-amber">
            Watchlist
          </span>
          <span className="text-[10px] text-text-muted">{symbols.length}</span>
        </div>
        <button onClick={() => setAdding(true)}
          className="text-[10px] text-text-muted hover:text-accent-amber flex items-center gap-1">
          <Plus className="w-3 h-3" /> add
        </button>
      </div>

      <div className="divide-y divide-bg-line/40 max-h-96 overflow-y-auto">
        {symbols.map((sym) => (
          <WatchlistRow key={sym} sym={sym}
            onOpen={() => router.push(`/symbol/${sym}`)}
            onRemove={() => remove(sym)} />
        ))}

        {adding && (
          <div className="flex items-center gap-2 px-3 py-2 bg-bg-base/40">
            <input autoFocus value={newSym}
              onChange={(e) => setNewSym(e.target.value.toUpperCase())}
              onKeyDown={(e) => {
                if (e.key === "Enter") add();
                if (e.key === "Escape") { setAdding(false); setNewSym(""); }
              }}
              placeholder="Symbol (e.g. WIPRO)"
              className="flex-1 bg-bg-base border border-bg-line rounded px-2 py-1 text-[12px] font-mono" />
            <button onClick={add} className="text-[10px] text-accent-amber font-bold">add</button>
            <button onClick={() => { setAdding(false); setNewSym(""); }}
              className="text-[10px] text-text-muted">cancel</button>
          </div>
        )}

        {symbols.length === 0 && !adding && (
          <div className="px-3 py-6 text-center text-text-muted text-[11px]">
            No symbols saved. Click <span className="text-accent-amber">+ add</span> above.
          </div>
        )}
      </div>
    </div>
  );
}

function WatchlistRow({ sym, onOpen, onRemove }:
                       { sym: string; onOpen: () => void; onRemove: () => void }) {
  const { data: q } = useSWR<any>(`/api/market/quote/${sym}?exchange=NSE`, fetcher,
    { refreshInterval: 10_000 });
  const ltp = q?.ltp || 0;
  const close = q?.close || ltp;
  const change = ltp - close;
  const changePct = close ? (change / close) * 100 : 0;
  const up = change >= 0;

  return (
    <div className="flex items-center gap-2 px-3 py-2 group hover:bg-bg-base/40 cursor-pointer"
          onClick={onOpen}>
      <div className="flex-1 min-w-0">
        <div className="text-text-primary text-[12px] font-semibold truncate">{sym}</div>
        <div className="text-[9px] text-text-muted">
          {q?.is_live === true ? <span className="text-accent-green">live</span> :
           q?.is_live === false ? <span className="text-accent-amber">paper</span> : "—"}
        </div>
      </div>
      <div className="text-right shrink-0">
        <AnimatedNumber value={ltp} decimals={2}
          className="text-text-primary font-semibold text-[12px] tabular block" />
        <div className={clsx("text-[10px] tabular flex items-center gap-1 justify-end",
          up ? "text-accent-green" : "text-accent-red")}>
          {up ? <TrendingUp className="w-2.5 h-2.5" /> : <TrendingDown className="w-2.5 h-2.5" />}
          {up ? "+" : ""}{change.toFixed(2)} ({up ? "+" : ""}{changePct.toFixed(2)}%)
        </div>
      </div>
      <button onClick={(e) => { e.stopPropagation(); onRemove(); }}
        className="opacity-0 group-hover:opacity-100 text-text-muted hover:text-accent-red transition-opacity">
        <X className="w-3 h-3" />
      </button>
    </div>
  );
}
