"""
OnFood Server Watcher — Web Dashboard.

A FastAPI web application that provides a browser-based monitoring dashboard
for the OnFood backend server. Features:
  - Authentication (session-based login)
  - Real-time metrics dashboard (auto-refreshing)
  - Log file viewing (tail with configurable lines)
  - Log file downloads
  - Server health probing

Run:
    python web.py
    # or: uvicorn web:app --host 0.0.0.0 --port 9000
"""

import json
import os
import secrets
import time
from collections import deque
from datetime import datetime
from pathlib import Path
from typing import Optional

import httpx
from fastapi import FastAPI, Request, Form, Depends, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse, FileResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from starlette.middleware.sessions import SessionMiddleware

# ─── Load Configuration ──────────────────────────────────────────────────────
CONFIG_PATH = Path(__file__).parent / "config.json"
CONFIG = {}
if CONFIG_PATH.exists():
    try:
        with open(CONFIG_PATH, "r", encoding="utf-8") as f:
            CONFIG = json.load(f)
    except Exception:
        CONFIG = {}

WEB_CONFIG = CONFIG.get("web", {})
SERVER_URL = os.getenv("SERVER_URL", CONFIG.get("server_url", "http://localhost:8000")).rstrip("/")
LOG_DIR_VAL = os.getenv("LOG_DIRECTORY")
if LOG_DIR_VAL:
    LOG_DIR = Path(LOG_DIR_VAL)
else:
    LOG_DIR = Path(__file__).parent / CONFIG.get("log_directory", "../onfoodserver/logs")

ADMIN_USERNAME = os.getenv("ADMIN_USERNAME", WEB_CONFIG.get("admin_username", "karthiksupport"))
ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD", WEB_CONFIG.get("admin_password", "karthik@6"))
SECRET_KEY = os.getenv("SECRET_KEY", WEB_CONFIG.get("secret_key", secrets.token_hex(32)))
WEB_HOST = os.getenv("WEB_HOST", WEB_CONFIG.get("host", "0.0.0.0"))
WEB_PORT = int(os.getenv("WEB_PORT", str(WEB_CONFIG.get("port", 9000))))

ALERT_CONFIG = CONFIG.get("alerts", {})

# ─── App Setup ────────────────────────────────────────────────────────────────
app = FastAPI(
    title="OnFood Server Watcher",
    docs_url=None,
    redoc_url=None,
)
app.add_middleware(SessionMiddleware, secret_key=SECRET_KEY)

TEMPLATES_DIR = Path(__file__).parent / "templates"
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))

# Valid log file names (prevent path traversal)
ALLOWED_LOG_FILES = {"behavior.log", "request.log", "response.log", "errors.log"}


# ─── Authentication ──────────────────────────────────────────────────────────

def get_current_user(request: Request) -> str:
    """Dependency that returns the logged-in username or redirects to login."""
    user = request.session.get("user")
    if not user:
        raise HTTPException(status_code=401, detail="Not authenticated")
    return user


def require_login(request: Request) -> str:
    """Dependency for page routes — redirects to /login instead of 401."""
    user = request.session.get("user")
    if not user:
        # For API calls, raise 401; for page loads, we'll handle in the route
        raise HTTPException(status_code=401)
    return user


# ─── Auth Routes ─────────────────────────────────────────────────────────────

@app.get("/login", response_class=HTMLResponse)
async def login_page(request: Request, error: str = ""):
    """Show the login form."""
    # If already logged in, redirect to dashboard
    if request.session.get("user"):
        return RedirectResponse("/", status_code=302)
    return templates.TemplateResponse(
        request=request,
        name="login.html",
        context={"error": error},
    )


@app.post("/login")
async def login_submit(
    request: Request,
    username: str = Form(...),
    password: str = Form(...),
):
    """Validate credentials and create session."""
    if (
        secrets.compare_digest(username, ADMIN_USERNAME)
        and secrets.compare_digest(password, ADMIN_PASSWORD)
    ):
        request.session["user"] = username
        request.session["login_time"] = datetime.now().isoformat()
        return RedirectResponse("/", status_code=302)
    return templates.TemplateResponse(
        request=request,
        name="login.html",
        context={"error": "Invalid username or password"},
    )


