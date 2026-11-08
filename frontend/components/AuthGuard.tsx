"use client";

import { useEffect, useState } from "react";
import { usePathname, useRouter } from "next/navigation";
import { isAuthenticated, getUser } from "@/lib/auth";

const PUBLIC_PATHS = ["/login", "/signup"];

// Paths admins can access. Anything else (or under /portal/) is for everyone.
// Non-admins hitting an admin path get redirected to /portal.
const ADMIN_PATH_PREFIXES = [
  "/admin",
  "/calibration",
  "/backtest",
  "/ml",
  "/pipeline",
  "/risk",
  "/advanced",
  "/methodology",
  "/settings",   // broker creds etc — admin only
];

function isAdminPath(pathname: string) {
  return ADMIN_PATH_PREFIXES.some((p) => pathname === p || pathname.startsWith(p + "/"));
}

/**
 * Auth + role-based routing:
 *  - Not authenticated → /login (unless on a public path)
 *  - Authenticated non-admin on admin path → /portal
 *  - Authenticated user on / → /portal (their home) for non-admins
 */
export function AuthGuard({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();
  const router = useRouter();
  const [checked, setChecked] = useState(false);

  useEffect(() => {
    const isPublic = PUBLIC_PATHS.includes(pathname);
    if (isPublic) {
      setChecked(true);
      return;
    }
    if (!isAuthenticated()) {
      router.replace(`/login?next=${encodeURIComponent(pathname)}`);
      return;
    }
    const user = getUser();
    if (user && !user.is_superuser) {
      // Non-admin tried admin-only path → push to portal
      if (isAdminPath(pathname)) {
        router.replace("/portal");
        return;
      }
      // Non-admin landed on admin home → push to portal
      if (pathname === "/") {
        router.replace("/portal");
        return;
      }
    }
    setChecked(true);
  }, [pathname, router]);

  if (!checked) {
    if (PUBLIC_PATHS.includes(pathname)) return <>{children}</>;
    return (
      <div className="flex items-center justify-center h-screen text-text-muted text-sm">
        Loading…
      </div>
    );
  }
  return <>{children}</>;
}
