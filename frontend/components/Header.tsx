"use client";

import { useEffect, useState } from "react";
import useSWR from "swr";
import { Activity, Moon, Wifi, WifiOff, Clock, User as UserIcon, LogOut, ShieldCheck } from "lucide-react";
import { fetcher } from "@/lib/api";
import { ChangeBadge, PulseBadge, AnimatedNumber } from "@/components/animated";
import { SymbolSearch } from "@/components/SymbolSearch";
import { ThemeToggle } from "@/components/ThemeToggle";
import { getUser, clearSession } from "@/lib/auth";
import { useRouter } from "next/navigation";
import Link from "next/link";
import clsx from "clsx";


function UserMenu() {
  const router = useRouter();
  const [user, setUser] = useState<ReturnType<typeof getUser>>(null);
  const [open, setOpen] = useState(false);

  useEffect(() => { setUser(getUser()); }, []);
  if (!user) return null;

  function logout() {
    clearSession();
    router.replace("/login");
  }

  return (
    <div className="relative">
      <button onClick={() => setOpen(!open)}
              className="flex items-center gap-1.5 px-2 py-1 rounded bg-bg-panel border border-bg-line hover:border-accent-amber">
        <UserIcon className="w-3.5 h-3.5 text-accent-amber" />
        <span className="text-[10px] uppercase font-bold text-text-primary truncate max-w-[120px]">
          {user.full_name || user.email}
        </span>
        {user.is_superuser && (
          <ShieldCheck className="w-3 h-3 text-accent-amber" />
        )}
      </button>
      {open && (
        <div className="absolute right-0 top-full mt-1 w-52 bg-bg-surface border border-bg-line rounded shadow-cardHover z-50 text-[11px]">
          <div className="px-3 py-2 border-b border-bg-line">
            <div className="text-text-primary font-semibold truncate">{user.full_name || "—"}</div>
            <div className="text-text-muted truncate">{user.email}</div>
            <div className="text-[9px] uppercase text-accent-amber mt-0.5">
              {user.is_superuser ? "Admin" : "User"}
            </div>
          </div>
          {user.is_superuser && (
            <Link href="/admin/users" onClick={() => setOpen(false)}
                   className="block px-3 py-2 text-text-secondary hover:bg-bg-panel border-b border-bg-line">
              Manage users
            </Link>
          )}
          <button onClick={logout}
                  className="w-full text-left px-3 py-2 text-accent-red hover:bg-accent-red/5 flex items-center gap-2">
            <LogOut className="w-3 h-3" /> Sign out
          </button>
        </div>
      )}
    </div>
  );
}

// Client-only clock — avoids SSR/CSR hydration mismatch
function useClientClock(refreshMs = 30_000): string {
  const [now, setNow] = useState<string>("");
  useEffect(() => {
    const tick = () => setNow(
      new Date().toLocaleString("en-IN", { dateStyle: "medium", timeStyle: "short" })
    );
    tick();
    const id = setInterval(tick, refreshMs);
    return () => clearInterval(id);
  }, [refreshMs]);
  return now;
}

