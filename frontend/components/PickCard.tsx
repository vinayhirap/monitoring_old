"use client";

/**
 * Reusable pick card — two variants:
 *   • compact  → small tile for home page / sidebars (symbol + verdict + entry only)
 *   • expanded → full card with 4-level grid (Entry / SL / Target / R:R)
 *                and stars + confidence on the right
 *
 * Colored left-border by verdict (green = BUY, red = SELL, amber = WATCH/WAIT).
 * Click anywhere on the card → navigates to /portal/symbol/{symbol}.
 */

import { useRouter } from "next/navigation";
import { TrendingUp, TrendingDown, Star, ArrowRight, AlertCircle, Minus, Clock } from "lucide-react";
import { fmt } from "@/lib/format";
import clsx from "clsx";


export type Pick = {
  symbol: string;
  sector?: string;
  direction?: "BULLISH" | "BEARISH" | "NEUTRAL";
  verdict?: string;                 // optional richer verdict if available
  stars?: number;
  confidence?: number;
  entry?: number;
  stoploss?: number;
  targets?: number[];
  best_instrument?: string;
  horizon?: string;
  // Live tape-consistency fields (added by backend `tape_consistency.enrich_picks`).
  // Optional everywhere — when absent the card renders the original verdict only.
  live_ltp?: number | null;
  day_change_pct?: number | null;
  tape_status?: "ALIGNED" | "WEAK_ALIGNMENT" | "CONTRADICTED" | "OVEREXTENDED" | "STALE";
  hora_conflict?: boolean;
  live_verdict?: "PROCEED" | "WAIT" | "AVOID_NOW";
  live_label?: string;
  live_reasons?: string[];
};


function borderClassFor(verdictOrDirection: string): string {
  const v = (verdictOrDirection || "").toUpperCase();
  if (v.includes("STRONG_BUY") || v === "BULLISH" || v === "BUY")  return "border-l-accent-green";
  if (v.includes("STRONG_SELL") || v === "BEARISH" || v === "SELL") return "border-l-accent-red";
  if (v === "AVOID")                                                return "border-l-accent-red";
  if (v === "WATCH" || v === "WAIT")                                return "border-l-accent-amber";
  return "border-l-bg-line";
}


function tintBgFor(verdictOrDirection: string): string {
  const v = (verdictOrDirection || "").toUpperCase();
  if (v.includes("BUY") || v === "BULLISH")  return "bg-accent-green/[0.02]";
  if (v.includes("SELL") || v === "BEARISH" || v === "AVOID") return "bg-accent-red/[0.02]";
  if (v === "WATCH" || v === "WAIT")                          return "bg-accent-amber/[0.02]";
  return "";
}


function VerdictBadge({ verdict, direction }:
                       { verdict?: string; direction?: string }) {
  const label = verdict || direction || "—";
  const v = label.toUpperCase();
  const isBuy  = v.includes("BUY")  || v === "BULLISH";
  const isSell = v.includes("SELL") || v === "BEARISH" || v === "AVOID";
  const isWait = v === "WAIT" || v === "WATCH";

  const Icon = isBuy ? TrendingUp : isSell ? TrendingDown : isWait ? Minus : AlertCircle;
  const cls = isBuy
    ? "text-accent-green bg-accent-green/10 border-accent-green/30"
    : isSell
    ? "text-accent-red bg-accent-red/10 border-accent-red/30"
    : isWait
    ? "text-accent-amber bg-accent-amber/10 border-accent-amber/30"
    : "text-text-secondary bg-bg-base border-bg-line";

  return (
    <span className={clsx("inline-flex items-center gap-1 px-2 py-0.5 rounded border text-[10px] font-bold uppercase tracking-wider", cls)}>
      <Icon className="w-3 h-3" />
      {label.replace(/_/g, " ")}
    </span>
  );
}


function StarRow({ stars = 0 }: { stars?: number }) {
  return (
    <div className="inline-flex gap-0.5">
      {Array.from({ length: 5 }).map((_, i) => (
        <Star key={i} className={clsx("w-3 h-3",
          i < stars ? "fill-accent-amber text-accent-amber" : "text-text-muted/30")} />
      ))}
    </div>
  );
}


/** Small chip showing today's % change. Color follows the SIGN of the change,
 *  not the recommendation direction — so a BULLISH pick that's down today
 *  shows red, surfacing the contradiction visually. */
