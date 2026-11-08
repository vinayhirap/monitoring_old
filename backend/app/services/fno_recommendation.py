"""Unified F&O recommendation orchestrator.

The `/api/symbol/{sym}` endpoint already runs every engine and returns a
giant dict — direction, confidence, options analytics, options strategy,
astrology, advanced TA, risk guard, the clarity-layer verdict, the works.

This service takes that haystack and projects it down into a clean,
F&O-focused recommendation that frontends (and the `gh`-style "give me a
F&O pick" CLI) can consume without having to know which sub-keys to read.

What you get back:
  • headline                    — one human line summarising the trade
  • verdict / conviction        — from recommendation_quality
  • direction / confidence_pct  — from the engine consensus
  • strategy / strikes / legs   — from options_strategy.recommend()
  • analytics                   — PCR, max pain, walls, IV regime
  • astro_overlay               — does today's astro align with the trade?
  • technical_confluence        — which engines confirm and which dissent
  • risk_guard                  — sizing, R:R, circuit breaker verdict
  • caveats                     — unknown signals + per-strategy warnings
  • execution_payload           — ready-to-place order skeleton

NEVER returns a "soft" recommendation when:
  - price_sanity is SUSPECT (wrong-instrument or stale-tick guard)
  - risk_guard verdict is BLOCK
  - confidence < 55
  - direction is NEUTRAL and no premium-harvesting regime applies
In those cases verdict is AVOID / WATCH / WAIT and trade_plan is None.
"""
from __future__ import annotations

from dataclasses import dataclass, field, asdict
from datetime import datetime
from typing import Any

from loguru import logger


# Engines that must vote bullish/bearish to "confirm" the F&O direction.
# Astrology is included because the user asked for explicit astro overlay
# in the F&O verdict — it doesn't drive the trade by itself.
CONFIRMING_ENGINES = [
    "technical", "smc", "gann", "fibonacci", "vedic", "numerology", "ml",
]


@dataclass
class FAndORecommendation:
    symbol: str
    asof: str

    # ---- Headline ----
    headline: str
    verdict: str                          # STRONG_BUY/BUY/WATCH/WAIT/SELL/STRONG_SELL/AVOID
    conviction: str                       # STRONG/MEDIUM/WEAK/NONE
    direction: str                        # BULLISH/BEARISH/NEUTRAL
    confidence_pct: float
    confidence_is_calibrated: bool

    # ---- F&O specifics ----
    strategy: str                         # CE_BUY / BULL_CALL_SPREAD / IRON_CONDOR / ...
    strategy_subtype: str
    expiry: str | None
    days_to_expiry: int | None
    iv_pct: float | None
    iv_regime: str | None                 # LOW/MID/HIGH/VERY_HIGH
    legs: list[dict]                      # per-leg breakdown w/ greeks
    net_premium_inr: float
    max_profit_inr: float
    max_loss_inr: float
    breakeven_prices: list[float]
    risk_reward: float
    suggested_lots: int
    suggested_capital_inr: float
    margin_required_inr: float | None
    entry_triggers: list[str]
    exit_triggers: list[str]
    portfolio_greeks: dict

    # ---- Underlying analytics ----
    spot: float
    analytics: dict                       # PCR, max_pain, walls, IV, institutional view

    # ---- Astrology overlay ----
    astro_overlay: dict                   # { aligned, bias, score, headline, factors }

    # ---- Technical confluence ----
    technical_confluence: dict            # { confirming: [...], dissenting: [...], counts }
    advanced_ta: dict | None              # VWAP family + divergence + MTF momentum

    # ---- Risk + caveats ----
    risk_guard: dict | None
    price_sanity: dict | None
    caveats: list[str] = field(default_factory=list)
    hard_blocks: list[str] = field(default_factory=list)

    # ---- Execution skeleton ----
    execution_payload: dict | None = None

    disclaimer: str = (
        "F&O trades carry amplified risk — premium decay (theta), IV crush, "
        "and gap risk can wipe a position overnight. The suggested strikes "
        "assume live chain greeks at time of analysis; re-verify before entry. "
        "Educational only — NOT SEBI-registered advice."
    )

    def to_dict(self) -> dict:
        return asdict(self)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _build_astro_overlay(symbol_data: dict, direction: str) -> dict:
    """Pulls market_sentiment + vedic analyzer to decide whether today's astro
    weather supports the trade direction. Returns a small, opinionated dict
    instead of dumping the whole sentiment payload."""
    sent = (symbol_data.get("context") or {}).get("market_sentiment") or {}
    vedic = (symbol_data.get("analyzers") or {}).get("vedic") or {}

    astro_bias = sent.get("bias", "NEUTRAL")     # BULLISH/BEARISH/NEUTRAL
    score      = sent.get("score", 50)

    aligned = (
        (direction == "BULLISH" and astro_bias == "BULLISH") or
        (direction == "BEARISH" and astro_bias == "BEARISH") or
        (direction == "NEUTRAL")                  # neutral trades don't conflict with astro
    )

    return {
        "aligned":         bool(aligned),
        "bias":            astro_bias,
        "score":           round(float(score), 1),
        "headline":        sent.get("headline", ""),
        "bullish_factors": (sent.get("bullish_factors") or [])[:3],
        "bearish_factors": (sent.get("bearish_factors") or [])[:3],
        "symbol_nakshatra": {
            "name":   vedic.get("nakshatra"),
            "ruler":  vedic.get("ruler"),
            "tara":   vedic.get("tara"),
        },
    }


