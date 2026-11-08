# Razorpay Setup — End-to-End Checklist

Practical, ordered checklist to take Razorpay from "not configured" to "fully
working subscription payments" on a deployed MarketLens instance.

Each step ends with a **verify** command you can run to confirm the step
landed. If verify fails, fix that step before moving on.

---

## 0. Prerequisites

- Razorpay account: <https://razorpay.com/> (free; KYC needed for live mode)
- Backend deployed and reachable on a public URL (Razorpay webhooks need to hit you)
- Admin access to your EC2 box or wherever the backend runs

---

## 1. Create API keys

1. Razorpay dashboard → **Settings → API Keys → Generate Key**
2. You'll get a `key_id` (starts `rzp_test_` or `rzp_live_`) and a `key_secret`
3. **Save the secret immediately** — Razorpay only shows it once

**Mode discipline:** start in TEST mode (`rzp_test_*`) until end-to-end works,
then swap to LIVE.

---

## 2. Create the three subscription plans

Razorpay dashboard → **Subscriptions → Plans → Create Plan**

Create one plan per tier. The defaults that match MarketLens's
`TIER_PRICING_INR`:

| Tier         | Frequency | Amount (paise) | Display amount |
| ------------ | --------- | -------------- | -------------- |
| BASIC        | Monthly   | 49900          | ₹499 / month   |
| INTERMEDIATE | Monthly   | 149900         | ₹1,499 / month |
| ADVANCED     | Monthly   | 299900         | ₹2,999 / month |

After creating each plan, copy its `plan_id` (looks like `plan_NkWyP3...`).

**Verify:** in the dashboard you should see three plans labelled BASIC,
INTERMEDIATE, ADVANCED with monthly recurrence.

---

## 3. Set up the webhook endpoint

Razorpay dashboard → **Settings → Webhooks → Add New Webhook**

| Field                 | Value                                                       |
| --------------------- | ----------------------------------------------------------- |
| Webhook URL           | `https://YOUR-DOMAIN/api/payments/razorpay/webhook`         |
| Secret                | any random 32+ char string — save this as `WEBHOOK_SECRET`  |
| Active events         | `subscription.activated`, `subscription.charged`, `subscription.cancelled`, `subscription.completed`, `payment.failed` |
| Alert email           | your ops email — Razorpay alerts you on delivery failures   |

**Verify:** dashboard shows the webhook as **Active**.

---

## 4. Set env vars on the backend

Edit `backend/.env` and add:

```
RAZORPAY_KEY_ID=rzp_test_xxxxxxxxxxxx
RAZORPAY_KEY_SECRET=<the secret from step 1>
RAZORPAY_WEBHOOK_SECRET=<the secret from step 3>
RAZORPAY_PLAN_BASIC=plan_xxxxxxxxxxxx
RAZORPAY_PLAN_INTERMEDIATE=plan_xxxxxxxxxxxx
RAZORPAY_PLAN_ADVANCED=plan_xxxxxxxxxxxx
```

Restart the backend so the values are picked up:

```bash
# systemd users:
sudo systemctl restart marketlens-backend

# or if you launched via start.sh:
pkill -f "uvicorn app.main" && ./start.sh --prod
```

**Verify:** hit the diagnose endpoint as an admin user:

```bash
curl -s -H "Authorization: Bearer $ADMIN_TOKEN" \
     https://YOUR-DOMAIN/api/payments/razorpay/diagnose | jq
```

Expected output:

```json
{
  "configured": true,
  "missing_env": [],
  "key_mode": "test",
  "plans_mapped": { "BASIC": "plan_...", "INTERMEDIATE": "plan_...", "ADVANCED": "plan_..." },
  "api_check": {
    "reachable": true,
    "auth_ok": true,
    "plan_count_visible": 1,
    "mode": "test"
  },
  "next_steps": ["✓ Configured. ..."]
}
```

If `api_check.auth_ok` is `false`, the KEY_ID/SECRET pair is wrong — go back
to step 1 and confirm you copied them correctly.

---

## 5. Sandbox payment — test mode end-to-end

This is the part that the "is everything actually wired up" question hangs on.

### 5a. Log in as a non-admin user (FREE tier)

Use the test account or create one via signup. Confirm they're on FREE
in `/portal/profile`.

### 5b. Trigger an upgrade

From `/portal/profile` → "Plans & pricing" → click **Upgrade to BASIC**.

Or from any tier-gated endpoint that 402s — the `UpgradeModal` opens
automatically.

### 5c. Pay using Razorpay test cards

Razorpay test mode accepts the published test cards:

