"use client";

/**
 * Renders a "this feature needs a higher tier" prompt when the backend
 * returned HTTP 402 with the structured payload:
 *
 *     { message, current_tier, required_tier, upgrade_url }
 *
 * Pages typically use it via `<MaybeUpgrade error={swrError} />` so the
 * paywall surface looks the same everywhere:
 *
 *     const { data, error } = useSWR(..., authedFetcher);
 *     if (error?.status === 402) return <MaybeUpgrade error={error} />;
 *
 * Or, more concisely, use `<TierGate error={error}>...children...</TierGate>`
 * which renders children when there's no 402, and the upgrade card when there is.
 */

import Link from "next/link";
import { Lock, ArrowRight, Sparkles } from "lucide-react";
import { ApiError } from "@/lib/auth";


type TierPayload = {
  message?: string;
  current_tier?: string;
  required_tier?: string;
  upgrade_url?: string;
};


function readPayload(err: unknown): TierPayload | null {
  if (!(err instanceof ApiError) || err.status !== 402) return null;
  // FastAPI wraps the HTTPException detail in `.detail`. Older code paths
  // may put the dict at the top level. Handle both.
  const b = err.body || {};
  return b.detail || b;
}


export function UpgradeRequired({ error }: { error: unknown }) {
  const payload = readPayload(error);
  if (!payload) return null;

  const required = payload.required_tier || "a higher tier";
  const current = payload.current_tier || "FREE";
  const href = payload.upgrade_url || "/portal/profile";

  return (
    <div className="bg-gradient-to-br from-accent-amber/10 via-accent-violet/5 to-bg-surface
                     border border-accent-amber/30 rounded-lg p-6 text-center">
      <div className="inline-flex items-center justify-center w-12 h-12 rounded-full
                       bg-accent-amber/15 mb-3">
        <Lock className="w-6 h-6 text-accent-amber" />
      </div>
      <h2 className="text-lg font-bold text-text-primary mb-1">
        {required} subscription required
      </h2>
      <p className="text-[12px] text-text-secondary mb-4 max-w-md mx-auto">
        {payload.message ||
          `This feature is included with the ${required} tier. You are currently on ${current}.`}
      </p>

      <div className="flex items-center justify-center gap-2 text-[11px] text-text-muted mb-5">
        <span className="px-2 py-0.5 rounded bg-bg-base border border-bg-line uppercase font-bold">
          {current}
        </span>
        <ArrowRight className="w-3 h-3" />
        <span className="px-2 py-0.5 rounded bg-accent-amber/20 border border-accent-amber/40
                          text-accent-amber uppercase font-bold">
          {required}
        </span>
      </div>

      <Link href={href}
            className="inline-flex items-center gap-1.5 bg-accent-amber text-white font-bold
                       px-4 py-2 rounded text-sm hover:bg-accent-gold transition-colors">
        <Sparkles className="w-4 h-4" />
        See plans & upgrade
      </Link>
    </div>
  );
}


/**
 * Convenience wrapper: if `error` is a 402, render the upgrade card;
 * otherwise render `children`. Lets pages stay clean:
 *
 *   <TierGate error={error}>
 *     {data && <ScanResults data={data} />}
 *   </TierGate>
 *
 * Non-402 errors fall through to children (so generic error UI in the page
 * itself still gets to render).
 */
export function TierGate({ error, children }:
                          { error: unknown; children: React.ReactNode }) {
  if (error instanceof ApiError && error.status === 402) {
    return <UpgradeRequired error={error} />;
  }
  return <>{children}</>;
}
