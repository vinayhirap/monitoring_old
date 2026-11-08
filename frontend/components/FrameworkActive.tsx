"use client";

import { Activity, Sparkles, Hash, Compass, BarChart3, Moon, Clock } from "lucide-react";
import clsx from "clsx";

/**
 * Transparent "what's actually running" pill row. Surfaces every engine,
 * its current weight in the decision blend, and whether it's ON/OFF.
 * Goal: no black box — the user can see exactly which layers are
 * contributing to a recommendation right now.
 */
const ENGINES = [
  { name: "Technical",  icon: BarChart3, weight: 30, calibrated: true,  group: "price" },
  { name: "SMC/ICT",    icon: Activity,  weight: 20, calibrated: true,  group: "price" },
  { name: "Options",    icon: BarChart3, weight: 20, calibrated: false, group: "price" },
  { name: "Gann",       icon: Compass,   weight: 12, calibrated: false, group: "geometric" },
  { name: "Fibonacci",  icon: Compass,   weight: 12, calibrated: false, group: "geometric" },
  { name: "Vedic time", icon: Sparkles,  weight: 12, calibrated: false, group: "cyclical" },
  { name: "Numerology", icon: Hash,      weight: 6,  calibrated: false, group: "cyclical" },
  { name: "Lunar",      icon: Moon,      weight: "gate", calibrated: false, group: "veto" },
  { name: "Hora",       icon: Clock,     weight: "gate", calibrated: false, group: "veto" },
];

export function FrameworkActive() {
  return (
    <div className="border border-bg-line rounded p-3 bg-bg-panel">
      <div className="flex items-center justify-between mb-2">
        <span className="text-[10px] uppercase text-text-muted tracking-wider">
          Active framework — engines contributing to every recommendation
        </span>
        <a href="/methodology" className="text-[10px] text-accent-amber underline">
          methodology
        </a>
      </div>
      <div className="flex flex-wrap gap-2">
        {ENGINES.map((e) => {
          const Icon = e.icon;
          const isGate = e.weight === "gate";
          return (
            <div key={e.name}
                 className={clsx(
                   "flex items-center gap-1.5 px-2 py-1 rounded border text-[10px]",
                   isGate
                     ? "border-accent-red/40 bg-accent-red/5 text-accent-red"
                     : e.group === "price"
                       ? "border-accent-green/40 bg-accent-green/5 text-accent-green"
                       : e.group === "geometric"
                         ? "border-accent-blue/40 bg-accent-blue/5 text-accent-blue"
                         : "border-accent-violet/40 bg-accent-violet/5 text-accent-violet"
                 )}>
              <Icon className="w-3 h-3" />
              <span className="font-semibold">{e.name}</span>
              <span className="text-text-muted">
                {isGate ? "veto-gate" : `${e.weight}%`}
              </span>
              {e.calibrated && (
                <span className="text-[8px] uppercase bg-accent-amber/20 text-accent-amber px-1 rounded">cal</span>
              )}
            </div>
          );
        })}
      </div>
      <div className="text-[9px] text-text-muted mt-2 flex gap-4">
        <span><span className="text-accent-green">●</span> price-anchored</span>
        <span><span className="text-accent-blue">●</span> geometric</span>
        <span><span className="text-accent-violet">●</span> cyclical (lower weight)</span>
        <span><span className="text-accent-red">●</span> veto-gate (can downgrade to WAIT)</span>
        <span><span className="text-accent-amber">cal</span> = backtest-calibrated</span>
      </div>
    </div>
  );
}