function DayChangePill({ pct }: { pct?: number | null }) {
  if (pct == null) return null;
  const up = pct > 0;
  const flat = Math.abs(pct) < 0.05;
  return (
    <span className={clsx(
      "inline-flex items-center gap-0.5 px-1.5 py-0.5 rounded text-[10px] font-bold tabular",
      flat ? "bg-text-muted/10 text-text-muted"
           : up ? "bg-accent-green/10 text-accent-green"
                : "bg-accent-red/10 text-accent-red",
    )}>
      {up ? "▲" : flat ? "·" : "▼"} {Math.abs(pct).toFixed(2)}%
    </span>
  );
}


/** Inline banner shown when the pick direction conflicts with today's tape
 *  or the current planetary hora. Returns null when everything is aligned. */
function TapeConflictBanner({ pick }: { pick: Pick }) {
  if (!pick.tape_status && !pick.hora_conflict) return null;
  if (pick.tape_status === "ALIGNED" && !pick.hora_conflict) return null;

  const isHardConflict =
    pick.tape_status === "CONTRADICTED" || pick.live_verdict === "AVOID_NOW";
  const cls = isHardConflict
    ? "bg-accent-red/10 border-accent-red/30 text-accent-red"
    : "bg-accent-amber/10 border-accent-amber/30 text-accent-amber";
  const Icon = isHardConflict ? AlertCircle : Clock;

  return (
    <div className={clsx("flex items-start gap-1.5 px-2 py-1.5 rounded border text-[10px] mt-2",
                          cls)}>
      <Icon className="w-3 h-3 shrink-0 mt-0.5" />
      <div>
        <span className="font-bold uppercase tracking-wider">
          {pick.live_label || "Tape check"}
        </span>
        {pick.live_reasons && pick.live_reasons.length > 0 && (
          <div className="text-text-secondary leading-snug mt-0.5">
            {pick.live_reasons[0]}
          </div>
        )}
      </div>
    </div>
  );
}


// ─── Compact variant ─────────────────────────────────────────────────────

export function PickCardCompact({ pick }: { pick: Pick }) {
  const router = useRouter();
  const verdictOrDir = pick.verdict || pick.direction || "";
  const isAvoidNow = pick.live_verdict === "AVOID_NOW";
  return (
    <button
      onClick={() => router.push(`/portal/symbol/${pick.symbol}`)}
      className={clsx(
        "w-full text-left bg-bg-surface border border-bg-line border-l-4 rounded-lg",
        "p-3 hover:border-accent-amber transition-colors group",
        // When tape contradicts, fade the card slightly so users don't act on it blindly
        isAvoidNow && "opacity-80",
        borderClassFor(verdictOrDir), tintBgFor(verdictOrDir),
      )}
    >
      <div className="flex items-center justify-between mb-2">
        <div className="min-w-0">
          <div className="flex items-center gap-1.5">
            <span className="font-bold text-text-primary text-sm truncate">{pick.symbol}</span>
            <DayChangePill pct={pick.day_change_pct} />
          </div>
          {pick.sector && (
            <div className="text-[9px] uppercase text-text-muted tracking-tight">{pick.sector}</div>
          )}
        </div>
        <VerdictBadge verdict={pick.verdict} direction={pick.direction} />
      </div>

      <div className="flex items-center justify-between text-[11px]">
        <div>
          <span className="text-text-muted">Entry </span>
          <span className="font-semibold tabular text-text-primary">
            {pick.entry ? `₹${fmt.inr(pick.entry)}` : "—"}
          </span>
          {pick.live_ltp != null && (
            <>
              <span className="text-text-muted ml-1.5">LTP </span>
              <span className="font-semibold tabular text-text-primary">
                ₹{fmt.inr(pick.live_ltp)}
              </span>
            </>
          )}
        </div>
        <div className="flex items-center gap-2">
          <StarRow stars={pick.stars} />
          <span className={clsx("font-bold tabular text-[12px]",
            (pick.confidence || 0) >= 70 ? "text-accent-green"
            : (pick.confidence || 0) >= 55 ? "text-accent-amber"
            : "text-text-muted")}>
            {Math.round(pick.confidence || 0)}%
          </span>
        </div>
      </div>

      {/* Tape / hora conflict banner — surfaces "stock is down today" or
          "current hora is wrong direction" so users don't blindly act on
          a stale BULLISH rating when the tape contradicts it. */}
      <TapeConflictBanner pick={pick} />
    </button>
  );
}


// ─── Expanded variant ────────────────────────────────────────────────────

