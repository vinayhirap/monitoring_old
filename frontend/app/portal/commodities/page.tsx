"use client";

import useSWR from "swr";
import { useRouter } from "next/navigation";
import { authedFetcher as fetcher, ApiError } from "@/lib/auth";
import { UpgradeRequired } from "@/components/UpgradeRequired";
import { Coins, Flame, ArrowRight, Star } from "lucide-react";
import clsx from "clsx";


export default function PortalCommoditiesPage() {
  const router = useRouter();
  const { data, error, isLoading } = useSWR<any>("/api/commodities/scan", fetcher,
    { refreshInterval: 300_000, shouldRetryOnError: false });

  // FREE / BASIC users will hit a 402 here (gated to INTERMEDIATE+).
  // Surface the paywall card instead of a generic error.
  if (error instanceof ApiError && error.status === 402) {
    return (
      <div className="space-y-4">
        <div className="bg-bg-surface border border-bg-line rounded-lg p-4">
          <h1 className="text-xl font-bold text-text-primary mb-1">Commodities</h1>
          <p className="text-[12px] text-text-muted">
            GOLD, SILVER, CRUDE OIL, NATURAL GAS, COPPER and more — analyzed with technical + Mundane astrology.
          </p>
        </div>
        <UpgradeRequired error={error} />
      </div>
    );
  }

  return (
    <div className="space-y-4">
      <div className="bg-bg-surface border border-bg-line rounded-lg p-4">
        <h1 className="text-xl font-bold text-text-primary mb-1">Commodities</h1>
        <p className="text-[12px] text-text-muted">
          GOLD, SILVER, CRUDE OIL, NATURAL GAS, COPPER and more — analyzed with technical + Mundane astrology.
        </p>
      </div>

      {isLoading && !data && (
        <div className="text-text-muted text-center py-12">Scanning commodities…</div>
      )}

      {error && !(error instanceof ApiError && error.status === 402) && (
        <div className="bg-accent-red/10 border border-accent-red/30 rounded p-3 text-[12px] text-accent-red">
          Failed to load commodities. {error?.message || String(error)}
        </div>
      )}

      {data && (
        <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
          {[...(data.top_buy || []), ...(data.top_sell || [])].map((c: any) => (
            <CommodityCard key={c.symbol} c={c}
              onClick={() => router.push(`/portal/symbol/${c.symbol}`)} />
          ))}
        </div>
      )}

      {data?.disclaimer && (
        <div className="text-[10px] text-text-muted italic text-center pt-4">
          {data.disclaimer}
        </div>
      )}
    </div>
  );
}


function CommodityCard({ c, onClick }: { c: any; onClick: () => void }) {
  const dColor = c.direction === "BULLISH" ? "text-accent-green" :
                  c.direction === "BEARISH" ? "text-accent-red" : "text-text-muted";
  const dBg = c.direction === "BULLISH" ? "bg-accent-green/10" :
              c.direction === "BEARISH" ? "bg-accent-red/10" : "bg-bg-base";

  const isEnergy = c.category?.includes("Energy");
  const Icon = isEnergy ? Flame : Coins;

  return (
    <button onClick={onClick}
      className="text-left bg-bg-surface border border-bg-line rounded-lg p-4 hover:border-accent-amber transition-all hover:shadow-cardHover group w-full">
      <div className="flex items-start gap-3">
        <div className={clsx("p-2 rounded-lg", dBg)}>
          <Icon className={clsx("w-5 h-5", dColor)} />
        </div>
        <div className="flex-1 min-w-0">
          <div className="font-bold text-base text-text-primary">{c.display}</div>
          <div className="text-[10px] text-text-muted uppercase tracking-wider">
            {c.category} · ruled by {c.ruling_planet}
          </div>
          {c.top_astro_reason && (
            <div className="text-[10px] text-text-muted mt-1 italic line-clamp-2">
              {c.top_astro_reason}
            </div>
          )}
        </div>
        <div className="text-right">
          <div className={clsx("text-[10px] font-bold uppercase", dColor)}>
            {c.direction}
          </div>
          <div className="text-lg font-bold tabular text-accent-amber">
            {Math.round(c.confidence)}%
          </div>
          <ArrowRight className="w-4 h-4 text-text-muted group-hover:text-accent-amber ml-auto mt-1" />
        </div>
      </div>
    </button>
  );
}
