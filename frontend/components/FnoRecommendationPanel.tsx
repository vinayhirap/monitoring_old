"use client";

/**
 * F&O recommendation panel — consumes /api/options/recommend/{symbol}.
 *
 * Shows the full multi-engine F&O verdict for a single symbol:
 *   • Headline + verdict pill + conviction stars + confidence %
 *   • Strategy name + per-leg breakdown (strike, premium, greeks, action)
 *   • P&L envelope: max profit, max loss, breakevens, R:R
 *   • Options analytics: PCR, max pain, IV regime, support/resistance walls
 *   • Astro overlay: aligned-with-trade flag + symbol nakshatra
 *   • Technical confluence: confirming vs dissenting engine count
 *   • Caveats + hard-blocks
 *   • Suggested lots + capital + entry/exit triggers
 *
 * Degradation:
 *   • Free/Basic tier → endpoint 402s, ApiError fires global UpgradeModal,
 *     this panel renders a tier-gated stub with an Upgrade CTA.
 *   • Options chain unavailable → backend returns verdict=AVOID with the
 *     reason in `headline`; we render that, not an error.
 *   • Any other error → small inline error block, never breaks the page.
 */

import useSWR from "swr";
import { useState } from "react";
import { authedFetcher as fetcher, authedFetch, ApiError } from "@/lib/auth";
import { fmt } from "@/lib/format";
import {
  TrendingUp, TrendingDown, Minus, AlertTriangle, Sparkles, Activity,
  CheckCircle2, XCircle, Lock, Loader2, Send, Info,
} from "lucide-react";
import clsx from "clsx";


export function FnoRecommendationPanel({ symbol }: { symbol: string }) {
  const { data, error, isLoading } = useSWR<any>(
    `/api/options/recommend/${symbol}?horizon=INTRADAY`,
    fetcher,
    { refreshInterval: 60_000, shouldRetryOnError: false },
  );

  // Tier gate — endpoint 402s for FREE/BASIC users. The global UpgradeModal
  // also pops automatically (we dispatch the event from authedFetcher), so
  // this is just the inline state shown on the panel itself.
  if (error instanceof ApiError && error.status === 402) {
    return (
      <div className="bg-bg-surface border border-bg-line rounded-lg p-5 text-center">
        <Lock className="w-6 h-6 text-accent-amber mx-auto mb-2" />
        <h3 className="font-bold text-text-primary mb-1">F&O recommendations are INTERMEDIATE+</h3>
        <p className="text-[12px] text-text-secondary max-w-md mx-auto">
          Unlock per-symbol option strategy with strike picks, greeks, max pain,
          PCR, IV regime, and astro overlay. {error.body?.detail?.message
            ? <span className="block mt-1 text-text-muted">{error.body.detail.message}</span>
            : null}
        </p>
      </div>
    );
  }

  if (error) {
    return (
      <div className="bg-accent-red/5 border border-accent-red/30 rounded-lg p-4 text-[12px] text-accent-red flex items-start gap-2">
        <AlertTriangle className="w-4 h-4 shrink-0 mt-0.5" />
        <div>
          <strong>F&O recommendation unavailable.</strong>
          <div className="text-[11px] mt-1 text-text-muted">
            {String(error.message)}
          </div>
        </div>
      </div>
    );
  }

  if (isLoading || !data) {
    return (
      <div className="bg-bg-surface border border-bg-line rounded-lg p-5 flex items-center gap-2 text-[12px] text-text-muted">
        <Loader2 className="w-4 h-4 animate-spin" />
        Computing F&O recommendation for {symbol}…
      </div>
    );
  }

  // If safe_build returned an error wrapper, show it cleanly
  if (data.error) {
    return (
      <div className="bg-accent-amber/5 border border-accent-amber/30 rounded-lg p-4 text-[12px]">
        <strong className="text-accent-amber">F&O analysis incomplete</strong>
        <div className="text-text-secondary mt-1">{data.headline || data.error}</div>
      </div>
    );
  }

  return <FnoCard rec={data} />;
}


// ─── Main card ────────────────────────────────────────────────────────────

