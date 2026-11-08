# MarketLens — AI Trading Platform

> Bloomberg-style trading terminal combining Technical Analysis, Smart Money Concepts, Gann Theory, Vedic Astrology, Nakshatra cycles, Numerology, and F&O analytics — with Angel One SmartAPI execution.

**Disclaimer:** This platform is for **educational and analytical purposes only** and is **not SEBI-registered financial advice**. Astrology and numerology are positioned as an *alternative analytical layer* / *experimental confluence engine* — not as guaranteed predictors of market movement. Trade at your own risk.

---

## 🔥 The Pipeline — primary analysis flow

The **Pipeline** page is the platform's headline feature. It runs a strict 4-stage gated funnel
across the full NSE F&O universe (~180 stocks):

```
  Universe (180 symbols)
        ↓
  STAGE 1  ✦  Esoteric Pre-Filter
            • Per-symbol Astrology / Nakshatra match (Moon tara from symbol)
            • Numerology compatibility with today's date
            • Gann key-level proximity (Square of 9)
            • Fibonacci golden-ratio proximity (auto-pivot)
            → Symbols below esoteric_min get DROPPED.
        ↓
  STAGE 2  ✦  Technical Confirmation
            • RSI / MACD / EMA stack / Bollinger / ATR / ADX / VWAP
            • Smart Money Concepts: BoS, CHoCH, Order Blocks, FVGs
            • Multi-timeframe agreement
            → Stocks whose technical signal disagrees with esoteric lean get DROPPED.
        ↓
  STAGE 3  ✦  Strategy Selection
            • Picks best playbook based on direction + IV regime + capital:
              - EQUITY_BUY / EQUITY_SHORT
              - FUT_LONG  / FUT_SHORT
              - OPT_CE_BUY / OPT_PE_BUY
              - OPT_BULL_CALL_SPREAD / OPT_BEAR_PUT_SPREAD
              - OPT_IRON_CONDOR / OPT_LONG_STRADDLE / OPT_SHORT_STRANGLE
              - WAIT (no edge)
            • Computes entry / SL / multi-target / qty / capital allocation /
              expected max profit & loss / option legs.
        ↓
  STAGE 4  ✦  Accuracy Attachment
            • Runs a fast walk-forward backtest per finalist (last 120 bars)
            • Attaches hit-rate, profit factor, expectancy, max drawdown
            → Final confidence = 30% esoteric + 50% technical + 20% historical accuracy
```

**Visit `/pipeline`** in the UI to run it, tune thresholds, and see the funnel collapse the
180-symbol universe down to a handful of high-conviction finalists with full strategy plans.

---

## Stack

| Layer | Technology |
|---|---|
| Backend | Python 3.11+ / FastAPI / SQLAlchemy / SQLite |
| Astrology | Swiss Ephemeris (`pyswisseph`) — Vedic sidereal (Lahiri ayanamsa) |
| Technical | `pandas`, `numpy`, custom indicators (RSI, MACD, EMA, SMC, ICT) |
| Frontend | Next.js 14 / React / TypeScript / TailwindCSS |
| Charts | Recharts (lightweight); pluggable to TradingView Lightweight Charts |
| Broker | Angel One SmartAPI (`smartapi-python`) |
| State | SWR for client-side data fetching |

---

## Project layout

