# Ripple Backend

FastAPI service for Ripple. It exposes HTTP APIs and uses Supabase (`SUPABASE_URL`, `SUPABASE_SECRET_KEY`).

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
sudo -u ripple .venv/bin/uvicorn app.main:app --host 127.0.0.1 --port 8000
```

Check: `curl -s http://127.0.0.1:8000/health` should return JSON with `"status":"ok"`. Stop with Ctrl+C.

**CORS:** `app/main.py` currently allows `http://localhost:8081` and `http://127.0.0.1:8081`. For a production web origin, update `allow_origins` (or make it configurable) before relying on browser clients from another host.

---

## Run as a systemd service

### 1. Unit file

Create `/etc/systemd/system/ripple-backend.service`:

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
    --port 8000 \
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

- **`--host 127.0.0.1`:** binds only on loopback. Put **nginx** (or another reverse proxy) in front for TLS and public access, proxying to `http://127.0.0.1:8000`.
- To expose the app directly on all interfaces (e.g. no reverse proxy), use `--host 0.0.0.0` and open the port in your firewall.
- **`--workers`:** Uvicorn worker processes. You can set `1` for lighter servers or increase for CPU-bound workloads; each worker is a separate process.

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

After code or dependency updates:

```bash
cd /opt/ripple-backend
sudo -u ripple .venv/bin/pip install -r requirements.txt
sudo systemctl restart ripple-backend.service
```

---

## Endpoints

| Path | Description |
|------|-------------|
| `GET /health` | Liveness check |
| (see `app/routers/`) | Alarm and related APIs |

API docs (when enabled by FastAPI): `GET /docs` (Swagger) and `GET /redoc`.
