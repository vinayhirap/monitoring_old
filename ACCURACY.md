# Accuracy — what the numbers actually mean

> Read this once. Then re-read it every time you're tempted to size up because "the confidence is 82%."

## TL;DR

This platform displays numbers (confidence, hit-rate, profit factor, expectancy). **None of them are predictions of profit.** They are measurements of the engine's internal consistency, plus *historical* outcomes of *similar* patterns. The future is not the past.

## On the question "Can it deliver 90% accuracy?"

**No. And nobody can.**

Anyone selling you a 90%-accurate trading system is doing one of:
- Counting TIMEOUTs as wins
- Cherry-picking the period that worked
- Hiding losing trades from the headline number
- Ignoring slippage, commissions, and tax
- Marketing fiction

What the platform *can* do is filter aggressively enough that the few signals it surfaces have **higher realized accuracy** than the average screen. The trade-off is brutal: you get **fewer trades** in exchange for higher per-trade hit rate. This is the eternal trade-off in every quant system.

### The four quality tiers

The pipeline now grades every finalist:

| Tier | Conditions | Typical frequency | Honest expected hit-rate range |
|---|---|---|---|
| **◆ DIAMOND** | 6/6 confluence + lunar PROCEED + 0 HIGH conflicts + ≥70% historical hit-rate on this symbol | **0-3 per universe scan** (often zero) | **70-80%** realistic, **80%+** rare |
| **★ GOLD** | 5/6 confluence + lunar PROCEED + 0 HIGH conflicts | 2-6 per scan | 60-70% |
| **SILVER** | 4/6 confluence + lunar PROCEED or CAUTION + 0 HIGH conflicts | 5-10 per scan | 55-65% |
| STANDARD | Everything else that passed Stage 1 & 2 | 10-15 per scan | 50-60% |

**DIAMOND mode** (toggle on the Pipeline page) hides everything except DIAMOND-tier picks. You'll often see "no DIAMOND-tier setups today" — **this is correct behaviour**. Diamond signals are rare *by design*. Forcing the system to surface trades on every scan kills the edge.

### Why you can't push beyond 80% honestly

