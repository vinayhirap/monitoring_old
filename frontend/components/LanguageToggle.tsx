"use client";

/**
 * Language toggle — switches the user's explanation language between
 * English and Hindi. Persisted in localStorage so it survives page
 * reloads. Triggers a window event so SWR-using pages can refetch with
 * the new lang query param.
 *
 * Backend: the `lang` query param is read by /api/symbol/{ticker}. Other
 * portal endpoints don't need it yet (their copy is in the page itself,
 * not generated). When we add Hindi to those pages, this toggle becomes
 * the single source of truth.
 */

import { useEffect, useState } from "react";
import clsx from "clsx";

const STORAGE_KEY = "marketlens_lang";

export type AppLang = "en" | "hi";

export function getLang(): AppLang {
  if (typeof window === "undefined") return "en";
  const saved = localStorage.getItem(STORAGE_KEY);
  return saved === "hi" ? "hi" : "en";
}

export function setLang(lang: AppLang) {
  if (typeof window === "undefined") return;
  localStorage.setItem(STORAGE_KEY, lang);
  window.dispatchEvent(new CustomEvent("marketlens:lang-change", { detail: lang }));
}

export function LanguageToggle() {
  const [lang, setLangState] = useState<AppLang>("en");

  useEffect(() => {
    setLangState(getLang());
  }, []);

  const choose = (l: AppLang) => {
    setLangState(l);
    setLang(l);
  };

  return (
    <div className="flex items-center gap-0.5 text-[10px] font-bold tabular bg-bg-base rounded p-0.5"
          aria-label="Language switcher">
      <button onClick={() => choose("en")}
        className={clsx("px-1.5 py-0.5 rounded transition-colors",
          lang === "en" ? "bg-accent-amber text-white"
                          : "text-text-secondary hover:text-text-primary")}
        title="English">
        EN
      </button>
      <button onClick={() => choose("hi")}
        className={clsx("px-1.5 py-0.5 rounded transition-colors",
          lang === "hi" ? "bg-accent-amber text-white"
                          : "text-text-secondary hover:text-text-primary")}
        title="हिन्दी (Hindi)">
        हिं
      </button>
    </div>
  );
}
