"""WebSocket server — pushes live ticks + signal updates to subscribed UIs.

Two channels:
  • /ws/ticks?symbols=RELIANCE,TCS    — live LTP / bid / ask broadcasts
  • /ws/signals                        — pipeline-emitted signal updates

The Angel One WS V2 client (app/ws/angelone_ws.py — STUB) feeds this broker.
Until that client is wired, /ws/ticks emits synthetic ticks every 2s so the
UI plumbing can be developed end-to-end.
"""
from __future__ import annotations

import asyncio
import json
import random
from datetime import datetime
from typing import Iterable

from fastapi import APIRouter, WebSocket, WebSocketDisconnect, Query
from loguru import logger


router = APIRouter()

# Simple in-memory broker — fine for single-worker deployment. Replace with
# Redis pub/sub when scaling to multiple workers.
class _Broker:
    def __init__(self):
        self._subs: dict[str, set[WebSocket]] = {}

    async def subscribe(self, channel: str, ws: WebSocket) -> None:
        self._subs.setdefault(channel, set()).add(ws)

    async def unsubscribe(self, channel: str, ws: WebSocket) -> None:
        if channel in self._subs:
            self._subs[channel].discard(ws)

    async def publish(self, channel: str, message: dict) -> None:
        if channel not in self._subs:
            return
        dead = []
        for ws in list(self._subs[channel]):
            try:
                await ws.send_json(message)
            except Exception:
                dead.append(ws)
        for ws in dead:
            self._subs[channel].discard(ws)


broker = _Broker()


# ---------------------------------------------------------------------------
# /ws/ticks — live LTP feed
# ---------------------------------------------------------------------------

@router.websocket("/ws/ticks")
async def ws_ticks(ws: WebSocket, symbols: str = Query("")):
    """Subscribe to live ticks for comma-separated symbols.
    Until the Angel One WS client is wired, emits synthetic ticks for plumbing.
    """
    await ws.accept()
    syms = [s.strip().upper() for s in symbols.split(",") if s.strip()] or ["NIFTY"]
    for s in syms:
        await broker.subscribe(f"ticks:{s}", ws)
    logger.info("WS connect ticks: {}", syms)

    # Synthetic emitter — REPLACE with real Angel One WS pipe in production.
    try:
        prices = {s: 1000 + random.random() * 2000 for s in syms}
        while True:
            for s in syms:
                # Random-walk ±0.3%
                prices[s] = max(1.0, prices[s] * (1 + (random.random() - 0.5) * 0.006))
                tick = {
                    "symbol": s,
                    "ts": datetime.utcnow().isoformat(),
                    "ltp": round(prices[s], 2),
                    "bid": round(prices[s] - 0.05, 2),
                    "ask": round(prices[s] + 0.05, 2),
                    "source": "synthetic",
                }
                await ws.send_json(tick)
            await asyncio.sleep(2)
    except WebSocketDisconnect:
        for s in syms:
            await broker.unsubscribe(f"ticks:{s}", ws)
        logger.info("WS disconnect ticks: {}", syms)


# ---------------------------------------------------------------------------
# /ws/signals — pipeline signal pushes
# ---------------------------------------------------------------------------

@router.websocket("/ws/signals")
async def ws_signals(ws: WebSocket):
    """Subscribe to all new signals (pipeline emits → push here)."""
    await ws.accept()
    await broker.subscribe("signals:all", ws)
    try:
        while True:
            # Keep-alive — real signals arrive via broker.publish() from elsewhere
            await asyncio.sleep(30)
            await ws.send_json({"type": "ping", "ts": datetime.utcnow().isoformat()})
    except WebSocketDisconnect:
        await broker.unsubscribe("signals:all", ws)


# ---------------------------------------------------------------------------
# Helper for other modules to broadcast a signal
# ---------------------------------------------------------------------------

async def publish_signal(signal: dict) -> None:
    """Call from the pipeline whenever a new signal is finalised."""
    await broker.publish("signals:all", {"type": "signal", "payload": signal})


async def publish_tick(symbol: str, tick: dict) -> None:
    await broker.publish(f"ticks:{symbol}", tick)
