"""FastAPI entry point."""
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import ORJSONResponse
from loguru import logger

from app.config import settings
from app.database import init_db
from app.api import (
    analysis,
    technical,
    astrology,
    numerology,
    gann,
    options,
    signals,
    broker,
    market,
    exit as exit_api,
    recommend,
    backtest,
    pipeline,
    hora,
    alerts as alerts_api,
    risk as risk_api,
    forecast as forecast_api,
    advanced as advanced_api,
    moon as moon_api,
    ml as ml_api,
    symbol as symbol_api,
    # Professional layer (added in the 8-block upgrade)
    journal as journal_api,
    risk_advanced as risk_adv_api,
    portfolio as portfolio_api,
    backtest_pro as backtest_pro_api,
    ml_pro as ml_pro_api,
    backfill as backfill_api,
    auth as auth_api,
    commodities as commodities_api,
    quant as quant_api,
    calibration as calibration_api,
    nse as nse_api,
    portal as portal_api,
    subscription as subscription_api,
    optimize as optimize_api,
    astro_lab as astro_lab_api,
    scanner_admin as scanner_admin_api,
)
from app.ws import server as ws_server


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Starting MarketLens backend (env={}, paper={}, live_only={})",
                 settings.app_env, settings.paper_mode, settings.live_only)

    # Credentials diagnostic — print which ones were found (don't print values)
    cred_status = {
        "ANGELONE_API_KEY":      "✓ set" if settings.angelone_api_key else "✗ MISSING",
        "ANGELONE_CLIENT_CODE":  "✓ set" if settings.angelone_client_code else "✗ MISSING",
        "ANGELONE_TOTP_SECRET":  "✓ set" if settings.angelone_totp_secret else "✗ MISSING",
        "ANGELONE_PASSWORD":     "✓ set (optional)" if settings.angelone_password else "— blank (optional)",
        "LIVE_ONLY":             "✓ true" if settings.live_only else "false",
    }
    logger.info("Credentials check:")
    for k, v in cred_status.items():
        logger.info("  {:30s} {}", k, v)

    init_db()

    # Warm Angel One scrip master cache in the background (~25MB download once/day).
    try:
        import threading
        from app.services import instruments
        threading.Thread(target=instruments.load, name="scrip-master-loader", daemon=True).start()
    except Exception as e:
        logger.warning("instrument master warmup failed: {}", e)

    # Daily signals-journal retention purge — keep last 14 days. Runs every 6h.
    try:
        import threading, time as _t
        from app.services.signals_logger import purge_older_than_days
        def _retention_loop():
            while True:
                _t.sleep(6 * 3600)        # every 6 hours
                try:
                    purge_older_than_days(days=14)
                except Exception as e:
                    logger.debug("retention purge crashed: {}", e)
        threading.Thread(target=_retention_loop, name="journal-retention", daemon=True).start()
        logger.info("Journal retention thread started (14-day window, purges every 6h)")
    except Exception as e:
        logger.warning("retention setup failed: {}", e)

    # Load ML models if previously trained (silent no-op if not trained yet)
    try:
        from app.engines import ml
        if ml.load():
            logger.info("ML ensemble loaded — predictions available via /api/ml/predict")
        else:
            logger.info("ML models not yet trained — POST /api/ml/train to enable")
    except Exception as e:
        logger.warning("ML load failed: {}", e)

    # Auto-login at startup + background retry loop (LIVE_ONLY mode).
    from app.brokers.angelone import broker_instance, BrokerError
    import threading, time

    def _attempt_login(reason: str) -> bool:
        try:
            broker_instance.login()
            if broker_instance.is_authenticated():
                logger.success("✓ Angel One auto-login OK ({}) — LIVE mode", reason)
                return True
            logger.warning("Angel One auto-login: {} — not authenticated", reason)
        except BrokerError as e:
            broker_instance._last_error = str(e)
            logger.error("LIVE_ONLY login failed ({}): {}", reason, e)
        except Exception as e:
            broker_instance._last_error = str(e)
            logger.exception("Auto-login crashed ({}): {}", reason, e)
        return False

    def _retry_loop():
        while True:
            time.sleep(300)   # 5 min
            if broker_instance.is_authenticated():
                continue
            logger.info("Retrying Angel One login (broker still unauthenticated)…")
            _attempt_login("retry")

    if not settings.paper_mode:
        ok = _attempt_login("startup")
        if not ok and settings.live_only:
            logger.error(
                "⚠ LIVE_ONLY=true but auto-login failed. Backend will serve 503 "
                "for market-data endpoints until login succeeds. Retry every 5 min. "
                "Visit /api/broker/diagnose for step-by-step root cause."
            )
        if settings.live_only:
            threading.Thread(target=_retry_loop, name="broker-retry", daemon=True).start()
    else:
        if settings.live_only:
            logger.error(
                "⚠ LIVE_ONLY=true but credentials missing in .env. Set "
                "ANGELONE_API_KEY + ANGELONE_CLIENT_CODE + ANGELONE_TOTP_SECRET."
            )
        else:
            logger.info("PAPER mode — set credentials in .env to enable live trading")

    # Start the background picks scanner — it precomputes /top-picks every
    # SCAN_INTERVAL_MINUTES so the API endpoint responds in milliseconds
    # instead of running a full scan inline per request.
    try:
        from app.jobs import picks_scanner
        picks_scanner.start_scheduler()
    except Exception as e:
        logger.warning("Picks scanner failed to start: {} — API will fall back to inline scan", e)

    # Start the order-status poller — reconciles OPEN/PARTIAL live orders
    # with the broker every 30s so fills propagate to our DB and the UI
    # eventually shows FILLED instead of OPEN forever. No-op if broker
    # isn't authenticated (it self-checks each pass).
    try:
        from app.jobs import order_status_poller
        order_status_poller.start_scheduler()
    except Exception as e:
        logger.warning("Order status poller failed to start: {} — live orders won't auto-update", e)

    yield

    # Stop schedulers cleanly on shutdown
    try:
        from app.jobs import picks_scanner
        picks_scanner.stop_scheduler()
    except Exception:
        pass
    try:
        from app.jobs import order_status_poller
        order_status_poller.stop_scheduler()
    except Exception:
        pass

    logger.info("Shutting down MarketLens backend")


