# 🔭 OnFood Server Watcher & Web Dashboard

Real-time monitoring dashboard and telemetry hub for the OnFood backend.

---

## 🚀 Running with Docker

### Option 1: Standalone Docker Compose (Recommended)

From inside the `server_watcher/` directory:

```bash
docker compose up -d --build
```

Access the dashboard at: **`http://localhost:9000`**

- **Default Username:** `karthiksupport`
- **Default Password:** `karthik@6`

---

### Option 2: Running with Docker CLI

```bash
# 1. Build the Docker image
docker build -t onfood-server-watcher:latest .

# 2. Run the container
docker run -d \
  --name onfood-server-watcher \
  -p 9000:9000 \
  -e SERVER_URL=http://host.docker.internal:8000 \
  -e LOG_DIRECTORY=/logs \
  -e ADMIN_USERNAME=karthiksupport \
  -e ADMIN_PASSWORD=karthik@6 \
  -v "$(pwd)/../onfoodserver/logs:/logs:ro" \
  onfood-server-watcher:latest
```

---

### Option 3: Running Locally (Without Docker)

```powershell
# Install requirements
pip install -r requirements.txt

# Run the web dashboard
python web.py

# Or run the terminal CLI live dashboard
python watcher.py
```

---

## ⚙️ Environment Variables

All settings can be configured via environment variables or inside `config.json`:

| Variable | Default | Description |
|---|---|---|
| `SERVER_URL` | `http://localhost:8000` | URL of the OnFood backend server to probe |
| `LOG_DIRECTORY` | `/logs` | Path where OnFood logs are located |
| `WEB_HOST` | `0.0.0.0` | Host interface to bind to |
| `WEB_PORT` | `9000` | Port for the dashboard UI |
| `ADMIN_USERNAME` | `karthiksupport` | Dashboard login username |
| `ADMIN_PASSWORD` | `karthik@6` | Dashboard login password |
| `SECRET_KEY` | *(auto-generated)* | Secret key for signing web sessions |

---

## 📊 Features

- **Live Server Status:** Real-time health check indicator with ping response time (ms).
- **Online Users & WebSocket Tracking:** Live table of connected user IDs, client IPs, user-agents, active socket counts, and connection durations.
- **SSE Streams:** Real-time counter of open order-tracking Server-Sent Event channels.
- **Log Viewer & Downloader:** Read the last 100-500 lines of `behavior.log`, `request.log`, `response.log`, and `errors.log`, or download them directly.
- **Resource Monitoring:** CPU% and RSS memory usage from the backend process.
- **Top Endpoints & Latencies:** Breakdown of highest volume API routes and p50/p95/p99 latency percentiles.
