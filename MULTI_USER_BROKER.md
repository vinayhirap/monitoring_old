# Multi-user broker architecture

Until this refactor, the platform had ONE shared Angel One session — every
user's trade routed through the operator's account. That model is
**incompatible with real-money multi-user trading** for three reasons:

1. **Legal**: orders placed in your account on behalf of users requires a
   Power of Attorney or Authorized Person registration with SEBI. Without
   it, you're effectively running an unregistered broker.
2. **Financial**: one user's bad day blows up everyone's margin. Position
   limits, settlement obligations — all pooled on your account.
3. **Operational**: Angel One rate-limits the API per account. 100 users
   placing intraday orders against one session hits caps within minutes.

The refactor introduces **per-user broker sessions** — each user logs into
their own Angel One account from the app, the platform stores their
credentials encrypted, and uses them to authenticate per-user requests.

## What changed

| Area | Before | After |
|---|---|---|
| Broker client | `broker_instance` singleton with operator's creds | Per-user `AngelOneBroker` instance from `broker_session_manager.get_for_user(db, user_id)` |
| Credential storage | Operator's `.env` only | Encrypted per-user in `user_broker_sessions` table |
| Trade routing | All orders → operator's account | Each user's orders → their own account |
| Order book polling | One global poll | Per-user polls, iterates `connected_user_ids()` |
| User onboarding | N/A (operator-only) | New page `/portal/broker` for the user to connect |
| Encryption | None for broker creds | Fernet (AES-128-CBC + HMAC) via `services/credential_crypto.py` |

The **legacy** `broker_instance` singleton still exists for operator-level
operations that don't touch user funds:
- Market data quotes (`/api/market/quote`)
- Scrip-master refresh
- LTP cross-checks for price sanity

These are READ-ONLY and use the operator's session for efficiency.

## Setup steps (one-time, ops)

### 1. Generate a Fernet master key

```bash
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
# Output: example_44_char_base64_string=
```

### 2. Set the env var in `backend/.env`

```
BROKER_CRED_KEY=example_44_char_base64_string=
```

This is the master key that encrypts ALL user broker credentials.
**Losing it loses every user's stored credentials.** Backup off-host
(password manager, vault, etc.).

### 3. Run the migration

```bash
cd backend
source venv/bin/activate
python migrations/004_per_user_broker_sessions.py
```

This creates the `user_broker_sessions` table. Idempotent.

### 4. Restart the backend

```bash
sudo systemctl restart marketlens-backend
```

### 5. Verify

```bash
curl -H "Authorization: Bearer <any_user_token>" \
     http://localhost:8000/api/broker/me/status
# Should return: {"connected": false, "ever_connected": false}
```

## User onboarding flow

1. User logs into the platform
2. Navigates to `/portal/broker` (linkable from `/portal/profile`)
3. Pastes their own Angel One credentials:
   - API key (from `smartapi.angelone.in`)
   - Client code (their Angel One ID)
   - TOTP secret (base32 from Angel One mobile app)
   - Password (only if their account requires PIN+TOTP)
4. Backend attempts a live login with those credentials
5. On success: credentials are Fernet-encrypted and persisted; session token cached
6. User can now place LIVE orders — they route to their own account

## Key rotation

If `BROKER_CRED_KEY` is ever compromised:

```bash
# Generate new key
NEW_KEY=$(python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())")

# Set both — new key for encryption, old for decryption fallback
BROKER_CRED_KEY=$NEW_KEY
BROKER_CRED_KEY_OLD=$PREVIOUS_KEY    # the leaked one

# Restart backend. Re-encrypt happens lazily — next time each user's creds
# are decrypted, they're re-encrypted under the new key on save.
```

After all users have done at least one operation (placement, status check,
etc.) post-rotation, remove `BROKER_CRED_KEY_OLD` from the env.

## Security boundaries

| Threat | Mitigation |
|---|---|
| DB-only attacker (SQL injection, backup leak) | Credentials are encrypted; useless without master key |
| RAM-dump attacker | Plaintext credentials are in memory during login only (~1 second). Not defended. For that level of threat use AWS KMS / HSM. |
| Master-key leak | Rotation procedure above. Until rotated, all credentials are compromised. |
| Replay attack on session token | Session token expires every ~24h. Stored encrypted same as credentials. |
| Operator goes rogue | Has master key + DB access = can decrypt all stored credentials. **This is the fundamental trust model — you are the custodian of your users' broker credentials. Operate accordingly.** |

## When a user wants out

`DELETE /api/broker/me/disconnect` wipes all four credential ciphertexts
and the session tokens. The user can also regenerate their Angel One API
key from the broker's dashboard for belt-and-suspenders.

## Multi-broker future

The schema is keyed by `(user_id, broker)` unique constraint, so adding
Zerodha / Upstox / Fyers later is:

1. Create `app/brokers/zerodha.py` with the same `BrokerBase` interface
2. Extend `broker_session_manager._new_broker_client()` to dispatch based on `broker` field
3. Add a broker-picker to `/portal/broker` UI

The trade-executor, order-poller, and risk-guard are already broker-agnostic.
