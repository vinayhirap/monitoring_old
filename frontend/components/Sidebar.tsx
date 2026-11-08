"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useState } from "react";
import {
  LayoutDashboard, Target, CalendarDays, Briefcase, Settings,
  Wrench, ChevronDown, ChevronRight,
  BookOpen, Compass, Hash, Sparkles, BarChart3,
  FlaskConical, Brain, Zap, ShieldAlert, LogOut, Activity, Filter,
  Coins, Gauge,
} from "lucide-react";
import clsx from "clsx";

type NavItem = {
  href: string;
  label: string;
  icon: any;
  badge?: string;
};

const PRIMARY: NavItem[] = [
  { href: "/",                 label: "Home",            icon: LayoutDashboard },
  { href: "/recommendations",  label: "Recommendations", icon: Target, badge: "TOP" },
  { href: "/commodities",      label: "Commodities",     icon: Coins, badge: "MCX" },
  { href: "/forecast",         label: "Forecast",        icon: CalendarDays },
  { href: "/portfolio",        label: "Portfolio",       icon: Briefcase },
];

const TOOLS: { title: string; items: NavItem[] }[] = [
  {
    title: "Trading",
    items: [
      { href: "/pipeline",      label: "Pipeline (advanced)", icon: Filter },
      { href: "/signals",       label: "Live Signals",        icon: Activity },
      { href: "/exit-analysis", label: "Exit Analysis",       icon: LogOut },
    ],
  },
  {
    title: "Validation",
    items: [
      { href: "/advanced",    label: "Multi-TF · Sectors",  icon: Zap },
      { href: "/backtest",    label: "Backtest",            icon: FlaskConical },
      { href: "/calibration", label: "Calibration Check",   icon: Gauge, badge: "TRUTH" },
      { href: "/ml",          label: "ML Model",            icon: Brain, badge: "AI" },
      { href: "/risk",        label: "Risk",                icon: ShieldAlert },
    ],
  },
  {
    title: "Engines",
    items: [
      { href: "/vedic-timing",   label: "Vedic Timing",  icon: Sparkles },
      { href: "/astro-lab",      label: "Astro Lab",     icon: Sparkles, badge: "EXP" },
      { href: "/symbol-cycles",  label: "Symbol Cycles", icon: Hash },
      { href: "/gann",           label: "Gann",          icon: Compass },
      { href: "/options",        label: "Options F&O",   icon: BarChart3 },
    ],
  },
];

const FOOTER: NavItem[] = [
  { href: "/methodology", label: "Methodology", icon: BookOpen },
  { href: "/settings",    label: "Settings",    icon: Settings },
];


export function Sidebar() {
  const path = usePathname();
  const [toolsOpen, setToolsOpen] = useState(
    // auto-open if user is on a tool page
    TOOLS.some((g) => g.items.some((i) => path === i.href || path?.startsWith(i.href + "/")))
  );

  return (
    <aside className="w-56 shrink-0 bg-bg-surface border-r border-bg-line flex flex-col">

      {/* Brand */}
      <div className="p-4 border-b border-bg-line">
        <div className="flex items-center gap-2.5">
          <div className="w-9 h-9 rounded-lg bg-gradient-to-br from-accent-amber to-accent-gold
                          flex items-center justify-center text-black font-bold text-sm shadow-glow">
            AP
          </div>
          <div>
            <div className="font-bold text-text-primary text-[14px] leading-none tracking-wide">MarketLens</div>
            <div className="text-[9px] text-text-muted mt-1 uppercase tracking-wider">Multi-Analyzer Terminal</div>
          </div>
        </div>
      </div>

      {/* Nav */}
      <nav className="flex-1 px-2 py-3 overflow-y-auto">

        {/* Primary actions */}
        <div className="space-y-px">
          {PRIMARY.map((item) => <NavLink key={item.href} item={item} path={path} />)}
        </div>

        {/* Tools — collapsible group */}
        <div className="mt-3">
          <button onClick={() => setToolsOpen(!toolsOpen)}
            className="w-full flex items-center gap-2 px-3 py-1.5 rounded text-[12px]
                        text-text-secondary hover:bg-bg-panel hover:text-text-primary transition-colors">
            {toolsOpen
              ? <ChevronDown className="w-3.5 h-3.5" />
              : <ChevronRight className="w-3.5 h-3.5" />}
            <Wrench className="w-3.5 h-3.5" />
            <span className="flex-1 text-left font-semibold">Tools</span>
            <span className="text-[9px] text-text-muted">
              {TOOLS.reduce((n, g) => n + g.items.length, 0)}
            </span>
          </button>

          {toolsOpen && (
            <div className="mt-1 ml-2 pl-3 border-l border-bg-line space-y-3">
              {TOOLS.map((group) => (
                <div key={group.title}>
                  <div className="px-2 mb-1 text-[9px] uppercase text-text-muted/70 tracking-wider font-semibold">
                    {group.title}
                  </div>
                  <div className="space-y-px">
                    {group.items.map((item) => (
                      <NavLink key={item.href} item={item} path={path} size="sm" />
                    ))}
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>

        {/* Footer nav */}
        <div className="mt-4 pt-3 border-t border-bg-line space-y-px">
          {FOOTER.map((item) => <NavLink key={item.href} item={item} path={path} />)}
        </div>
      </nav>

      {/* Footer disclaimer */}
      <div className="p-3 border-t border-bg-line text-[9.5px] text-text-muted leading-snug">
        <div className="font-semibold text-text-secondary mb-0.5">Educational use only</div>
        Cyclical layers are confluence enhancements, not standalone signals.
      </div>
    </aside>
  );
}


function NavLink({ item, path, size = "md" }:
                  { item: NavItem; path: string | null; size?: "md" | "sm" }) {
  const { href, label, icon: Icon, badge } = item;
  const active = path === href || (href !== "/" && path?.startsWith(href + "/"));
  return (
    <Link
      href={href}
      className={clsx(
        "flex items-center gap-2.5 rounded transition-all duration-150",
        size === "sm" ? "px-2 py-1 text-[11.5px]" : "px-3 py-1.5 text-[12.5px]",
        active
          ? "bg-gradient-to-r from-accent-amber/15 to-transparent text-accent-amber border-l-2 border-accent-amber font-semibold"
          : "text-text-secondary hover:bg-bg-panel hover:text-text-primary border-l-2 border-transparent",
      )}
    >
      <Icon className={clsx("w-3.5 h-3.5 shrink-0", active && "text-accent-amber")} />
      <span className="flex-1">{label}</span>
      {badge && (
        <span className="text-[8px] px-1.5 py-0.5 rounded bg-accent-amber/20 text-accent-amber font-bold tracking-wider">
          {badge}
        </span>
      )}
    </Link>
  );
}