@app.get("/logout")
async def logout(request: Request):
    """Clear session and redirect to login."""
    request.session.clear()
    return RedirectResponse("/login", status_code=302)


# ─── Dashboard Page ──────────────────────────────────────────────────────────

@app.get("/", response_class=HTMLResponse)
async def dashboard_page(request: Request):
    """Main dashboard page (requires login)."""
    user = request.session.get("user")
    if not user:
        return RedirectResponse("/login", status_code=302)
    return templates.TemplateResponse(
        request=request,
        name="dashboard.html",
        context={
            "user": user,
            "server_url": SERVER_URL,
        },
    )


# ─── Log File Helpers ────────────────────────────────────────────────────────

def _resolve_log_path(filename: str) -> Path:
    """Resolve a log filename to its absolute path, guarding against traversal."""
    if filename not in ALLOWED_LOG_FILES:
        raise HTTPException(status_code=404, detail=f"Log file '{filename}' not found")
    path = (LOG_DIR / filename).resolve()
    if not path.exists():
        raise HTTPException(status_code=404, detail=f"Log file '{filename}' does not exist yet")
    return path


def _tail_file(path: Path, n: int = 100) -> tuple[list[str], int]:
    """Read the last N lines of a file efficiently."""
    if not path.exists():
        return [], 0
    with open(path, "r", encoding="utf-8", errors="replace") as f:
        all_lines = f.readlines()
    total = len(all_lines)
    return [line.rstrip() for line in all_lines[-n:]], total


def _parse_behavior_entries(lines: list[str]) -> list[dict]:
    """Parse behavior.log JSON lines into dicts."""
    entries = []
    for line in lines:
        # Each line: "2026-10-02 19:33:28,117 INFO {json...}"
        try:
            # Find the JSON part (after "INFO " or "ERROR ")
            json_start = line.find("{")
            if json_start >= 0:
                entry = json.loads(line[json_start:])
                # Add timestamp from log prefix
                entry["_time"] = line[:23] if len(line) > 23 else ""
                entries.append(entry)
        except (json.JSONDecodeError, ValueError):
            continue
    return entries


def _parse_error_entries(lines: list[str]) -> list[dict]:
    """Parse errors.log JSON lines into dicts."""
    entries = []
    for line in lines:
        try:
            json_start = line.find("{")
            if json_start >= 0:
                entry = json.loads(line[json_start:])
                entry["_time"] = line[:23] if len(line) > 23 else ""
                entries.append(entry)
        except (json.JSONDecodeError, ValueError):
            continue
    return entries


# ─── Stats Computation ───────────────────────────────────────────────────────

