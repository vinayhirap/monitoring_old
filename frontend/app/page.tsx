"use client";

import { useRouter } from "next/navigation";
import useSWR from "swr";
import { fetcher } from "@/lib/api";
import { Panel, Stat } from "@/components/Panel";
import { SymbolSearch } from "@/components/SymbolSearch";
import { Watchlist } from "@/components/Watchlist";
import { fmt } from "@/lib/format";
import { AnimatedNumber } from "@/components/animated";
import {
  ShieldCheck, TrendingUp, TrendingDown, ArrowRight, Target,
} from "lucide-react";
import clsx from "clsx";

const POPULAR = ["NIFTY", "BANKNIFTY", "RELIANCE", "TCS", "ICICIBANK", "HDFCBANK", "INFY", "SBIN"];

export default function Dashboard() {
  const router = useRouter();
  const { data: indices } = useSWR<any>("/api/market/indices", fetcher, { refreshInterval: 5_000 });
  const { data: hora } = useSWR<any>("/api/hora/current", fetcher, { refreshInterval: 60_000 });
  const { data: lunar } = useSWR<any>("/api/moon/reading", fetcher, { refreshInterval: 300_000 });
  const { data: sentiment } = useSWR<any>("/api/astrology/market-sentiment", fetcher, { refreshInterval: 120_000 });
  const { data: signals } = useSWR<any>("/api/signals/live", fetcher, { refreshInterval: 120_000 });

  const topPicks = (signals?.signals || [])
    .filter((x: any) => !x.error && x.signal !== "NEUTRAL")
    .sort((a: any, b: any) => b.confidence - a.confidence)
    .slice(0, 5);

  return (
    <div className="space-y-4">
      {/* ─────── Hero row: search + market pulse ─────── */}
      <div className="grid grid-cols-12 gap-4">
        <div className="col-span-12 lg:col-span-7">
          <div className="bg-card border border-bg-line rounded-md p-5 shadow-card">
            <div className="text-[10px] uppercase text-text-muted tracking-wider mb-2 font-semibold">
              Multi-Analyzer Stock Terminal
            </div>
            <SymbolSearch autoFocus />
            <div className="flex flex-wrap gap-1.5 mt-3">
              {POPULAR.map((s) => (
                <button key={s} onClick={() => router.push(`/symbol/${s}`)}
                  className="text-[10px] px-2 py-1 rounded border border-bg-line
                              text-text-secondary hover:border-accent-amber hover:text-accent-amber
                              hover:bg-accent-amber/5 transition-colors font-mono">
                  {s}
                </button>
              ))}
            </div>
            <div className="text-[10px] text-text-muted mt-3">
              Search any NSE symbol or click a chip — opens unified detail view with chart,
              all 7 analyzers, recommendation, weekly outlook, and conflict check.
            </div>
          </div>
        </div>

        <div className="col-span-12 lg:col-span-5">
          <MarketPulse hora={hora} lunar={lunar} sentiment={sentiment} />
        </div>
      </div>

      {/* Indices snapshot tiles */}
      {indices?.indices && (
        <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
          {indices.indices.filter((ix: any) => !ix.error).slice(0, 4).map((ix: any) => (
            <IndexTile key={ix.symbol} ix={ix}
              onClick={() => router.push(`/symbol/${ix.symbol}`)} />
          ))}
        </div>
      )}

      {/* ─────── Main 2-column: watchlist + top picks ─────── */}
      <div className="grid grid-cols-12 gap-4">
        <div className="col-span-12 lg:col-span-5">
          <Watchlist />
        </div>

        <div className="col-span-12 lg:col-span-7">
          <Panel title="Today's Top Picks"
            right={
              <a href="/recommendations" className="text-[11px] text-accent-amber underline">
                see all →
              </a>
            }>
            {topPicks.length === 0 && (
              <div className="text-text-muted text-[11px] py-3">
                No high-confidence picks yet — visit{" "}
                <a href="/recommendations" className="text-accent-amber underline">Recommendations</a>{" "}
                to run a full scan.
              </div>
            )}
            <div className="divide-y divide-bg-line/40">
              {topPicks.map((p: any) => (
                <TopPickRow key={p.symbol} pick={p}
                  onClick={() => router.push(`/symbol/${p.symbol}`)} />
              ))}
            </div>
          </Panel>
        </div>
      </div>

      <div className="text-[10px] text-text-muted text-center pt-2 pb-4">
        Educational and analytical use only. Cyclical layers are confluence enhancements, not standalone trade rationale.
        See <a href="/methodology" className="text-accent-amber underline">methodology</a> for details.
      </div>
    </div>
  );
}

// ─────────────────────────────────────────────────────────────────────────────