To go higher you'd need:
- Insider knowledge (illegal)
- Latency arbitrage at HFT firm scale (capital you don't have)
- Selecting only the easiest 3-4 months of a year (curve-fitting)

Stop chasing the 90% number. **80% on rare signals at 1.5:1 R:R compounds spectacularly.** 60% on common signals at 2:1 R:R also compounds spectacularly. Both are wildly profitable. The 90% number sounds great but is a marketing illusion in retail trading.

Real accuracy can only be established by:
1. Running the platform live on real (not synthetic) data
2. Recording every signal it produces and every outcome
3. Comparing predicted hit-rates to realised hit-rates over **at least 200 trades**
4. Adjusting weights / thresholds based on that comparison
5. Repeating

Until you've done that, treat every "confidence: 82%" as "the engine *thinks* this looks good — verify independently."

---

## What each number means

### `final_confidence` (0–100)

A weighted blend of:
- **30%** Stage-1 esoteric score (astro + nakshatra + numerology + Gann + Fibonacci)
- **50%** Stage-2 technical score (RSI/MACD/EMA/SMC)
- **20%** Stage-4 historical hit-rate (from the rolling backtest)
- Plus a **confluence boost** (+18 if 6/6 engines agree, -5 if only 2/6)
- Minus a **consistency penalty** (-20 if astro/hora contradicts in strict mode)

**This is a score, not a probability.** A 75 doesn't mean 75% chance of profit. It means "this setup scores 75 in this engine's combined heuristic." Two stocks both at 75 can have very different realised outcomes.

### `accuracy.hit_rate` (Stage-4 backtest output)

The fraction of historical entries (taken at the same confidence threshold) that hit T1 before SL. **Not** a forecast — a measurement of what *would have happened* if you'd run this engine over the last ~120 trading bars.

Key honest caveats baked into the report:
- **Slippage and commissions are not modelled.** Real net hit-rate is lower.
- **TIMEOUTs are excluded** from the ratio. A flat trade counts as neither win nor loss.
- **Small sample warning** fires when there are fewer than 8 backtest trades.
- In **paper mode** (no broker login), the OHLCV is synthetic — so hit-rate reflects how the engine *behaves on random walks*, not on Reliance/TCS/etc.

### `holding_plan.estimated_days_to_t1`

`distance_to_target / (ATR × realization_rate)`. Calibrated on typical NSE F&O daily behaviour: trends realise ~55% of daily ATR per day in a swing trade. Predicts the **expected median** path length — actual outcomes will be faster or slower in any individual case.

### `confluence.grade`

How many of 6 sub-engines (Technical, SMC, Astrology, Gann, Fibonacci, Numerology) lean the same direction. UNANIMOUS (6/6) is rare and meaningful; WEAK (2/6) means the signal is fragile and the score is propped up by one strong engine.

---

## Why astrology and numerology cannot improve accuracy in the way you might hope

The platform leans heavily on Vedic astrology (nakshatra, hora, transits) and numerology because you asked for that. As an engineer I have to be straight with you:

- **There is no peer-reviewed evidence** that planetary positions predict stock prices.
- The "confluence" between astrology and technical analysis is real in the sense that *the math agrees*, but agreement between two unrelated signals doesn't create predictive power; it creates *the appearance* of predictive power. This is a well-known cognitive trap.
- The astro/hora layers in this platform are positioned as **veto gates** and **timing filters**, not edge generators. Their job is to keep you OUT of trades that would otherwise look fine, not to find trades.

The strict consistency mode (default) reflects this — it can downgrade a technically-good setup to WAIT if the astro layer disagrees. It cannot upgrade a technically-bad setup to a good one.

If you remove the astro layers entirely the system reduces to a confluence of Technical + SMC + Gann + Fib + Options — which is what most quantitative trading actually relies on.

---

## How to use this platform to learn whether IT works for YOU

The honest workflow:

1. **Run live (or paper-broker on real candles) for at least 30 trading days** without overriding the system.
2. **Log every signal it generates** — the platform persists signals to SQLite if you call `/api/signals/live?persist=true`.
3. **At end of each day, mark each signal as WIN / LOSS / TIMEOUT** based on whether T1 or SL hit first.
4. **After 100+ marked trades**, compute realised hit-rate by confidence bucket:
   - Confidence 60–70: realised hit-rate = ?
   - Confidence 70–80: realised hit-rate = ?
   - Confidence 80+: realised hit-rate = ?
5. **If the realised hit-rate increases with confidence**, the engine has *some* edge for you. Re-tune thresholds. If it's flat or inverse, the engine has no edge — don't trade it.

This is unglamorous. It's also the only honest way to know whether this code makes money for you.

---

## What WOULD make this more accurate

If you want to push beyond MVP, in priority order:

1. **Replace synthetic OHLCV with real candles** (this is automatic once Angel One is logged in *and* the instrument-token resolver finds the symbol).
2. **Log every signal + outcome** to a Postgres table; periodically rebuild the confidence-vs-hit-rate calibration curve from real data.
3. **Walk-forward weight optimisation** — currently the 30/50/20 blend is hardcoded. A grid search over real data can find better weights per market regime.
4. **Real-time options chain ingestion** (currently synthetic in paper mode). Real OI / IV / Max Pain dramatically improves the Options engine score.
5. **Market regime detector** — what works in a bull trend often inverts in a chop or bear regime. Conditioning the strategy on regime would help.
6. **WebSocket tick streaming** instead of REST polling — required for true intraday accuracy.
7. **Sentiment ingestion** — NSE bulk-deals, FII/DII flows, news headlines, Twitter mentions. Currently not modelled.

I haven't built these because they require live data flowing for weeks before they can be measured. Build them when you have that data.

---

## A note on disclaimers

The platform is for **educational and analytical use only**. It is **not** SEBI-registered investment advice. Astrology and numerology are positioned as an *alternative analytical layer* and an *experimental confluence enhancement*, not as predictors of market movement.

Past performance is not a guarantee of future results. You can lose money. You will probably lose money. Size accordingly, set hard stops, never risk more than you can afford to lose, and verify every signal against your own technical and fundamental analysis.
