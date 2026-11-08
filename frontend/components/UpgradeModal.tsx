"use client";

/**
 * Global "upgrade required" modal.
 *
 * Listens for `marketlens:upgrade-required` window events (fired by
 * `authedFetcher` whenever the backend returns HTTP 402). When the event
 * fires, the modal opens and shows the tier ladder filtered to the
 * required tier and above — the user can click "Upgrade" right there
 * without leaving their current page.
 *
 * Mount once at the root of the app (RootLayout). It renders nothing
 * until the event fires.
 *
 * The event payload is the body of the 402 response from the backend,
 * which `dependencies.require_tier` shapes as:
 *   { message, current_tier, required_tier, upgrade_url }
 */

import { useEffect, useState, useCallback } from "react";
import { X, Lock } from "lucide-react";
import { SubscriptionTierCard } from "@/components/SubscriptionTierCard";


type UpgradePayload = {
  message?: string;
  current_tier?: "FREE" | "BASIC" | "INTERMEDIATE" | "ADVANCED";
  required_tier?: "FREE" | "BASIC" | "INTERMEDIATE" | "ADVANCED";
  upgrade_url?: string;
  /** Optional context — e.g. "Trying to view F&O recommendations" */
  source?: string;
};


// Event-name constant exported so callers (auth.ts) use the same string.
export const UPGRADE_EVENT = "marketlens:upgrade-required";


export function UpgradeModal() {
  const [payload, setPayload] = useState<UpgradePayload | null>(null);

  useEffect(() => {
    function onUpgrade(e: Event) {
      const detail = (e as CustomEvent<UpgradePayload>).detail || {};
      setPayload(detail);
    }
    window.addEventListener(UPGRADE_EVENT, onUpgrade as EventListener);
    return () => window.removeEventListener(UPGRADE_EVENT, onUpgrade as EventListener);
  }, []);

  const close = useCallback(() => setPayload(null), []);

  // Close on Escape
  useEffect(() => {
    if (!payload) return;
    function onKey(e: KeyboardEvent) { if (e.key === "Escape") close(); }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [payload, close]);

  if (!payload) return null;

  const required = payload.required_tier || "BASIC";
  const current  = payload.current_tier  || "FREE";

  return (
    <div className="fixed inset-0 z-50 bg-black/70 flex items-center justify-center p-4 overflow-y-auto"
          onClick={close}>
      <div className="bg-bg-surface rounded-lg shadow-2xl w-full max-w-5xl max-h-[90vh] overflow-y-auto"
            onClick={(e) => e.stopPropagation()}>
        {/* Header */}
        <div className="sticky top-0 bg-bg-surface border-b border-bg-line px-5 py-3.5 flex items-start justify-between gap-4 z-10">
          <div className="flex items-start gap-3">
            <div className="bg-accent-amber/10 border border-accent-amber/40 rounded p-2 shrink-0">
              <Lock className="w-4 h-4 text-accent-amber" />
            </div>
            <div>
              <h2 className="font-bold text-text-primary text-base">
                {required} tier required
              </h2>
              <p className="text-[12px] text-text-secondary mt-0.5">
                {payload.message ||
                  `This feature is available on the ${required} plan and above. Your current plan: ${current}.`}
              </p>
            </div>
          </div>
          <button onClick={close} className="text-text-muted hover:text-text-primary shrink-0">
            <X className="w-5 h-5" />
          </button>
        </div>

        {/* Tier ladder — show from required onwards so the choice is clear */}
        <div className="p-5">
          <SubscriptionTierCard
            currentTier={current}
            highlightTier={required}
            hideTiers={["FREE"]}
            onUpgradeStarted={() => {/* keep modal open until Razorpay closes */}}
          />
          <p className="text-[10px] text-text-muted text-center mt-4">
            After payment confirmation, your account is upgraded automatically.
            Refresh the page if the new tier doesn't appear within a minute.
          </p>
        </div>
      </div>
    </div>
  );
}


/**
 * Convenience helper — fire the upgrade event from anywhere.
 * Use this when you want to programmatically prompt for an upgrade
 * (e.g. from a "Try this F&O feature" button on the marketing page),
 * without depending on a backend 402 response.
 */
export function requestUpgrade(payload: UpgradePayload) {
  if (typeof window === "undefined") return;
  window.dispatchEvent(new CustomEvent(UPGRADE_EVENT, { detail: payload }));
}
