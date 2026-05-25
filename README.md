# Ripple Backend

FastAPI service for Ripple. It exposes HTTP APIs and uses Supabase (`SUPABASE_URL`, `SUPABASE_SECRET_KEY`).

**Default listen port:** `8001` (set via `uvicorn --port`; production nginx should proxy to `http://127.0.0.1:8001`).

## Requirements

- **OS:** Ubuntu 24.04 LTS (or compatible)
- **Python:** 3.12 (the default on Ubuntu 24)
- **Network:** outbound HTTPS to your Supabase project
- A Supabase project and service role (secret) key

## Install on Ubuntu 24

These steps assume you deploy under `/opt/ripple-backend`. Adjust paths if you use another directory.

### 1. System packages

```bash
sudo apt update
sudo apt install -y git python3 python3-venv python3-pip
```

### 2. Application user (recommended)

```bash
sudo useradd --system --home /opt/ripple-backend --shell /usr/sbin/nologin ripple
```

### 3. Code and ownership

```bash
sudo mkdir -p /opt/ripple-backend
sudo chown ripple:ripple /opt/ripple-backend
```

Clone the repository as `ripple` (or clone elsewhere and copy files in):

```bash
sudo -u ripple git clone <YOUR_REPO_URL> /opt/ripple-backend
```

If the repo already lives on the server, ensure the app root (the folder that contains `app/` and `requirements.txt`) is at `/opt/ripple-backend`.

### 4. Python virtual environment

```bash
cd /opt/ripple-backend
sudo -u ripple python3 -m venv .venv
sudo -u ripple .venv/bin/pip install --upgrade pip
sudo -u ripple .venv/bin/pip install -r requirements.txt
```

### 5. Environment variables

Create `/opt/ripple-backend/.env` owned by `ripple` with mode `600`:

```bash
sudo -u ripple install -m 600 /dev/null /opt/ripple-backend/.env
sudo -u ripple nano /opt/ripple-backend/.env
```

Minimum contents:

```env
SUPABASE_URL=https://YOUR_PROJECT.supabase.co
SUPABASE_SECRET_KEY=your_supabase_secret_key
```

Apply any SQL migrations in `supabase/migrations/` to your Supabase project when you set up or upgrade the database.

### 6. Quick manual test (optional)

```bash
cd /opt/ripple-backend
sudo -u ripple .venv/bin/uvicorn app.main:app --host 127.0.0.1 --port 8001
```

Check: `curl -s http://127.0.0.1:8001/health` should return JSON with `"status":"ok"`. Stop with Ctrl+C.

**CORS:** `app/main.py` currently allows `http://localhost:8081` and `http://127.0.0.1:8081`. For a production web origin, update `allow_origins` (or make it configurable) before relying on browser clients from another host.

---

## Local development

From the repo root (with `.venv` activated):

```bash
uvicorn app.main:app --reload --host 127.0.0.1 --port 8001
```

Point the mobile app at `http://localhost:8001` (or your LAN IP on a physical device).

---

## Run as a systemd service

### 1. Unit file

Copy the template from this repo, or create `/etc/systemd/system/ripple-backend.service`:

```bash
sudo cp deploy/ripple-backend.service /etc/systemd/system/ripple-backend.service
```

Or create `/etc/systemd/system/ripple-backend.service` manually:

```ini
[Unit]
Description=Ripple FastAPI backend (Uvicorn)
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=ripple
Group=ripple
WorkingDirectory=/opt/ripple-backend
EnvironmentFile=/opt/ripple-backend/.env
ExecStart=/opt/ripple-backend/.venv/bin/uvicorn app.main:app \
    --host 127.0.0.1 \
    --port 8001 \
    --workers 2
Restart=on-failure
RestartSec=5

# Hardening (optional; relax if something breaks)
NoNewPrivileges=true
PrivateTmp=true

[Install]
WantedBy=multi-user.target
```

Notes:

- **`--host 127.0.0.1`:** binds only on loopback. Put **nginx** (or another reverse proxy) in front for TLS and public access, proxying to `http://127.0.0.1:8001`.
- To expose the app directly on all interfaces (e.g. no reverse proxy), use `--host 0.0.0.0` and open the port in your firewall.
- **`--workers`:** Uvicorn worker processes. You can set `1` for lighter servers or increase for CPU-bound workloads; each worker is a separate process.

If you already run on port `8000`, change `--port` to `8001` in the unit file, update any **nginx** `proxy_pass` (e.g. `http://127.0.0.1:8001`), then `sudo systemctl daemon-reload && sudo systemctl restart ripple-backend.service`.

### 2. Enable and start

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now ripple-backend.service
sudo systemctl status ripple-backend.service
```

Logs:

```bash
journalctl -u ripple-backend.service -f
```

---

## Deploy updates (pull latest code and restart)

Use this when the app is already installed and you only need the newest code from Git and a service restart.

SSH into the server (for example as `ubuntu`), then:

### 1. Pull the latest code

The app directory should be owned by the `ripple` user (see [Install on Ubuntu 24](#install-on-ubuntu-24)). Pull as that user so file permissions stay correct:

```bash
cd /opt/ripple-backend
sudo -u ripple git pull
```

If Git asks for credentials, configure access for the `ripple` user (deploy key, credential helper, or `git remote` URL with a token—never commit secrets).

Resolve any merge conflicts before continuing. If you deploy a **specific branch**:

```bash
sudo -u ripple git fetch origin
sudo -u ripple git checkout YOUR_BRANCH
sudo -u ripple git pull origin YOUR_BRANCH
```

### 2. Install Python dependencies (when `requirements.txt` changed)

```bash
cd /opt/ripple-backend
sudo -u ripple .venv/bin/pip install -r requirements.txt
```

Skip this step if only application code changed and `requirements.txt` is unchanged.

### 3. Database migrations (if any)

If the release adds SQL under `supabase/migrations/`, apply those changes in the Supabase SQL editor (or your migration process) before or right after deploy, as your team prefers.

### 4. Reload systemd only if you edited the unit file

```bash
sudo systemctl daemon-reload
```

Not needed for a normal code-only deploy.

### 5. Restart the backend

```bash
sudo systemctl restart ripple-backend.service
sudo systemctl status ripple-backend.service
```

### 6. Smoke check

```bash
curl -s http://127.0.0.1:8001/health
```

If something fails, inspect logs: `journalctl -u ripple-backend.service -n 100 --no-pager`.

**Summary one-liner** (after `cd /opt/ripple-backend` and when you always want pip + restart):

```bash
cd /opt/ripple-backend && sudo -u ripple git pull && sudo -u ripple .venv/bin/pip install -r requirements.txt && sudo systemctl restart ripple-backend.service && curl -s http://127.0.0.1:8001/health
```

---

## Endpoints

| Path | Description |
|------|-------------|
| `GET /health` | Liveness check |
| (see `app/routers/`) | Alarm and related APIs |

API docs (when enabled by FastAPI): `GET /docs` (Swagger) and `GET /redoc`.