app = FastAPI(
    title="MarketLens API",
    version="0.1.0",
    description=(
        "AI trading platform combining Technical Analysis, Smart Money Concepts, "
        "Gann Theory, Vedic Astrology, Numerology and F&O analytics. "
        "**Educational use only — not SEBI-registered financial advice.**"
    ),
    default_response_class=ORJSONResponse,
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# CSRF protection — installed but disabled by default. Activates when
# CSRF_PROTECTION_ENABLED=true in env. Needed only when you switch from
# Bearer-token auth to cookie auth. See app/middleware/csrf.py for the
# full rationale + frontend hook-up steps.
from app.middleware import csrf as csrf_middleware
csrf_middleware.install(app)


@app.get("/", tags=["health"])
async def root():
    return {
        "service": "MarketLens API",
        "version": "0.1.0",
        "paper_mode": settings.paper_mode,
        "docs": "/docs",
    }


@app.get("/health", tags=["health"])
@app.get("/api/health", tags=["health"])
async def health(detailed: bool = False):
    """Health probe.

    Default (no params) returns the minimal {status: ok} payload that the
    auto-deploy workflow + load balancer health checks rely on. Setting
    `?detailed=true` triggers a per-subsystem probe — DB, broker,
    scheduler, limiter backend, optional integrations. Use the detailed
    view for ops dashboards and incident debugging.
    """
    if not detailed:
        return {"status": "ok"}

    from datetime import datetime
    from sqlalchemy import text

    subsystems: dict = {}

    # ---- Database ----
    try:
        from app.database import SessionLocal
        with SessionLocal() as db:
            db.execute(text("SELECT 1"))
        subsystems["database"] = {"ok": True}
    except Exception as e:
        subsystems["database"] = {"ok": False, "error": str(e)}

    # ---- Broker (Angel One) ----
    try:
        from app.brokers.angelone import broker_instance
        subsystems["broker"] = {
            "ok": broker_instance.is_authenticated(),
            "mode": "live" if broker_instance.is_authenticated() else
                     "paper" if settings.paper_mode else "unauthenticated",
            "last_error": getattr(broker_instance, "_last_error", None),
        }
    except Exception as e:
        subsystems["broker"] = {"ok": False, "error": str(e)}

    # ---- Login rate limiter backend ----
    try:
        from app.services import auth_service
        subsystems["login_limiter"] = {
            "ok": True, "backend": auth_service.get_backend_name(),
        }
    except Exception as e:
        subsystems["login_limiter"] = {"ok": False, "error": str(e)}

    # ---- Background scanner ----
    try:
        from app.jobs import picks_scanner
        sched = picks_scanner._scheduler
        subsystems["picks_scanner"] = {
            "ok": sched is not None,
            "running": sched is not None and sched.running,
            "interval_minutes": picks_scanner.SCAN_INTERVAL_MINUTES,
        }
    except Exception as e:
        subsystems["picks_scanner"] = {"ok": False, "error": str(e)}

    # ---- Telegram bot (optional) ----
    try:
        from app.services import telegram_bot
        subsystems["telegram_bot"] = {
            "ok": True, "configured": telegram_bot.is_configured(),
        }
    except Exception as e:
        subsystems["telegram_bot"] = {"ok": False, "error": str(e)}

    # ---- Twitter bot (optional) ----
    try:
        from app.services import twitter_bot
        subsystems["twitter_bot"] = {
            "ok": True, "configured": twitter_bot.is_configured(),
        }
    except Exception as e:
        subsystems["twitter_bot"] = {"ok": False, "error": str(e)}

    # ---- Local LLM (optional) ----
    try:
        from app.services import local_llm
        subsystems["local_llm"] = local_llm.get_status()
    except Exception as e:
        subsystems["local_llm"] = {"ok": False, "error": str(e)}

    # ---- Calibrator (offline-ML) ----
    try:
        from app.services import calibration_fit
        cal = calibration_fit.get_active_calibrator()
        subsystems["calibrator"] = {
            "ok": True,
            "active": cal is not None,
            "n_samples": cal.n_samples if cal else 0,
            "fitted_at": cal.fitted_at.isoformat() if cal else None,
        }
    except Exception as e:
        subsystems["calibrator"] = {"ok": False, "error": str(e)}

    # Overall — green only if all *load-bearing* subsystems are OK.
    # Optional integrations (Telegram, Twitter, LLM) being unconfigured
    # is NOT a health failure.
    load_bearing = ("database", "login_limiter")
    overall_ok = all(subsystems[k]["ok"] for k in load_bearing)

    return {
        "status": "ok" if overall_ok else "degraded",
        "asof": datetime.utcnow().isoformat(),
        "subsystems": subsystems,
    }


# ---- Routers ----
app.include_router(analysis.router, prefix="/api/analysis", tags=["analysis"])
app.include_router(technical.router, prefix="/api/technical", tags=["technical"])
app.include_router(astrology.router, prefix="/api/astrology", tags=["astrology"])
app.include_router(numerology.router, prefix="/api/numerology", tags=["numerology"])
app.include_router(gann.router, prefix="/api/gann", tags=["gann"])
app.include_router(options.router, prefix="/api/options", tags=["options"])
app.include_router(signals.router, prefix="/api/signals", tags=["signals"])
app.include_router(broker.router, prefix="/api/broker", tags=["broker"])
app.include_router(market.router, prefix="/api/market", tags=["market"])
app.include_router(exit_api.router, prefix="/api/exit", tags=["exit-analysis"])
app.include_router(recommend.router, prefix="/api/recommend", tags=["recommendations"])
app.include_router(backtest.router, prefix="/api/backtest", tags=["backtest"])
app.include_router(pipeline.router, prefix="/api/pipeline", tags=["pipeline"])
app.include_router(hora.router, prefix="/api/hora", tags=["hora"])
app.include_router(alerts_api.router, prefix="/api/alerts", tags=["alerts"])
app.include_router(risk_api.router, prefix="/api/risk", tags=["risk"])
app.include_router(forecast_api.router, prefix="/api/forecast", tags=["forecast"])
app.include_router(advanced_api.router, prefix="/api/advanced", tags=["advanced"])
app.include_router(moon_api.router, prefix="/api/moon", tags=["moon"])
app.include_router(ml_api.router, prefix="/api/ml", tags=["ml"])
app.include_router(symbol_api.router, prefix="/api/symbol", tags=["symbol"])

# ---- Professional layer (8-block upgrade) ----
app.include_router(journal_api.router,     prefix="/api/journal",       tags=["journal"])
app.include_router(risk_adv_api.router,    prefix="/api/risk-advanced", tags=["risk-advanced"])
app.include_router(portfolio_api.router,   prefix="/api/portfolio",     tags=["portfolio"])
app.include_router(backtest_pro_api.router, prefix="/api/backtest-pro", tags=["backtest-pro"])
app.include_router(ml_pro_api.router,      prefix="/api/ml-pro",        tags=["ml-pro"])
app.include_router(backfill_api.router,    prefix="/api/backfill",      tags=["backfill"])
app.include_router(auth_api.router,        prefix="/api/auth",          tags=["auth"])
app.include_router(auth_api.admin_router,  prefix="/api/admin",         tags=["admin"])
app.include_router(commodities_api.router, prefix="/api/commodities",   tags=["commodities"])
app.include_router(quant_api.router,       prefix="/api/quant",         tags=["quant"])
app.include_router(calibration_api.router, prefix="/api/calibration",   tags=["calibration"])
app.include_router(nse_api.router,         prefix="/api/nse",           tags=["nse"])
app.include_router(portal_api.router,            prefix="/api/portal", tags=["portal"])
app.include_router(subscription_api.user_router, prefix="/api/portal", tags=["subscription"])
app.include_router(subscription_api.admin_router, prefix="/api/admin", tags=["admin"])
app.include_router(scanner_admin_api.router, prefix="/api/admin/scanner", tags=["admin"])
app.include_router(optimize_api.router,           prefix="/api/optimize",  tags=["optimize"])
app.include_router(astro_lab_api.router,          prefix="/api/astro-lab", tags=["astro-lab"])
# Payment processor — Razorpay (no-op when env vars unset). Mounted at root
# rather than under /api so the public webhook URL is clean.
from app.api import payments as payments_api
app.include_router(payments_api.router, prefix="/api/payments", tags=["payments"])

# Trade execution — order placement, positions, fills. Paper-mode by
# default; live mode requires authenticated broker connection.
from app.api import trade as trade_api
app.include_router(trade_api.router, prefix="/api/trade", tags=["trade"])

app.include_router(ws_server.router)   # WebSocket routes use raw /ws/* paths
