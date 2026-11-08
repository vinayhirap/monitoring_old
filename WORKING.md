# WORKING.md — the guaranteed setup that always works

> If something isn't working, follow this file top-to-bottom in order.
> Every step has a verification command. **Don't skip steps.**

## The architecture you have

```
┌──────────────────────────────────────────────────────────────┐
│  Your browser (on your laptop, anywhere in the world)        │
│                          │                                   │
│                          │ HTTP — only port 3000             │
│                          ▼                                   │
│  ┌────────────────────────────────────────────────────────┐  │
│  │ AWS EC2 / VM (your-server-ip)                           │  │
│  │                                                        │  │
│  │  Port 3000 ── Next.js (frontend)                       │  │
│  │                     │                                  │  │
│  │                     │ proxy /api/* to localhost:8000   │  │
│  │                     ▼                                  │  │
│  │  Port 8000 ── FastAPI (backend)  ← internal only      │  │
│  │                     │                                  │  │
│  │                     ▼                                  │  │
│  │             SQLite (marketlens.db)                     │  │
│  │             ~/.cache/marketlens/scrip_master.json      │  │
│  │                                                        │  │
│  │  Port 8000 is NOT exposed externally — only Next.js    │  │
│  │  proxies through it. You only need port 3000 open.     │  │
│  └────────────────────────────────────────────────────────┘  │
└──────────────────────────────────────────────────────────────┘
```

This is the most-foolproof topology: **you only need to open port 3000 in your VM firewall.** The browser talks to Next.js (port 3000), and Next.js talks to FastAPI over localhost. No CORS issues, no second-port firewall rules, no environment variable juggling.

---

## Setup steps (do once)

### A. AWS Security Group / VM firewall — open port 3000

| Cloud | How |
|---|---|
| **AWS EC2** | Console → EC2 → Instances → your instance → Security tab → click the SG link → Edit inbound rules → Add rule: Custom TCP, port 3000, Source 0.0.0.0/0 → Save |
| **Linux ufw** | `sudo ufw allow 3000` |
| **iptables** | `sudo iptables -A INPUT -p tcp --dport 3000 -j ACCEPT` |

**Verify** from your laptop:
```bash
curl -i http://your-server-ip:3000
```
Should return HTML (not "Connection refused" or hang).

### B. The project should be owned by ONE user — `hcsadmin` recommended

Right now you've been switching between root and hcsadmin. That breaks the Next.js cache. Fix:

```bash
sudo chown -R hcsadmin:hcsadmin /home/hcsadmin/marketlens
```

From now on, run everything as `hcsadmin`:
```bash
su - hcsadmin
cd ~/marketlens
```

### C. Backend `.env` — put credentials here ONCE

`/home/hcsadmin/marketlens/.env`:
```ini
APP_ENV=development
SECRET_KEY=any-random-string-you-like-12345
DATABASE_URL=sqlite:///./marketlens.db

# Angel One (TOTP-only login)
ANGELONE_API_KEY=s4zfIPcY
ANGELONE_CLIENT_CODE=M188467
ANGELONE_TOTP_SECRET=POVQWTEEHAVRLBTP6HJ4762VCM
# ANGELONE_PASSWORD intentionally blank

# CORS not needed since we're proxying through Next.js — but harmless to leave
CORS_ORIGINS=http://localhost:3000

# Astro defaults (Mumbai)
ASTRO_LATITUDE=19.0760
ASTRO_LONGITUDE=72.8777
ASTRO_TIMEZONE=Asia/Kolkata
ASTRO_AYANAMSA=LAHIRI

# Risk
RISK_MAX_DAILY_LOSS_PCT=2.0
RISK_MAX_POSITION_PCT=5.0

# Alerts (optional — fill in to get Telegram notifications)
ALERTS_ENABLED=false
TELEGRAM_BOT_TOKEN=
TELEGRAM_CHAT_ID=
```

### D. Frontend `.env.local` — leave empty (the default works)

```bash
cat > /home/hcsadmin/marketlens/frontend/.env.local << 'EOF'
# Intentionally empty — same-origin /api proxy works everywhere.
EOF
```

---

## Reset & first run (do once after pulling latest code)

```bash
su - hcsadmin
cd ~/marketlens

# Nuke any stale build / venv state
rm -rf frontend/.next frontend/node_modules frontend/package-lock.json
rm -rf backend/.venv

# Make scripts executable
chmod +x start.sh start-backend.sh start-frontend.sh
```

