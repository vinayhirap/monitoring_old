"use client";

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { Home, TrendingUp, Target, Coins, User as UserIcon, LogOut, ShieldCheck, Activity, Menu, X, History, Calendar, BarChart3, Wallet, Clock, Grid3x3, Zap, Briefcase } from "lucide-react";
import { getUser, clearSession, isAdmin } from "@/lib/auth";
import { ThemeToggle } from "@/components/ThemeToggle";
import { LanguageToggle } from "@/components/LanguageToggle";
import { LiveMarketTicker } from "@/components/LiveMarketTicker";
import { ErrorBoundary } from "@/components/ErrorBoundary";
import { AIStatusChip } from "@/components/AIStatusChip";
import { useT, type I18nKey } from "@/lib/i18n";
import clsx from "clsx";


// Nav entries reference i18n KEYS (not literal strings) so the labels
// re-render when the language toggle fires. The render path resolves
// each key with `t()` inside the component below.
const NAV: { href: string; labelKey: I18nKey; icon: any }[] = [
  { href: "/portal",                 labelKey: "nav.home",          icon: Home },
  { href: "/portal/recommendations", labelKey: "nav.picks",         icon: Target },
  { href: "/portal/astro-fno",       labelKey: "nav.intraday_fno",  icon: Zap },
  { href: "/portal/sectors",         labelKey: "nav.sectors",       icon: Grid3x3 },
  { href: "/portal/positions",       labelKey: "nav.positions",     icon: Wallet },
  { href: "/portal/holdings",        labelKey: "nav.holdings",      icon: Briefcase },
  { href: "/portal/orders",          labelKey: "nav.orders",        icon: Clock },
  { href: "/portal/options",         labelKey: "nav.fno",           icon: TrendingUp },
  { href: "/portal/commodities",     labelKey: "nav.commodities",   icon: Coins },
  { href: "/portal/forecast/NIFTY",  labelKey: "nav.forecast",     icon: Calendar },
  { href: "/portal/performance",     labelKey: "nav.track_record", icon: BarChart3 },
  { href: "/portal/history",         labelKey: "nav.history",      icon: History },
];