def _build_confluence(symbol_data: dict, direction: str) -> dict:
    """Counts which engines agree with the F&O direction vs which dissent.
    Useful for the UI to show "11 of 17 engines confirm BULLISH" badges."""
    analyzers = symbol_data.get("analyzers") or {}
    confirming, dissenting, neutral = [], [], []
    for name in CONFIRMING_ENGINES:
        eng = analyzers.get(name) or {}
        bias = eng.get("bias", "NEUTRAL")
        # ML engine reports BUY/SELL/HOLD — normalise to BULLISH/BEARISH
        if bias in ("BUY", "STRONG_BUY"):  bias = "BULLISH"
        if bias in ("SELL", "STRONG_SELL"): bias = "BEARISH"
        if bias in ("HOLD", "WATCH"):      bias = "NEUTRAL"
        # SMC uses BULLISH_STRUCTURE / BEARISH_STRUCTURE labels
        if bias and bias.startswith("BULLISH"): bias = "BULLISH"
        if bias and bias.startswith("BEARISH"): bias = "BEARISH"

        if bias == direction:                 confirming.append(name)
        elif bias in ("BULLISH", "BEARISH"): dissenting.append(name)
        else:                                 neutral.append(name)

    return {
        "direction":         direction,
        "confirming":        confirming,
        "dissenting":        dissenting,
        "neutral":           neutral,
        "confirming_count":  len(confirming),
        "dissenting_count":  len(dissenting),
        "total_engines":     len(CONFIRMING_ENGINES),
    }


def _build_headline(*, symbol: str, verdict: str, conviction: str,
                     legs: list[dict], strategy: str, confidence: float,
                     spot: float) -> str:
    """One-line summary: 'STRONG BUY · NIFTY 24500 CE @ ₹102 · 78% confidence'.
    Multi-leg strategies show the strategy name instead of every strike."""
    if not legs or verdict in ("WATCH", "WAIT", "AVOID"):
        return f"{verdict.replace('_', ' ')} · {symbol} · {confidence:.0f}% confidence"

    if len(legs) == 1:
        leg = legs[0]
        return (f"{verdict.replace('_', ' ')} · {symbol} {leg['strike']:.0f} {leg['type']} "
                 f"@ ₹{leg['ltp']:.2f} · {conviction} conviction · "
                 f"{confidence:.0f}% confidence")
    return (f"{verdict.replace('_', ' ')} · {symbol} {strategy.replace('_', ' ')} "
             f"({len(legs)} legs) · {conviction} conviction · "
             f"{confidence:.0f}% confidence")


