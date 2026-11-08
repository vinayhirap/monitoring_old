# ROADMAP — Engine Advancement Brief

> Audience: engineers extending MarketLens beyond the current MVP.
> Each tier is independently shippable. Each task lists: **what / why /
> files / metrics / success criteria**. Don't start Tier N+1 until Tier N
> has a green metric.

---

## Tier 1 — Upgrade the core engines

**Theme:** stop reporting heuristic 0–100 scores and start reporting
*calibrated probabilities*. Replace gut weights with measured weights.

### 1.1 Calibrated technical-engine confidence
- **What.** Today `engines/technical.py` returns a heuristic `score` (sum of
  reason-points clamped to 0–100). Replace it with a calibrated probability
  of "T1 hit before SL within N bars" using **isotonic regression** on
  historical backtest outcomes.
- **Why.** A 75 today and a 75 a year ago mean different things. Calibrated
  probabilities are comparable across time and across symbols, and feed
  downstream Bayesian aggregation cleanly.
- **Files to add.**
  - `backend/app/engines/calibration.py` — fit + serve isotonic mapping
    (`sklearn.isotonic.IsotonicRegression`)
  - `backend/scripts/calibrate_technical.py` — offline trainer; reads
    persisted signal/outcome rows from SQLite, writes
    `~/.cache/marketlens/calibrator_technical.pkl`
  - Modify `engines/technical.analyze()` to load the pickle on first call
    and emit both `raw_score` and `calibrated_prob`
- **Metrics.**
  - **Reliability diagram** (predicted vs realised hit-rate per 5% bucket).
    Slope ≥ 0.85, intercept ≤ 0.1 = well-calibrated.
  - **Brier score** ≤ 0.22 on 20% out-of-sample fold.
- **Success criteria.** UI confidence number on a finalist card reads "BUY 72%"
  and over 100 such trades the realised hit-rate is 65–80% (within calibration
  interval).

### 1.2 Probability scoring for SMC structures
- **What.** Replace SMC reason-points (`score += 25` for CHoCH etc.) with
  empirical priors: *given a CHoCH at this premium/discount zone, what's
  the historical probability of trend continuation 5 bars later?*
- **Files.** `backend/app/engines/smc.py` — add `_empirical_prior(structure_type, zone, atr_pct)`
  reading a lookup table built offline from the persisted signal/outcome log.
- **Metrics.** Log-loss against held-out trades ≤ 0.55.
- **Success criteria.** When SMC says 0.78 probability of bullish continuation,
  the realised continuation rate over 100 such setups is 70–85%.

### 1.3 Improved Gann engine — full Square of 9 vs cardinal/ordinal
- **What.** Current `engines/gann.py` computes price levels at 45° harmonics
  only. Production Gann uses:
  - The full hexagonal Square (24 angles)
  - Cardinal (N/E/S/W) vs Ordinal (NE/SE/SW/NW) cross — cardinals are
    historically the strongest reversal levels
  - Anchored squares from prior major H/L pivots, not just last close
  - Square-rooted time (price-time squaring across multiple anchors)
- **Files.** `backend/app/engines/gann.py` — extend `square_of_9_levels`
  to return per-angle strength (cardinal=1.0, ordinal=0.7, intermediate=0.4).
  Add `engines/gann_anchored.py` for multi-anchor projections.
- **Metrics.** Touch-rate of cardinal levels within ±0.5% over next 20 bars
  measured against random level baseline; expect ≥ 1.5× baseline.
- **Success criteria.** Cardinal-level reactions are statistically
  distinguishable from noise (p < 0.05 over 500 historical events).

### 1.4 Add Wyckoff phase detection
- **What.** Detect Wyckoff phases: Accumulation (A→E), Markup, Distribution,
  Markdown. Classify the symbol's current phase from volume + structure.