export function Header() {
  const clock = useClientClock();
  const { data: status } = useSWR<any>("/api/broker/status", fetcher, { refreshInterval: 30_000 });
  const { data: phase } = useSWR<any>("/api/astrology/moon-phase", fetcher, { refreshInterval: 60_000 });
  const { data: hora } = useSWR<any>("/api/hora/current", fetcher, { refreshInterval: 60_000 });
  const { data: indices } = useSWR<{ indices: any[] }>("/api/market/indices", fetcher, { refreshInterval: 5_000 });
  const { data: lunar } = useSWR<any>("/api/moon/reading", fetcher, { refreshInterval: 300_000 });

  const live = status?.authenticated && !status?.paper_mode;

  return (
    <header className="border-b border-bg-line bg-bg-surface flex flex-col text-xs">

      {/* ─────── Top row: indices ticker ─────── */}
      {indices?.indices && (
        <div className="flex items-center gap-6 px-4 py-1.5 bg-bg-base/80 border-b border-bg-line overflow-x-auto">
          {indices.indices.map((ix: any) =>
            ix.error ? (
              <span key={ix.symbol} className="text-text-muted text-[10px] shrink-0" title={ix.error}>
                {ix.display}: —
              </span>
            ) : (
              <div key={ix.symbol} className="flex items-center gap-2 shrink-0">
                <span className="text-text-muted uppercase text-[10px] tracking-wider font-semibold">
                  {ix.display}
                </span>
                <AnimatedNumber value={ix.price || 0} decimals={2}
                  className="text-text-primary font-semibold tabular text-[12px]" />
                <ChangeBadge value={ix.change ?? 0} pct={ix.change_pct ?? 0} />
                {ix.is_live === true ? (
                  <span className="text-accent-green text-[9px] uppercase font-bold tracking-wider">● live</span>
                ) : (
                  <span className="text-accent-amber text-[9px] uppercase font-semibold">paper</span>
                )}
              </div>
            )
          )}
        </div>
      )}

      {/* ─────── Main row: logo + global search + status pills ─────── */}
      <div className="flex items-center px-4 gap-4 h-12">
        <div className="flex items-center gap-2 text-accent-amber font-bold tracking-wider text-[13px]">
          <Activity className="w-4 h-4" />
          MARKETLENS
        </div>

        <SymbolSearch className="w-80 max-w-xs ml-2" />

        <div className="ml-auto flex items-center gap-3">
          {/* Broker status */}
          {live ? (
            <div className="flex items-center gap-1.5 px-2 py-1 rounded
                            bg-accent-green/10 border border-accent-green/30 text-accent-green">
              <Wifi className="w-3.5 h-3.5" />
              <span className="text-[10px] uppercase font-bold tracking-wider">Live</span>
              <span className="text-[10px] text-text-secondary">Angel One</span>
            </div>
          ) : (
            <div className="flex items-center gap-1.5 px-2 py-1 rounded
                            bg-accent-amber/10 border border-accent-amber/30 text-accent-amber">
              <WifiOff className="w-3.5 h-3.5" />
              <span className="text-[10px] uppercase font-bold tracking-wider">Paper</span>
            </div>
          )}

          {/* Clock */}
          <div className="text-[11px] text-text-secondary tabular hidden md:block"
                suppressHydrationWarning>
            {clock || "—"}
          </div>

          {/* Theme toggle */}
          <ThemeToggle />

          {/* User dropdown */}
          <UserMenu />
        </div>
      </div>

      {/* ─────── Cyclical / timing strip ─────── */}
      <div className="flex items-center px-4 gap-3 h-9 bg-bg-base/40 border-t border-bg-line/60 overflow-x-auto">
        <div className="text-[9px] text-text-muted uppercase tracking-wider font-semibold shrink-0">Timing</div>

        {hora && (
          <div className="flex items-center gap-1.5 shrink-0">
            <Clock className="w-3 h-3 text-text-muted" />
            <span className="text-text-muted text-[10px] uppercase">Hora</span>
            <span className={clsx("text-[11px] font-bold",
              hora.bias === "bullish" ? "text-accent-green"
              : hora.bias === "bearish" ? "text-accent-red"
              : "text-text-secondary")}>
              {hora.ruler}
            </span>
            <span className={clsx("text-[9px] uppercase px-1 py-0.5 rounded font-semibold",
              hora.bias === "bullish" ? "bg-accent-green/15 text-accent-green"
              : hora.bias === "bearish" ? "bg-accent-red/15 text-accent-red"
              : "bg-bg-line text-text-secondary")}>
              {hora.bias}
            </span>
            <span className="text-text-muted text-[10px]">
              → {hora.next_ruler} {hora.next_change_in_minutes}m
            </span>
          </div>
        )}

        {phase && (
          <div className="flex items-center gap-1.5 shrink-0 border-l border-bg-line pl-3">
            <Moon className="w-3 h-3 text-text-muted" />
            <span className="text-text-secondary text-[11px]">{phase.phase}</span>
            <span className="text-text-muted text-[10px]">· {phase.paksha} · tithi {phase.tithi}</span>
          </div>
        )}

        {lunar && (
          <>
            {(lunar.gate === "AVOID" || lunar.gate === "WAIT") ? (
              <PulseBadge color="red"
                className="bg-accent-red/15 text-accent-red border border-accent-red/40">
                Gate: {lunar.gate}
              </PulseBadge>
            ) : (
              <span className={clsx("text-[9px] uppercase px-1.5 py-0.5 rounded border font-semibold",
                lunar.gate === "CAUTION" ? "border-accent-amber/40 text-accent-amber bg-accent-amber/10"
                : "border-accent-green/40 text-accent-green bg-accent-green/10")} title={lunar.summary}>
                Gate: {lunar.gate}
              </span>
            )}
            {lunar.is_void_of_course && (
              <PulseBadge color="red" className="bg-accent-red/20 text-accent-red font-bold">v/c</PulseBadge>
            )}
            {lunar.is_full_moon && (
              <PulseBadge color="violet" className="bg-accent-violet/20 text-accent-violet font-bold">full moon</PulseBadge>
            )}
            {lunar.eclipse_zone && (
              <PulseBadge color="red" className="bg-accent-red/20 text-accent-red font-bold">eclipse</PulseBadge>
            )}
          </>
        )}
      </div>
    </header>
  );
}
