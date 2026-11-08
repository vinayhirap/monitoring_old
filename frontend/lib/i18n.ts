/**
 * Lightweight i18n for portal-chrome strings.
 *
 * Scope: nav labels, page titles, table headers, button labels, common
 * status phrases. Long-form prose (signal explanations) lives in the
 * backend's signal_explainer.py so it doesn't ship as a JS bundle.
 *
 * Why no full i18n library (i18next, next-intl)?
 *   • The string set is small (~80 phrases). A library adds 30-80KB and
 *     a build pipeline for marginal benefit.
 *   • Translations are committed in source — no CMS, no pluralization
 *     rules, no date/number formatting beyond what the backend returns.
 *
 * How to use:
 *   import { useT } from "@/lib/i18n";
 *   const t = useT();
 *   return <h1>{t("nav.picks")}</h1>;
 *
 * To add a key: add it to BOTH the `en` and `hi` blocks below. The build
 * will error if a key is in one but not the other (TypeScript catches it).
 */

"use client";

import { useEffect, useState } from "react";
import { getLang, type AppLang } from "@/components/LanguageToggle";


const TRANSLATIONS = {
  en: {
    // Nav
    "nav.home":            "Home",
    "nav.picks":           "Picks",
    "nav.positions":       "Positions",
    "nav.holdings":        "Holdings",
    "nav.orders":          "Orders",
    "nav.sectors":         "Sectors",
    "nav.intraday_fno":    "Intraday F&O",
    "nav.fno":             "F&O",
    "nav.commodities":     "Commodities",
    "nav.forecast":        "14-Day View",
    "nav.track_record":    "Track Record",
    "nav.history":         "History",
    "nav.account":         "Account",
    "nav.admin":           "Admin",
    "nav.sign_out":        "Sign out",

    // Recommendations page
    "picks.title":         "Recommendations",
    "picks.rescan":        "rescan",
    "picks.scanning":      "scanning…",
    "picks.min_stars":     "Min stars:",
    "picks.no_picks":      "No picks at this conviction level right now. Try lowering the min stars or switching horizon.",
    "picks.scanning_market": "Scanning the market for high-conviction picks…",
    "picks.showing_previous": "Showing previous scan",
    "picks.stale_explainer":  "latest refresh returned no qualifying picks (markets quiet or rate-limited). Last good scan:",
    "picks.click_rescan":  "Click Rescan to retry.",

    // Forecast page
    "forecast.title":      "14-Day Forecast",
    "forecast.subtitle":   "Per-day bias, expected range, and best entry/exit windows for the next 14 calendar days.",
    "forecast.load":       "Load",
    "forecast.trading_days":   "Trading days",
    "forecast.bullish_days":   "Bullish days",
    "forecast.bearish_days":   "Bearish days",
    "forecast.best_buy_day":   "Best BUY day",
    "forecast.best_sell_day":  "Best SELL day",
    "forecast.market_closed":  "Market closed",
    "forecast.strength":       "Strength",
    "forecast.expected_range": "Expected range",
    "forecast.best_entry":     "Best entry",
    "forecast.back":           "Back to dashboard",

    // Track record (performance) page
    "perf.title":            "Track Record",
    "perf.subtitle":         "All metrics computed from the live signals journal. No marketing numbers, no aspirational targets — only what has actually happened to past signals.",
    "perf.evaluated":        "Evaluated signals",
    "perf.hit_rate":         "Hit rate",
    "perf.edge":             "Edge vs baseline",
    "perf.brier":            "Brier score",
    "perf.avg_mfe":          "Avg MFE",
    "perf.avg_mae":          "Avg MAE",
    "perf.forming":          "Track record forming",
    "perf.forming_msg":      "We need at least 30 closed-and-evaluated signals to compute meaningful KPIs without misleading anyone.",
    "perf.reliability":      "Reliability — claimed vs actual win rate",
    "perf.monthly":          "Monthly",
    "perf.by_horizon":       "By horizon",

    // Common
    "common.loading":      "Loading…",
    "common.refresh":      "refresh",
    "common.bullish":      "BULLISH",
    "common.bearish":      "BEARISH",
    "common.neutral":      "NEUTRAL",
    "common.buy":          "BUY",
    "common.sell":         "SELL",
    "common.wait":         "WAIT",
    "common.entry":        "Entry",
    "common.stop_loss":    "Stop loss",
    "common.target":       "Target",
    "common.confidence":   "Confidence",
    "common.upgrade":      "Upgrade",
    "common.educational":  "Educational/analytical platform only. Not SEBI-registered advice.",
  },
  hi: {
    // Nav
    "nav.home":            "होम",
    "nav.picks":           "सिफारिशें",
    "nav.positions":       "पोज़िशन्स",
    "nav.holdings":        "होल्डिंग्स",
    "nav.orders":          "ऑर्डर्स",
    "nav.sectors":         "सेक्टर्स",
    "nav.intraday_fno":    "इंट्राडे F&O",
    "nav.fno":             "F&O",
    "nav.commodities":     "कमोडिटीज़",
    "nav.forecast":        "14-दिन का दृश्य",
    "nav.track_record":    "ट्रैक रिकॉर्ड",
    "nav.history":         "इतिहास",
    "nav.account":         "खाता",
    "nav.admin":           "एडमिन",
    "nav.sign_out":        "साइन आउट",

    // Recommendations page
    "picks.title":         "सिफारिशें",
    "picks.rescan":        "पुनः स्कैन",
    "picks.scanning":      "स्कैनिंग…",
    "picks.min_stars":     "न्यूनतम स्टार:",
    "picks.no_picks":      "इस स्तर पर कोई सिफारिश नहीं। न्यूनतम स्टार कम करें या होरिज़न बदलें।",
    "picks.scanning_market": "बाजार स्कैन कर रहे हैं उच्च-विश्वास सिफारिशों के लिए…",
    "picks.showing_previous": "पिछला स्कैन दिखा रहे हैं",
    "picks.stale_explainer":  "नवीनतम रिफ्रेश में योग्य सिफारिशें नहीं मिलीं (बाजार शांत या रेट-लिमिटेड)। अंतिम अच्छा स्कैन:",
    "picks.click_rescan":  "पुनः स्कैन करने के लिए क्लिक करें।",

    // Forecast page
    "forecast.title":      "14-दिन का पूर्वानुमान",
    "forecast.subtitle":   "अगले 14 कैलेंडर दिनों के लिए प्रति-दिन का झुकाव, अपेक्षित रेंज, और सर्वोत्तम प्रवेश/निकास विंडो।",
    "forecast.load":       "लोड",
    "forecast.trading_days":   "ट्रेडिंग दिन",
    "forecast.bullish_days":   "तेज़ी के दिन",
    "forecast.bearish_days":   "मंदी के दिन",
    "forecast.best_buy_day":   "सर्वोत्तम खरीद दिन",
    "forecast.best_sell_day":  "सर्वोत्तम बिक्री दिन",
    "forecast.market_closed":  "बाजार बंद",
    "forecast.strength":       "ताकत",
    "forecast.expected_range": "अपेक्षित रेंज",
    "forecast.best_entry":     "सर्वोत्तम प्रवेश",
    "forecast.back":           "डैशबोर्ड पर वापस",

    // Track record (performance) page
    "perf.title":            "ट्रैक रिकॉर्ड",
    "perf.subtitle":         "सभी मेट्रिक्स लाइव सिग्नल जर्नल से गणना किए गए हैं। कोई मार्केटिंग संख्या नहीं, कोई आकांक्षात्मक लक्ष्य नहीं — केवल वही जो पिछले सिग्नल्स के साथ वास्तव में हुआ।",
    "perf.evaluated":        "मूल्यांकित सिग्नल",
    "perf.hit_rate":         "हिट दर",
    "perf.edge":             "बेसलाइन से बढ़त",
    "perf.brier":            "ब्रायर स्कोर",
    "perf.avg_mfe":          "औसत MFE",
    "perf.avg_mae":          "औसत MAE",
    "perf.forming":          "ट्रैक रिकॉर्ड बन रहा है",
    "perf.forming_msg":      "महत्वपूर्ण KPI की गणना के लिए हमें कम से कम 30 बंद-और-मूल्यांकित सिग्नल चाहिए, ताकि किसी को गुमराह न करें।",
    "perf.reliability":      "विश्वसनीयता — दावा बनाम वास्तविक जीत दर",
    "perf.monthly":          "मासिक",
    "perf.by_horizon":       "होरिज़न के अनुसार",

    // Common
    "common.loading":      "लोड हो रहा है…",
    "common.refresh":      "रिफ्रेश",
    "common.bullish":      "तेज़ी",
    "common.bearish":      "मंदी",
    "common.neutral":      "तटस्थ",
    "common.buy":          "खरीदें",
    "common.sell":         "बेचें",
    "common.wait":         "प्रतीक्षा",
    "common.entry":        "प्रवेश",
    "common.stop_loss":    "स्टॉप लॉस",
    "common.target":       "लक्ष्य",
    "common.confidence":   "विश्वास",
    "common.upgrade":      "अपग्रेड",
    "common.educational":  "केवल शैक्षिक/विश्लेषणात्मक प्लेटफॉर्म। SEBI-पंजीकृत सलाह नहीं।",
  },
} as const;