---

## Run (every time)

Open **two SSH terminals** to the VM (easier to see logs):

**Terminal 1 — backend:**
```bash
cd ~/marketlens
./start-backend.sh
```

Wait until you see:
```
INFO:     Uvicorn running on http://0.0.0.0:8000 (Press CTRL+C to quit)
```

**Terminal 2 — frontend:**
```bash
cd ~/marketlens
./start-frontend.sh
```

Wait until you see:
```
✓ Ready in Xs
```

---

## Verify (in order — DO NOT skip)

### 1. Backend internal check (on the VM)
```bash
curl -i http://localhost:8000/health
```
Expect: `200 OK` and `{"status":"ok"}`. **If this fails, backend isn't running — paste the backend terminal output.**

### 2. Frontend internal check (on the VM)
```bash
curl -i http://localhost:3000/api/broker/status
```
Expect: `200 OK` and JSON with `broker`, `authenticated`, `paper_mode`. **If this fails, the Next.js proxy is broken — paste the frontend terminal output.**

### 3. Frontend external check (from your laptop)
```bash
curl -i http://your-server-ip:3000
```
Expect: `200 OK` and HTML. **If this hangs, port 3000 is blocked — fix Security Group (Step A above).**

### 4. Open in browser
```
http://your-server-ip:3000
```

You should see:
- Top of the page: indices ticker (NIFTY, BANKNIFTY, etc.) with prices
- Header: Moon phase, Hora ruler, lunar gate badge
- Dashboard cards: populated with actual numbers, not "—"
- **No red banner** at the top saying "Backend unreachable"

If you DO see the red banner, it means the Next.js server can't reach FastAPI on localhost:8000. The most common cause: **backend isn't running.** Check Terminal 1.

---

## Login to Angel One (after the above works)

1. Click **Settings** in the sidebar
2. Connection Diagnostic panel should be green
3. **Leave all 3 form fields blank** (we put credentials in `.env`)
4. Click **Login**
5. Header changes from amber `PAPER MODE` to green `LIVE — Angel One`
6. Indices ticker switches from synthetic to real

---

## Stopping

In each terminal: **Ctrl-C**. That's it.

---

## When something breaks — read this exact list

| Symptom | Cause | Fix |
|---|---|---|
| Red "Backend unreachable" banner | FastAPI not running | Check Terminal 1 backend log |
| Cards show "—" but no banner | Refresh — banner should appear shortly | If not, check browser DevTools Network tab |
| `curl` from laptop hangs | Port 3000 blocked | AWS Security Group → add inbound 3000 |
| `curl` from laptop "Connection refused" | Frontend not running | Check Terminal 2 |
| Pipeline scan takes >2 min | Normal for ~180 symbol full scan | Wait, or use QUICK mode (top-50) |
| TOTP login rejected | Server time skew | `sudo timedatectl set-ntp true` on VM |
| `npm install` permission errors | Ownership mix (root/hcsadmin) | `sudo chown -R hcsadmin:hcsadmin .` |
| `.next` corruption errors | Cache from previous session | `rm -rf frontend/.next` and restart frontend |
| Python import errors at startup | Outdated venv | `rm -rf backend/.venv` and rerun start-backend.sh |

---

## Why this is now bulletproof

Three changes I made to remove the moving parts:

1. **Same-origin API proxy** — the browser only ever calls relative `/api/*` URLs. The Next.js dev server handles the proxy to FastAPI. **No CORS configuration, no second open port, no env-var juggling.** Works on localhost, AWS, GCP, behind nginx, with any domain.

2. **Persistent "Backend Unreachable" banner** — if the API layer is broken for any reason, every page now shows a red banner at the top. No more silent "—" everywhere with no explanation.

3. **Extended proxy timeout** (180 seconds) — long pipeline scans (full universe) won't get killed by Node's default short timeout anymore.

If after following this file the app still doesn't work, paste:
- Last 30 lines of backend terminal output
- Last 30 lines of frontend terminal output
- Output of `curl -i http://localhost:8000/health` (on VM)
- Output of `curl -i http://localhost:3000/api/broker/status` (on VM)
- Output of `curl -i http://your-server-ip:3000` (from laptop)

Those five outputs identify the failure in seconds. Without them I'm guessing.