- **Files.** `backend/app/engines/wyckoff.py` (new).
- **Metrics.** Phase classification stability — same symbol shouldn't flip
  phase > 2× per month in a trending period.
- **Success criteria.** Markup-phase finalists have 1.5× win rate vs
  Distribution-phase shorts (or vice versa) over 100 trades.

### 1.5 Order-flow proxy (no L2 data needed)
- **What.** Approximate buying vs selling pressure from candle anatomy:
  *aggressive buyer share* ≈ (close − low) / (high − low) weighted by volume.
  Cumulative-delta proxy: rolling sum over N bars.
- **Files.** `backend/app/engines/orderflow.py` (new).
- **Metrics.** Correlation with realised next-bar direction ≥ 0.15 (low,
  but it's an edge signal).
- **Success criteria.** Adding the flow score to the decision blend
  improves walk-forward Sharpe by ≥ 0.1.

---

## Tier 2 — Cross-engine propagation

**Theme:** stop averaging weighted scores. Start propagating beliefs.

### 2.1 Bayesian aggregator
- **What.** Replace the current weighted-sum `final_confidence` with a
  proper Bayesian fusion of engine outputs. Each engine's calibrated
  probability becomes likelihood; cross-engine correlations are estimated
  from the historical log and used to deflate redundant signals.
- **Why.** Today, technical + SMC are highly correlated — they're double-counted
  by a weighted sum. Bayesian fusion correctly attributes ~75% of their
  joint information to one of them. Vedic timing is nearly independent —
  its small weight is correctly preserved.
- **Files.**
  - `backend/app/engines/bayesian.py` — fuse multiple `EngineOutput`
    objects into `P(direction | all_engines)`
  - `backend/scripts/estimate_engine_correlations.py` — offline mutual-info
    estimator; produces `~/.cache/marketlens/engine_corr.json`
- **Metrics.** Out-of-sample log-loss improvement ≥ 0.05 vs current weighted
  sum.
- **Success criteria.** Bayesian aggregator confidence is better calibrated
  (Brier ≤ 0.20) AND has lower realised drawdown on the live signal log.

### 2.2 Conflict scoring with calibrated severity
- **What.** Today `engines/consistency.py` uses hardcoded
  severity tiers (HIGH/MEDIUM/LOW). Replace with *empirical conflict cost*:
  measure the realised hit-rate degradation when each specific conflict
  fires, and weight accordingly.
- **Why.** Maybe Saturn-hora HIGH-conflict only costs 5% realised hit-rate
  (overweighted), while astro-direction HIGH-conflict costs 25%
  (correctly weighted). Stop guessing — measure.
- **Files.** `backend/scripts/measure_conflict_cost.py` — for each conflict
  type, query persisted signals where it fired vs where it didn't, compare
  realised hit-rates. `engines/consistency.py` loads the cost matrix at
  runtime.
- **Metrics.** Each conflict's measured cost has a 95% CI not crossing zero
  over ≥ 50 events.
- **Success criteria.** Strict-mode downgrades save more capital than they
  cost (measured as missed gains from upgraded WAITs that would have won).

### 2.3 Drop redundant engines (mutual information audit)
- **What.** Compute mutual information `I(engine_i ; engine_j)` over the
  signal log. If any pair has I > 0.6, drop the lower-edge one OR fuse
  them into a single engine.
- **Files.** `backend/scripts/engine_mutual_info.py`. Output: report
  + recommendation.
- **Metrics.** No two engines with I > 0.6 in the final stack.
- **Success criteria.** Same out-of-sample performance with fewer engines
  = simpler system, faster pipeline, fewer hyperparameters to tune.

---

## Tier 3 — Validation infrastructure

**Theme:** prove the system works (or doesn't) before trusting any number
in the UI.

### 3.1 Monte Carlo backtest with bootstrap
- **What.** Current `engines/backtest.py` is a single walk-forward run.
  Wrap it in a bootstrap loop: resample trade outcomes 1000× to get a
  *distribution* of realised metrics (Sharpe, hit-rate, drawdown) instead
  of a single point estimate.
- **Why.** A single walk-forward giving Sharpe=1.4 might be Sharpe ∈ [0.3, 2.5]
  with 95% CI — completely different decision.
- **Files.**
  - `backend/app/engines/backtest_mc.py` — wraps `backtest.run`,
    returns `MCReport` with `sharpe_mean`, `sharpe_p05`, `sharpe_p95`, etc.
  - `frontend/app/backtest/page.tsx` — surface the CI bands on the equity-
    curve chart.
- **Metrics.** Confidence intervals tight enough to be actionable
  (Sharpe CI width < 1.0 over 200 trades).
- **Success criteria.** Backtest page displays "Sharpe 1.4 [0.9, 1.8]"
  with shaded band on the equity curve.

### 3.2 Probabilistic forecasting
- **What.** `engines/forecast.py` currently outputs a daily *score* per
  symbol. Add a *return distribution* — quantile regression on
  technical + cyclical features to predict P(next-day-return > x).
- **Files.** `backend/app/engines/forecast_prob.py`. Use
  `sklearn.ensemble.GradientBoostingRegressor(loss="quantile", alpha=[0.1, 0.5, 0.9])`.
- **Metrics.** Pinball loss on 20% held-out fold.
- **Success criteria.** Predicted 10th-percentile move covers realised
  10th-percentile move within 5% absolute error.

### 3.3 Empirical astrology validation
- **What.** Statistically validate (or refute) each astrology rule the
  platform uses. Regression: `next_5_day_return ~ moon_nakshatra +
  hora_ruler + tithi + paksha + retrograde_count`. Drop features with
  non-significant coefficients.
- **Why.** Some astro rules may have real correlation (Mercury retrograde
  → higher whipsaw volatility?). Most won't. Be honest about which.
- **Files.** `backend/scripts/validate_astrology.py`. Output: report
  with coefficient + p-value per rule.
- **Metrics.** Each rule's coefficient 95% CI does or doesn't cross zero.
- **Success criteria.** Rules whose CI crosses zero are removed from
  scoring OR downgraded to LOW severity in the consistency validator.
  The UI surfaces "this rule has p=0.03 historical edge" vs "this rule
  has p=0.41 — kept for tradition, no measured edge."

---

## Tier 4 — Adaptive system

**Theme:** the platform learns from its own outcomes over time.

### 4.1 Market regime detector
- **What.** Classify current market regime: `TRENDING_UP`, `TRENDING_DOWN`,
  `CHOPPY`, `HIGH_VOL`, `LOW_VOL`. Use HMM or simple rules (ADX>25 +
  ATR percentile + price/200EMA distance).
- **Why.** Strategy weights that work in trends invert in chop. Without
  regime awareness, a trend-following engine will quietly bleed P&L during
  chop periods.
- **Files.** `backend/app/engines/regime.py`. Surface in dashboard header
  as a regime chip.
- **Metrics.** Regime stability — no more than 2 regime changes per month.
- **Success criteria.** Per-regime backtest stats are statistically
  distinguishable (different mean Sharpe), AND the system adapts weights
  per regime (see 4.2).

### 4.2 Meta-learner over regime
- **What.** Train a meta-model (gradient boosting) that takes the regime
  + per-engine raw scores as input and outputs the optimal weighted blend
  *per regime*. Weights become regime-conditional, not fixed.
- **Files.** `backend/app/engines/meta_learner.py`. Trained nightly by
  `backend/scripts/train_meta_learner.py`. Loaded into pipeline at startup.
- **Metrics.** Cross-validated Sharpe improvement ≥ 0.3 vs fixed-weight
  baseline, holding all else equal.
- **Success criteria.** During a chop regime, meta-learner correctly
  downweights trend-following engines. UI shows current weights and they
  visibly shift when regime flips.

### 4.3 Live feedback loop
- **What.** Persist every pipeline finalist + its outcome (WIN / LOSS /
  TIMEOUT) by checking actual price vs the entry/SL/T1 stored at signal
  time. Nightly job rebuilds the calibration tables (1.1, 1.2, 2.2)
  from the growing dataset.
- **Files.**
  - `backend/app/models/signal_outcome.py` — new table linking Signal→Outcome
  - `backend/app/services/outcome_marker.py` — daily cron-job that fetches
    last N days of OHLC and stamps each open signal
  - `backend/app/api/calibration.py` — `/api/calibration/realized` returns
    the calibration curve (predicted-bucket → realised hit-rate) for the UI
  - `frontend/app/accuracy/page.tsx` — new page showing realised hit-rate
    by confidence bucket and quality grade, with calibration curve
- **Metrics.** Realised vs predicted Brier score, updated weekly.
- **Success criteria.** After 60 trading days, the `/accuracy` page shows
  a calibration curve that's monotonically increasing — i.e. higher
  predicted confidence really does correspond to higher realised hit-rate.
  *This is the platform's only honest accuracy proof.*

### 4.4 Online learning (stretch)
- **What.** Convert the meta-learner from nightly batch to online updates
  (river / scikit-multiflow). Weights adapt within-day as outcomes
  arrive.
- **Files.** Significant — full feedback architecture. Punt to Tier 5.
- **Why deferred.** Online learning is fragile; do it only after Tier 4.3
  proves a stable calibration curve exists.

---

## Tier success ladder

| Tier | Time estimate | Key external dependency |
|---|---|---|
| 1 | ~3 weeks | None (uses existing data) |
| 2 | ~2 weeks | ≥ 200 logged signals with outcomes |
| 3 | ~4 weeks | ≥ 500 logged signals |
| 4.1–4.3 | ~6 weeks | ≥ 1000 logged signals (≈ 60 trading days live) |
| 4.4 | ~4 weeks | Tier 4 proven stable |

**Total honest timeline to production-grade adaptive system: 4–5 months
of live operation.** The first 60 trading days are pure data collection
— Tiers 2/3/4 cannot start until that dataset exists.

---

## Cross-cutting prerequisites

1. **Signal-outcome persistence** must ship first (it's the input to every
   tier). Already half-built (`/api/signals/live?persist=true`); just needs
   the daily outcome-marker job (4.3 file list).
2. **Live broker connection** — calibration on synthetic OHLCV is
   meaningless. The platform must run live for the data to be useful.
3. **CI/CD for the offline trainers** — calibrators and meta-learners
   must rebuild automatically; otherwise they go stale and silently
   degrade.

---

## What changes for the user as each tier ships

| User-visible after... | Change |
|---|---|
| Tier 1 | "Confidence" numbers become calibrated probabilities. UI tooltip: "of 100 trades at 70%, 65–75 historically hit T1 first." |
| Tier 2 | Conflict severities are measured, not hardcoded. Consistency banner explains *exactly* how much edge each conflict costs. |
| Tier 3 | Backtest page shows confidence bands on equity curve, not a single line. Astrology page marks each rule "measured edge p=X" or "no measured edge". |
| Tier 4 | Dashboard shows current regime + active weight blend. New `/accuracy` page proves realised matches predicted. |

---

## Killing the project — when to stop

If by end of Tier 4.3 (≈ 6 months in), the realised calibration curve is
**flat** (high-confidence signals win no more than low-confidence ones),
the platform has no measurable edge and pursuing 4.4 is wasted effort.
Honestly:

- Either keep it as an educational toolkit
- OR remove the trading recommendations and reposition as a market-cycles
  visualization product
- DO NOT continue to deploy real capital on a system whose calibration
  curve is flat

This exit criterion is the engineering brief's most important deliverable.
Build the measurement infrastructure first; the trading edge is what it
finds, not what we assert.