| Card                | Number                | Outcome  |
| ------------------- | --------------------- | -------- |
| Success             | `4111 1111 1111 1111` | Approved |
| Insufficient funds  | `5104 0600 0000 0008` | Declined |

Use any future expiry (e.g. `12/30`) and any CVV (`123`).

After Razorpay shows "Payment Successful":

- The Razorpay webhook fires `subscription.activated`
- Your backend's `_on_subscription_activated` upserts the user's
  `subscriptions` row to tier=BASIC and extends `valid_until` by 30 days
- The frontend reloads the page and `/portal/profile` now shows BASIC

### 5d. Verify the webhook landed

```bash
# Tail backend log on EC2
tail -f logs/backend.log | grep -i razorpay

# Should see lines like:
#   Razorpay event handled: subscription.activated → {'ok': True, ...}
```

If the user's tier didn't update:

1. Check the webhook *delivery log* in Razorpay dashboard → Settings →
   Webhooks → click your webhook → "Recent Deliveries"
2. Look at the response status. `200` = your backend accepted it. `400` =
   signature verification failed (WEBHOOK_SECRET mismatch). `5xx` = your
   backend errored.
3. If `400`: `RAZORPAY_WEBHOOK_SECRET` in `.env` doesn't match the one in
   the dashboard. Fix and restart.

### 5e. Verify the tier in the DB

```bash
# On EC2 with the backend venv:
python -c "
from app.database import SessionLocal
from app.models.subscription import Subscription
db = SessionLocal()
for s in db.query(Subscription).all():
    print(s.user_id, s.tier, s.valid_until, s.is_active)
"
```

The test user should appear with `tier=BASIC` and a `valid_until` ~30 days
out.

---

## 6. Switch to LIVE mode (only after step 5 passes in test mode)

1. Razorpay dashboard → **Mode toggle (top-right) → Live mode**
2. Regenerate API keys in live mode (Settings → API Keys → Generate)
3. Recreate the three plans in live mode (test/live plans are separate)
4. Recreate the webhook in live mode
5. Update `.env` with the new `rzp_live_*` key + new plan_ids + new
   webhook secret
6. Restart backend
7. Re-run `curl /api/payments/razorpay/diagnose` — `key_mode` should now
   say `live`

**One real payment** at the lowest tier (₹499) is the only way to confirm
the live wiring. Razorpay refunds it to you (you're paying yourself) but
the bank fees stay — budget ~₹30 for the validation.

---

## Common failure modes

| Symptom                                                                       | Cause                                                                     | Fix                                                                                                          |
| ----------------------------------------------------------------------------- | ------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------ |
| `/diagnose` shows `configured: false`                                         | One or more env vars missing                                              | Set them in `.env` and restart                                                                               |
| `api_check.auth_ok: false` with `401 Auth rejected`                            | Wrong `RAZORPAY_KEY_SECRET`                                               | Regenerate keys in dashboard, update `.env`                                                                  |
| Webhook delivery shows `400` in Razorpay dashboard                             | `RAZORPAY_WEBHOOK_SECRET` doesn't match                                   | Copy secret from dashboard webhook config into `.env`, restart                                               |
| Payment goes through but user's tier doesn't update                            | Webhook is sending events you don't subscribe to, OR `user_email` missing | Confirm events list (step 3) covers `subscription.activated`. Check `notes.user_email` on the subscription   |
| Frontend "Upgrade to BASIC" button shows error "RAZORPAY_PLAN_BASIC not mapped"| `RAZORPAY_PLAN_BASIC` env var unset                                       | Set it to the test-mode plan_id from step 2, restart                                                         |
| `key_mode: unknown` in diagnose                                                | Key doesn't start with `rzp_test_` or `rzp_live_`                         | You're using a custom key — usually a copy/paste typo. Re-fetch from dashboard                               |
| Webhook fires but the user gets put on the wrong tier                          | `plan_id → tier` mapping in `.env` is wrong                               | Cross-check `RAZORPAY_PLAN_*` vars against actual plan_ids in dashboard. Use diagnose `plans_mapped` output  |

---

## Reference

- Razorpay subscriptions docs: <https://razorpay.com/docs/payments/subscriptions/>
- Test cards: <https://razorpay.com/docs/payments/payments/test-card-details/>
- Webhook event reference: <https://razorpay.com/docs/webhooks/payloads/subscriptions/>
- Backend code: [`backend/app/services/razorpay_handler.py`](app/services/razorpay_handler.py)
- Backend endpoints: [`backend/app/api/payments.py`](app/api/payments.py)