function FnoCard({ rec }: { rec: any }) {
  const verdict     = rec.verdict || "WATCH";
  const conviction  = rec.conviction || "NONE";
  const direction   = rec.direction || "NEUTRAL";
  const confidence  = rec.confidence_pct || 0;
  const isCalibrated = !!rec.confidence_is_calibrated;

  const isBuy  = verdict.includes("BUY")  || direction === "BULLISH";
  const isSell = verdict.includes("SELL") || direction === "BEARISH" || verdict === "AVOID";
  const isWait = verdict === "WATCH" || verdict === "WAIT";

  const borderClass =
    isBuy  ? "border-l-accent-green" :
    isSell ? "border-l-accent-red"   :
    isWait ? "border-l-accent-amber" : "border-l-bg-line";

  const pillClass =
    isBuy  ? "bg-accent-green text-white" :
    isSell ? "bg-accent-red text-white"   :
    isWait ? "bg-accent-amber/15 text-accent-amber" : "bg-bg-base text-text-muted";

  return (
    <div className={clsx("bg-bg-surface border border-bg-line border-l-4 rounded-lg p-5 space-y-4",
                          borderClass)}>
      {/* Header — verdict pill + conviction stars + confidence */}
      <div className="flex items-start justify-between gap-4 flex-wrap">
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2 mb-1">
            <span className={clsx("inline-block px-3 py-1 rounded font-black text-sm tracking-wider", pillClass)}>
              F&O · {verdict.replace(/_/g, " ")}
            </span>
            {rec.strategy && rec.strategy !== "WAIT" && (
              <span className="text-[10px] uppercase font-bold tracking-wider text-text-secondary border border-bg-line rounded px-2 py-0.5">
                {rec.strategy.replace(/_/g, " ")}
              </span>
            )}
          </div>
          {rec.headline && (
            <div className="text-[14px] font-semibold text-text-primary leading-snug">
              {rec.headline}
            </div>
          )}
          {rec.strategy_subtype && rec.strategy_subtype !== "n/a" && (
            <div className="text-[11px] text-text-muted mt-0.5">{rec.strategy_subtype}</div>
          )}
        </div>
        <div className="text-right shrink-0">
          <ConvictionStars conviction={conviction} />
          <div className="mt-1.5 text-[11px]">
            <span className={clsx("font-bold",
              confidence >= 70 ? "text-accent-green"
              : confidence >= 55 ? "text-accent-amber"
              : "text-text-muted")}>
              {confidence.toFixed(0)}%
            </span>
            <span className="text-text-muted"> confidence</span>
            {isCalibrated && (
              <span className="ml-1 text-[9px] uppercase font-bold text-accent-violet">calibrated</span>
            )}
          </div>
        </div>
      </div>

      {/* Hard blocks — when present, surface red banner above everything else */}
      {(rec.hard_blocks?.length || 0) > 0 && (
        <div className="bg-accent-red/10 border border-accent-red/30 rounded p-3 text-[12px] text-accent-red">
          <strong className="block mb-1">Hard blocks:</strong>
          <ul className="space-y-0.5">
            {rec.hard_blocks.map((b: string, i: number) => <li key={i}>· {b}</li>)}
          </ul>
        </div>
      )}

      {/* Legs — only when there's an actionable strategy */}
      {rec.legs && rec.legs.length > 0 && (
        <LegsTable legs={rec.legs} />
      )}

      {/* P&L envelope */}
      {(rec.max_profit_inr || rec.max_loss_inr) && (
        <div className="grid grid-cols-2 sm:grid-cols-4 gap-2 text-[12px]">
          <PnlCell label="Max profit"   value={rec.max_profit_inr} positive />
          <PnlCell label="Max loss"     value={rec.max_loss_inr} />
          <PnlCell label="R:R"          value={rec.risk_reward ? `${rec.risk_reward.toFixed(2)}x` : "—"} isText />
          <PnlCell label="Suggested lots" value={rec.suggested_lots || 0} asInt />
        </div>
      )}

      {/* Analytics row — PCR, Max Pain, IV regime, walls */}
      {rec.analytics && Object.keys(rec.analytics).length > 0 && (
        <AnalyticsRow analytics={rec.analytics} expiry={rec.expiry}
                       daysToExpiry={rec.days_to_expiry} ivRegime={rec.iv_regime} />
      )}

      {/* Two-column: astro overlay + technical confluence */}
      <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
        {rec.astro_overlay && (
          <AstroOverlayCard overlay={rec.astro_overlay} direction={direction} />
        )}
        {rec.technical_confluence && (
          <ConfluenceCard confluence={rec.technical_confluence} />
        )}
      </div>

      {/* Entry / exit triggers */}
      {((rec.entry_triggers?.length || 0) > 0 || (rec.exit_triggers?.length || 0) > 0) && (
        <TriggersBlock entry={rec.entry_triggers} exit={rec.exit_triggers} />
      )}

      {/* Caveats */}
      {(rec.caveats?.length || 0) > 0 && (
        <div className="border-t border-bg-line pt-3 text-[11px]">
          <div className="text-[10px] uppercase tracking-wider font-bold text-text-muted mb-1.5">
            What we don't know yet
          </div>
          <ul className="space-y-0.5 text-text-secondary leading-relaxed">
            {rec.caveats.slice(0, 5).map((c: string, i: number) => <li key={i}>· {c}</li>)}
          </ul>
        </div>
      )}

      {/* Place-trade CTA — only when the verdict is actionable AND legs exist */}
      {(rec.legs?.length || 0) > 0
       && rec.execution_payload
       && (rec.verdict === "BUY" || rec.verdict === "STRONG_BUY"
            || rec.verdict === "SELL" || rec.verdict === "STRONG_SELL") && (
        <PlaceTradeButton rec={rec} />
      )}

      {/* Disclaimer */}
      <div className="text-[10px] text-text-muted italic border-t border-bg-line pt-2">
        {rec.disclaimer || "F&O carries amplified risk. Verify every recommendation before risking capital."}
      </div>
    </div>
  );
}


