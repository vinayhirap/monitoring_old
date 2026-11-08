"use client";

/**
 * Horizontal timeline of every planetary hora during today's NSE session.
 *
 * Each hora is rendered as a colored segment (width proportional to its
 * duration) with the ruler name and start time. Green = bullish, red =
 * bearish, amber = neutral. A vertical "now" marker shows the current
 * moment in the session.
 *
 * Click a segment to expand the notes (e.g. "Restrictive, heavy; PSU/infra
 * /metals. Strong for PE/short, AVOID CE/long.") so the user knows WHY a
 * particular hora window is bullish or bearish.
 *
 * Use case driven by feedback: when the forecast card only shows the
 * BEST windows (e.g. Mercury 09:30-10:35 bullish, Mars 14:00-15:05 bearish),
 * the user has no way to see what was active during the gap. NIFTY dropped
 * hard between 10:35 and 14:00 because Saturn hora (~11:40-12:45) hit; this
 * widget makes that obvious at a glance.
 */

import useSWR from "swr";
import { useState, useMemo } from "react";
import { authedFetcher as fetcher } from "@/lib/auth";
import {
  TrendingUp, TrendingDown, Minus, Clock, Sparkles, Info,
} from "lucide-react";
import clsx from "clsx";


type HoraSegment = {
  hora_index:       number;
  ruler:            string;
  bias:             "bullish" | "bearish" | "neutral";
  weight:           number;
  notes:            string;
  start_iso:        string;
  end_iso:          string;
  duration_minutes: number;
  is_current:       boolean;
  is_past:          boolean;
  is_future:        boolean;
};

type TimelineData = {
  date:     string;
  weekday:  string;
  timeline: HoraSegment[];
  current:  any;
  asof:     string;
};


function biasColor(bias: string): { bar: string; text: string; border: string; tint: string } {
  if (bias === "bullish")
    return { bar: "bg-accent-green",  text: "text-accent-green",
              border: "border-accent-green/40", tint: "bg-accent-green/10" };
  if (bias === "bearish")
    return { bar: "bg-accent-red",    text: "text-accent-red",
              border: "border-accent-red/40",   tint: "bg-accent-red/10" };
  return { bar: "bg-accent-amber",    text: "text-accent-amber",
            border: "border-accent-amber/40",  tint: "bg-accent-amber/10" };
}


function biasIcon(bias: string) {
  if (bias === "bullish") return TrendingUp;
  if (bias === "bearish") return TrendingDown;
  return Minus;
}


function fmtTime(iso: string): string {
  try {
    const d = new Date(iso);
    return d.toLocaleTimeString("en-IN", {
      hour: "2-digit", minute: "2-digit", hour12: false,
    });
  } catch { return iso; }
}


