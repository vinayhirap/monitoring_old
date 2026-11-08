"use client";

/**
 * Positions page — currently-open positions with live unrealized P&L.
 *
 * Refreshes every 5 seconds so users see ticking P&L. Default tab shows
 * paper positions (safer default); toggle to switch to live.
 */

import { useState } from "react";
import useSWR, { mutate } from "swr";
import Link from "next/link";
import { authedFetcher as fetcher, authedFetch } from "@/lib/auth";
import { fmt } from "@/lib/format";
import {
  TrendingUp, TrendingDown, RefreshCw, Wallet, X, Target, Shield,
} from "lucide-react";
import clsx from "clsx";


export default function PortalPositionsPage() {
  const url = `/api/trade/positions`;
  const { data, isLoading } = useSWR<any>(url, fetcher,
    { refreshInterval: 5_000, shouldRetryOnError: false });

  // Trading status — drives the ON/OFF banner at the top.
  const { data: tradingStatus, mutate: mutateStatus } = useSWR<any>(
    "/api/trade/status", fetcher, { refreshInterval: 30_000 });

  const summaryUrl = `/api/trade/summary?days=30`;
  const { data: summary } = useSWR<any>(summaryUrl, fetcher,
    { refreshInterval: 30_000 });

  async function toggleTrading() {
    const next = !tradingStatus?.trading_enabled;
    const verb = next ? "ENABLE" : "DISABLE";
    if (!confirm(`${verb} trading? When ON, orders go to Angel One with real money.`)) return;
    try {
      await authedFetch("/api/trade/toggle", {
        method: "POST", body: JSON.stringify({ enabled: next }),
      });
      mutateStatus();
    } catch (e: any) {
      alert(`Toggle failed: ${e.message}`);
    }
  }

  async function closePosition(symbol: string, qty: number, direction: string) {
    if (!tradingStatus?.trading_enabled) {
      alert("Trading is OFF. Enable it first before placing close orders.");
      return;
    }
    if (!confirm(`Close ${Math.abs(qty)} ${symbol} ${direction}? This places a reversing LIVE order.`)) return;
    try {
      await authedFetch("/api/trade/place", {
        method: "POST",
        body: JSON.stringify({
          symbol,
          exchange: "NSE",
          direction: direction === "LONG" ? "SELL" : "BUY",
          quantity: Math.abs(qty),
          product_type: "DELIVERY",
          order_type: "MARKET",
        }),
      });
      mutate(url);
    } catch (e: any) {
      alert(`Close failed: ${e.message}`);
    }
  }

  return (
    <div className="space-y-4">
      {/* Header */}
      <div className="bg-bg-surface border border-bg-line rounded-lg p-4">
        <div className="flex items-center justify-between flex-wrap gap-3">
          <div>
            <h1 className="text-xl font-bold text-text-primary flex items-center gap-2">
              <Wallet className="w-5 h-5 text-accent-amber" />
              Positions
            </h1>
            <p className="text-[11px] text-text-muted mt-1">
              Open positions with live mark-to-market P&L. Refreshes every 5 seconds.
            </p>
          </div>
          <button onClick={() => mutate(url)} disabled={isLoading}
            className="text-[11px] flex items-center gap-1 text-accent-amber hover:text-accent-gold disabled:opacity-50">
            <RefreshCw className={clsx("w-3 h-3", isLoading && "animate-spin")} />
            refresh
          </button>
        </div>
      </div>

      {/* Trading ON/OFF kill-switch banner — visible across all trading pages */}
      <TradingStatusBanner status={tradingStatus} onToggle={toggleTrading} />

      {/* Summary cards */}
      {data && (
        <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
          <SummaryCard label="Open positions" value={String(data.count || 0)} />
          <SummaryCard label="Unrealized P&L"
            value={`₹${fmt.inr(data.total_unrealized_pnl || 0)}`}
            color={(data.total_unrealized_pnl || 0) >= 0 ? "text-accent-green" : "text-accent-red"} />
          {summary && (
            <>
              <SummaryCard label="Realized (30d)"
                value={`₹${fmt.inr(summary.total_realized_pnl || 0)}`}
                color={(summary.total_realized_pnl || 0) >= 0 ? "text-accent-green" : "text-accent-red"} />
              <SummaryCard label="Win rate (30d)"
                value={summary.winning_closes + summary.losing_closes > 0
                  ? `${Math.round((summary.win_rate || 0) * 100)}%`
                  : "—"}
                sub={`${summary.winning_closes}W / ${summary.losing_closes}L`} />
            </>
          )}
        </div>
      )}

      {/* Positions table */}
      {isLoading && !data && (
        <div className="text-text-muted text-center py-12">Loading positions…</div>
      )}

      {data && data.positions?.length === 0 && (
        <div className="bg-bg-surface border border-bg-line rounded p-8 text-center">
          <Wallet className="w-10 h-10 text-text-muted mx-auto mb-2" />
          <p className="text-text-muted text-sm">
            No open positions.
            <Link href="/portal/recommendations" className="text-accent-amber hover:underline ml-1">
              Browse recommendations →
            </Link>
          </p>
        </div>
      )}

      {data && data.positions?.length > 0 && (
        <div className="broker-table-wrap">
          <table className="broker-table">
            <thead>
              <tr>
                <th>Symbol</th>
                <th>Side</th>
                <th className="num">Qty</th>
                <th className="num">Avg entry</th>
                <th className="num">LTP</th>
                <th className="num">P&L (₹)</th>
                <th className="num">P&L (%)</th>
                <th className="num">SL</th>
                <th className="num">T1</th>
                <th className="num">Action</th>
              </tr>
            </thead>
            <tbody>
              {data.positions.map((p: any) => (
                <tr key={p.id}>
                  <td>
                    <Link href={`/portal/symbol/${p.symbol}`}
                          className="font-bold text-text-primary hover:text-accent-amber">
                      {p.symbol}
                    </Link>
                    <div className="text-[9px] text-text-muted">{p.product_type}</div>
                  </td>
                  <td>
                    <span className={clsx("broker-pill",
                      p.direction === "LONG" ? "bull" : "bear")}>
                      {p.direction}
                    </span>
                  </td>
                  <td className="num">{Math.abs(p.net_quantity)}</td>
                  <td className="num">₹{fmt.inr(p.avg_entry_price)}</td>
                  <td className="num">{p.ltp ? `₹${fmt.inr(p.ltp)}` : "—"}</td>
                  <td className={clsx("num font-bold",
                    (p.unrealized_pnl || 0) >= 0 ? "text-accent-green" : "text-accent-red")}>
                    {(p.unrealized_pnl || 0) >= 0 ? "+" : ""}₹{fmt.inr(p.unrealized_pnl)}
                  </td>
                  <td className={clsx("num",
                    (p.unrealized_pnl_pct || 0) >= 0 ? "text-accent-green" : "text-accent-red")}>
                    {(p.unrealized_pnl_pct || 0) > 0 ? "+" : ""}{(p.unrealized_pnl_pct || 0).toFixed(2)}%
                  </td>
                  <td className="num text-accent-red">
                    {p.current_sl ? `₹${fmt.inr(p.current_sl)}` : "—"}
                  </td>
                  <td className="num text-accent-green">
                    {p.current_t1 ? `₹${fmt.inr(p.current_t1)}` : "—"}
                  </td>
                  <td className="num">
                    <button onClick={(e) => { e.stopPropagation(); closePosition(p.symbol, p.net_quantity, p.direction); }}
                      className="text-[10px] text-accent-red hover:underline font-semibold">
                      Close
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}


function SummaryCard({ label, value, sub, color }:
                      { label: string; value: string; sub?: string; color?: string }) {
  return (
    <div className="bg-bg-surface border border-bg-line rounded-lg p-3">
      <div className="text-[9px] uppercase text-text-muted tracking-wider font-semibold">
        {label}
      </div>
      <div className={clsx("text-xl font-bold tabular mt-1", color || "text-text-primary")}>
        {value}
      </div>
      {sub && <div className="text-[10px] text-text-muted">{sub}</div>}
    </div>
  );
}


/**
 * TradingStatusBanner — the single ON/OFF kill-switch surface.
 *
 * Renders prominently above positions/orders so users always know whether
 * orders will actually go through. Clicking the toggle hits
 * /api/trade/toggle and flips trading_enabled on the user record.
 *
 * When trading is OFF, the entire backend executor refuses orders with
 * TRADING_DISABLED. When ON, orders are LIVE — there is no paper mode.
 */
function TradingStatusBanner({ status, onToggle }:
                              { status: any; onToggle: () => void }) {
  if (!status) return null;
  const isOn = status.trading_enabled;
  const brokerOk = status.broker_authenticated;
  const canTrade = status.can_place_orders;

  return (
    <div className={clsx(
      "border-2 rounded-lg p-3 flex items-center justify-between flex-wrap gap-3",
      isOn
        ? "border-accent-green/50 bg-accent-green/5"
        : "border-accent-amber/50 bg-accent-amber/5"
    )}>
      <div className="flex items-center gap-3">
        <div className={clsx(
          "w-12 h-12 rounded-full flex items-center justify-center text-xl font-black",
          isOn ? "bg-accent-green/20 text-accent-green"
               : "bg-accent-amber/20 text-accent-amber"
        )}>
          {isOn ? "ON" : "OFF"}
        </div>
        <div>
          <div className="text-sm font-bold text-text-primary">
            Trading is {isOn ? "ON" : "OFF"}
          </div>
          <div className="text-[11px] text-text-secondary">
            {isOn
              ? "Live orders will be placed with Angel One immediately."
              : "All order placement is blocked at the server. Toggle ON to enable live trading."}
          </div>
          {isOn && !brokerOk && (
            <div className="text-[10px] text-accent-red mt-0.5">
              ⚠ Broker not authenticated — orders will be refused until you connect Angel One.
            </div>
          )}
        </div>
      </div>
      <button onClick={onToggle}
        className={clsx(
          "px-4 py-2 rounded font-bold text-[12px] uppercase tracking-wider",
          isOn
            ? "bg-accent-red text-white hover:bg-accent-red/90"
            : "bg-accent-green text-white hover:bg-accent-green/90"
        )}>
        Turn {isOn ? "OFF" : "ON"}
      </button>
    </div>
  );
}
