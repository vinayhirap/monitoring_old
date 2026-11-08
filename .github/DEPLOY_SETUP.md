# Auto-deploy setup (one-time, ~15 minutes)

The deploy workflow at `.github/workflows/deploy.yml` automatically pushes
every commit on `main` to your EC2 server. This permanently fixes the
"files don't reach EC2" sync issue.

## One-time setup steps

### 1. Get your EC2 SSH key into GitHub Secrets

```bash
# Locally — print the PEM contents
cat ~/.ssh/marketlens-ec2.pem
```

Copy the **entire output** (including the `-----BEGIN ... PRIVATE KEY-----`
and `-----END ... PRIVATE KEY-----` lines).

### 2. Add four repository secrets

Go to: **GitHub repo → Settings → Secrets and variables → Actions → New repository secret**

| Secret name | Value | Example |
|---|---|---|
| `EC2_SSH_PRIVATE_KEY` | Paste the PEM contents from step 1 | `-----BEGIN RSA PRIVATE KEY-----\nMIIE...\n-----END RSA PRIVATE KEY-----` |
| `EC2_HOST` | Your EC2 public DNS or Elastic IP | `ec2-13-234-56-78.ap-south-1.compute.amazonaws.com` |
| `EC2_USER` | SSH username | `ubuntu` |
| `EC2_APP_DIR` | Absolute path on EC2 to the app folder | `/home/ubuntu/MarketLens` |

Optional:
- `SLACK_WEBHOOK_URL` — get notified if a deploy fails

### 3. (Optional but recommended) Set up systemd services on EC2

The workflow first tries `sudo systemctl restart marketlens-backend` and
`sudo systemctl restart marketlens-frontend`. If those services don't
exist, it falls back to `nohup ./start-*.sh` — which works but isn't
robust to reboots.

To set up proper systemd services on EC2:

```bash
# Backend service
sudo tee /etc/systemd/system/marketlens-backend.service > /dev/null <<EOF
[Unit]
Description=MarketLens Backend (FastAPI)
After=network.target

[Service]
Type=simple
User=ubuntu
WorkingDirectory=/home/ubuntu/MarketLens/backend
ExecStart=/home/ubuntu/MarketLens/backend/venv/bin/uvicorn app.main:app --host 0.0.0.0 --port 8000
Restart=on-failure
RestartSec=5
StandardOutput=append:/var/log/marketlens-backend.log
StandardError=append:/var/log/marketlens-backend.log

[Install]
WantedBy=multi-user.target
EOF

# Frontend service
sudo tee /etc/systemd/system/marketlens-frontend.service > /dev/null <<EOF
[Unit]
Description=MarketLens Frontend (Next.js)
After=network.target

[Service]
Type=simple
User=ubuntu
WorkingDirectory=/home/ubuntu/MarketLens/frontend
ExecStart=/usr/bin/npm run start
Restart=on-failure
RestartSec=5
StandardOutput=append:/var/log/marketlens-frontend.log
StandardError=append:/var/log/marketlens-frontend.log

[Install]
WantedBy=multi-user.target
EOF

# Grant the ubuntu user passwordless sudo for these specific systemctl calls
echo "ubuntu ALL=(ALL) NOPASSWD: /bin/systemctl restart marketlens-backend, /bin/systemctl restart marketlens-frontend" | sudo tee /etc/sudoers.d/marketlens

# Enable + start
sudo systemctl daemon-reload
sudo systemctl enable marketlens-backend marketlens-frontend
sudo systemctl start marketlens-backend marketlens-frontend
```

### 4. Verify by pushing a small change

```bash
git commit --allow-empty -m "chore: verify deploy workflow"
git push origin main
```

Watch the workflow run at **GitHub repo → Actions tab**. On success, you
should see all three jobs pass: test → deploy → health check.

## What runs on every push

1. **Test job** — runs `pytest` on the backend. If any test fails,
   deploy is BLOCKED. (This is intentional: broken code should never
   reach production.)
2. **Deploy job** — rsync's the changed files to EC2, then SSHes in to
   restart services.
3. **Health check** — probes `/api/health` for 60 seconds. If no 200,
   the workflow fails (and Slack gets pinged if configured).

## Manual deploy

Don't want to push a commit? Go to **Actions tab → Deploy to EC2 →
Run workflow** and click the button. Runs the same flow against the
current `main`.

## Rollback

If a deploy breaks production:

```bash
# Locally — revert the bad commit
git revert HEAD
git push origin main
# This triggers another deploy with the previous code
```

Or roll back manually via SSH if you need to be faster:

```bash
ssh ubuntu@<EC2_HOST>
cd /home/ubuntu/MarketLens
git log --oneline -5     # find the good commit
git reset --hard <good-sha>
sudo systemctl restart marketlens-backend marketlens-frontend
```
