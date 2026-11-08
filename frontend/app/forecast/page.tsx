"use client";

import { useState } from "react";
import useSWR from "swr";
import { fetcher } from "@/lib/api";
import { Panel, Stat } from "@/components/Panel";
import { fmt, biasColor } from "@/lib/format";
import { CalendarDays, Search, ArrowUpRight, ArrowDownRight, Moon, Clock } from "lucide-react";
import clsx from "clsx";

export default function ForecastPage() {
  const [symbol, setSymbol] = useState("");
  const [submitted, setSubmitted] = useState("");
  const [days, setDays] = useState(7);

  const marketUrl = `/api/forecast/market?days=${days}`;
  const { data: market } = useSWR<any>(marketUrl, fetcher, { refreshInterval: 600_000 });

  const symbolUrl = submitted ? `/api/forecast/symbol/${submitted}?days=${days}` : null;
  const { data: outlook, isLoading: outlookLoading } = useSWR<any>(symbolUrl, fetcher);

  function submit(e: React.FormEvent) {
    e.preventDefault();
    if (symbol.trim()) setSubmitted(symbol.trim().toUpperCase());
  }

  return (
    <div className="space-y-4">
      {/* Symbol search */}
      <Panel
        title="Symbol Outlook — day-by-day cyclical bias"
        right={
          <select value={days} onChange={(e) => setDays(parseInt(e.target.value))}
            className="bg-bg-base border border-bg-line rounded px-2 py-1 text-[11px]">
            <option value={7}>Next 7 days</option>
            <option value={14}>Next 14 days</option>
            <option value={21}>Next 21 days</option>
          </select>
        }
      >
        <form onSubmit={submit} className="flex gap-2 items-center">
          <Search className="w-4 h-4 text-text-muted" />
          <input
            value={symbol}
            onChange={(e) => setSymbol(e.target.value.toUpperCase())}
            placeholder="Search any stock e.g. RELIANCE, TCS, NIFTY, BANKNIFTY"
            className="flex-1 bg-bg-base border border-bg-line rounded px-3 py-1.5 text-sm font-mono"
          />
          <button type="submit"
            className="px-4 py-1.5 bg-accent-amber text-black rounded text-sm font-semibold">
            Forecast
          </button>
        </form>
        <div className="text-[10px] text-text-muted mt-2">
          Per-day composite of cyclical inputs (Moon nakshatra tara from symbol, day-lord climate,
          date–symbol numerology, Gann cycle proximity). Surfaces calendar-favorable vs unfavorable days.
          Not a price forecast — a <em>timing</em> outlook for confluence with technicals.
        </div>
      </Panel>

      {outlookLoading && submitted && (
        <div className="text-text-secondary text-sm">Computing {submitted} outlook…</div>
      )}

      {outlook && <SymbolOutlookCard outlook={outlook} />}

      {/* Market weekly calendar */}
      <Panel title="Market Calendar — Upcoming Cyclical Events"
        right={<span className="text-[10px] text-text-muted">{market?.from ? `from ${market.from}` : ""}</span>}>
        {!market && <div className="text-text-muted text-xs">Loading market calendar…</div>}
        {market && <MarketCalendar market={market} />}
      </Panel>
    </div>
  );
}

// ---------------------------------------------------------------------------

function SymbolOutlookCard({ outlook }: { outlook: any }) {
  return (
    <div className="space-y-3">
      <Panel title={`${outlook.symbol} — Weekly Outlook`}>
        <div className="grid grid-cols-2 md:grid-cols-5 gap-3 text-[11px]">
          <Stat label="Symbol nakshatra" value={outlook.symbol_nakshatra}
            sub={`Ruler: ${outlook.symbol_nakshatra_ruler}`} color="text-accent-violet" />
          <Stat label="Root number" value={outlook.symbol_root_number} color="text-accent-amber" />
          <Stat label="Best BUY day"
            value={outlook.best_buy_day || "—"}
            color="text-accent-green"
            sub={outlook.best_buy_day ? "highest score" : "no high-edge day in window"} />
          <Stat label="Best SELL day"
            value={outlook.best_sell_day || "—"}
            color="text-accent-red"
            sub={outlook.best_sell_day ? "lowest score" : "no high-edge day in window"} />
          <Stat label="Days analyzed" value={outlook.days?.length || 0} />
        </div>
        <div className="text-[11px] text-text-secondary mt-3 border-t border-bg-line pt-2">{outlook.summary}</div>
      </Panel>

      {/* Day-by-day grid */}
      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-7 gap-3">
        {(outlook.days || []).map((d: any) => <DayCard key={d.date} d={d} />)}
      </div>
    </div>
  );
}

