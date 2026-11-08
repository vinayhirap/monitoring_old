"use client";

/**
 * Tiny status chip showing whether the online-learner AI is active.
 *
 * Three states:
 *   • LEARNING — model has < 30 evaluated samples (warmup)
 *   • READY    — model is trained, predictions are trustworthy
 *   • OFF      — model state not available (likely backend down)
 *
 * Polls /api/health?detailed=true once per minute. Tucked into the
 * portal header next to the broker badge so users can always see
 * whether the AI layer is contributing to their recommendations.
 */

import useSWR from "swr";
import { authedFetcher as fetcher } from "@/lib/auth";
import { Sparkles, AlertCircle } from "lucide-react";
import clsx from "clsx";


export function AIStatusChip() {
  const { data, error } = useSWR<any>("/api/health?detailed=true", fetcher,
    { refreshInterval: 60_000, shouldRetryOnError: false });

  if (error || !data) {
    return (
      <span className="hidden md:inline-flex items-center gap-1 text-[9px] uppercase font-bold text-text-muted bg-bg-base border border-bg-line rounded px-2 py-1"
            title="AI status unavailable — backend may be down">
        <AlertCircle className="w-3 h-3" />
        AI ·  —
      </span>
    );
  }

  const cal = data.subsystems?.calibrator;
  const n  = cal?.n_samples || 0;
  // Show "ready" when the calibrator has fitted; otherwise show sample count.
  // Calibrator activates with the same data the online learner uses.
  const ready = cal?.active;

  return (
    <span className={clsx(
      "hidden md:inline-flex items-center gap-1 text-[9px] uppercase font-bold rounded px-2 py-1 border",
      ready
        ? "bg-accent-violet/10 text-accent-violet border-accent-violet/40"
        : "bg-bg-base text-text-muted border-bg-line"
    )}
      title={ready
        ? `Online AI is trained on ${n} closed signals — predictions are trustworthy`
        : `AI is in warmup — needs ≥30 closed signals (currently ${n}). Predictions hidden until then.`}>
      <Sparkles className="w-3 h-3" />
      AI · {ready ? "READY" : `LEARNING ${n}`}
    </span>
  );
}