export function HoraDayTimeline() {
  const { data, error, isLoading } = useSWR<TimelineData>(
    "/api/hora/day-timeline",
    fetcher,
    { refreshInterval: 60_000, shouldRetryOnError: false },
  );

  const [expanded, setExpanded] = useState<number | null>(null);

  // Compute "now" marker position as a % across the timeline
  const nowPct = useMemo(() => {
    if (!data?.timeline?.length) return 0;
    const first = new Date(data.timeline[0].start_iso).getTime();
    const last  = new Date(data.timeline[data.timeline.length - 1].end_iso).getTime();
    const now   = Date.now();
    if (now < first) return 0;
    if (now > last)  return 100;
    return ((now - first) / (last - first)) * 100;
  }, [data]);

  if (error) {
    return (
      <div className="bg-bg-surface border border-bg-line rounded-lg p-3 text-[11px] text-text-muted">
        Hora timeline unavailable.
      </div>
    );
  }
  if (isLoading || !data) {
    return (
      <div className="bg-bg-surface border border-bg-line rounded-lg p-3 text-[11px] text-text-muted flex items-center gap-2">
        <Clock className="w-3.5 h-3.5 animate-pulse" />
        Loading today's hora schedule…
      </div>
    );
  }
  if (!data.timeline?.length) {
    return null;
  }

  // Total span in minutes (used to scale segment widths)
  const totalMin = data.timeline.reduce((s, h) => s + h.duration_minutes, 0);
  const currentHora = data.timeline.find((h) => h.is_current);

  return (
    <div className="bg-bg-surface border border-bg-line rounded-lg p-4 space-y-3">
      {/* Header */}
      <div className="flex items-start justify-between gap-3 flex-wrap">
        <div>
          <div className="flex items-center gap-2 text-text-primary font-bold text-sm">
            <Sparkles className="w-4 h-4 text-accent-amber" />
            Today's hora schedule
            <span className="text-text-muted font-normal text-[11px]">
              · {data.weekday} {data.date}
            </span>
          </div>
          <p className="text-[11px] text-text-secondary mt-0.5 max-w-xl leading-snug">
            Every planetary hora during the NSE session, with its directional bias.
            The market behaves differently in each — green windows favor longs,
            red windows favor shorts.
          </p>
        </div>
        {currentHora && <CurrentHoraChip h={currentHora} />}
      </div>

      {/* Timeline bar */}
      <div className="relative">
        <div className="flex h-10 rounded overflow-hidden border border-bg-line">
          {data.timeline.map((h, idx) => {
            const colors = biasColor(h.bias);
            const widthPct = (h.duration_minutes / totalMin) * 100;
            const isOpen = expanded === idx;
            return (
              <button
                key={idx}
                onClick={() => setExpanded(isOpen ? null : idx)}
                style={{ width: `${widthPct}%` }}
                title={`${h.ruler} · ${h.bias} · ${fmtTime(h.start_iso)}–${fmtTime(h.end_iso)}`}
                className={clsx(
                  "relative flex flex-col items-center justify-center text-[9px] font-bold tracking-wider",
                  "border-r border-bg-line/40 last:border-r-0 transition-opacity",
                  h.is_past   && "opacity-40",
                  h.is_future && "opacity-90",
                  h.is_current && "ring-2 ring-accent-amber ring-inset",
                  colors.bar,
                  // Inverse text on saturated bg
                  "text-white",
                )}
              >
                <span className="uppercase">{h.ruler.slice(0, 3)}</span>
                <span className="text-[8px] opacity-80">{fmtTime(h.start_iso)}</span>
              </button>
            );
          })}
        </div>

        {/* Current-time marker */}
        {nowPct > 0 && nowPct < 100 && (
          <div
            className="absolute top-0 bottom-0 w-0.5 bg-text-primary pointer-events-none"
            style={{ left: `${nowPct}%` }}
            aria-label="Current time"
          >
            <div className="absolute -top-2 left-1/2 -translate-x-1/2 w-2 h-2 rotate-45 bg-text-primary" />
          </div>
        )}
      </div>

      {/* Legend row */}
      <div className="flex items-center gap-4 text-[10px] text-text-muted">
        <LegendItem color="bg-accent-green"  label="Bullish (buy windows)" />
        <LegendItem color="bg-accent-amber"  label="Neutral (intraday scalps)" />
        <LegendItem color="bg-accent-red"    label="Bearish (sell/avoid buys)" />
        <span className="ml-auto italic">Click any window for details</span>
      </div>

      {/* Expanded segment details */}
      {expanded !== null && data.timeline[expanded] && (
        <ExpandedDetail seg={data.timeline[expanded]} />
      )}
    </div>
  );
}


function CurrentHoraChip({ h }: { h: HoraSegment }) {
  const colors = biasColor(h.bias);
  const Icon = biasIcon(h.bias);
  // Minutes remaining until this hora ends
  const minsLeft = Math.max(0, Math.round(
    (new Date(h.end_iso).getTime() - Date.now()) / 60_000,
  ));
  return (
    <div className={clsx("inline-flex flex-col items-end px-3 py-1.5 rounded border",
                          colors.border, colors.tint)}>
      <div className="flex items-center gap-1.5 text-[10px] uppercase font-bold tracking-wider text-text-muted">
        <Clock className="w-3 h-3" /> Active now
      </div>
      <div className={clsx("flex items-center gap-1.5 font-bold text-sm", colors.text)}>
        <Icon className="w-3.5 h-3.5" />
        {h.ruler} · {h.bias.toUpperCase()}
      </div>
      <div className="text-[10px] text-text-muted tabular">
        {fmtTime(h.start_iso)}–{fmtTime(h.end_iso)} · {minsLeft}m left
      </div>
    </div>
  );
}


function ExpandedDetail({ seg }: { seg: HoraSegment }) {
  const colors = biasColor(seg.bias);
  const Icon = biasIcon(seg.bias);
  return (
    <div className={clsx("border rounded p-3", colors.border, colors.tint)}>
      <div className="flex items-start gap-2">
        <Icon className={clsx("w-4 h-4 shrink-0 mt-0.5", colors.text)} />
        <div className="flex-1 min-w-0">
          <div className="flex items-baseline gap-2 flex-wrap">
            <div className={clsx("font-bold text-sm", colors.text)}>
              {seg.ruler} hora
            </div>
            <div className="text-[10px] uppercase tracking-wider text-text-muted">
              {fmtTime(seg.start_iso)}–{fmtTime(seg.end_iso)} · {seg.duration_minutes}m
            </div>
            <div className={clsx("text-[10px] uppercase font-bold tracking-wider px-1.5 py-0.5 rounded",
                                  colors.tint, colors.text)}>
              {seg.bias} · weight {seg.weight}
            </div>
          </div>
          <div className="text-[12px] text-text-secondary leading-snug mt-1">
            {seg.notes}
          </div>
          {seg.is_past && (
            <div className="text-[10px] text-text-muted mt-1 italic flex items-center gap-1">
              <Info className="w-3 h-3" /> This window has passed.
            </div>
          )}
        </div>
      </div>
    </div>
  );
}


function LegendItem({ color, label }: { color: string; label: string }) {
  return (
    <span className="inline-flex items-center gap-1.5">
      <span className={clsx("w-2.5 h-2.5 rounded", color)} />
      {label}
    </span>
  );
}
