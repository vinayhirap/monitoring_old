"use client";

import { createContext, useContext, useEffect, useState } from "react";

type Theme = "light" | "dark";

interface ThemeContextType {
  theme: Theme;
  toggle: () => void;
  setTheme: (t: Theme) => void;
}

const ThemeContext = createContext<ThemeContextType>({
  theme: "light",
  toggle: () => {},
  setTheme: () => {},
});

const STORAGE_KEY = "marketlens_theme";


/**
 * Adds/removes `.dark` on <html>. Persists to localStorage. Defaults to
 * the user's OS preference on first load.
 */
export function ThemeProvider({ children }: { children: React.ReactNode }) {
  const [theme, setThemeState] = useState<Theme>("light");

  // Load saved preference on mount
  useEffect(() => {
    if (typeof window === "undefined") return;
    const saved = localStorage.getItem(STORAGE_KEY) as Theme | null;
    const prefersDark = window.matchMedia?.("(prefers-color-scheme: dark)").matches;
    const initial: Theme = saved ?? (prefersDark ? "dark" : "light");
    applyTheme(initial);
    setThemeState(initial);
  }, []);

  function applyTheme(t: Theme) {
    if (typeof document === "undefined") return;
    const root = document.documentElement;
    // briefly disable transitions so theme switch is instant (no flash)
    root.classList.add("no-transition");
    if (t === "dark") root.classList.add("dark");
    else              root.classList.remove("dark");
    setTimeout(() => root.classList.remove("no-transition"), 50);
  }

  function setTheme(t: Theme) {
    setThemeState(t);
    applyTheme(t);
    localStorage.setItem(STORAGE_KEY, t);
  }

  function toggle() {
    setTheme(theme === "light" ? "dark" : "light");
  }

  return (
    <ThemeContext.Provider value={{ theme, toggle, setTheme }}>
      {children}
    </ThemeContext.Provider>
  );
}


export function useTheme() {
  return useContext(ThemeContext);
}
