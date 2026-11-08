"use client";

import { Moon, Sun } from "lucide-react";
import { useTheme } from "@/components/ThemeProvider";
import clsx from "clsx";


/**
 * Compact theme toggle button — fits in the header. Use in both admin
 * Header and PortalLayout.
 */
export function ThemeToggle({ className }: { className?: string }) {
  const { theme, toggle } = useTheme();
  return (
    <button onClick={toggle}
      aria-label={`Switch to ${theme === "light" ? "dark" : "light"} theme`}
      title={`Switch to ${theme === "light" ? "dark" : "light"} theme`}
      className={clsx(
        "p-1.5 rounded border border-bg-line bg-bg-panel hover:border-accent-amber hover:text-accent-amber transition-colors",
        className,
      )}>
      {theme === "light"
        ? <Moon  className="w-3.5 h-3.5" />
        : <Sun   className="w-3.5 h-3.5" />}
    </button>
  );
}
