"""Top-N stock recommender.

Scans the NSE F&O universe (or a custom symbol list) by running the full
decision engine on each symbol, then:
  • filters by minimum confidence
  • ranks by composite score
  • groups by sector for sector-rotation views
  • separates BUY-side and SELL-side recommendations

Designed to be the "What should I trade today?" panel of the platform.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Literal
from concurrent.futures import ThreadPoolExecutor, as_completed

from loguru import logger

from app.engines import decision, recommendation_grade, signal_stability
from app.services.market_data import get_ohlcv
from app.services.universe import all_symbols, sector_of, top_liquid, INDICES


@dataclass
class Recommendation:
    symbol: str
    sector: str
    signal: str
    trend: str
    confidence: float
    entry: float
    stoploss: float
    targets: list[float]
    risk_reward: float
    capital_allocation_pct: float
    engines: dict
    reasons: dict


@dataclass
class RecommendationSet:
    asof: str
    universe_size: int
    scanned: int
    min_confidence: float
    horizon: str
    top_buy: list[dict] = field(default_factory=list)
    top_sell: list[dict] = field(default_factory=list)
    by_sector: dict[str, dict] = field(default_factory=dict)
    errors: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "asof": self.asof,
            "universe_size": self.universe_size,
            "scanned": self.scanned,
            "min_confidence": self.min_confidence,
            "horizon": self.horizon,
            "top_buy": self.top_buy,
            "top_sell": self.top_sell,
            "by_sector": self.by_sector,
            "errors": self.errors,
            "disclaimer": (
                "Recommendations blend technical, SMC, options, astrology, Gann, "
                "and numerology signals. Astrology/numerology layers are confluence "
                "enhancements only. Verify each pick before deploying capital."
            ),
        }


def _score_one(symbol: str, horizon: str, capital: float) -> dict | None:
    try:
        df = get_ohlcv(symbol, periods=250)
        # Skip dead / circuit-locked / zero-price instruments (zero range -> divide-by-zero)
        if df is None or len(df) < 30 or float(df["close"].iloc[-1]) <= 0 \
                or float((df["high"] - df["low"]).tail(20).sum()) <= 0:
            return {"symbol": symbol, "error": "skipped: flat or zero-price data"}
        return decision.aggregate(symbol=symbol, df=df, horizon=horizon, capital=capital)
    except Exception as e:
        logger.warning("recommender: {} failed: {}", symbol, e)
        return {"symbol": symbol, "error": str(e)}


def scan(
    symbols: list[str] | None = None,
    horizon: Literal["INTRADAY", "SWING", "POSITIONAL"] = "SWING",
    capital: float = 100_000,
    min_confidence: float = 60.0,
    top_n: int = 10,
    parallel: int = 6,
    quick: bool = True,
) -> RecommendationSet:
    """Run the decision engine across `symbols` and return ranked recommendations.

    quick=True  → scan top-50 most-liquid F&O names (~15-30s)
    quick=False → scan full ~180 stock universe (~60-120s)
    """
    universe = symbols or (top_liquid(50) if quick else all_symbols(include_indices=True))
    asof = datetime.now().isoformat()
    results: list[dict] = []
    errors: list[str] = []

    with ThreadPoolExecutor(max_workers=parallel) as pool:
        futures = {pool.submit(_score_one, sym, horizon, capital): sym for sym in universe}
        for fut in as_completed(futures):
            sym = futures[fut]
            try:
                res = fut.result()
                if res is None:
                    continue
                if "error" in res:
                    errors.append(f"{sym}: {res['error']}")
                else:
                    results.append(res)
            except Exception as e:
                errors.append(f"{sym}: {e}")

    # Split buy vs sell
    buys = [r for r in results if r["signal"] in ("BUY", "STRONG_BUY") and r["confidence"] >= min_confidence]
    sells = [r for r in results if r["signal"] in ("SELL", "STRONG_SELL") and r["confidence"] >= min_confidence]

    buys.sort(key=lambda x: -x["confidence"])
    sells.sort(key=lambda x: -x["confidence"])

    # Sector aggregation — average confidence + counts
    by_sector: dict[str, dict] = {}
    for r in results:
        sect = sector_of(r["symbol"])
        if sect not in by_sector:
            by_sector[sect] = {"sector": sect, "count": 0, "avg_confidence": 0.0,
                                "bullish": 0, "bearish": 0, "neutral": 0, "top": []}
        s = by_sector[sect]
        s["count"] += 1
        s["avg_confidence"] += r["confidence"]
        if r["signal"] in ("BUY", "STRONG_BUY"):
            s["bullish"] += 1
        elif r["signal"] in ("SELL", "STRONG_SELL"):
            s["bearish"] += 1
        else:
            s["neutral"] += 1
        s["top"].append({"symbol": r["symbol"], "signal": r["signal"], "confidence": r["confidence"]})

    for sect, s in by_sector.items():
        s["avg_confidence"] = round(s["avg_confidence"] / max(1, s["count"]), 2)
        s["top"] = sorted(s["top"], key=lambda x: -x["confidence"])[:3]

    return RecommendationSet(
        asof=asof,
        universe_size=len(universe),
        scanned=len(results),
        min_confidence=min_confidence,
        horizon=horizon,
        top_buy=[_to_reco(r) for r in buys[:top_n]],
        top_sell=[_to_reco(r) for r in sells[:top_n]],
        by_sector=by_sector,
        errors=errors[:10],
    )


def _to_reco(r: dict) -> dict:
    return {
        "symbol": r["symbol"],
        "sector": sector_of(r["symbol"]),
        "signal": r["signal"],
        "trend": r["trend"],
        "confidence": r["confidence"],
        "entry": r["entry"],
        "stoploss": r["stoploss"],
        "targets": r["targets"],
        "risk_reward": r["risk_reward"],
        "capital_allocation_pct": r["capital_allocation_pct"],
        "engines": {k: {"score": v["score"], "bias": v["bias"]} for k, v in r["engines"].items()},
        "reasons": r["reasons"],
    }


# ===========================================================================
# Professional-grade scan — combines decision.aggregate + recommendation_grade
#                         + signal_stability hysteresis
# Used by /api/recommend/professional. Returns BlackRock-style payload:
#   conviction label + stars + instrument ranking + risk variants + stability.
# ===========================================================================

def professional_scan(
    symbols: list[str] | None = None,
    horizon: Literal["INTRADAY", "SWING", "POSITIONAL"] = "SWING",
    capital: float = 100_000,
    min_stars: int = 3,
    top_n: int = 10,
    parallel: int = 6,
    quick: bool = True,
    apply_stability: bool = True,
    universe_name: str | None = None,
    apply_prefilter: bool | None = None,
) -> dict:
    """Return ranked, professionally-graded recommendations.

    Universe selection priority:
      1. Explicit `symbols` list (highest priority — caller knows best)
      2. `universe_name` resolved via universe.universe_for() — supports
         "fno_top50", "fno", "nifty500", "all_nse"
      3. `quick=True` → top 50 liquid (default fast path)
      4. `quick=False` → F&O 180 universe

    Prefiltering: when the resolved universe is > 250 symbols, a fast
    prefilter (volume + volatility + price + circuit check, one batched
    broker call) cuts it to ~200-300 high-quality candidates BEFORE the
    expensive per-symbol pipeline runs. This is what makes "scan all NSE"
    achievable in 3-5 min instead of 30+. Default behaviour matches the
    universe size:
      • > 250 symbols → prefilter on by default
      • ≤ 250 → no prefilter
    Set `apply_prefilter=True/False` to override.

    Each entry has:
      conviction_label, stars, confidence + CI, engine_agreement_pct,
      instrument_ranking (best-fit first), risk_variants
      (AGGRESSIVE/MODERATE/CONSERVATIVE sizing), stability_score, and the
      raw signal underneath for transparency.
    """
    # ----- Resolve initial universe -----
    if symbols:
        universe = symbols
    elif universe_name:
        from app.services.universe import universe_for
        universe = universe_for(universe_name)
    elif quick:
        universe = top_liquid(50)
    else:
        universe = all_symbols(include_indices=True)

    # ----- Optional prefilter for large universes -----
    prefilter_stats: dict | None = None
    use_prefilter = apply_prefilter
    if use_prefilter is None:
        # Auto-enable when the universe is large enough to make the full scan slow
        use_prefilter = len(universe) > 250

    if use_prefilter:
        try:
            from app.services import universe_filter
            filtered_symbols, fstats = universe_filter.prefilter(universe)
            prefilter_stats = fstats.to_dict()
            universe = filtered_symbols
        except Exception as e:
            logger.warning("Prefilter failed, falling back to full universe: {}", e)
            prefilter_stats = {"error": str(e)}
    asof = datetime.now().isoformat()
    graded: list[dict] = []
    errors: list[str] = []

    with ThreadPoolExecutor(max_workers=parallel) as pool:
        futures = {
            pool.submit(_score_one, sym, horizon, capital): sym
            for sym in universe
        }
        for fut in as_completed(futures):
            sym = futures[fut]
            try:
                sig = fut.result()
                if sig is None or "error" in sig:
                    if sig and "error" in sig:
                        errors.append(f"{sym}: {sig['error']}")
                    continue

                # Pull derived metrics for grading
                tech = sig.get("engines", {}).get("technical", {}).get("details", {})
                opt  = sig.get("engines", {}).get("options",   {}).get("details", {})
                atr  = tech.get("atr14")
                atr_pct = (atr / max(sig.get("entry", 1), 1)) * 100 if atr else None
                iv_pct = None
                if opt.get("atm", {}).get("iv") is not None:
                    iv_pct = float(opt["atm"]["iv"]) * 100  # iv stored as fraction

                pg = recommendation_grade.grade(
                    sig, capital=capital, is_fno=True,
                    iv_pct=iv_pct, atr_pct=atr_pct, requested_horizon=horizon,
                ).to_dict()

                # ----- Hysteresis layer -----
                if apply_stability:
                    stab = signal_stability.evaluate(
                        symbol=sym, horizon=horizon,
                        new_label=pg["conviction_label"],
                        new_direction=pg["direction"],
                        new_confidence=pg["confidence"],
                    ).to_dict()
                    # If we stuck with a previously-displayed signal, surface that
                    if not stab["use_new"]:
                        pg["conviction_label"] = stab["displayed_label"]
                        pg["confidence"] = stab["displayed_confidence"]
                        pg["direction"] = stab["displayed_direction"]
                    pg["stability"] = stab
                else:
                    pg["stability"] = None

                graded.append({
                    "symbol": sym,
                    "sector": sector_of(sym),
                    "grade": pg,
                    "raw_signal": {
                        "signal": sig["signal"],
                        "confidence": sig["confidence"],
                        "entry": sig["entry"],
                        "stoploss": sig["stoploss"],
                        "targets": sig["targets"],
                        "risk_reward": sig["risk_reward"],
                    },
                })

                # ----- Persist to signals_journal (for history + future ML training) -----
                # Only log signals worth tracking: BUY/SELL with ≥ min_stars conviction
                if pg.get("stars", 0) >= min_stars and pg.get("direction") != "NEUTRAL":
                    try:
                        from app.services.signals_logger import log_signal
                        log_signal(sig, horizon=horizon, grade=pg)
                    except Exception as e:
                        logger.debug("signal_logger failed (non-fatal): {}", e)
            except Exception as e:
                errors.append(f"{sym}: {e}")

    # Filter by stars and split direction
    finalists = [g for g in graded if g["grade"]["stars"] >= min_stars]
    buys  = [g for g in finalists if g["grade"]["direction"] == "BULLISH"]
    sells = [g for g in finalists if g["grade"]["direction"] == "BEARISH"]
    buys.sort(key=lambda g: (-g["grade"]["stars"], -g["grade"]["confidence"]))
    sells.sort(key=lambda g: (-g["grade"]["stars"], g["grade"]["confidence"]))

    return {
        "asof": asof,
        "universe_size": len(universe),
        "universe_name": universe_name,
        "prefilter":   prefilter_stats,
        "scanned": len(graded),
        "min_stars": min_stars,
        "horizon": horizon,
        "top_buy": buys[:top_n],
        "top_sell": sells[:top_n],
        "errors": errors[:10],
        "disclaimer": (
            "Conviction stars reflect ENGINE AGREEMENT across technical, SMC, "
            "options, astrology, Gann, and numerology layers. Stars are NOT a "
            "measure of predictive accuracy. Validate every signal in paper "
            "trading for 30+ sessions before risking real capital. This is NOT "
            "SEBI-registered investment advice."
        ),
    }