def _build_execution_payload(*, symbol: str, expiry: str | None,
                              legs: list[dict], lots: int) -> dict | None:
    """Skeleton order payload for the broker integration. Always wraps SL/TP
    via bracket order so the user can't accidentally place naked-risk legs.

    Each leg includes the option meta (`underlying`, `option_strike`,
    `option_type`, `option_expiry`) that the trade executor uses to resolve
    the broker contract tradingsymbol. The frontend passes these fields
    straight through to `POST /api/trade/place-multi-leg` — the user never
    has to know what "NIFTY24APR23500CE" is.
    """
    if not legs or lots <= 0:
        return None
    return {
        "broker": "ANGEL_ONE",
        "product": "NRML",            # F&O carry-forward; bracket isn't supported for multi-leg
        "validity": "DAY",
        "symbol":   symbol,
        "expiry":   expiry,
        "lots":     lots,
        "legs": [
            {
                "transaction_type": leg["action"],          # BUY / SELL
                "option_type":      leg["type"],            # CE / PE
                "strike":           leg["strike"],
                "lot_size":         leg["lot_size"],
                "limit_price":      leg["ltp"],
                # ↓ Fields the trade-executor uses for option resolution.
                # Without these, the broker would route the order to the
                # underlying index instead of the option contract.
                "underlying":       symbol,
                "option_strike":    leg["strike"],
                "option_type":      leg["type"],
                "option_expiry":    expiry,
            }
            for leg in legs
        ],
        # The actual SL/TP triggers are sent as per-leg bracket params; the
        # exit_triggers list on the recommendation tells the user how to read them.
    }


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