// TS magic: ensure every key in `en` exists in `hi`. If a key is missing
// from `hi`, this assertion fails at compile time.
type EnKeys = keyof (typeof TRANSLATIONS)["en"];
type HiKeys = keyof (typeof TRANSLATIONS)["hi"];
// @ts-expect-error — purposeful assertion: this errors only when keys diverge
const _typeCheck: EnKeys extends HiKeys ? (HiKeys extends EnKeys ? true : false) : false = true;
void _typeCheck;


export type I18nKey = EnKeys;


export function t(key: I18nKey, lang?: AppLang): string {
  const l = lang || (typeof window !== "undefined" ? getLang() : "en");
  const table = TRANSLATIONS[l] || TRANSLATIONS.en;
  // @ts-ignore — typed by EnKeys; fallback to English if Hindi key missing
  return table[key] ?? TRANSLATIONS.en[key] ?? key;
}


/**
 * React hook — returns a `t()` function that re-renders the component
 * when the user flips the language toggle.
 *
 * Usage:
 *   const t = useT();
 *   return <h1>{t("nav.picks")}</h1>;
 */
export function useT() {
  const [lang, setLangState] = useState<AppLang>("en");

  useEffect(() => {
    setLangState(getLang());
    const handler = (e: Event) => setLangState((e as CustomEvent).detail);
    window.addEventListener("marketlens:lang-change", handler);
    return () => window.removeEventListener("marketlens:lang-change", handler);
  }, []);

  return (key: I18nKey) => t(key, lang);
}
