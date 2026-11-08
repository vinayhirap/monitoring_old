"use client";

import useSWR from "swr";
import { fetcher } from "@/lib/api";
import { Panel } from "@/components/Panel";
import { fmt, biasColor } from "@/lib/format";

export default function VedicTimingPage() {
  const { data: transits } = useSWR<any>("/api/astrology/transits", fetcher, { refreshInterval: 60_000 });
  const { data: sentiment } = useSWR<any>("/api/astrology/market-sentiment", fetcher, { refreshInterval: 120_000 });

  const planets = transits?.planets ? Object.values(transits.planets) : [];

  return (
    <div className="grid grid-cols-12 gap-4">
      <div className="col-span-12">
        <Panel title="What this page measures">
          <p className="text-[11px] text-text-secondary leading-relaxed">
            This is a <span className="text-accent-amber">behavioral timing layer</span> based on the Hindu/Vedic calendar
            (panchang). Indian retail traders have followed muhurta-based timing for generations; this page surfaces the same
            cyclical markers (nakshatra, planetary day, hora, tithi) as a <em>confluence and veto layer</em> for technical setups,
            not as a standalone prediction. Calculations use the Lahiri ayanamsa via Swiss Ephemeris (Moshier).
            See <a href="/methodology" className="text-accent-amber underline">/methodology</a> for how this feeds the decision pipeline.
          </p>
        </Panel>
      </div>

      <div className="col-span-12 lg:col-span-8">
        <Panel title="Sidereal Planetary Positions (Lahiri ayanamsa)">
          <table className="w-full text-[12px] tabular">
            <thead className="text-text-muted text-[10px] uppercase">
              <tr className="border-b border-bg-line">
                <th className="text-left py-2 px-2">Body</th>
                <th className="text-right">Long (°)</th>
                <th className="text-left pl-4">Sign</th>
                <th className="text-left">Nakshatra</th>
                <th className="text-center">Pada</th>
                <th className="text-right">Speed</th>
                <th className="text-center">Motion</th>
              </tr>
            </thead>
            <tbody>
              {planets.map((p: any) => (
                <tr key={p.name} className="border-b border-bg-line/40">
                  <td className="py-1.5 px-2 text-text-primary font-semibold">{p.name}</td>
                  <td className="text-right text-text-secondary">{fmt.num(p.longitude, 3)}</td>
                  <td className="pl-4 text-text-primary">{p.sign?.name}</td>
                  <td className="text-accent-violet">{p.nakshatra?.name}</td>
                  <td className="text-center text-text-secondary">{p.nakshatra?.pada}</td>
                  <td className="text-right text-text-muted">{fmt.num(p.speed, 4)}</td>
                  <td className="text-center">
                    {p.retrograde
                      ? <span className="text-accent-red">Rx</span>
                      : <span className="text-accent-green">D</span>}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </Panel>
      </div>

      <div className="col-span-12 lg:col-span-4 space-y-4">
        <Panel title="Today's Timing Bias">
          <div className={`text-2xl font-bold ${biasColor(sentiment?.bias)}`}>
            {sentiment?.bias || "—"}
          </div>
          <div className="text-text-secondary text-xs mt-1">{sentiment?.headline}</div>
          <div className="mt-3 grid grid-cols-2 gap-2 text-[11px]">
            <div>
              <div className="text-text-muted uppercase">Score</div>
              <div className="text-accent-amber tabular text-lg">{fmt.num(sentiment?.score, 1)}</div>
            </div>
            <div>
              <div className="text-text-muted uppercase">Expected vol</div>
              <div className="text-accent-red tabular text-lg">{fmt.num(sentiment?.volatility_pct, 1)}%</div>
            </div>
          </div>
        </Panel>

        <Panel title="Lunar Phase">
          <div className="text-[11px] text-text-secondary">
            {transits?.moon_phase?.phase} · {transits?.moon_phase?.paksha} paksha · tithi {transits?.moon_phase?.tithi}
          </div>
          <div className="mt-2 text-[11px] text-text-muted">
            Illumination: <span className="text-accent-amber">{transits?.moon_phase?.illumination_pct}%</span>
            <br />Sun-Moon elongation: {fmt.num(transits?.moon_phase?.elongation_deg, 1)}°
          </div>
        </Panel>

        <Panel title="Active Aspects">
          <ul className="text-[11px] space-y-1 max-h-64 overflow-auto">
            {(sentiment?.raw?.aspects || []).slice(0, 12).map((a: any, i: number) => (
              <li key={i} className="flex justify-between">
                <span className="text-text-primary">
                  {a.planet_a} <span className="text-text-muted">{a.aspect}°</span> {a.planet_b}
                </span>
                <span className={biasColor(a.nature.toUpperCase())}>{a.nature}</span>
              </li>
            ))}
          </ul>
        </Panel>
      </div>

      <div className="col-span-12 grid grid-cols-2 gap-4">
        <Panel title="Supportive Timing Factors">
          <ul className="text-[12px] text-accent-green space-y-1 list-disc pl-4">
            {(sentiment?.bullish_factors || []).map((f: string, i: number) => <li key={i}>{f}</li>)}
          </ul>
        </Panel>
        <Panel title="Restrictive Timing Factors">
          <ul className="text-[12px] text-accent-red space-y-1 list-disc pl-4">
            {(sentiment?.bearish_factors || []).map((f: string, i: number) => <li key={i}>{f}</li>)}
          </ul>
        </Panel>
      </div>
    </div>
  );
}
