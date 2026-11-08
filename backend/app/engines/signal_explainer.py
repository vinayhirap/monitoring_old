"""Signal explainer — generates fluent natural-language reasoning from
the structured recommendation payload.

Design philosophy:

A local LLM (Llama 3, Phi-3, Mistral via llama.cpp) WOULD produce more
fluent output, but at the cost of:
  • 2-5GB RAM permanently resident
  • 500ms - 2s per inference on CPU
  • Non-deterministic outputs (different runs → different prose)
  • Operational complexity (model files, version pinning, GGUF format)

For 90% of trading-explanation needs, a deterministic template-based
generator produces output that READS like an LLM but is:
  • Instant (microseconds)
  • Auditable (same inputs → same output)
  • Free (no token cost, no API key, no inference cost)
  • Reliable (no hallucination — only mentions what the data says)

This module is the result.

When you want a real LLM:
  • Drop in `llama_cpp_python` + a GGUF model (Phi-3-mini-Q4 is ~2GB).
  • Replace `explain()` body with a prompt to the model passing the
    structured data dict.
  • Keep this template-based version as a fallback for `LLAMA_DISABLED`
    environments.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional
import random


@dataclass
class Explanation:
    headline: str                          # 1-line summary
    body: list[str]                        # 2-4 sentences of reasoning
    cautions: list[str] = field(default_factory=list)
    confidence_phrase: str = ""            # "high conviction" / "moderate" / "low"

    def to_dict(self) -> dict:
        return self.__dict__


# ----------------------------------------------------------------------------
# Localization — per-language phrase tables
# ----------------------------------------------------------------------------
#
# Supported: "en" (English, default), "hi" (Hindi, Devanagari).
# To add a new language: extend _PHRASES and the per-sentence-builder
# language switches below. The public API (`explain()`) takes a `lang`
# kwarg; everything downstream just picks from the tables.

_PHRASES: dict[str, dict] = {
    "en": {
        "bullish_opener":  "Buyers are in control",
        "bearish_opener":  "Sellers are in control",
        "neutral_opener":  "Setup is balanced — no clear directional edge",
        "conf_high":       "high conviction",
        "conf_mod":        "moderate conviction",
        "conf_weak":       "weak conviction",
        "conf_noedge":     "no edge — system suggests WAIT",
        # Section labels
        "section_why":     "Why this signal",
        # Sentence templates (positional formatting)
        "tech_with_rsi":   "Technical: RSI at {rsi:.0f}, {reason}.",
        "tech_oversold":   "Technical: RSI is oversold, {reason}.",
        "tech_overbought": "Technical: RSI is overbought, {reason}.",
        "advanced_ta":     "Advanced TA confluence — {n}/3 sub-engines (VWAP, divergence, multi-timeframe) agree on {dir}.",
        "vwap_stretched_up":   "Price is stretched {dist:+.2f}% above VWAP — mean-reversion candidate.",
        "vwap_stretched_down": "Price is stretched {dist:.2f}% below VWAP — oversold bounce candidate.",
        "vwap_holding_up":   "Price holding above VWAP ({dist:+.2f}%) — buyers in control.",
        "vwap_holding_down": "Price holding below VWAP ({dist:.2f}%) — sellers in control.",
        "sl_confluence":  "Stop-loss is at {dist:.2f}% — backed by {n} independent methods converging at the same level.",
        "sl_structural":  "Stop-loss is structural — placed just below the recent swing low.",
        "sl_fib":         "Stop-loss anchored to Fibonacci confluence — {dist:.2f}% from entry.",
        "sl_gann":        "Stop-loss anchored to a Gann natural-square support level.",
        "ha_with_mfe":   "Historical analogs: {n} similar past setups, {wr:.0f}% won and {t1:.0f}% hit T1 (avg best-case move {mfe:+.2f}%).",
        "ha_no_mfe":     "Historical analogs: {n} similar past setups, {wr:.0f}% won and {t1:.0f}% hit T1.",
        "candle":         "Candlestick: {pattern} pattern firing — adds {dir} confirmation.",
        "rg_blocked":     "⛔ Risk guard has BLOCKED this trade — see warnings below.",
        "rg_wait":        "⚠ Risk guard suggests waiting — reward-to-risk only {rr}:1.",
        "rg_ok":          "Sizing OK at {qty} qty — {pct:.2f}% of capital at risk.",
        "astro_cyclic":   "Cyclical timing: {dir} alignment for the day.",
        "astro_explicit": "Astrology: symbol is in {nak} — {dir} alignment.",
        "caution_low_conf":   "Confidence is only {conf:.0f}% — system suggests waiting for stronger setup.",
        "caution_conflicted": "Engines disagree on direction — confluence is poor, treat as low-conviction.",
        "caution_validation": "Validation found {n} engine conflict(s) — see admin view for details.",
        "caution_circuit":    "Loss circuit-breaker active — step back today, fresh session resets it tomorrow.",
    },
    "hi": {
        "bullish_opener":  "खरीदारों का नियंत्रण है",
        "bearish_opener":  "विक्रेताओं का नियंत्रण है",
        "neutral_opener":  "सेटअप संतुलित है — कोई स्पष्ट दिशा नहीं",
        "conf_high":       "उच्च विश्वास",
        "conf_mod":        "मध्यम विश्वास",
        "conf_weak":       "कमजोर विश्वास",
        "conf_noedge":     "कोई बढ़त नहीं — सिस्टम प्रतीक्षा करने का सुझाव देता है",
        "section_why":     "यह सिग्नल क्यों",
        "tech_with_rsi":   "टेक्निकल: RSI {rsi:.0f} पर, {reason}.",
        "tech_oversold":   "टेक्निकल: RSI ओवरसोल्ड है, {reason}.",
        "tech_overbought": "टेक्निकल: RSI ओवरबॉट है, {reason}.",
        "advanced_ta":     "एडवांस्ड TA कन्फ्लूएंस — {n}/3 सब-इंजन (VWAP, डायवर्जेंस, मल्टी-टाइमफ्रेम) {dir} पर सहमत.",
        "vwap_stretched_up":   "कीमत VWAP से {dist:+.2f}% ऊपर खिंची है — मीन-रिवर्शन का उम्मीदवार.",
        "vwap_stretched_down": "कीमत VWAP से {dist:.2f}% नीचे खिंची है — ओवरसोल्ड बाउंस का उम्मीदवार.",
        "vwap_holding_up":   "कीमत VWAP के ऊपर है ({dist:+.2f}%) — खरीदारों का नियंत्रण.",
        "vwap_holding_down": "कीमत VWAP के नीचे है ({dist:.2f}%) — विक्रेताओं का नियंत्रण.",
        "sl_confluence":  "स्टॉप-लॉस {dist:.2f}% पर — {n} स्वतंत्र विधियाँ इसी स्तर पर मिलती हैं.",
        "sl_structural":  "स्ट्रक्चरल स्टॉप-लॉस — हाल के स्विंग लो के ठीक नीचे रखा गया.",
        "sl_fib":         "फिबोनैचि कन्फ्लूएंस पर स्टॉप-लॉस — एंट्री से {dist:.2f}%.",
        "sl_gann":        "गैन नेचुरल-स्क्वायर सपोर्ट पर स्टॉप-लॉस.",
        "ha_with_mfe":   "ऐतिहासिक एनालॉग्स: {n} समान पुराने सेटअप, {wr:.0f}% जीते और {t1:.0f}% ने T1 छुआ (औसत बेस्ट मूव {mfe:+.2f}%).",
        "ha_no_mfe":     "ऐतिहासिक एनालॉग्स: {n} समान पुराने सेटअप, {wr:.0f}% जीते और {t1:.0f}% ने T1 छुआ.",
        "candle":         "कैंडलस्टिक: {pattern} पैटर्न बना — {dir} पुष्टि जोड़ता है.",
        "rg_blocked":     "⛔ रिस्क गार्ड ने यह ट्रेड ब्लॉक किया है — चेतावनियाँ देखें.",
        "rg_wait":        "⚠ रिस्क गार्ड प्रतीक्षा का सुझाव देता है — रिवॉर्ड-टू-रिस्क केवल {rr}:1.",
        "rg_ok":          "साइज़िंग ठीक है — {qty} qty, पूंजी का {pct:.2f}% जोखिम पर.",
        "astro_cyclic":   "साइक्लिकल समय: दिन के लिए {dir} संरेखण.",
        "astro_explicit": "ज्योतिष: सिंबल {nak} में है — {dir} संरेखण.",
        "caution_low_conf":   "विश्वास केवल {conf:.0f}% — सिस्टम मजबूत सेटअप की प्रतीक्षा का सुझाव देता है.",
        "caution_conflicted": "इंजन दिशा पर असहमत हैं — कन्फ्लूएंस कमजोर, कम विश्वास मानें.",
        "caution_validation": "वैलिडेशन ने {n} इंजन विरोध पाए — एडमिन व्यू देखें.",
        "caution_circuit":    "लॉस सर्किट-ब्रेकर सक्रिय — आज पीछे हटें, कल का सत्र इसे रीसेट करता है.",
    },
}

# Direction labels per language
_DIR_WORD = {
    "en": {"BULLISH": "bullish", "BEARISH": "bearish", "NEUTRAL": "neutral"},
    "hi": {"BULLISH": "तेज़ी", "BEARISH": "मंदी", "NEUTRAL": "तटस्थ"},
}


def _p(lang: str, key: str) -> str:
    """Phrase accessor with English fallback for missing keys."""
    return _PHRASES.get(lang, _PHRASES["en"]).get(key) or _PHRASES["en"][key]


def _dir_word(lang: str, direction: str) -> str:
    return _DIR_WORD.get(lang, _DIR_WORD["en"]).get(direction, direction.lower())


def _confidence_phrase(conf: float, lang: str = "en") -> str:
    if conf >= 75:
        return _p(lang, "conf_high")
    if conf >= 60:
        return _p(lang, "conf_mod")
    if conf >= 50:
        return _p(lang, "conf_weak")
    return _p(lang, "conf_noedge")


def _pick_opener(direction: str, lang: str = "en") -> str:
    if direction == "BULLISH":
        return _p(lang, "bullish_opener")
    if direction == "BEARISH":
        return _p(lang, "bearish_opener")
    return _p(lang, "neutral_opener")


# ----------------------------------------------------------------------------
# Reasoning paragraph builders
# ----------------------------------------------------------------------------

def _technical_sentence(data: dict, lang: str = "en") -> Optional[str]:
    t = (data.get("analyzers") or {}).get("technical") or {}
    bias = t.get("bias")
    ind  = t.get("indicators") or {}
    rsi  = ind.get("rsi14")
    if not bias or bias == "NEUTRAL":
        return None
    reason = (t.get("reasons") or ["trend confirmed"])[0].lower()
    if rsi is None:
        # Fallback to RSI-with-50 template
        return _p(lang, "tech_with_rsi").format(rsi=50, reason=reason)
    if rsi > 70:
        return _p(lang, "tech_overbought").format(reason=reason)
    if rsi < 30:
        return _p(lang, "tech_oversold").format(reason=reason)
    return _p(lang, "tech_with_rsi").format(rsi=rsi, reason=reason)


def _advanced_ta_sentence(data: dict, lang: str = "en") -> Optional[str]:
    ata = data.get("advanced_ta") or {}
    if not ata or ata.get("error"):
        return None
    confluence = ata.get("confluence_count", 0)
    bias = ata.get("composite_bias", "NEUTRAL")
    if confluence >= 2:
        return _p(lang, "advanced_ta").format(n=confluence, dir=_dir_word(lang, bias))
    return None


def _vwap_sentence(data: dict, lang: str = "en") -> Optional[str]:
    v = (data.get("advanced_ta") or {}).get("vwap") or {}
    if not v or v.get("error"):
        return None
    zone = v.get("zone", "")
    dist = v.get("distance_pct", 0) or 0
    if zone == "ABOVE_2S":
        return _p(lang, "vwap_stretched_up").format(dist=dist)
    if zone == "BELOW_2S":
        return _p(lang, "vwap_stretched_down").format(dist=dist)
    if zone in ("ABOVE_1S", "BULLISH"):
        return _p(lang, "vwap_holding_up").format(dist=dist)
    if zone in ("BELOW_1S", "BEARISH"):
        return _p(lang, "vwap_holding_down").format(dist=dist)
    return None


def _stop_loss_sentence(data: dict, lang: str = "en") -> Optional[str]:
    sl = data.get("stop_loss_analysis") or {}
    if not sl or sl.get("error"):
        return None
    method = sl.get("recommended_method", "")
    distance = sl.get("distance_pct", 0) or 0
    if method == "CONFLUENCE":
        n = sl.get("confluence_count", 0)
        return _p(lang, "sl_confluence").format(dist=distance, n=n)
    if method == "STRUCTURAL":
        return _p(lang, "sl_structural")
    if method == "FIB":
        return _p(lang, "sl_fib").format(dist=distance)
    if method == "GANN":
        return _p(lang, "sl_gann")
    return None


def _historical_analog_sentence(data: dict, lang: str = "en") -> Optional[str]:
    ha = data.get("historical_analog") or {}
    outcomes = ha.get("outcomes") or {}
    n = outcomes.get("n", 0)
    if n < 8 or not ha.get("has_enough_data"):
        return None
    wr = (outcomes.get("win_rate", 0) or 0) * 100
    t1 = (outcomes.get("t1_hit_rate", 0) or 0) * 100
    mfe = outcomes.get("avg_mfe")
    if mfe is not None:
        return _p(lang, "ha_with_mfe").format(n=n, wr=wr, t1=t1, mfe=mfe)
    return _p(lang, "ha_no_mfe").format(n=n, wr=wr, t1=t1)


def _candle_sentence(data: dict, lang: str = "en") -> Optional[str]:
    cp = data.get("candlestick_patterns") or {}
    if not cp or cp.get("error"):
        return None
    headline = cp.get("headline_pattern")
    bias = cp.get("composite_bias", "NEUTRAL")
    if headline and bias != "NEUTRAL":
        return _p(lang, "candle").format(pattern=headline.lower(), dir=_dir_word(lang, bias))
    return None


def _risk_guard_sentence(data: dict, lang: str = "en") -> Optional[str]:
    rg = data.get("risk_guard") or {}
    if not rg or rg.get("error"):
        return None
    verdict = rg.get("verdict")
    if verdict == "BLOCK":
        return _p(lang, "rg_blocked")
    if verdict == "DOWNGRADE_WAIT":
        return _p(lang, "rg_wait").format(rr=rg.get("risk_reward_ratio", "?"))
    if verdict == "OK" and rg.get("suggested_quantity"):
        return _p(lang, "rg_ok").format(qty=rg["suggested_quantity"],
                                           pct=rg.get("risk_pct_of_capital", 0) or 0)
    return None


def _astrology_sentence(data: dict, hide_astrology: bool, lang: str = "en") -> Optional[str]:
    """Astrology phrasing is gated by hide_astrology — user portal hides
    nakshatra names, admin portal shows them."""
    vedic = (data.get("analyzers") or {}).get("vedic") or {}
    bias = vedic.get("bias")
    if not bias or bias == "NEUTRAL":
        return None
    if hide_astrology:
        return _p(lang, "astro_cyclic").format(dir=_dir_word(lang, bias))
    nak = vedic.get("nakshatra")
    if nak:
        return _p(lang, "astro_explicit").format(nak=nak, dir=_dir_word(lang, bias))
    return None


# ----------------------------------------------------------------------------
# Main entry point
# ----------------------------------------------------------------------------

def explain(data: dict, *, hide_astrology: bool = False, lang: str = "en") -> Explanation:
    """Generate a fluent explanation of the recommendation from the
    structured symbol-detail payload.

    Args:
      data: the dict returned by /api/symbol/{ticker}
      hide_astrology: when True, astrology terms are neutralized (USER role)
      lang: 'en' (English) or 'hi' (Hindi). Unknown languages fall back to English.

    Returns:
      Explanation with headline + body + cautions.
    """
    # Normalize language code; unknown → 'en'
    if lang not in _PHRASES:
        lang = "en"

    direction = data.get("direction", "NEUTRAL")
    confidence = data.get("confidence", 50) or 50

    # ---- Headline ----
    opener = _pick_opener(direction, lang)
    conf_phrase = _confidence_phrase(confidence, lang)
    headline = f"{opener} — {conf_phrase} ({confidence:.0f}%)."

    # ---- Body — assemble sentences from the structured data ----
    body: list[str] = []
    builders = [
        lambda d: _technical_sentence(d, lang),
        lambda d: _advanced_ta_sentence(d, lang),
        lambda d: _vwap_sentence(d, lang),
        lambda d: _candle_sentence(d, lang),
        lambda d: _historical_analog_sentence(d, lang),
        lambda d: _stop_loss_sentence(d, lang),
        lambda d: _astrology_sentence(d, hide_astrology, lang),
        lambda d: _risk_guard_sentence(d, lang),
    ]
    for fn in builders:
        try:
            sentence = fn(data)
            if sentence:
                body.append(sentence)
        except Exception:
            # Defensive: one builder failing must not break the whole panel
            continue

    # ---- Cautions ----
    cautions: list[str] = []
    if confidence < 50:
        cautions.append(_p(lang, "caution_low_conf").format(conf=confidence))
    cb = data.get("confidence_band") or {}
    if cb.get("conviction_quality") in ("CONFLICTED", "MIXED"):
        cautions.append(_p(lang, "caution_conflicted"))
    val = data.get("validation") or {}
    conflicts = val.get("conflicts", []) if isinstance(val, dict) else []
    if conflicts:
        cautions.append(_p(lang, "caution_validation").format(n=len(conflicts)))
    rg = data.get("risk_guard") or {}
    if rg.get("in_circuit_breaker"):
        cautions.append(_p(lang, "caution_circuit"))

    return Explanation(
        headline=headline,
        body=body,
        cautions=cautions,
        confidence_phrase=conf_phrase,
    )
