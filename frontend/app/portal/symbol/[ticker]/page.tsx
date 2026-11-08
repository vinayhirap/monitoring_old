"use client";

import { useState, useEffect } from "react";
import useSWR from "swr";
import Link from "next/link";
import { authedFetcher as fetcher } from "@/lib/auth";
import { getLang, type AppLang } from "@/components/LanguageToggle";
import { SimpleRecommendation } from "@/components/SimpleRecommendation";
import { FnoRecommendationPanel } from "@/components/FnoRecommendationPanel";
import { ChevronLeft, AlertTriangle, Zap } from "lucide-react";


/**
 * Portal-side symbol page — uses ONLY the clean SimpleRecommendation card.
 * Engine internals, calibration, quant indicators, Gann tables, etc. are NOT
 * shown to portal users. They see one decision card.
 */
export default function PortalSymbolPage({ params }: { params: { ticker: string } }) {
  const sym = params.ticker.toUpperCase();

  // Track language preference; re-fetch when user flips the toggle.
  const [lang, setLangState] = useState<AppLang>("en");
  useEffect(() => {
    setLangState(getLang());
    const handler = (e: Event) => setLangState((e as CustomEvent).detail);
    window.addEventListener("marketlens:lang-change", handler);
    return () => window.removeEventListener("marketlens:lang-change", handler);
  }, []);

  const { data, error, isLoading } = useSWR<any>(
    `/api/symbol/${sym}?horizon=SWING&lang=${lang}`,
    fetcher,
    { refreshInterval: 30_000 }   // refresh every 30s so live price updates
  );

  return (
    <div className="space-y-4">
      <Link href="/portal" className="inline-flex items-center text-[12px] text-text-muted hover:text-accent-amber gap-1">
        <ChevronLeft className="w-3.5 h-3.5" /> Back to dashboard
      </Link>

      {isLoading && !data && (
        <div className="text-center text-text-muted py-12">Loading {sym}…</div>
      )}

      {error && (
        <div className="border border-accent-red/40 bg-accent-red/5 rounded p-4 text-sm text-accent-red flex items-start gap-2">
          <AlertTriangle className="w-4 h-4 shrink-0 mt-0.5" />
          <div>
            <strong>Could not load {sym}.</strong>
            <div className="mt-1 text-[11px]">{String(error.message)}</div>
            <div className="mt-2 text-[11px] text-text-muted">
              The symbol may not be in the F&O universe or live data may be temporarily unavailable.
            </div>
          </div>
        </div>
      )}

      {data && <SimpleRecommendation data={data} hideAstrology={true} />}

      {/* F&O recommendation panel — calls /api/options/recommend/{sym} which
          orchestrates astro + technical + options engines into one verdict.
          Tier-gated to INTERMEDIATE+; the panel handles its own 402 / error
          states so it doesn't break this page when unavailable. */}
      {data && (
        <div className="pt-2">
          <div className="flex items-center gap-2 mb-2">
            <Zap className="w-4 h-4 text-accent-amber" />
            <h2 className="text-sm font-bold text-text-primary">
              F&amp;O recommendation
            </h2>
          </div>
          <FnoRecommendationPanel symbol={sym} />
        </div>
      )}

      <div className="text-[10px] text-text-muted text-center italic pt-4 border-t border-bg-line">
        Recommendation refreshes every 30 seconds while the page is open.
        Educational/analytical only — verify before placing real orders.
      </div>
    </div>
  );
}
