"use client";

import { useState } from "react";
import { authedFetch, ApiError } from "@/lib/auth";
import { fmt } from "@/lib/format";
import { X, AlertTriangle, ShieldCheck, Ban } from "lucide-react";

/**
 * Order draft schema. Aligned with /api/trade/place.
 *
 * Every order placed through this modal is LIVE (real money). There is no
 * paper mode anywhere in the platform — if trading is disabled at the
 * account level the backend refuses the order outright with TRADING_DISABLED.
 */
export interface OrderDraft {
  symbol: string;
  exchange: string;
  direction: "BUY" | "SELL";
  order_type: "MARKET" | "LIMIT" | "SL" | "SL-M";
  product_type: "INTRADAY" | "DELIVERY" | "MARGIN" | "MIS" | "CNC" | "NRML";
  quantity: number;
  price?: number;
  trigger_price?: number;
  // Companion levels — pulled from the recommendation when launched from there
  stoploss?: number;
  target_1?: number;
  target_2?: number;
  target_3?: number;
  // Tracking
  source_signal_id?: number;
  source_type?: "MANUAL" | "AUTO_SIGNAL";
  capital?: number;
}

export function OrderConfirmModal({
  draft, onClose, onPlaced,
}: { draft: OrderDraft | null; onClose: () => void; onPlaced?: (res: any) => void }) {
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");
  const [riskGuardResult, setRiskGuardResult] = useState<any>(null);
  const [acknowledged, setAcknowledged] = useState(false);

  if (!draft) return null;

  const notional = draft.quantity * (draft.price || 0);

  // Risk-reward sanity check before submission. Doesn't replace the
  // backend risk_guard (which runs again at execution moment), but
  // gives instant feedback in the modal.
  const slDistance = draft.stoploss && draft.price
    ? Math.abs(draft.price - draft.stoploss)
    : 0;
  const t1Distance = draft.target_1 && draft.price
    ? Math.abs(draft.target_1 - draft.price)
    : 0;
  const rr = slDistance > 0 ? (t1Distance / slDistance).toFixed(2) : "—";

  async function place() {
    if (!acknowledged || !draft) return;
    setBusy(true); setErr(""); setRiskGuardResult(null);

    try {
      // Posts to the new /api/trade/place — fully auth-gated, idempotent,
      // and pre-trade risk-guarded. Falls through to a useful error message
      // if the backend's risk_guard rejects the trade.
      const res = await authedFetch("/api/trade/place", {
        method: "POST",
        body: JSON.stringify({
          symbol:        draft.symbol,
          exchange:      draft.exchange,
          direction:     draft.direction,
          quantity:      draft.quantity,
          product_type:  draft.product_type,
          order_type:    draft.order_type,
          price:         draft.price,
          trigger_price: draft.trigger_price,
          stoploss:      draft.stoploss,
          target_1:      draft.target_1,
          target_2:      draft.target_2,
          target_3:      draft.target_3,
          source_signal_id: draft.source_signal_id,
          source_type:   draft.source_type || "MANUAL",
          capital:       draft.capital || 100000,
        }),
      });
      const data = await res.json();

      if (!res.ok || !data.ok) {
        // Risk-guard block produces ok:false + risk_guard payload — surface it
        setRiskGuardResult(data.risk_guard || null);
        setErr(data.message || data.rejected_reason || `HTTP ${res.status}`);
        return;
      }

      onPlaced?.(data);
      onClose();
    } catch (e: any) {
      if (e instanceof ApiError && e.body?.risk_guard) {
        setRiskGuardResult(e.body.risk_guard);
      }
      setErr(e.message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="fixed inset-0 bg-black/70 z-50 flex items-center justify-center p-4">
      <div className="bg-bg-panel border border-bg-line rounded max-w-md w-full">
        <div className="flex items-center justify-between px-4 py-3 border-b border-bg-line">
          <div className="flex items-center gap-2 text-accent-amber">
            <AlertTriangle className="w-4 h-4" />
            <span className="font-semibold">Confirm Order</span>
          </div>
          <button onClick={onClose} className="text-text-muted hover:text-text-primary">
            <X className="w-4 h-4" />
          </button>
        </div>

        <div className="px-4 py-3 space-y-3 text-sm">
          <div className={`text-center py-2 rounded ${draft.direction === "BUY"
            ? "bg-accent-green/15 text-accent-green" : "bg-accent-red/15 text-accent-red"}`}>
            <div className="text-2xl font-bold tracking-wider">{draft.direction}</div>
            <div className="text-lg">{draft.symbol}</div>
            <div className="text-xs text-text-muted">{draft.exchange} · {draft.product_type}</div>
          </div>

          <div className="grid grid-cols-2 gap-3 text-[12px] tabular">
            <Row label="Order type" value={draft.order_type} />
            <Row label="Quantity" value={String(draft.quantity)} />
            <Row label="Price" value={draft.price ? `₹${fmt.inr(draft.price)}` : "MARKET"} />
            {draft.trigger_price ? <Row label="Trigger" value={`₹${fmt.inr(draft.trigger_price)}`} /> : null}
            <Row label="Notional" value={`₹${fmt.inr(notional)}`} highlight />
            <Row label="Mode" value="LIVE"
                  highlight highlightColor="text-accent-red" />
          </div>

          {(draft.stoploss || draft.target_1) && (
            <div className="grid grid-cols-2 gap-3 text-[12px] tabular pt-2 border-t border-bg-line">
              {draft.stoploss && <Row label="Stop loss" value={`₹${fmt.inr(draft.stoploss)}`}
                                       highlight highlightColor="text-accent-red" />}
              {draft.target_1 && <Row label="Target 1" value={`₹${fmt.inr(draft.target_1)}`}
                                        highlight highlightColor="text-accent-green" />}
              {draft.target_2 && <Row label="Target 2" value={`₹${fmt.inr(draft.target_2)}`} />}
              {draft.target_3 && <Row label="Target 3" value={`₹${fmt.inr(draft.target_3)}`} />}
              {slDistance > 0 && (
                <Row label="R:R ratio" value={`${rr}:1`}
                       highlight={Number(rr) < 1.5}
                       highlightColor={Number(rr) >= 1.5 ? "text-accent-green" : "text-accent-amber"} />
              )}
            </div>
          )}

          <div className="text-[11px] text-accent-red border border-accent-red/40 rounded p-2 bg-accent-red/5">
            ⚠ This is a <span className="font-bold">LIVE</span> order using real capital.
            Trade will be placed with Angel One immediately and cannot be undone.
          </div>

          {/* Risk-guard rejection panel — shown when backend refused the trade */}
          {riskGuardResult && riskGuardResult.verdict === "BLOCK" && (
            <div className="border border-accent-red/40 bg-accent-red/5 rounded p-3 text-[11px]">
              <div className="flex items-center gap-1 font-bold text-accent-red uppercase mb-1">
                <Ban className="w-3.5 h-3.5" /> Risk Guard blocked this trade
              </div>
              <ul className="space-y-0.5 text-text-secondary">
                {(riskGuardResult.reasons || []).map((r: string, i: number) => (
                  <li key={i}>• {r}</li>
                ))}
              </ul>
            </div>
          )}

          <label className="flex items-start gap-2 text-[11px] text-text-secondary cursor-pointer">
            <input type="checkbox" checked={acknowledged}
              onChange={(e) => setAcknowledged(e.target.checked)} className="mt-0.5" />
            <span>
              I've reviewed the order details, my risk dashboard shows headroom for this trade,
              and I accept full responsibility for the outcome.
            </span>
          </label>

          {err && !riskGuardResult && (
            <div className="text-accent-red text-[11px]">{err}</div>
          )}
        </div>

        <div className="px-4 py-3 border-t border-bg-line flex gap-2 justify-end">
          <button onClick={onClose}
            className="px-3 py-1.5 text-[12px] text-text-secondary border border-bg-line rounded hover:bg-bg-line">
            Cancel
          </button>
          <button onClick={place} disabled={!acknowledged || busy}
            className="px-4 py-1.5 text-[12px] font-semibold rounded bg-accent-amber text-black disabled:opacity-40 disabled:cursor-not-allowed">
            {busy ? "Placing…" : `Confirm ${draft.direction}`}
          </button>
        </div>
      </div>
    </div>
  );
}

function Row({ label, value, highlight, highlightColor }:
              { label: string; value: string; highlight?: boolean; highlightColor?: string }) {
  return (
    <div>
      <div className="text-[10px] uppercase text-text-muted">{label}</div>
      <div className={highlight
        ? (highlightColor || "text-accent-amber font-semibold")
        : "text-text-primary"}>{value}</div>
    </div>
  );
}
