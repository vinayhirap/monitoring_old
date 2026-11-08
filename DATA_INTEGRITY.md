# Data integrity — debugging when the price shown is wrong

The COALINDIA bug (₹1827 in app vs ₹457 real) is the canonical example
of what this guide solves. Use this when a user reports a price that's
clearly different from their broker terminal / TradingView.

## How the platform protects users now

Every call to `/api/symbol/{ticker}` runs a **price sanity cross-check**:

1. **Last candle close** (from `get_ohlcv`)
2. **Live broker LTP** (from `broker_instance.quote()`)
3. **Spot used in analysis** (the live_spot value the engines see)

If any pair disagrees by more than **2%**, the response includes:

```json
{
  "price_sanity": {
    "verdict": "SUSPECT",
    "candle_close": 1827.80,
    "broker_ltp": 457.55,
    "discrepancy_pct": 75.0,
    "reasons": [
      "Candle close ₹1827.80 differs from broker LTP ₹457.55 by 75.00% — likely wrong instrument token or stale cache."
    ]
  }
}
```

The frontend ALWAYS surfaces a SUSPECT verdict:

- **User portal** (`SimpleRecommendation`): the entire recommendation card
  is hidden behind a red "do not trade" banner. **No misleading analysis
  is shown.**
- **Admin/advanced symbol page**: a red banner appears at the top of the
  page with diagnostic numbers; the rest of the page still renders so
  admins can debug.

## Common root causes (in order of frequency)

### 1. Wrong scrip-master mapping (most common)

After a corporate action — bonus issue, stock split, name change — the
old token may still be in the scrip-master cache. The cache returns the
PRE-event symbol/token mapping; the engine fetches candles for that
token; the candles look fine but they're for the OLD instrument.

**Verify:**
```bash
curl https://your-server/api/market/diagnose/COALINDIA
```

Look at step 1's output. If `name` field doesn't match the user-visible
name (or if no row at all), the mapping is broken.

**Fix:**
```bash
curl -X POST https://your-server/api/market/instruments/refresh
# Then re-run the diagnose call. Step 1 should now show the right name.
```

### 2. Stale candle cache (post-event)

Even after refreshing the scrip master, the in-memory + DB candle cache
might still have pre-event prices. The cache key is `(symbol, exchange,
interval)` — and the SYMBOL string didn't change, so the cache lookup
hits stale rows.

**Verify:** in `/api/market/diagnose/{sym}` output, step 4 returns the
sanity report with `last_bar_at`. If the last bar is from BEFORE the
corporate action date, the cache is stale.

**Fix:**
```bash
# Wipe the long-term cache for this symbol and re-backfill from scratch
curl -X POST "https://your-server/api/backfill/run?symbols=COALINDIA&force=true"
# Wait a minute for backfill to complete, then reload the symbol page.
```

### 3. Wrong exchange segment

User requests symbol on NSE but it's actually trading on BSE (or vice
versa). Common with dual-listed scrips and ADRs.

**Verify:** the symbol page URL has `?exchange=NSE` query — try `?exchange=BSE`.
If the diagnose endpoint with `exchange=BSE` returns OK, that's the fix.

**Fix:** Edit the instrument's `default_exchange` in your scrip-master
config, or just instruct users to specify the correct exchange.

### 4. Synthetic-fallback leaking through

If `LIVE_ONLY=false` in the backend `.env`, the system can fall back to
`synthetic_ohlcv()` when broker calls fail. Synthetic data has reasonable
shapes but completely fictional prices.

**Verify:** `/api/symbol/{ticker}` returns `"data_source": "synthetic_fallback"`
when this happens. The UI shows a warning banner.

**Fix:** Set `LIVE_ONLY=true` in `.env` and restart. Then OHLCV failures
return HTTP 503 instead of silently serving fake data — the UI shows a
"live feed unavailable" state instead of a fake recommendation.

## Diagnostic walkthrough — the COALINDIA scenario

The user reported COALINDIA at ₹1827 (app) vs ₹457 (TradingView).
What an admin should do:

```bash
# Step 1: confirm the platform agrees something's wrong
curl https://your-server/api/symbol/COALINDIA \
  -H "Authorization: Bearer <admin_token>" \
  | jq '.price_sanity'

# Expected output: verdict="SUSPECT", reasons names the issue.

# Step 2: drill into which layer is broken
curl https://your-server/api/market/diagnose/COALINDIA \
  -H "Authorization: Bearer <admin_token>" \
  | jq

# Read the "steps" array. The first ok=false is the root cause.

# Step 3: based on the failing step, apply the matching fix above.

# Step 4: re-run /api/market/diagnose/COALINDIA. Verify overall_ok=true.

# Step 5: tell the user to reload the symbol page.
```

## Hard guards in the code

These protections live in code so they survive any future regression:

- **`app/services/price_sanity.py`** — does the 3-way cross-check
- **`app/api/symbol.py`** — calls sanity on every request, returns verdict
- **`app/api/market.py:diagnose_symbol`** — step-by-step trace endpoint
- **`SimpleRecommendation.tsx`** — refuses to render analysis when SUSPECT
- **`app/symbol/[ticker]/page.tsx`** — full-width red banner when SUSPECT

The 2% threshold is set in `price_sanity.py` as
`MAX_PRICE_DISCREPANCY_PCT`. Increase it cautiously — at 5% you'd miss
the COALINDIA case (75% off) but also the 3% normal-day discrepancy
when a stock has gapped between candle close and the live LTP.

## When the sanity check is intentionally SUSPECT

There are legitimate cases:
- **Open auction window** (09:00–09:08): broker LTP differs from the
  previous close substantially
- **Symbol mid-suspension** (announced corporate event): broker LTP
  doesn't update, candle close is stale
- **Holiday next day**: the candle is from the prior session

The sanity check will still flag these. The user-facing message
explains the discrepancy; the admin can override by tagging the symbol
in `instruments.suspension_list` (TODO if you want to silence specific
known-flagged symbols).

## Long-term: never trust a single source

The COALINDIA bug taught us not to trust any one data path. Every price
that drives a recommendation should be backed by two sources that agree:

- **Strategy execution** uses `ltp_data["ltp"]` (the live broker quote
  refresh) rather than the candle close
- **Risk guard** uses the broker LTP for the per-share risk calculation
- **Stop-loss engine** uses the live spot for level proximity

Each of these is a place where a 75% data error would cascade into
catastrophic position sizing. The sanity check is the safety net under
all of them.