function MarketPulse({ hora, lunar, sentiment }: any) {
  const lunarOk = lunar?.gate === "PROCEED";
  const horaBias = hora?.bias || "neutral";
  const sentimentBias = sentiment?.bias || "NEUTRAL";
  const greens = [lunarOk, horaBias !== "bearish", sentimentBias !== "BEARISH"].filter(Boolean).length;
  const overall = greens === 3 ? "GREEN" : greens >= 2 ? "AMBER" : "RED";
  const overallColor = overall === "GREEN" ? "text-accent-green border-accent-green/50 bg-accent-green/5"
                       : overall === "AMBER" ? "text-accent-amber border-accent-amber/50 bg-accent-amber/5"
                       : "text-accent-red border-accent-red/50 bg-accent-red/5";
  return (
    <div className={clsx("border rounded-md p-4 h-full shadow-card", overallColor)}>
      <div className="flex items-center gap-2 mb-3">
        <ShieldCheck className="w-4 h-4" />
        <span className="text-[10px] uppercase tracking-wider text-text-muted font-semibold">Market Pulse</span>
        <span className="ml-auto font-bold text-[13px]">{overall} · {greens}/3 gates open</span>
      </div>
      <div className="grid grid-cols-3 gap-2">
        <Pulse label="Lunar" big={lunar?.gate || "—"} sub={lunar?.phase_name}
          ok={lunarOk} critical={lunar?.gate === "AVOID"} />
        <Pulse label="Hora" big={hora?.ruler || "—"}
          sub={hora?.bias} ok={horaBias === "bullish"}
          critical={horaBias === "bearish" && hora?.weight >= 0.85} />
        <Pulse label="Climate" big={sentimentBias}
          sub={sentiment?.score ? `score ${fmt.num(sentiment.score, 0)}` : ""}
          ok={sentimentBias === "BULLISH"} critical={sentimentBias === "BEARISH"} />
      </div>
    </div>
  );
}

function Pulse({ label, big, sub, ok, critical }:
                { label: string; big: string; sub?: string; ok: boolean; critical?: boolean }) {
  const color = critical ? "text-accent-red"
                : ok ? "text-accent-green"
                : "text-accent-amber";
  return (
    <div className="border border-bg-line bg-bg-panel rounded p-2">
      <div className="text-[9px] uppercase text-text-muted tracking-wider">{label}</div>
      <div className={`text-base font-bold ${color}`}>{big}</div>
      {sub && <div className="text-[9px] text-text-muted truncate">{sub}</div>}
    </div>
  );
}

function IndexTile({ ix, onClick }: { ix: any; onClick: () => void }) {
  const up = (ix.change ?? 0) >= 0;
  return (
    <button onClick={onClick}
      className="bg-card border border-bg-line rounded-md p-3 text-left
                  hover:border-accent-amber hover:shadow-cardHover transition-all group">
      <div className="flex items-center justify-between">
        <span className="text-[10px] uppercase text-text-muted tracking-wider font-semibold">{ix.display}</span>
        {ix.is_live === true
          ? <span className="text-[9px] text-accent-green uppercase font-bold">● live</span>
          : <span className="text-[9px] text-accent-amber uppercase">paper</span>}
      </div>
      <AnimatedNumber value={ix.price || 0} decimals={2}
        className="text-xl font-bold text-text-primary tabular block mt-1" />
      <div className={clsx("text-[11px] tabular flex items-center gap-1",
        up ? "text-accent-green" : "text-accent-red")}>
        {up ? <TrendingUp className="w-3 h-3" /> : <TrendingDown className="w-3 h-3" />}
        {up ? "+" : ""}{ix.change?.toFixed(2)} ({up ? "+" : ""}{ix.change_pct?.toFixed(2)}%)
      </div>
    </button>
  );
}

function TopPickRow({ pick, onClick }: { pick: any; onClick: () => void }) {
  const isBuy = pick.signal?.includes("BUY");
  return (
    <button onClick={onClick}
      className="w-full flex items-center gap-3 px-3 py-2.5 hover:bg-bg-base/40 text-left group transition-colors">
      <div className={clsx(
        "w-9 h-9 rounded flex items-center justify-center text-[10px] font-bold uppercase tracking-wider shrink-0",
        isBuy ? "bg-accent-green/15 text-accent-green border border-accent-green/30"
              : "bg-accent-red/15 text-accent-red border border-accent-red/30"
      )}>
        {pick.signal?.includes("STRONG") ? "★" : ""}{isBuy ? "BUY" : "SELL"}
      </div>
      <div className="flex-1 min-w-0">
        <div className="text-text-primary font-semibold text-[13px]">{pick.symbol}</div>
        <div className="text-[10px] text-text-muted truncate">
          {pick.engines?.technical?.reason?.slice(0, 60) || pick.trend}
        </div>
      </div>
      <div className="text-right shrink-0">
        <div className="text-accent-amber font-bold text-[12px] tabular">{fmt.num(pick.confidence, 0)}%</div>
        <div className="text-[10px] text-text-muted tabular">
          ₹{fmt.inr(pick.entry)} → ₹{fmt.inr(pick.targets?.[0])}
        </div>
      </div>
      <ArrowRight className="w-3 h-3 text-text-muted group-hover:text-accent-amber transition-colors shrink-0" />
    </button>
  );
}