export function PickCardExpanded({ pick }: { pick: Pick }) {
  const router = useRouter();
  const verdictOrDir = pick.verdict || pick.direction || "";
  const target1 = pick.targets?.[0];
  const target2 = pick.targets?.[1];
  const risk = pick.entry && pick.stoploss ? Math.abs(pick.entry - pick.stoploss) : 0;
  const reward = pick.entry && target1 ? Math.abs(target1 - pick.entry) : 0;
  const rr = risk > 0 ? (reward / risk) : 0;

  const isAvoidNow = pick.live_verdict === "AVOID_NOW";
  return (
    <div
      className={clsx(
        "bg-bg-surface border border-bg-line border-l-4 rounded-lg p-4 hover:border-accent-amber transition-colors",
        isAvoidNow && "opacity-90",
        borderClassFor(verdictOrDir), tintBgFor(verdictOrDir),
      )}
    >
      {/* Header */}
      <div className="flex items-start justify-between gap-3 mb-3 pb-3 border-b border-bg-line">
        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-2 flex-wrap">
            <h3 className="text-base font-bold text-text-primary">{pick.symbol}</h3>
            {pick.horizon && (
              <span className="text-[9px] uppercase tracking-wider font-bold text-text-secondary border border-bg-line rounded px-1.5 py-0.5">
                {pick.horizon}
              </span>
            )}
            <DayChangePill pct={pick.day_change_pct} />
          </div>
          {pick.sector && (
            <div className="text-[10px] uppercase text-text-muted tracking-tight mt-0.5">
              {pick.sector}
            </div>
          )}
          {pick.live_ltp != null && (
            <div className="text-[11px] text-text-muted mt-1">
              Live LTP:{" "}
              <span className="font-semibold tabular text-text-primary">
                ₹{fmt.inr(pick.live_ltp)}
              </span>
            </div>
          )}
        </div>
        <div className="text-right shrink-0">
          <VerdictBadge verdict={pick.verdict} direction={pick.direction} />
          <div className="mt-1.5 flex items-center justify-end gap-2">
            <StarRow stars={pick.stars} />
            <span className={clsx("text-sm font-bold tabular",
              (pick.confidence || 0) >= 70 ? "text-accent-green"
              : (pick.confidence || 0) >= 55 ? "text-accent-amber"
              : "text-text-muted")}>
              {Math.round(pick.confidence || 0)}%
            </span>
          </div>
        </div>
      </div>

      {/* Tape / hora conflict banner — render at the TOP so it's the first
          thing the user sees on a contradicted pick. */}
      <TapeConflictBanner pick={pick} />

      {/* 4-level grid */}
      <div className="grid grid-cols-2 sm:grid-cols-4 gap-2 mb-3">
        <Level label="Entry"     value={pick.entry}    anchor="border-l-accent-blue/60" />
        <Level label="Target 1"  value={target1}       anchor="border-l-accent-green/60" valueClass="text-accent-green" />
        <Level label="Stop loss" value={pick.stoploss} anchor="border-l-accent-red/60"   valueClass="text-accent-red" />
        <Level label="R:R"       value={rr ? `${rr.toFixed(2)}x` : "—"}
                anchor="border-l-accent-amber/60"
                valueClass={rr >= 2 ? "text-accent-green" : rr >= 1.5 ? "text-accent-amber" : "text-text-muted"}
                isText />
      </div>

      {/* Optional second target if present */}
      {target2 && (
        <div className="text-[10px] text-text-muted mb-3">
          Target 2: <span className="font-semibold text-text-secondary tabular">₹{fmt.inr(target2)}</span>
          {pick.targets?.[2] && (
            <> · Target 3: <span className="font-semibold text-text-secondary tabular">₹{fmt.inr(pick.targets[2])}</span></>
          )}
        </div>
      )}

      {/* CTA */}
      <button
        onClick={() => router.push(`/portal/symbol/${pick.symbol}`)}
        className="w-full mt-1 flex items-center justify-center gap-1.5 text-[11px] font-semibold uppercase tracking-wider text-accent-amber hover:text-accent-gold py-2 rounded border border-accent-amber/30 hover:bg-accent-amber/5"
      >
        View full analysis
        <ArrowRight className="w-3.5 h-3.5" />
      </button>
    </div>
  );
}


function Level({ label, value, anchor, valueClass, isText }:
                 { label: string; value: any; anchor: string; valueClass?: string; isText?: boolean }) {
  const empty = value == null || value === "";
  const display = isText
    ? (empty ? "—" : String(value))
    : (empty ? "—" : `₹${fmt.inr(Number(value))}`);
  return (
    <div className={clsx("border-l-2 bg-bg-base/40 rounded-r px-2.5 py-1.5", anchor)}>
      <div className="text-[9px] uppercase tracking-wider text-text-muted font-semibold">
        {label}
      </div>
      <div className={clsx("text-sm font-bold tabular mt-0.5", valueClass || "text-text-primary")}>
        {display}
      </div>
    </div>
  );
}