function DayCard({ d }: { d: any }) {
  const isBuy = d.bias === "BULLISH";
  const isSell = d.bias === "BEARISH";
  const gradeColor =
    d.grade === "EXCELLENT" ? "bg-accent-green/20 text-accent-green border-accent-green/40"
    : d.grade === "GOOD"    ? "bg-accent-green/10 text-accent-green border-accent-green/30"
    : d.grade === "OK"      ? "bg-accent-amber/10 text-accent-amber border-accent-amber/30"
    : d.grade === "WEAK"    ? "bg-accent-red/10 text-accent-red border-accent-red/30"
                            : "bg-accent-red/20 text-accent-red border-accent-red/50";
  return (
    <div className={`border rounded bg-panel-grad ${
      isBuy ? "border-accent-green/40" : isSell ? "border-accent-red/40" : "border-bg-line"
    }`}>
      <div className="px-2 py-1.5 border-b border-bg-line flex items-center justify-between">
        <div className="text-[10px]">
          <div className="text-text-primary font-semibold">{d.weekday.slice(0, 3)}</div>
          <div className="text-text-muted">{d.date.slice(5)}</div>
        </div>
        <span className={`text-[9px] uppercase font-bold px-1.5 py-0.5 rounded border ${gradeColor}`}>
          {d.grade}
        </span>
      </div>

      <div className="p-2 space-y-1.5">
        <div className="flex items-center justify-between">
          <span className="text-[11px] tabular font-bold">
            {isBuy && <ArrowUpRight className="w-3 h-3 text-accent-green inline" />}
            {isSell && <ArrowDownRight className="w-3 h-3 text-accent-red inline" />}
            <span className={biasColor(d.bias)}> {fmt.num(d.score, 0)}</span>
          </span>
          <span className="text-[9px] text-text-muted uppercase">{d.day_lord}</span>
        </div>

        <div className="text-[10px] text-text-secondary border-t border-bg-line/40 pt-1">
          <div className="flex items-center gap-1">
            <Moon className="w-2.5 h-2.5 text-text-muted" />
            <span className="text-accent-violet">{d.moon_nakshatra}</span>
            <span className="text-text-muted">p{d.moon_pada}</span>
          </div>
          <div className="text-text-muted text-[9px]">tara {d.tara_from_symbol}/27</div>
        </div>

        {d.intraday_windows?.length > 0 && (
          <div className="text-[9px] border-t border-bg-line/40 pt-1">
            <div className="text-text-muted uppercase mb-0.5">Best hora windows</div>
            {d.intraday_windows.slice(0, 2).map((w: any, i: number) => (
              <div key={i} className="flex items-center gap-1">
                <Clock className="w-2.5 h-2.5 text-text-muted shrink-0" />
                <span className={
                  w.bias === "bullish" ? "text-accent-green"
                  : w.bias === "bearish" ? "text-accent-red"
                  : "text-text-secondary"
                }>{w.ruler}</span>
                <span className="text-text-muted">{w.start}-{w.end}</span>
              </div>
            ))}
          </div>
        )}

        {d.events?.length > 0 && (
          <div className="text-[9px] text-accent-amber border-t border-bg-line/40 pt-1">
            {d.events.slice(0, 2).map((e: string, i: number) => (
              <div key={i}>• {e}</div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------

function MarketCalendar({ market }: { market: any }) {
  return (
    <div className="space-y-3">
      <table className="w-full text-[11px] tabular">
        <thead className="text-text-muted text-[10px] uppercase">
          <tr className="border-b border-bg-line">
            <th className="text-left py-1.5 px-2">Date</th>
            <th className="text-left">Day</th>
            <th className="text-center">Day-lord</th>
            <th className="text-left">Moon</th>
            <th className="text-center">Paksha · Tithi</th>
            <th className="text-right">Astro Score</th>
            <th className="text-center">Bias</th>
            <th className="text-left">Events</th>
          </tr>
        </thead>
        <tbody>
          {market.days.map((d: any) => (
            <tr key={d.date} className="border-b border-bg-line/40 hover:bg-bg-panel">
              <td className="py-1 px-2 text-text-primary">{d.date}</td>
              <td>{d.weekday}</td>
              <td className={clsx("text-center text-[10px]",
                d.day_lord_bias === "bullish" ? "text-accent-green"
                : d.day_lord_bias === "bearish" ? "text-accent-red"
                : "text-text-secondary")}>{d.day_lord}</td>
              <td className="text-accent-violet">{d.moon_nakshatra}</td>
              <td className="text-center text-text-secondary">{d.moon_paksha} · {d.tithi}</td>
              <td className="text-right text-accent-amber tabular">{fmt.num(d.score, 1)}</td>
              <td className={`text-center font-semibold ${biasColor(d.bias)}`}>{d.bias}</td>
              <td className="text-[10px] text-text-secondary">
                {d.events?.length > 0 ? d.events.join(" · ") : <span className="text-text-muted">—</span>}
              </td>
            </tr>
          ))}
        </tbody>
      </table>

      {market.upcoming_gann_dates?.length > 0 && (
        <div className="border-t border-bg-line pt-2 text-[11px]">
          <div className="text-text-muted uppercase mb-1">⚡ Upcoming Gann cycle dates in window</div>
          <ul className="text-text-secondary space-y-0.5">
            {market.upcoming_gann_dates.map((g: any, i: number) => (
              <li key={i}>
                <span className="text-accent-amber tabular">{g.projected_date}</span>{" "}
                <span className="text-text-muted">— {g.cycle_days}d cycle ({g.significance})</span>
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}