def _compute_stats() -> dict:
    """Compute dashboard statistics from log files."""
    behavior_path = LOG_DIR / "behavior.log"
    errors_path = LOG_DIR / "errors.log"

    # Read last 1000 behavior entries for stats
    behavior_lines, behavior_total = _tail_file(behavior_path, 1000)
    behavior_entries = _parse_behavior_entries(behavior_lines)

    # Read last 100 error entries
    error_lines, error_total = _tail_file(errors_path, 100)
    error_entries = _parse_error_entries(error_lines)

    # Filter to only request_behavior events
    request_entries = [e for e in behavior_entries if e.get("event") == "request_behavior"]

    # Basic stats
    total_requests = behavior_total  # rough count (one line per request)
    durations = [e.get("duration_ms", 0) for e in request_entries if "duration_ms" in e]
    statuses = [e.get("status", 0) for e in request_entries]

    avg_latency = round(sum(durations) / len(durations), 1) if durations else 0
    sorted_durations = sorted(durations)
    p50 = sorted_durations[len(sorted_durations) // 2] if sorted_durations else 0
    p95 = sorted_durations[int(len(sorted_durations) * 0.95)] if sorted_durations else 0
    p99 = sorted_durations[int(len(sorted_durations) * 0.99)] if sorted_durations else 0

    # Latest resource info
    latest = request_entries[-1] if request_entries else {}
    memory_rss_mb = latest.get("memory_rss_mb", 0)
    cpu_percent = latest.get("cpu_percent", 0)
    in_flight = latest.get("in_flight_at_end", 0)

    # Time-windowed stats (approximate from last entries)
    now_entries_1m = request_entries[-50:]  # rough approximation
    now_entries_5m = request_entries[-200:]
    error_count_5m = sum(1 for e in request_entries[-200:] if e.get("is_error"))

    # Status code distribution
    status_2xx = sum(1 for s in statuses if 200 <= s < 300)
    status_4xx = sum(1 for s in statuses if 400 <= s < 500)
    status_5xx = sum(1 for s in statuses if s >= 500)

    # Recent requests (last 25)
    recent_requests = []
    for e in request_entries[-25:]:
        recent_requests.append({
            "time": e.get("_time", "")[-12:],  # HH:MM:SS,ms
            "method": e.get("method", ""),
            "path": e.get("path_template", ""),
            "status": e.get("status", 0),
            "duration_ms": e.get("duration_ms", 0),
            "client_ip": e.get("client_ip", ""),
            "user_id": (e.get("user_id", "") or "")[:8],
        })
    recent_requests.reverse()  # newest first

    # Recent errors (last 15)
    recent_errors = []
    for e in error_entries[-15:]:
        recent_errors.append({
            "time": e.get("_time", "")[-12:],
            "path": e.get("path", ""),
            "error_type": e.get("error_type", ""),
            "message": str(e.get("error", ""))[:120],
            "method": e.get("method", ""),
            "req_id": e.get("req_id", ""),
        })
    recent_errors.reverse()

    # Top endpoints
    endpoint_stats: dict[str, dict] = {}
    for e in request_entries:
        path = e.get("path_template", "unknown")
        method = e.get("method", "?")
        key = f"{method} {path}"
        if key not in endpoint_stats:
            endpoint_stats[key] = {"path": key, "count": 0, "total_ms": 0}
        endpoint_stats[key]["count"] += 1
        endpoint_stats[key]["total_ms"] += e.get("duration_ms", 0)

    top_endpoints = sorted(endpoint_stats.values(), key=lambda x: x["count"], reverse=True)[:10]
    for ep in top_endpoints:
        ep["avg_latency_ms"] = round(ep["total_ms"] / ep["count"], 1) if ep["count"] else 0
        del ep["total_ms"]

    max_ep_count = top_endpoints[0]["count"] if top_endpoints else 1

    # Log file info
    log_files = []
    for fname in sorted(ALLOWED_LOG_FILES):
        fpath = LOG_DIR / fname
        if fpath.exists():
            stat = fpath.stat()
            size = stat.st_size
            if size >= 1_000_000:
                size_human = f"{size / 1_000_000:.1f} MB"
            elif size >= 1_000:
                size_human = f"{size / 1_000:.1f} KB"
            else:
                size_human = f"{size} B"
            log_files.append({
                "name": fname,
                "size_bytes": size,
                "size_human": size_human,
                "modified": datetime.fromtimestamp(stat.st_mtime).strftime("%Y-%m-%d %H:%M:%S"),
            })

    return {
        "total_requests": total_requests,
        "avg_latency_ms": avg_latency,
        "p50_ms": p50,
        "p95_ms": p95,
        "p99_ms": p99,
        "memory_rss_mb": round(memory_rss_mb, 1),
        "cpu_percent": round(cpu_percent, 1),
        "in_flight": in_flight,
        "requests_1m": len(now_entries_1m),
        "requests_5m": len(now_entries_5m),
        "error_count_5m": error_count_5m,
        "status_2xx": status_2xx,
        "status_4xx": status_4xx,
        "status_5xx": status_5xx,
        "recent_requests": recent_requests,
        "recent_errors": recent_errors,
        "top_endpoints": top_endpoints,
        "max_endpoint_count": max_ep_count,
        "log_files": log_files,
        "thresholds": {
            "latency_warn_ms": ALERT_CONFIG.get("latency_warn_ms", 500),
            "latency_critical_ms": ALERT_CONFIG.get("latency_critical_ms", 2000),
            "memory_warn_mb": ALERT_CONFIG.get("memory_warn_mb", 256),
            "memory_critical_mb": ALERT_CONFIG.get("memory_critical_mb", 512),
        },
    }


async def _get_live_server_data() -> dict:
    """Fetch live connection, active user, and health data from OnFood server."""
    result = {
        "server_status": "down",
        "server_response_ms": 0,
        "websockets": {"total_connections": 0, "active_users_count": 0, "users": []},
        "sse": {"total_connections": 0, "active_users_count": 0, "users": []},
        "http_active_users": [],
        "http_active_count": 0,
    }

    # 1. Try the rich live monitoring endpoint
    try:
        async with httpx.AsyncClient(timeout=2.5) as client:
            t0 = time.perf_counter()
            resp = await client.get(f"{SERVER_URL}/api/monitoring/live")
            elapsed = round((time.perf_counter() - t0) * 1000, 1)
            if resp.status_code == 200:
                data = resp.json()
                result["server_status"] = "up"
                result["server_response_ms"] = elapsed
                result["websockets"] = data.get("websockets", result["websockets"])
                result["sse"] = data.get("sse", result["sse"])
                result["http_active_users"] = data.get("http_active_users", [])
                result["http_active_count"] = len(result["http_active_users"])
                if data.get("in_flight_requests") is not None:
                    result["live_in_flight"] = data["in_flight_requests"]
                if data.get("memory_rss_mb") is not None:
                    result["live_memory_rss_mb"] = data["memory_rss_mb"]
                if data.get("cpu_percent") is not None:
                    result["live_cpu_percent"] = data["cpu_percent"]
                return result
    except Exception:
        pass

    # 2. Fallback to root health check /
    try:
        async with httpx.AsyncClient(timeout=2.0) as client:
            t0 = time.perf_counter()
            resp = await client.get(f"{SERVER_URL}/")
            elapsed = round((time.perf_counter() - t0) * 1000, 1)
            if resp.status_code == 200:
                result["server_status"] = "up"
                result["server_response_ms"] = elapsed
                return result
    except Exception as e:
        result["server_status"] = "down"
        result["error"] = str(e)

    return result


# ─── API Routes ──────────────────────────────────────────────────────────────

@app.get("/api/stats")
async def api_stats(request: Request):
    """Return dashboard statistics and live user/websocket metrics as JSON."""
    if not request.session.get("user"):
        return JSONResponse({"error": "unauthorized"}, status_code=401)
    stats = _compute_stats()
    live = await _get_live_server_data()
    stats.update(live)
    return stats


@app.get("/api/health")
async def api_health(request: Request):
    """Probe the OnFood server health."""
    if not request.session.get("user"):
        return JSONResponse({"error": "unauthorized"}, status_code=401)
    live = await _get_live_server_data()
    return {
        "status": live["server_status"],
        "response_ms": live["server_response_ms"],
        "websockets": live["websockets"],
        "sse": live["sse"],
        "http_active_count": live["http_active_count"],
    }


@app.get("/api/logs/{filename}")
async def api_log_tail(request: Request, filename: str, lines: int = 100):
    """Return the last N lines of a log file."""
    if not request.session.get("user"):
        return JSONResponse({"error": "unauthorized"}, status_code=401)
    path = _resolve_log_path(filename)
    tail_lines, total = _tail_file(path, min(lines, 500))
    return {"lines": tail_lines, "total_lines": total, "filename": filename}


@app.get("/api/download/{filename}")
async def api_download(request: Request, filename: str):
    """Download a log file."""
    if not request.session.get("user"):
        return RedirectResponse("/login", status_code=302)
    path = _resolve_log_path(filename)
    return FileResponse(
        path=str(path),
        filename=filename,
        media_type="text/plain",
    )


# ─── Entry Point ─────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import uvicorn
    print(f"\n  OnFood Server Watcher -- Web Dashboard")
    print(f"  -------------------------------------")
    print(f"  URL:      http://localhost:{WEB_PORT}")
    print(f"  Username: {ADMIN_USERNAME}")
    print(f"  Watching: {LOG_DIR.resolve()}")
    print(f"  Server:   {SERVER_URL}")
    print()
    uvicorn.run(
        "web:app",
        host=WEB_HOST,
        port=WEB_PORT,
        reload=True,
        log_level="info",
    )
