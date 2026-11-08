"use client";

/**
 * SymbolSearchAutocomplete — fuzzy search box for picking a symbol.
 *
 * Debounced 250ms. Shows up to 8 results in a dropdown. Click or Enter
 * to select. Keyboard nav: ↑/↓ to highlight, Enter to confirm, Esc to close.
 *
 * Usage:
 *   <SymbolSearchAutocomplete onPick={(sym) => router.push(`/portal/symbol/${sym}`)} />
 *
 * Drop-in for the existing SymbolSearch component — same prop signature.
 */

import { useState, useEffect, useRef, useCallback } from "react";
import { authedFetcher as fetcher } from "@/lib/auth";
import { Search, X } from "lucide-react";
import clsx from "clsx";


export interface SymbolResult {
  symbol: string;
  exchange: string;
  name: string;
  token?: string;
}


export function SymbolSearchAutocomplete({
  onPick, placeholder = "Search stock — NIFTY, RELIANCE, …",
  autoFocus = false,
}: {
  onPick: (sym: string, row: SymbolResult) => void;
  placeholder?: string;
  autoFocus?: boolean;
}) {
  const [query, setQuery] = useState("");
  const [results, setResults] = useState<SymbolResult[]>([]);
  const [open, setOpen] = useState(false);
  const [highlightIdx, setHighlightIdx] = useState(0);
  const inputRef = useRef<HTMLInputElement>(null);
  const wrapperRef = useRef<HTMLDivElement>(null);

  // ---- Debounced search ----
  useEffect(() => {
    if (!query.trim() || query.length < 1) {
      setResults([]); setOpen(false); return;
    }
    let cancelled = false;
    const timer = setTimeout(async () => {
      try {
        const res = await fetcher<{ results: SymbolResult[] }>(
          `/api/market/search?q=${encodeURIComponent(query)}&limit=8`,
        );
        if (!cancelled) {
          setResults(res.results || []);
          setOpen(true);
          setHighlightIdx(0);
        }
      } catch {
        if (!cancelled) { setResults([]); setOpen(false); }
      }
    }, 250);
    return () => { cancelled = true; clearTimeout(timer); };
  }, [query]);

  // ---- Click-outside to close ----
  useEffect(() => {
    const handler = (e: MouseEvent) => {
      if (wrapperRef.current && !wrapperRef.current.contains(e.target as Node)) {
        setOpen(false);
      }
    };
    document.addEventListener("mousedown", handler);
    return () => document.removeEventListener("mousedown", handler);
  }, []);

  const pick = useCallback((row: SymbolResult) => {
    onPick(row.symbol, row);
    setQuery(""); setResults([]); setOpen(false);
    inputRef.current?.blur();
  }, [onPick]);

  const handleKey = (e: React.KeyboardEvent<HTMLInputElement>) => {
    if (!open || results.length === 0) return;
    if (e.key === "ArrowDown") {
      e.preventDefault();
      setHighlightIdx((i) => Math.min(i + 1, results.length - 1));
    } else if (e.key === "ArrowUp") {
      e.preventDefault();
      setHighlightIdx((i) => Math.max(i - 1, 0));
    } else if (e.key === "Enter") {
      e.preventDefault();
      pick(results[highlightIdx]);
    } else if (e.key === "Escape") {
      setOpen(false);
    }
  };

  return (
    <div ref={wrapperRef} className="relative">
      <div className="flex items-center gap-2 bg-bg-base border border-bg-line rounded px-3 py-1.5 text-[12px] min-w-[260px] focus-within:border-accent-amber">
        <Search className="w-3.5 h-3.5 text-text-muted shrink-0" />
        <input
          ref={inputRef}
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          onFocus={() => results.length > 0 && setOpen(true)}
          onKeyDown={handleKey}
          autoFocus={autoFocus}
          placeholder={placeholder}
          className="flex-1 bg-transparent outline-none text-text-primary placeholder:text-text-muted/60"
        />
        {query && (
          <button onClick={() => { setQuery(""); setResults([]); }}
            className="text-text-muted hover:text-text-primary">
            <X className="w-3 h-3" />
          </button>
        )}
        <kbd className="text-[9px] text-text-muted bg-bg-surface border border-bg-line rounded px-1">
          ↵
        </kbd>
      </div>

      {/* Dropdown */}
      {open && results.length > 0 && (
        <div className="absolute top-full left-0 right-0 mt-1 bg-bg-surface border border-bg-line rounded-lg shadow-lg z-50 overflow-hidden">
          {results.map((r, i) => (
            <button key={`${r.symbol}-${r.exchange}-${i}`}
              onClick={() => pick(r)}
              onMouseEnter={() => setHighlightIdx(i)}
              className={clsx(
                "w-full px-3 py-2 text-left flex items-center justify-between gap-2 transition-colors",
                i === highlightIdx ? "bg-accent-amber/10" : "hover:bg-bg-base/60"
              )}>
              <div className="min-w-0">
                <div className="font-bold text-text-primary text-[12px]">{r.symbol}</div>
                {r.name && (
                  <div className="text-[10px] text-text-muted truncate">{r.name}</div>
                )}
              </div>
              <span className="text-[9px] text-text-muted font-bold uppercase shrink-0 bg-bg-base border border-bg-line rounded px-1.5 py-0.5">
                {r.exchange}
              </span>
            </button>
          ))}
        </div>
      )}

      {open && query && results.length === 0 && (
        <div className="absolute top-full left-0 right-0 mt-1 bg-bg-surface border border-bg-line rounded-lg shadow-lg z-50 p-3 text-[11px] text-text-muted text-center">
          No symbols match "{query}".
          <div className="text-[10px] mt-1 opacity-70">
            Try the bare ticker (e.g. RELIANCE, not RELIANCE.NS).
          </div>
        </div>
      )}
    </div>
  );
}