```
marketlens/
├── backend/
│   ├── app/
│   │   ├── main.py              # FastAPI entrypoint
│   │   ├── config.py            # Pydantic settings (.env)
│   │   ├── database.py          # SQLite + SQLAlchemy
│   │   ├── models/              # ORM models
│   │   ├── schemas/             # Pydantic I/O schemas
│   │   ├── api/                 # Route handlers
│   │   ├── engines/
│   │   │   ├── technical.py     # RSI/MACD/EMA/Bollinger/ATR/ADX/VWAP/Fib
│   │   │   ├── smc.py           # Smart Money Concepts + ICT
│   │   │   ├── astrology.py     # Vedic transits, Nakshatra, Moon phase
│   │   │   ├── numerology.py    # Symbol/date energy
│   │   │   ├── gann.py          # Square of 9, Angles, Time Cycles
│   │   │   ├── options.py       # Greeks, OI, PCR, Max Pain
│   │   │   └── decision.py      # AI confluence aggregator
│   │   ├── brokers/
│   │   │   ├── base.py
│   │   │   └── angelone.py      # SmartAPI wrapper
│   │   └── services/
│   │       ├── market_data.py
│   │       └── risk.py
│   ├── requirements.txt
│   └── run.py
├── frontend/
│   ├── app/                     # Next.js 14 app router
│   ├── components/              # Reusable UI
│   ├── lib/                     # API client + helpers
│   └── package.json
├── .env.example
├── start-backend.bat
├── start-frontend.bat
└── start-windows.bat            # one-shot launcher
```

---

## Quick start (Windows)

### Prerequisites
1. **Python 3.11+** — install from python.org (check "Add to PATH").
2. **Node.js 18+** — install from nodejs.org.
3. **Git** (optional but recommended).

### One-shot install + run

```powershell
# 1. Clone or download into d:\marketlens

# 2. Copy env template
copy .env.example .env
# (edit .env if you have Angel One creds; otherwise paper-trading mode)

# 3. Install + run everything
.\start-windows.bat
```

The launcher will:
- Create a Python virtualenv in `backend/.venv`
- `pip install -r backend/requirements.txt`
- `npm install` in `frontend/`
- Start FastAPI on **http://localhost:8000** (docs at `/docs`)
- Start Next.js on **http://localhost:3000**

### Manual install

**Backend**
```powershell
cd backend
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
python run.py
```

**Frontend** (in a second terminal)
```powershell
cd frontend
npm install
npm run dev
```

---

## Configuration (.env)

```ini
# Application
APP_ENV=development
SECRET_KEY=change-me-to-random-string
DATABASE_URL=sqlite:///./marketlens.db

# Angel One SmartAPI (leave blank for paper-trading)
ANGELONE_API_KEY=
ANGELONE_CLIENT_CODE=
ANGELONE_PASSWORD=
ANGELONE_TOTP_SECRET=

# Astrology
ASTRO_LATITUDE=19.0760     # Mumbai (NSE locality)
ASTRO_LONGITUDE=72.8777
ASTRO_TIMEZONE=Asia/Kolkata
ASTRO_AYANAMSA=LAHIRI

# Risk defaults
RISK_MAX_DAILY_LOSS_PCT=2.0
RISK_MAX_POSITION_PCT=5.0
```

---

## API endpoints

Full interactive docs: **http://localhost:8000/docs**

| Group | Endpoint | Purpose |
|---|---|---|
| **Pipeline** | `GET /api/pipeline/run` | **Full 4-stage gated pipeline (headline feature)** |
| Pipeline | `GET /api/pipeline/esoteric/{symbol}` | Stage 1 only for one symbol |
| Pipeline | `GET /api/pipeline/fibonacci/{symbol}` | Auto-detected Fib levels |
| Pipeline | `GET /api/pipeline/symbol-astro/{symbol}` | Per-symbol nakshatra match |
| Recommend | `GET /api/recommend/scan` | Top-N parallel scan (no gating) |
| Exit | `POST /api/exit/evaluate` | Should I sell this position? |
| Backtest | `GET /api/backtest/run/{symbol}` | Walk-forward accuracy report |
| Analysis | `POST /api/analysis/full` | Run full multi-engine analysis on a symbol |
| Technical | `POST /api/technical/score` | RSI/MACD/EMA/SMC scoring |
| Astrology | `GET  /api/astrology/transits` | Live planetary positions + Nakshatra |
| Astrology | `GET  /api/astrology/market-sentiment` | Bullish/bearish planetary read |
| Numerology | `GET  /api/numerology/symbol/{sym}` | Stock symbol energy score |
| Gann | `POST /api/gann/square9` | Square of 9 levels around a price |
| Gann | `POST /api/gann/time-cycles` | Time-reversal date projections |
| Options | `POST /api/options/analyze` | OI/PCR/Max Pain/Greeks |
| Signals | `GET  /api/signals/live` | Aggregated trade signals |
| Broker | `POST /api/broker/login` | Angel One SmartAPI login |
| Broker | `POST /api/broker/order` | Place order (live or paper) |

