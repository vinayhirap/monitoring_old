"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import useSWR from "swr";
import { authedFetcher as fetcher, ApiError } from "@/lib/auth";
import { UpgradeRequired } from "@/components/UpgradeRequired";
import { Star, TrendingUp, TrendingDown, ArrowRight, Target } from "lucide-react";
import clsx from "clsx";


export default function PortalOptionsPage() {
  const router = useRouter();
  const [horizon, setHorizon] = useState<"INTRADAY" | "SWING">("SWING");

  const { data, error, isLoading } = useSWR<any>(
    `/api/portal/top-picks?horizon=${horizon}&min_stars=3&top_n=10`,
    fetcher,
    { refreshInterval: 300_000, shouldRetryOnError: false }
  );

  // FREE/BASIC users hit 402 when selecting INTRADAY (only INTERMEDIATE+
  // allows non-SWING horizons). Show the upgrade card inline.
  const isPaywall = error instanceof ApiError && error.status === 402;

  return (
    <div className="space-y-4">
      <div className="bg-bg-surface border border-bg-line rounded-lg p-4">
        <h1 className="text-xl font-bold text-text-primary mb-2">F&O Recommendations</h1>
        <p className="text-[12px] text-text-muted">
          Picks with options strategy and best strike. Click any symbol to see the full trade plan
          including greeks, breakeven, and entry/exit triggers.
        </p>
        <div className="flex gap-1 bg-bg-base rounded p-0.5 mt-3 w-fit">
          {(["INTRADAY", "SWING"] as const).map((h) => (
            <button key={h} onClick={() => setHorizon(h)}
              className={clsx("text-[11px] px-3 py-1 rounded font-semibold uppercase",
                horizon === h ? "bg-accent-amber text-white"
                              : "text-text-secondary hover:text-text-primary")}>
              {h}
            </button>
          ))}
        </div>
      </div>

      {isPaywall && <UpgradeRequired error={error} />}

      {isLoading && !data && !isPaywall && (
        <div className="text-text-muted text-center py-12">Scanning F&O universe…</div>
      )}

      {!isPaywall && (
        <div className="space-y-3">
          {[...(data?.top_buy || []), ...(data?.top_sell || [])]
            .filter((p) => p.best_instrument === "OPTIONS" || p.best_instrument === "FUTURES")
            .map((p) => (
              <FnoCard key={p.symbol} pick={p}
                onClick={() => router.push(`/portal/symbol/${p.symbol}`)} />
            ))}
        </div>
      )}

      {data &&
        [...(data.top_buy || []), ...(data.top_sell || [])]
          .filter((p) => p.best_instrument === "OPTIONS" || p.best_instrument === "FUTURES")
          .length === 0 &&
        !isLoading && (
          <div className="text-center text-text-muted py-12 bg-bg-surface border border-bg-line rounded-lg">
            No high-conviction F&O picks right now. Check back later or browse{" "}
            <button onClick={() => router.push("/portal/recommendations")}
              className="text-accent-amber hover:underline">all recommendations</button>.
          </div>
        )}
    </div>
  );
}


function FnoCard({ pick, onClick }: { pick: any; onClick: () => void }) {
  const direction = pick.direction === "BULLISH" ? "BUY" : "SELL";
  const Icon = direction === "BUY" ? TrendingUp : TrendingDown;
  const dColor = direction === "BUY" ? "text-accent-green" : "text-accent-red";

  return (
    <button onClick={onClick}
      className="w-full text-left bg-bg-surface border border-bg-line rounded-lg p-4 hover:border-accent-amber transition-all hover:shadow-cardHover group">
      <div className="flex items-center justify-between flex-wrap gap-3">
        <div className="flex items-center gap-3">
          <div className={clsx("p-2 rounded-full",
            direction === "BUY" ? "bg-accent-green/10" : "bg-accent-red/10")}>
            <Icon className={clsx("w-5 h-5", dColor)} />
          </div>
          <div>
            <div className="font-bold text-lg text-text-primary">{pick.symbol}</div>
            <div className="text-[11px] text-text-muted">
              {pick.sector} · <span className={dColor}>{direction}</span>
            </div>
          </div>
        </div>

        <div className="flex items-center gap-4">
          <div className="text-right">
            <div className="text-[9px] text-text-muted uppercase tracking-wider">Strategy</div>
            <div className="text-sm font-bold text-accent-amber">
              {(pick.best_subtype || pick.best_instrument || "").replace(/_/g, " ")}
            </div>
          </div>

          <div className="text-right">
            <div className="text-[9px] text-text-muted uppercase tracking-wider">Confidence</div>
            <div className="flex items-center gap-1">
              <div className="text-base font-bold tabular text-accent-amber">
                {Math.round(pick.confidence || 0)}%
              </div>
              <div className="flex">
                {Array.from({ length: 5 }).map((_, i) => (
                  <Star key={i} className={clsx("w-2.5 h-2.5",
                    i < (pick.stars || 0)
                      ? "fill-accent-amber text-accent-amber"
                      : "text-text-muted/30")} />
                ))}
              </div>
            </div>
          </div>

          <ArrowRight className="w-4 h-4 text-text-muted group-hover:text-accent-amber" />
        </div>
      </div>

      <div className="mt-3 grid grid-cols-5 gap-2 text-[10px] text-center bg-bg-base rounded p-2 border border-bg-line/50">
        <div>
          <div className="text-text-muted">Entry</div>
          <div className="font-bold tabular">₹{pick.entry?.toFixed(2)}</div>
        </div>
        <div>
          <div className="text-accent-red">SL</div>
          <div className="font-bold tabular text-accent-red">₹{pick.stoploss?.toFixed(2)}</div>
        </div>
        {(pick.targets || []).slice(0, 3).map((t: number, i: number) => (
          <div key={i}>
            <div className="text-accent-green">T{i + 1}</div>
            <div className="font-bold tabular text-accent-green">₹{t.toFixed(2)}</div>
          </div>
        ))}
      </div>
    </button>
  );
}
