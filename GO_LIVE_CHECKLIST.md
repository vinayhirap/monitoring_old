# Go-live checklist — from prototype to production trading platform

This document covers what's needed to take MarketLens from "code complete" to
"safe to operate with real-money users." It's organized by topic. Items marked
**[LEGAL]** require Indian-law knowledge — don't proceed on those without an
attorney familiar with SEBI law.

---

## 0. Decide your business model (do this FIRST)

This decision drives every other answer below. Pick exactly one:

### A) Pure education / research tool (recommended starting point)
- Platform shows analysis, signals, historical track record
- **No order placement on user's behalf** — the user trades elsewhere using their own broker
- All "recommendations" are explicitly framed as analytical opinions, not advice
- Disclaimer-heavy: every page, every signal, every export

### B) SEBI-registered Research Analyst (RA)
- Allows you to publish "buy XYZ at ₹X target ₹Y stop ₹Z"-style recommendations legally
- **Requirements**: ₹50L net worth, NISM RA exam, professional qualifications
- Annual SEBI fee + ongoing compliance reporting
- Cannot manage user money (just publish recommendations)
- Restrictions on personal trading in recommended scrips

### C) SEBI-registered Investment Advisor (IA)
- Stricter than RA. Can give personalized advice.
- Higher net-worth requirement (₹2.5Cr for non-individuals)
- More compliance overhead

### D) Algo trading provider (highest bar)
- Place orders on behalf of users automatically
- Exchange algo approval required (NSE/BSE)
- Empanelment with a broker required
- Kill switch + audit logs mandated
- Each algo must be approved separately
- **Don't go here without a regulatory lawyer.** Recent enforcement has been aggressive.

The platform code **enables** all four paths. **Which one you operate under is your choice.**

---

## 1. Pre-launch (before the first real-money user)

### Engineering
- [ ] Auto-deploy working (`/.github/workflows/deploy.yml` — see `DEPLOY_SETUP.md`)
- [ ] Test suite passing in CI (`backend/pytest.ini` + `backend/tests/`)
- [ ] Backend health probe returns `status: ok` on `/api/health?detailed=true`
- [ ] All subsystem health items show `ok: true` (database, login_limiter, picks_scanner)
- [ ] Backups configured for the SQLite/Postgres database (daily, off-host)
- [ ] HTTPS terminated (Nginx/ALB) — never run uvicorn raw on port 80
- [ ] Log rotation set up (`/var/log/marketlens-*.log` filling the disk is a known production failure)

### Data
- [ ] Signal journal has at least **30 evaluated entries** before showing KPIs publicly
- [ ] Calibration fit produces a sensible reliability curve (`/portal/performance` shows it hugging the diagonal)
- [ ] Engine weight refit script tested (`/api/admin/refit-weights`)

### Security
- [ ] Default OWNER password changed from anything written in docs
- [ ] All admin endpoints return 401/403 without auth (`pytest test_api_smoke.py`)
- [ ] Login rate limiter active (`/api/health?detailed=true` shows backend)
- [ ] Password policy enforced (test signup with `password1` — must reject)
- [ ] CORS origins list is the actual production domain (not `*`)
- [ ] Environment file (`.env`) is **not** in git (verify with `git ls-files | grep env`)
- [ ] JWT secret is at least 32 random bytes (regenerate before launch)

### Operational
- [ ] Detailed health check responds (`curl /api/health?detailed=true`)
- [ ] Audit log accumulates entries (every user mutation should leave a trail)
- [ ] Telegram bot can be reached from EC2 (`/api/admin/telegram/diagnose` — add this endpoint if you want it)
- [ ] Twitter bot tested with one manual post (gate the auto-publish until ready)

### Regulatory **[LEGAL]**
- [ ] Decided your business model (A/B/C/D from §0)
- [ ] Terms of Service drafted by a lawyer who knows Indian fintech law
- [ ] Privacy policy compliant with the Digital Personal Data Protection Act 2023
- [ ] Disclaimer text reviewed by counsel (educational vs advice line)
- [ ] If RA-registered: NISM certificate + ₹50L NW certificate visible in admin console
- [ ] Risk Disclosure Document (RDD) acknowledged by every user at signup

---

## 2. Soft launch (paper mode only, friends and family)

### What to verify with 10-50 internal users
- [ ] Signup flow works end-to-end (email normalization, password policy)
- [ ] Login rate limiter triggers on 5 failures (verify it actually locks them out)
- [ ] Tier gating works (FREE user cannot see Commodities/INTRADAY)
- [ ] Recommendations refresh every 5 min via the picks scanner
- [ ] Telegram bot posts to the right tier channels (if configured)
- [ ] Twitter bot posts to public feed (if configured)
- [ ] Paper trades execute via `/api/trade/place` with `is_paper=true`
- [ ] Position P&L updates correctly when LTP moves
- [ ] Risk-guard blocks oversized trades (test: try to place a trade risking >2% of capital)
- [ ] Loss circuit-breaker activates after 5 consecutive losing paper trades
- [ ] Hindi UI works (toggle language, verify nav labels + explanations)
- [ ] Mobile layout works on a ≤375px screen (iPhone SE width)

### What you'll fix in soft launch
Plan for 2-4 weeks of paper-only operation. Expect to:
- Find UX issues that didn't show up in testing
- Discover engine edge cases (some symbol with weird data crashes a panel)
- Tune the calibration weights based on actual journal data
- Refine the recommendation tier-floor (`min_stars_visible`) based on user feedback

---

## 3. Going live (real money — only after soft launch)

### Pre-flight checks
- [ ] Soft launch ran ≥30 days with no critical bugs
- [ ] Signal journal has ≥200 evaluated entries
- [ ] Performance dashboard shows hit rate ≥52% (above NIFTY long bias)
- [ ] Brier score <0.22 (calibrated, not miscalibrated)
- [ ] Calibrator is active and Brier improvement is positive