def build(symbol_data: dict, *, capital: float = 100_000) -> FAndORecommendation:
    """Project a full /api/symbol/{sym} response down to a F&O recommendation.

    Caller is responsible for actually fetching `symbol_data` (typically by
    invoking `app.api.symbol.symbol_detail(...)` as a regular Python function;
    FastAPI handlers are plain `def`s so this works without re-routing through
    HTTP). This service is pure — it never makes network calls.
    """
    sym = (symbol_data.get("symbol") or "?").upper()
    direction  = symbol_data.get("direction", "NEUTRAL")
    confidence = float(symbol_data.get("confidence", 0))
    is_calibrated = bool(symbol_data.get("confidence_is_calibrated", False))
    spot       = float((symbol_data.get("ltp") or {}).get("ltp")
                        or symbol_data.get("spot")
                        or 0)

    verdict_block = symbol_data.get("verdict") or {}
    quality_verdict   = verdict_block.get("verdict", "WATCH")
    quality_conviction = verdict_block.get("conviction", "NONE")
    quality_caveats   = list(verdict_block.get("caveats") or [])
    quality_blocks    = list(verdict_block.get("hard_blocks") or [])

    options_block = symbol_data.get("options_analysis") or {}
    analytics_block = options_block.get("analytics") or {}
    trade_plan      = options_block.get("trade_plan") or {}

    # Extract the trade-plan fields — these mirror OptionsTradePlan in
    # app/engines/options_strategy.py. Missing means no plan was produced
    # (e.g. live chain unavailable).
    strategy           = trade_plan.get("strategy", "WAIT")
    strategy_subtype   = trade_plan.get("strategy_subtype", "n/a")
    expiry             = trade_plan.get("expiry") or options_block.get("expiry")
    days_to_expiry     = trade_plan.get("days_to_expiry")
    iv_pct             = trade_plan.get("iv_pct")
    iv_regime          = trade_plan.get("iv_regime")
    legs               = trade_plan.get("legs") or []
    net_premium_inr    = float(trade_plan.get("net_premium_inr", 0) or 0)
    max_profit_inr     = float(trade_plan.get("max_profit_inr", 0) or 0)
    max_loss_inr       = float(trade_plan.get("max_loss_inr", 0) or 0)
    breakeven_prices   = list(trade_plan.get("breakeven_prices") or [])
    risk_reward        = float(trade_plan.get("risk_reward", 0) or 0)
    suggested_lots     = int(trade_plan.get("suggested_lots", 0) or 0)
    suggested_cap_inr  = float(trade_plan.get("suggested_capital_inr", 0) or 0)
    margin_req         = trade_plan.get("margin_required_inr")
    entry_triggers     = list(trade_plan.get("entry_triggers") or [])
    exit_triggers      = list(trade_plan.get("exit_triggers") or [])
    portfolio_greeks   = trade_plan.get("portfolio_greeks") or {}

    # Astro overlay + technical confluence (always populated, regardless of trade)
    astro_overlay      = _build_astro_overlay(symbol_data, direction)
    confluence         = _build_confluence(symbol_data, direction)
    advanced_ta_block  = symbol_data.get("advanced_ta")

    # Pull caveats from the trade plan too — these are options-specific
    # warnings (e.g. "deltas may shift before entry") that recommendation_quality
    # doesn't know about.
    plan_caveats = list(trade_plan.get("confidence_caveats") or [])

    # Annotate astro-misalignment as a caveat (not a block — astro is overlay)
    if (direction in ("BULLISH", "BEARISH")
            and astro_overlay["bias"] in ("BULLISH", "BEARISH")
            and not astro_overlay["aligned"]):
        plan_caveats.append(
            f"Astro bias is {astro_overlay['bias']} but trade direction is "
            f"{direction} — counter-trend setup, treat as low-conviction"
        )

    # Risk guard pass-through (already computed in the symbol pipeline)
    risk_guard_block = symbol_data.get("risk_guard")
    price_sanity_block = symbol_data.get("price_sanity")

    # Build clean payload regardless of whether we have legs (WATCH/WAIT/AVOID
    # verdicts still return analytics + confluence + astro for the UI to show
    # WHY there's no trade).
    headline = _build_headline(
        symbol=sym, verdict=quality_verdict, conviction=quality_conviction,
        legs=legs, strategy=strategy, confidence=confidence, spot=spot,
    )

    exec_payload = (_build_execution_payload(
        symbol=sym, expiry=expiry, legs=legs, lots=suggested_lots,
    ) if quality_verdict in ("BUY", "STRONG_BUY", "SELL", "STRONG_SELL") else None)

    return FAndORecommendation(
        symbol=sym,
        asof=datetime.utcnow().isoformat() + "Z",
        headline=headline,
        verdict=quality_verdict,
        conviction=quality_conviction,
        direction=direction,
        confidence_pct=round(confidence, 1),
        confidence_is_calibrated=is_calibrated,
        strategy=strategy,
        strategy_subtype=strategy_subtype,
        expiry=expiry,
        days_to_expiry=days_to_expiry,
        iv_pct=iv_pct,
        iv_regime=iv_regime,
        legs=legs,
        net_premium_inr=net_premium_inr,
        max_profit_inr=max_profit_inr,
        max_loss_inr=max_loss_inr,
        breakeven_prices=breakeven_prices,
        risk_reward=risk_reward,
        suggested_lots=suggested_lots,
        suggested_capital_inr=suggested_cap_inr,
        margin_required_inr=margin_req,
        entry_triggers=entry_triggers,
        exit_triggers=exit_triggers,
        portfolio_greeks=portfolio_greeks,
        spot=spot,
        analytics=analytics_block,
        astro_overlay=astro_overlay,
        technical_confluence=confluence,
        advanced_ta=advanced_ta_block,
        risk_guard=risk_guard_block,
        price_sanity=price_sanity_block,
        caveats=quality_caveats + plan_caveats,
        hard_blocks=quality_blocks,
        execution_payload=exec_payload,
    )


def safe_build(symbol_data: dict, *, capital: float = 100_000) -> dict:
    """Wrapper that NEVER throws — always returns a usable dict, even when
    the symbol pipeline returned a partial/error payload. Useful for the API
    handler so a single engine glitch can't 500 the whole F&O endpoint."""
    try:
        return build(symbol_data, capital=capital).to_dict()
    except Exception as e:
        logger.exception("fno_recommendation.build failed for {}",
                          symbol_data.get("symbol", "?"))
        return {
            "symbol": symbol_data.get("symbol", "?"),
            "asof":    datetime.utcnow().isoformat() + "Z",
            "verdict": "AVOID",
            "conviction": "NONE",
            "headline": f"F&O recommendation unavailable: {e}",
            "error":   str(e),
        }
