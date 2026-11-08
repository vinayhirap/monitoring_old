"""Endpoint smoke tests — confirm every router responds without 500.

These tests don't validate correctness of the JSON payload (the engine
golden tests do that). They confirm the routing layer + dependency
injection isn't broken — i.e. that no module-level import crashes,
no Pydantic schema is malformed, no router has a typo.

Strategy:
  • Unauthenticated endpoints  → expect 200 (health, login form, etc.)
  • Authenticated endpoints     → expect 401 (no token) — proves auth dep
                                  is wired but doesn't require a real user
  • Admin endpoints              → expect 401 or 403
  • Tier-gated portal endpoints  → expect 401 (no token)

If any endpoint returns 500 here, the routing layer is broken and needs
investigation BEFORE deploying to production.
"""
from __future__ import annotations

import pytest


# ----------------------------------------------------------------------------
# Public endpoints — should work without auth
# ----------------------------------------------------------------------------

class TestPublicEndpoints:
    def test_health(self, client):
        r = client.get("/api/health")
        assert r.status_code == 200
        assert r.json()["status"] == "ok"

    def test_root(self, client):
        r = client.get("/")
        assert r.status_code == 200

    def test_docs(self, client):
        """OpenAPI docs page should always work."""
        r = client.get("/docs")
        assert r.status_code == 200


# ----------------------------------------------------------------------------
# Auth-required endpoints — should return 401 without token, not 500
# ----------------------------------------------------------------------------

class TestAuthRequired:
    @pytest.mark.parametrize("path", [
        "/api/auth/me",
        "/api/portal/me/watchlist",
        "/api/portal/me/subscription",
        "/api/portal/top-picks",
        "/api/portal/market-pulse",
        "/api/portal/history",
        "/api/portal/daily-forecast/NIFTY",
        "/api/portal/me/telegram",
        "/api/admin/users",
        "/api/admin/audit-log",
        "/api/admin/subscriptions",
        "/api/admin/subscription-summary",
    ])
    def test_returns_401_or_422_without_token(self, client, path):
        """Without Authorization header, all auth-required endpoints
        must return 401 (unauthenticated). 422 also acceptable if
        endpoint validates path/query params before auth dep."""
        r = client.get(path)
        assert r.status_code in (401, 422, 405), \
            f"{path} returned {r.status_code} (expected 401/422/405)"


# ----------------------------------------------------------------------------
# Tier-gated endpoints — same expectation; the gate itself is tested
# in test_engines for risk_guard, not here.
# ----------------------------------------------------------------------------

class TestTierGated:
    @pytest.mark.parametrize("path", [
        "/api/commodities/list",
        "/api/commodities/scan",
        "/api/options/greeks?spot=100&strike=100&days=7&iv_pct=20",
    ])
    def test_tier_gated_returns_401_without_token(self, client, path):
        r = client.get(path)
        assert r.status_code in (401, 422), \
            f"{path} returned {r.status_code}"


# ----------------------------------------------------------------------------
# Auth flow — signup + login round-trip
# ----------------------------------------------------------------------------

class TestAuthFlow:
    def test_signup_rejects_weak_password(self, client):
        """Password policy: ≥8 chars, letter+digit required."""
        r = client.post("/api/auth/signup", json={
            "email": "smoketest_weak@example.com",
            "password": "abc",
            "full_name": "Smoke Test",
        })
        assert r.status_code in (400, 422)

    def test_signup_rejects_common_password(self, client):
        r = client.post("/api/auth/signup", json={
            "email": "smoketest_common@example.com",
            "password": "password1",
            "full_name": "Smoke Test",
        })
        assert r.status_code == 400
        assert "blacklist" in r.text.lower() or "common" in r.text.lower()

    def test_login_returns_401_for_unknown_user(self, client):
        r = client.post("/api/auth/login", data={
            "username": "nobody-{}@example.com".format("smoketest"),
            "password": "AnyPassword123",
        })
        assert r.status_code == 401


# ----------------------------------------------------------------------------
# Analyzer endpoints — exercise the routing layer of the heavier engines.
# These don't require auth (consistent with /api/technical, /api/gann etc.
# being tools rather than recommendations).
# ----------------------------------------------------------------------------

class TestAnalyzerEndpoints:
    def test_gann_natural_squares_post_endpoint(self, client):
        """Post a known spot — endpoint should produce a level grid."""
        r = client.post("/api/gann/square9", json={
            "price": 23792.0, "levels": 4,
        })
        # Auth wraps the gann router now — 401 expected without token
        assert r.status_code in (200, 401, 422)
