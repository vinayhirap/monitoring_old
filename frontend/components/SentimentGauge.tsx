"use client";

/**
 * Sentiment gauge — horizontal stacked bar showing distribution of
 * BUY / WAIT / SELL picks across the top-picks feed.
 *
 * Drop into a page that already has the picks list; pass the three counts.
 * Gracefully handles all-zero state (renders a flat neutral bar).
 */

import { TrendingUp, Minus, TrendingDown } from "lucide-react";
import clsx from "clsx";


export function SentimentGauge({
  bullish,
  neutral,
  bearish,
  label = "Market sentiment",
}: {
  bullish: number;
  neutral: number;
  bearish: number;
  label?: string;
}) {
  const total = Math.max(1, bullish + neutral + bearish);
  const bPct = (bullish / total) * 100;
  const nPct = (neutral / total) * 100;
  const sPct = (bearish / total) * 100;

  // Headline mood — strongest bias wins
  const mood = bullish > bearish && bullish >= neutral
    ? "BULLISH"
    : bearish > bullish && bearish >= neutral
    ? "BEARISH"
    : "MIXED";

  const moodColor =
    mood === "BULLISH" ? "text-accent-green"
    : mood === "BEARISH" ? "text-accent-red"
    : "text-text-secondary";

  return (
    <div className="bg-bg-surface border border-bg-line rounded-lg p-4">
      <div className="flex items-center justify-between mb-3">
        <div className="text-[11px] uppercase tracking-wider font-bold text-text-muted">
          {label}
        </div>
        <div className={clsx("text-xs font-bold uppercase tracking-wider", moodColor)}>
          {mood}
        </div>
      </div>

      {/* Stacked bar */}
      <div className="flex h-3 rounded-full overflow-hidden bg-bg-base">
        {bullish > 0 && (
          <div className="bg-accent-green transition-all duration-300"
                style={{ width: `${bPct}%` }}
                aria-label={`${bullish} bullish picks`} />
        )}
        {neutral > 0 && (
          <div className="bg-accent-amber transition-all duration-300"
                style={{ width: `${nPct}%` }}
                aria-label={`${neutral} neutral picks`} />
        )}
        {bearish > 0 && (
          <div className="bg-accent-red transition-all duration-300"
                style={{ width: `${sPct}%` }}
                aria-label={`${bearish} bearish picks`} />
        )}
        {bullish + neutral + bearish === 0 && (
          <div className="bg-text-muted/20 w-full" />
        )}
      </div>

      {/* Legend */}
      <div className="flex items-center justify-between mt-3 text-[11px]">
        <div className="flex items-center gap-1.5 text-accent-green font-semibold">
          <TrendingUp className="w-3 h-3" />
          <span>Bullish</span>
          <span className="text-text-secondary font-normal">{bullish}</span>
        </div>
        <div className="flex items-center gap-1.5 text-accent-amber font-semibold">
          <Minus className="w-3 h-3" />
          <span>Neutral</span>
          <span className="text-text-secondary font-normal">{neutral}</span>
        </div>
        <div className="flex items-center gap-1.5 text-accent-red font-semibold">
          <TrendingDown className="w-3 h-3" />
          <span>Bearish</span>
          <span className="text-text-secondary font-normal">{bearish}</span>
        </div>
      </div>
    </div>
  );
}