export function PortalLayout({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();
  const router = useRouter();
  const [user, setUser] = useState<ReturnType<typeof getUser>>(null);
  const [mobileOpen, setMobileOpen] = useState(false);
  const t = useT();

  useEffect(() => { setUser(getUser()); }, []);

  function logout() {
    clearSession();
    router.replace("/login");
  }

  return (
    <div className="min-h-screen bg-bg-base flex flex-col">
      {/* Header */}
      <header className="bg-bg-surface border-b border-bg-line sticky top-0 z-30 shadow-card">
        <div className="max-w-6xl mx-auto px-4 sm:px-6 h-14 flex items-center justify-between">
          {/* Logo */}
          <Link href="/portal" className="flex items-center gap-2 text-accent-amber">
            <Activity className="w-6 h-6" />
            <span className="font-bold text-base tracking-wider">MARKETLENS</span>
          </Link>

          {/* Desktop nav */}
          <nav className="hidden md:flex items-center gap-1">
            {NAV.map((item) => {
              const active = pathname === item.href ||
                              (item.href !== "/portal" && pathname.startsWith(item.href));
              const Icon = item.icon;
              return (
                <Link key={item.href} href={item.href}
                  className={clsx(
                    "px-3 py-1.5 rounded text-[12px] font-semibold flex items-center gap-1.5 transition-colors",
                    active
                      ? "bg-accent-amber/10 text-accent-amber"
                      : "text-text-secondary hover:bg-bg-panel hover:text-text-primary"
                  )}>
                  <Icon className="w-3.5 h-3.5" />
                  {t(item.labelKey)}
                </Link>
              );
            })}
          </nav>

          {/* Right cluster — kept minimal. Admin link ONLY appears for
              true admin roles (OWNER/ADMIN/ANALYST), never for plain USERs.
              Hidden until user state is loaded to avoid flash of admin chrome. */}
          <div className="flex items-center gap-2">
            <AIStatusChip />
            <LanguageToggle />
            <ThemeToggle />
            {user !== null && isAdmin(user) && (
              <Link href="/admin/users"
                    className="hidden sm:flex items-center gap-1 text-[10px] uppercase font-bold text-accent-amber border border-accent-amber/40 rounded px-2 py-1 hover:bg-accent-amber/10"
                    title="Open admin console (admins only)">
                <ShieldCheck className="w-3 h-3" />
                Admin
              </Link>
            )}
            <Link href="/portal/profile"
                  className="hidden md:flex items-center gap-1.5 text-[11px] text-text-secondary hover:text-text-primary">
              <UserIcon className="w-3.5 h-3.5" />
              {user?.full_name || user?.email?.split("@")[0] || "Account"}
            </Link>
            <button onClick={logout}
                    className="hidden md:flex items-center gap-1 text-[11px] text-text-muted hover:text-accent-red"
                    title="Sign out">
              <LogOut className="w-3.5 h-3.5" />
            </button>
            {/* Mobile hamburger */}
            <button onClick={() => setMobileOpen(!mobileOpen)}
                    className="md:hidden text-text-secondary p-1">
              {mobileOpen ? <X className="w-5 h-5" /> : <Menu className="w-5 h-5" />}
            </button>
          </div>
        </div>

        {/* Mobile menu */}
        {mobileOpen && (
          <div className="md:hidden border-t border-bg-line bg-bg-surface">
            <nav className="px-4 py-2 space-y-0.5">
              {NAV.map((item) => {
                const active = pathname === item.href ||
                                (item.href !== "/portal" && pathname.startsWith(item.href));
                const Icon = item.icon;
                return (
                  <Link key={item.href} href={item.href}
                    onClick={() => setMobileOpen(false)}
                    className={clsx(
                      "flex items-center gap-2 px-3 py-2 rounded text-sm",
                      active
                        ? "bg-accent-amber/10 text-accent-amber"
                        : "text-text-secondary hover:bg-bg-panel"
                    )}>
                    <Icon className="w-4 h-4" />
                    {t(item.labelKey)}
                  </Link>
                );
              })}
              <Link href="/portal/profile" onClick={() => setMobileOpen(false)}
                className="flex items-center gap-2 px-3 py-2 rounded text-sm text-text-secondary hover:bg-bg-panel">
                <UserIcon className="w-4 h-4" /> {t("nav.account")}
              </Link>
              {user !== null && isAdmin(user) && (
                <Link href="/admin/users" onClick={() => setMobileOpen(false)}
                  className="flex items-center gap-2 px-3 py-2 rounded text-sm text-accent-amber hover:bg-accent-amber/10">
                  <ShieldCheck className="w-4 h-4" /> {t("nav.admin")}
                </Link>
              )}
              <button onClick={logout}
                className="w-full flex items-center gap-2 px-3 py-2 rounded text-sm text-accent-red hover:bg-accent-red/10">
                <LogOut className="w-4 h-4" /> {t("nav.sign_out")}
              </button>
            </nav>
          </div>
        )}
      </header>

      {/* Live index ticker — visible on every portal page.
          Wrapped in its own boundary so a ticker bug doesn't break the page. */}
      <ErrorBoundary scope="Market ticker"
                       fallback={() => <div className="h-1" />}>
        <LiveMarketTicker />
      </ErrorBoundary>

      {/* Main content — wrapped so a page render crash shows a fallback,
          NOT a white screen. Nav + ticker stay usable. */}
      <main className="flex-1 max-w-6xl mx-auto w-full px-4 sm:px-6 py-6">
        <ErrorBoundary scope="Page">
          {children}
        </ErrorBoundary>
      </main>

      {/* Footer */}
      <footer className="border-t border-bg-line bg-bg-surface mt-12">
        <div className="max-w-6xl mx-auto px-4 py-4 text-[10px] text-text-muted text-center">
          MarketLens · Educational platform · Not SEBI-registered financial advice
          <br className="sm:hidden" />
          <span className="hidden sm:inline"> · </span>
          Verify every recommendation before risking capital
        </div>
      </footer>
    </div>
  );
}