// ─── Place-trade CTA ─────────────────────────────────────────────────────

function PlaceTradeButton({ rec }: { rec: any }) {
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState<{ ok: boolean; message: string; details?: any } | null>(null);

  const legCount = rec.legs?.length || 0;
  const isMultiLeg = legCount > 1;

  async function placeTrade() {
    setBusy(true);
    setResult(null);
    try {
      // Build PlaceOrderRequest for each leg.
      //
      // CRITICAL: F&O orders need the option contract (e.g. NIFTY24APR23500CE),
      // not the underlying. We pass the underlying as `symbol` + the option
      // meta (strike / type / expiry) — the backend resolves the actual
      // tradingsymbol via `instruments.resolve_option_for_order` before
      // calling the broker. Without these meta fields the order would go to
      // the index (NIFTY), not the option contract.
      const legs = rec.legs.map((leg: any) => ({
        symbol:        rec.symbol,                   // underlying — backend resolves contract
        exchange:      "NFO",                         // NSE F&O segment
        direction:     leg.action,
        quantity:      leg.lot_size * (rec.suggested_lots || 1),
        product_type:  "NRML",
        order_type:    "LIMIT",
        price:         leg.ltp,
        stoploss:      leg.action === "BUY" ? leg.ltp * 0.5 : leg.ltp * 1.5,
        target_1:      leg.action === "BUY" ? leg.ltp * 1.5 : leg.ltp * 0.5,
        source_signal_id: null,
        source_type:   "AUTO_SIGNAL",
        capital:       100_000,
        // Option-contract resolution fields — without these the broker would
        // route the order to the underlying index (NIFTY) rather than the
        // option contract. Backend's _resolve_option_contract translates
        // these to the actual tradingsymbol (NIFTY24APR23500CE) + NFO token.
        option_strike: leg.strike,
        option_type:   leg.type,                    // CE or PE
        option_expiry: rec.expiry,                   // ISO date "YYYY-MM-DD"
      }));

      const endpoint = isMultiLeg ? "/api/trade/place-multi-leg" : "/api/trade/place";
      const body = isMultiLeg
        ? { legs, strategy_name: rec.strategy }
        : legs[0];

      const res = await authedFetch(endpoint, {
        method: "POST",
        body: JSON.stringify(body),
      });
      const data = await res.json();

      if (!res.ok) {
        setResult({
          ok: false,
          message: data?.detail || data?.message || `HTTP ${res.status}`,
        });
        return;
      }

      // Multi-leg: data.ok + data.failed_at_leg + data.rolled_back_count
      // Single-leg: data.ok + data.status + data.message
      if (isMultiLeg) {
        if (data.ok) {
          setResult({
            ok: true,
            message: `${legCount} legs placed (basket ${data.group_id?.slice(0, 8)}…)`,
            details: data,
          });
        } else {
          setResult({
            ok: false,
            message: data.message || `Leg ${data.failed_at_leg} failed`,
            details: data,
          });
        }
      } else {
        if (data.ok) {
          setResult({
            ok: true,
            message: `Order placed — id ${data.order_id}, status ${data.status}`,
            details: data,
          });
        } else {
          setResult({
            ok: false,
            message: data.rejected_reason || data.message || "Order rejected",
            details: data,
          });
        }
      }
    } catch (e: any) {
      setResult({ ok: false, message: e.message || String(e) });
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="border-t border-bg-line pt-3 space-y-2">
      <button onClick={placeTrade} disabled={busy}
              className={clsx(
                "w-full flex items-center justify-center gap-2 px-4 py-2.5 rounded font-bold text-sm uppercase tracking-wider transition-colors",
                busy
                  ? "bg-text-muted/20 text-text-muted cursor-wait"
                  : "bg-accent-amber text-white hover:bg-accent-gold",
              )}>
        {busy ? (
          <><Loader2 className="w-4 h-4 animate-spin" /> Placing…</>
        ) : (
          <><Send className="w-4 h-4" />
             {isMultiLeg ? `Place all ${legCount} legs` : "Place trade"}</>
        )}
      </button>

      {/* Pre-flight hint */}
      {!result && (
        <div className="text-[10px] text-text-muted flex items-start gap-1.5">
          <Info className="w-3 h-3 shrink-0 mt-0.5" />
          <span>
            {isMultiLeg
              ? `${legCount} legs will be placed atomically. If any leg fails, the earlier legs are auto-reversed.`
              : "Order is sent live to your broker. Verify the price and quantity before confirming."}
          </span>
        </div>
      )}

      {/* Result banner */}
      {result && (
        <div className={clsx(
          "flex items-start gap-2 p-2.5 rounded text-[11px] border",
          result.ok
            ? "border-accent-green/40 bg-accent-green/5 text-accent-green"
            : "border-accent-red/40 bg-accent-red/5 text-accent-red",
        )}>
          {result.ok
            ? <CheckCircle2 className="w-4 h-4 shrink-0 mt-0.5" />
            : <AlertTriangle className="w-4 h-4 shrink-0 mt-0.5" />}
          <div className="flex-1 min-w-0">
            <div className="font-semibold">{result.ok ? "Trade placed" : "Trade rejected"}</div>
            <div className="text-text-secondary mt-0.5">{result.message}</div>
            {result.details?.rolled_back_count != null && result.details.rolled_back_count > 0 && (
              <div className="mt-0.5 text-text-muted">
                Auto-reversed {result.details.rolled_back_count} earlier leg
                {result.details.rolled_back_count === 1 ? "" : "s"} to neutralize position.
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  );
}


// ─── Sub-components ──────────────────────────────────────────────────────

function ConvictionStars({ conviction }: { conviction: string }) {
  const stars = conviction === "STRONG" ? 5 :
                conviction === "MEDIUM" ? 4 :
                conviction === "WEAK"   ? 2 : 0;
  if (stars === 0) return null;
  return (
    <div className="flex items-center justify-end gap-0.5">
      {Array.from({ length: 5 }).map((_, i) => (
        <svg key={i} className={clsx("w-3.5 h-3.5",
          i < stars ? "fill-accent-amber text-accent-amber" : "fill-none text-text-muted/30")}
              viewBox="0 0 24 24" stroke="currentColor" strokeWidth="2">
          <path d="M12 2l3.09 6.26L22 9.27l-5 4.87 1.18 6.88L12 17.77l-6.18 3.25L7 14.14 2 9.27l6.91-1.01L12 2z" />
        </svg>
      ))}
    </div>
  );
}


function LegsTable({ legs }: { legs: any[] }) {
  return (
    <div className="border border-bg-line rounded overflow-hidden">
      <div className="bg-bg-base/50 px-3 py-1.5 text-[10px] uppercase font-bold tracking-wider text-text-muted">
        Strategy legs ({legs.length})
      </div>
      <table className="w-full text-[11px]">
        <thead className="bg-bg-base/30 text-text-muted">
          <tr>
            <th className="text-left py-1.5 px-3">Action</th>
            <th className="text-left">Type</th>
            <th className="text-right">Strike</th>
            <th className="text-right">LTP</th>
            <th className="text-right">Δ</th>
            <th className="text-right hidden sm:table-cell">Θ</th>
            <th className="text-right pr-3">Premium/lot</th>
          </tr>
        </thead>
        <tbody>
          {legs.map((leg, i) => (
            <tr key={i} className="border-t border-bg-line">
              <td className={clsx("py-1.5 px-3 font-bold",
                leg.action === "BUY" ? "text-accent-green" : "text-accent-red")}>
                {leg.action}
              </td>
              <td className="font-semibold">{leg.type}</td>
              <td className="text-right tabular">{leg.strike}</td>
              <td className="text-right tabular">₹{leg.ltp?.toFixed?.(2) || "—"}</td>
              <td className="text-right tabular text-text-secondary">{leg.delta?.toFixed?.(2) || "—"}</td>
              <td className="text-right tabular text-text-secondary hidden sm:table-cell">
                {leg.theta?.toFixed?.(2) || "—"}
              </td>
              <td className="text-right tabular pr-3 font-semibold">
                ₹{leg.premium_per_lot_inr ? fmt.inr(leg.premium_per_lot_inr) : "—"}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}


function PnlCell({ label, value, positive, isText, asInt }:
                  { label: string; value: any; positive?: boolean; isText?: boolean; asInt?: boolean }) {
  if (value == null) return <div />;
  const display = isText ? String(value)
    : asInt ? String(Math.round(Number(value)))
    : `₹${fmt.inr(Math.abs(Number(value)))}`;
  return (
    <div className="bg-bg-base/40 border border-bg-line rounded px-2.5 py-1.5">
      <div className="text-[9px] uppercase tracking-wider text-text-muted font-semibold">{label}</div>
      <div className={clsx("text-sm font-bold tabular mt-0.5",
        positive ? "text-accent-green"
        : (label === "Max loss" ? "text-accent-red" : "text-text-primary"))}>
        {display}
      </div>
    </div>
  );
}


function AnalyticsRow({ analytics, expiry, daysToExpiry, ivRegime }:
                       { analytics: any; expiry?: string; daysToExpiry?: number; ivRegime?: string }) {
  const items: { label: string; value: string; color?: string }[] = [];
  if (analytics.pcr != null) {
    const pcr = Number(analytics.pcr);
    items.push({
      label: "PCR",
      value: pcr.toFixed(2),
      color: pcr > 1.3 ? "text-accent-green" : pcr < 0.7 ? "text-accent-red" : "text-text-secondary",
    });
  }
  if (analytics.max_pain) {
    items.push({ label: "Max pain", value: String(analytics.max_pain) });
  }
  if (analytics.iv_atm_pct != null) {
    items.push({
      label: "ATM IV",
      value: `${Number(analytics.iv_atm_pct).toFixed(1)}%${ivRegime ? ` (${ivRegime})` : ""}`,
    });
  }
  if (analytics.support_wall) {
    items.push({ label: "Put wall", value: String(analytics.support_wall), color: "text-accent-green" });
  }
  if (analytics.resistance_wall) {
    items.push({ label: "Call wall", value: String(analytics.resistance_wall), color: "text-accent-red" });
  }
  if (expiry) {
    items.push({
      label: "Expiry",
      value: `${expiry}${daysToExpiry ? ` (${daysToExpiry}d)` : ""}`,
    });
  }
  if (items.length === 0) return null;

  return (
    <div className="flex flex-wrap gap-2 text-[11px]">
      {items.map((it) => (
        <div key={it.label}
              className="bg-bg-base/40 border border-bg-line rounded px-2.5 py-1 flex items-baseline gap-1.5">
          <span className="text-text-muted uppercase text-[9px] font-bold tracking-wider">
            {it.label}
          </span>
          <span className={clsx("font-bold tabular", it.color || "text-text-primary")}>
            {it.value}
          </span>
        </div>
      ))}
    </div>
  );
}


function AstroOverlayCard({ overlay, direction }: { overlay: any; direction: string }) {
  const aligned = overlay?.aligned;
  const Icon = aligned ? CheckCircle2 : XCircle;
  const color = aligned ? "text-accent-green" : "text-accent-amber";
  return (
    <div className="border border-bg-line rounded p-3">
      <div className="flex items-center gap-1.5 mb-2">
        <Sparkles className="w-3.5 h-3.5 text-accent-amber" />
        <div className="text-[10px] uppercase font-bold tracking-wider text-text-muted">
          Astrology overlay
        </div>
      </div>
      <div className="flex items-center gap-2 mb-1">
        <Icon className={clsx("w-4 h-4", color)} />
        <span className={clsx("text-[12px] font-bold", color)}>
          {aligned ? "Aligned" : "Not aligned"} with {direction.toLowerCase()} trade
        </span>
      </div>
      {overlay.headline && (
        <div className="text-[11px] text-text-secondary leading-snug">{overlay.headline}</div>
      )}
      {overlay.symbol_nakshatra?.name && (
        <div className="text-[10px] text-text-muted mt-1">
          Nakshatra: <span className="font-semibold text-text-secondary">
            {overlay.symbol_nakshatra.name}
          </span>
          {overlay.symbol_nakshatra.ruler && (
            <> · ruler: <span className="font-semibold text-text-secondary">
              {overlay.symbol_nakshatra.ruler}</span></>
          )}
        </div>
      )}
    </div>
  );
}


function ConfluenceCard({ confluence }: { confluence: any }) {
  const { confirming_count = 0, dissenting_count = 0, total_engines = 0, confirming = [] } = confluence || {};
  const ratio = total_engines > 0 ? confirming_count / total_engines : 0;
  const color = ratio >= 0.7 ? "text-accent-green"
              : ratio >= 0.4 ? "text-accent-amber"
              : "text-accent-red";
  return (
    <div className="border border-bg-line rounded p-3">
      <div className="flex items-center gap-1.5 mb-2">
        <Activity className="w-3.5 h-3.5 text-accent-amber" />
        <div className="text-[10px] uppercase font-bold tracking-wider text-text-muted">
          Technical confluence
        </div>
      </div>
      <div className={clsx("text-[14px] font-bold mb-1", color)}>
        {confirming_count}/{total_engines} engines confirm
        {dissenting_count > 0 && (
          <span className="text-text-muted font-normal text-[11px] ml-1">
            ({dissenting_count} dissent)
          </span>
        )}
      </div>
      {confirming.length > 0 && (
        <div className="flex flex-wrap gap-1 mt-1">
          {confirming.map((name: string) => (
            <span key={name}
                   className="text-[9px] uppercase font-bold text-accent-green bg-accent-green/10 border border-accent-green/30 rounded px-1.5 py-0.5">
              {name}
            </span>
          ))}
        </div>
      )}
    </div>
  );
}


function TriggersBlock({ entry = [], exit = [] }: { entry?: string[]; exit?: string[] }) {
  return (
    <div className="grid grid-cols-1 md:grid-cols-2 gap-3 text-[11px]">
      {entry.length > 0 && (
        <div className="border border-bg-line rounded p-3">
          <div className="text-[10px] uppercase font-bold tracking-wider text-accent-green mb-1.5">
            Entry triggers
          </div>
          <ul className="space-y-1 text-text-secondary leading-relaxed">
            {entry.map((t, i) => <li key={i}>· {t}</li>)}
          </ul>
        </div>
      )}
      {exit.length > 0 && (
        <div className="border border-bg-line rounded p-3">
          <div className="text-[10px] uppercase font-bold tracking-wider text-accent-red mb-1.5">
            Exit triggers
          </div>
          <ul className="space-y-1 text-text-secondary leading-relaxed">
            {exit.map((t, i) => <li key={i}>· {t}</li>)}
          </ul>
        </div>
      )}
    </div>
  );
}