### Live-trading gates
- [ ] Each user must complete a separate Angel One auth flow (NOT use your developer creds)
- [ ] User explicitly opts in to live mode in their settings
- [ ] Live mode requires re-authentication (password) before each session
- [ ] Live order placement has a hard cap on quantity that admins can adjust per-user
- [ ] Risk-guard rejection on live orders MUST block the trade (test with a 5% SL trade — should be refused)

### Day-0 operational
- [ ] Kill switch — an admin endpoint that puts the entire system in read-only mode immediately (`POST /api/admin/system/freeze`). Not yet built — see backlog.
- [ ] On-call rotation defined (who responds to a 3am order-routing failure?)
- [ ] Incident playbook for: broker auth failure, Angel One rate-limit cascade, calibrator producing garbage, signal scanner stalled
- [ ] Telegram channel for status updates (separate from signal channels)

---

## 4. The trading-application checklist (built in this turn)

What's now in place for trade execution:

| Component | Status |
|---|---|
| Order intent → DB record BEFORE broker contact | ✅ `Order` table |
| Idempotency (30s same-trade dedup) | ✅ `_check_duplicate` in trade_executor |
| Pre-trade risk gate re-runs at execution moment | ✅ `_run_risk_gate` |
| Risk-guard snapshot stored with every order (for audit) | ✅ `order.risk_guard_snapshot` |
| Paper-mode simulation (no broker call, virtual fills at LTP) | ✅ `_simulate_fill` |
| Live broker order submission via Angel One | ✅ `_submit_to_broker` |
| Position tracking with weighted-avg entry price | ✅ `_apply_fill_to_position` |
| Realized P&L computation on REDUCE/CLOSE fills | ✅ `TradeFill.realized_pnl` |
| Unrealized P&L at read time from LTP | ✅ `list_positions` endpoint |
| Order cancellation (paper + live) | ✅ `cancel()` in trade_executor |
| Trading summary (open count, P&L, win rate) | ✅ `/api/trade/summary` |
| UI: Positions page with auto-refresh | ✅ `/portal/positions` |
| UI: Orders page with cancel button | ✅ `/portal/orders` |
| UI: OrderConfirmModal wired to new endpoint | ✅ Re-wired |

What's intentionally NOT in this implementation (your future work):

| Component | Why deferred |
|---|---|
| **Real-time fill notifications via WebSocket** | Needs broker WebSocket integration + frontend SSE — substantial; for now we poll every 10s |
| **Bracket / cover orders (broker-side)** | Angel One's bracket order API is being deprecated; using local SL/T simulation is simpler |
| **Margin / cash check before order placement** | Requires per-user margin query; pulls from `broker.funds()` which exists but isn't wired |
| **Tax-loss harvesting / tax report PDF export** | Not a Day-1 feature; build when users ask |
| **Order modification (change SL/qty in place)** | Most users prefer cancel-and-reorder; skip until specifically requested |
| **Multi-user broker accounts (each user logs in to their own Angel One)** | Architectural change — currently single broker_instance is shared; for multi-user live trading, refactor to per-user broker sessions |
| **Kill switch / system freeze admin endpoint** | One-day fix; ship before live launch |
| **Automated outcome tracking for executed trades** | Right now positions are tracked; closing them and feeding back to signals_journal for the calibrator isn't auto-wired |

---

## 5. Architecture reference — what calls what

```
User clicks "Place Order" in SimpleRecommendation
       │
       ▼
<OrderConfirmModal>  (frontend)
   • Shows SL/T1/T2/T3 + R:R
   • User checks acknowledgment + clicks Confirm
       │
       ▼ POST /api/trade/place {Authorization: Bearer JWT}
       │
       ▼
api/trade.py:place_order  (FastAPI handler)
   • require_tier("BASIC") — auth + tier gate
   • Build OrderIntent dataclass
       │
       ▼
services/trade_executor.py:execute  (the safety-wrapped layer)
   • _check_duplicate — idempotency dedup
   • Basic validation (qty>0, direction valid)
   • _run_risk_gate — risk_guard.check() at THIS moment
        → If rejected: write FAILED order, return ExecutionResult(ok=false, risk_guard=...)
        → If accepted: continue
   • Create exec_orders row (status PENDING_RISK_CHECK)
   • Transition to PENDING_BROKER
       │
   ┌───┴──────────────────────────┐
   │                              │
   ▼ (is_paper=true)              ▼ (is_paper=false)
   _simulate_fill                  _submit_to_broker
   • Get current LTP                • broker_instance.place_order(...)
   • Create TradeFill at LTP        • On ack: status=OPEN
   • _apply_fill_to_position        • On rejection: status=REJECTED
   • status=FILLED                  • Order tracking polls broker (TODO: poller)
   │                              │
   └───┬──────────────────────────┘
       ▼
   Return ExecutionResult to API → JSON to frontend → UI updates
```

---

## 6. Final honest assessment

The platform is **technically complete for paper trading.** Users can:
- Sign up, subscribe to a tier
- Browse recommendations with risk-guarded SL/T levels
- Place paper orders that simulate fills at live LTP
- See live P&L on positions
- Cancel outstanding orders
- See historical fill data
- View their track record built from journal evaluations

For real-money trading you still need:
1. The **legal decision** in §0 of this document
2. **Per-user broker accounts** (the multi-tenant broker refactor)
3. **Kill switch + monitoring**
4. **30+ days of paper-mode user testing**
5. **A real lawyer review** of your TOS, privacy policy, and risk disclosure

The code is ready. The business and legal infrastructure isn't — that's
the work no one else can do for you.
