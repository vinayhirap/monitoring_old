"use client";

/**
 * Orders page — recent order history. Mostly read-only; users can cancel
 * OPEN/PARTIAL orders from here.
 */

import { useState } from "react";
import useSWR, { mutate } from "swr";
import Link from "next/link";
import { authedFetcher as fetcher, authedFetch } from "@/lib/auth";
import { fmt } from "@/lib/format";
import { Clock, RefreshCw } from "lucide-react";
import clsx from "clsx";


type StatusFilter = "" | "PENDING_RISK_CHECK" | "PENDING_BROKER" | "OPEN" | "FILLED" | "CANCELLED" | "REJECTED" | "FAILED";

const STATUS_LABELS: Record<string, string> = {
  PENDING_RISK_CHECK: "Risk check",
  PENDING_BROKER:     "Pending",
  OPEN:               "Open",
  PARTIAL:            "Partial",
  FILLED:             "Filled",
  CANCELLED:          "Cancelled",
  REJECTED:           "Rejected",
  FAILED:             "Failed",
};


export default function PortalOrdersPage() {
  const [status, setStatus] = useState<StatusFilter>("");
  const [days, setDays] = useState(7);

  const url = `/api/trade/orders?days=${days}` +
              (status ? `&status=${status}` : "");
  const { data, isLoading } = useSWR<any>(url, fetcher,
    { refreshInterval: 10_000, shouldRetryOnError: false });

  async function cancelOrder(orderId: number) {
    if (!confirm("Cancel this order?")) return;
    try {
      await authedFetch(`/api/trade/orders/${orderId}`, { method: "DELETE" });
      mutate(url);
    } catch (e: any) {
      alert(`Cancel failed: ${e.message}`);
    }
  }

  return (
    <div className="space-y-4">
      <div className="bg-bg-surface border border-bg-line rounded-lg p-4">
        <div className="flex items-center justify-between flex-wrap gap-3">
          <div>
            <h1 className="text-xl font-bold text-text-primary flex items-center gap-2">
              <Clock className="w-5 h-5 text-accent-amber" />
              Order History
            </h1>
            <p className="text-[11px] text-text-muted mt-1">
              Every order you've placed in the last {days} days. Pending orders auto-refresh every 10s.
            </p>
          </div>
          <button onClick={() => mutate(url)} disabled={isLoading}
            className="text-[11px] flex items-center gap-1 text-accent-amber hover:text-accent-gold disabled:opacity-50">
            <RefreshCw className={clsx("w-3 h-3", isLoading && "animate-spin")} />
            refresh
          </button>
        </div>

        {/* Filters */}
        <div className="flex flex-wrap items-center gap-3 mt-4">
          <div className="flex bg-bg-base rounded p-0.5">
            {[1, 7, 30, 90].map((d) => (
              <button key={d} onClick={() => setDays(d)}
                className={clsx("text-[11px] px-3 py-1 rounded font-semibold",
                  days === d ? "bg-accent-amber text-white" : "text-text-secondary")}>
                {d}d
              </button>
            ))}
          </div>
          <select value={status} onChange={(e) => setStatus(e.target.value as StatusFilter)}
            className="bg-bg-base border border-bg-line text-[11px] rounded px-2 py-1">
            <option value="">All statuses</option>
            {Object.entries(STATUS_LABELS).map(([k, v]) => (
              <option key={k} value={k}>{v}</option>
            ))}
          </select>
          <span className="text-[10px] text-text-muted ml-auto">
            {data?.count != null ? `${data.count} orders` : ""}
          </span>
        </div>
      </div>

      {isLoading && !data && (
        <div className="text-text-muted text-center py-12">Loading orders…</div>
      )}

      {data?.orders?.length === 0 && !isLoading && (
        <div className="bg-bg-surface border border-bg-line rounded p-8 text-center">
          <Clock className="w-10 h-10 text-text-muted mx-auto mb-2" />
          <p className="text-text-muted text-sm">No orders in this window.</p>
        </div>
      )}

      {data?.orders?.length > 0 && (
        <div className="broker-table-wrap">
          <table className="broker-table">
            <thead>
              <tr>
                <th>Placed</th>
                <th>Symbol</th>
                <th>Side</th>
                <th className="num">Qty</th>
                <th className="num">Price</th>
                <th className="num">Filled @</th>
                <th>Status</th>
                <th className="num">Action</th>
              </tr>
            </thead>
            <tbody>
              {data.orders.map((o: any) => (
                <tr key={o.id}>
                  <td className="text-text-muted text-[10px]">
                    {o.placed_at ? new Date(o.placed_at).toLocaleString("en-IN", {
                      hour: "2-digit", minute: "2-digit",
                      day: "2-digit", month: "short",
                    }) : "—"}
                  </td>
                  <td>
                    <Link href={`/portal/symbol/${o.symbol}`}
                          className="font-bold text-text-primary hover:text-accent-amber">
                      {o.symbol}
                    </Link>
                    <div className="text-[9px] text-text-muted">{o.product_type} · {o.order_type}</div>
                  </td>
                  <td>
                    <span className={clsx("broker-pill",
                      o.direction === "BUY" ? "bull" : "bear")}>
                      {o.direction}
                    </span>
                  </td>
                  <td className="num">
                    {o.filled_quantity || 0}/{o.quantity}
                  </td>
                  <td className="num">
                    {o.price ? `₹${fmt.inr(o.price)}` : <span className="text-text-muted">MKT</span>}
                  </td>
                  <td className="num">
                    {o.avg_fill_price ? `₹${fmt.inr(o.avg_fill_price)}` : "—"}
                  </td>
                  <td>
                    <span className={clsx("broker-pill",
                      o.status === "FILLED"   ? "bull" :
                      o.status === "OPEN" || o.status === "PARTIAL" ? "gold" :
                      o.status === "REJECTED" || o.status === "FAILED" ? "bear" :
                      "neut")}>
                      {STATUS_LABELS[o.status] || o.status}
                    </span>
                  </td>
                  <td className="num">
                    {(o.status === "OPEN" || o.status === "PARTIAL") && (
                      <button onClick={() => cancelOrder(o.id)}
                        className="text-[10px] text-accent-red hover:underline font-semibold">
                        Cancel
                      </button>
                    )}
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