---

## Output schema (every trade signal)

```json
{
  "symbol": "RELIANCE",
  "trend": "BULLISH",
  "signal": "BUY",
  "confidence": 78.4,
  "entry": 2945.5,
  "stoploss": 2912.0,
  "targets": [2978.0, 3010.0, 3055.0],
  "risk_reward": 2.4,
  "reasons": {
    "technical": "RSI 62 rising; MACD bullish cross; price above 20/50 EMA; BoS at 2930",
    "astrology": "Moon in Pushya (wealth nakshatra); Jupiter trine natal Sun of NSE",
    "gann": "Price at 2x90° Square of 9 support; time cycle hits 2026-05-15",
    "numerology": "RELIANCE = root 4 (stable); today's date root 8 (Saturn favoring)",
    "options": "PCR 1.34 bullish; max pain 2950; institutional CE writing at 3000"
  },
  "capital_allocation_pct": 3.5
}
```

---

## Engine details

### Astrology engine
- **Swiss Ephemeris** computes accurate planetary positions (geocentric/heliocentric, sidereal/tropical).
- **Lahiri ayanamsa** for Vedic sidereal calculations (default).
- **27 Nakshatras** with each pada — Moon-driven volatility windows.
- **Planetary aspects** (conjunction, opposition, trine, square, sextile).
- **Mercury retrograde** detection (impacts comms/tech sectors).
- **Eclipse + Rahu/Ketu** transit flags.
- Output: `bullish_score`, `bearish_score`, `volatility_window_pct`, `intraday_timing_windows[]`.

### Gann engine
- **Square of 9** wheel — supports/resistances at 45°/90°/180°/360° from any price.
- **Gann Angles** — 1x1 / 2x1 / 1x2 / 4x1 / 1x4 from anchor pivots.
- **Time cycles** — 30/60/90/120/180/360-day projections from major highs/lows.
- **Price-time squaring** detects when price = time (bar count) for reversal.
- **Hexagon** for sector rotation.

### Numerology engine
- **Pythagorean** (A=1..Z=8/9) and **Chaldean** (no 9) systems for symbol/name reduction.
- Compound + root number, with planetary ruler mapping (1=Sun..9=Mars).
- **Date numerology** for trade day energy.
- **Compatibility** between trader's life-path number and stock symbol number.

### Technical / SMC / ICT engine
- Standard: RSI, MACD, EMA(9/20/50/200), SMA, Bollinger, ATR, ADX, VWAP, Fibonacci.
- **Smart Money Concepts**: Order Blocks, Fair Value Gaps, Liquidity Sweeps, Break of Structure, Change of Character.
- **ICT**: Killzones (London/NY open), Premium/Discount zones, IPDA price levels.
- Multi-timeframe confluence scoring.

---

## Roadmap (post-MVP)

- WebSocket live tick streaming (Angel One Smart WebSocket V2)
- Backtesting engine over historical data
- Strategy builder (drag-drop conditions)
- Telegram + WhatsApp + Email alert dispatch
- Insider/bulk-deals scraper (NSE)
- Mobile app (React Native — share API)
- Migrate SQLite → PostgreSQL + Redis cache
- Production deploy guide (Docker, NGINX, SSL)

---

## License & disclaimer (repeat)

Educational & research use only. Astrology/numerology layers are confluence enhancements — **never** the sole basis for capital deployment. Verify every signal independently. Past performance ≠ future results. The authors accept no liability for trading losses.
