"use client";

import { usePathname } from "next/navigation";
import { Sidebar } from "@/components/Sidebar";
import { Header } from "@/components/Header";
import { HealthBanner } from "@/components/HealthBanner";
import { PortalLayout } from "@/components/PortalLayout";

const FULL_BLEED = ["/login", "/signup"];
const PORTAL_PREFIX = "/portal";

/**
 * Routing for chrome:
 *   • /login, /signup           → full bleed
 *   • /portal/*                 → clean PortalLayout (consumer-facing)
 *   • everything else           → admin chrome (sidebar + header)
 */
export function LayoutShell({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();
  if (FULL_BLEED.some((p) => pathname.startsWith(p))) {
    return <>{children}</>;
  }
  if (pathname === PORTAL_PREFIX || pathname.startsWith(PORTAL_PREFIX + "/")) {
    return <PortalLayout>{children}</PortalLayout>;
  }
  return (
    <div className="flex h-screen overflow-hidden">
      <Sidebar />
      <div className="flex-1 flex flex-col overflow-hidden">
        <HealthBanner />
        <Header />
        <main className="flex-1 overflow-auto p-4 bg-bg-base">{children}</main>
      </div>
    </div>
  );
}
