import asyncio
import json
import os
import argparse
from collections import deque
import time
import httpx
from rich.live import Live

from dashboard import Dashboard
from alerts import AlertEngine

class LogTailer:
    """Async file tail of behavior.log and errors.log."""
    def __init__(self, log_dir: str, files: list, max_entries: int = 1000):
        self.log_dir = log_dir
        self.files = files
        self.behavior_entries = deque(maxlen=max_entries)
        self.errors_entries = deque(maxlen=max_entries)
        self.file_positions = {}
        self.timestamps = deque(maxlen=max_entries)

    async def tail(self):
        for f in self.files:
            path = os.path.join(self.log_dir, f)
            if os.path.exists(path):
                with open(path, 'r') as fp:
                    fp.seek(0, 2)
                    self.file_positions[f] = fp.tell()
            else:
                self.file_positions[f] = 0

        while True:
            for f in self.files:
                path = os.path.join(self.log_dir, f)
                if not os.path.exists(path):
                    continue
                
                with open(path, 'r') as fp:
                    pos = self.file_positions.get(f, 0)
                    fp.seek(pos)
                    lines = fp.readlines()
                    self.file_positions[f] = fp.tell()
                    
                    for line in lines:
                        if not line.strip():
                            continue
                        try:
                            entry = json.loads(line)
                            entry['timestamp'] = time.time()
                            if f == "behavior.log":
                                self.behavior_entries.append(entry)
                                self.timestamps.append(time.time())
                            elif f == "errors.log":
                                self.errors_entries.append(entry)
                        except json.JSONDecodeError:
                            pass
            await asyncio.sleep(0.5)

    def get_latest_behavior(self) -> dict:
        return self.behavior_entries[-1] if self.behavior_entries else {}

    def get_request_rate(self, window_sec: int) -> int:
        now = time.time()
        cutoff = now - window_sec
        count = sum(1 for t in self.timestamps if t >= cutoff)
        return count

class HealthProbe:
    """Periodic async GET / to server_url to check health."""
    def __init__(self, url: str, interval: int = 5):
        self.url = url
        self.interval = interval
        self.is_healthy = False
        self.last_response_time_ms = 0.0

    async def probe(self):
        async with httpx.AsyncClient() as client:
            while True:
                try:
                    start = time.time()
                    r = await client.get(self.url, timeout=2.0)
                    dur = (time.time() - start) * 1000
                    self.is_healthy = r.status_code == 200
                    self.last_response_time_ms = dur
                except Exception:
                    self.is_healthy = False
                    self.last_response_time_ms = 0.0
                await asyncio.sleep(self.interval)

class MetricsScraper:
    """Periodic async GET /metrics to extract Prometheus values."""
    def __init__(self, url: str, interval: int = 5):
        self.url = url + "/metrics" if not url.endswith("/") else url + "metrics"
        self.interval = interval
        self.metrics = {}

    async def scrape(self):
        async with httpx.AsyncClient() as client:
            while True:
                try:
                    r = await client.get(self.url, timeout=2.0)
                    if r.status_code == 200:
                        self.parse_prometheus(r.text)
                except Exception:
                    pass
                await asyncio.sleep(self.interval)
                
    def parse_prometheus(self, text: str):
        for line in text.splitlines():
            if line.startswith("#") or not line.strip():
                continue
            parts = line.split()
            if len(parts) >= 2:
                key, val = parts[0], parts[1]
                try:
                    self.metrics[key] = float(val)
                except ValueError:
                    pass

async def main():
    parser = argparse.ArgumentParser(description="Server Watcher CLI")
    parser.add_argument("--config", default="config.json", help="Path to config file")
    parser.add_argument("--logs", default=None, help="Override log directory")
    args = parser.parse_args()

    try:
        with open(args.config, 'r') as f:
            config = json.load(f)
    except Exception as e:
        print(f"Error loading config: {e}")
        return

    config_dir = os.path.dirname(os.path.abspath(args.config))
    log_dir_raw = args.logs if args.logs else config.get("log_directory", ".")
    log_dir = os.path.normpath(os.path.join(config_dir, log_dir_raw))

    tailer = LogTailer(log_dir, config.get("tail_files", ["behavior.log", "errors.log"]))
    probe = HealthProbe(config.get("server_url", "http://localhost:8000"), config.get("poll_interval_seconds", 5))
    scraper = MetricsScraper(config.get("server_url", "http://localhost:8000"), config.get("poll_interval_seconds", 5))
    alerter = AlertEngine(config)

    asyncio.create_task(tailer.tail())
    asyncio.create_task(probe.probe())
    asyncio.create_task(scraper.scrape())

    dashboard = Dashboard(tailer, probe, scraper, alerter)

    try:
        with Live(dashboard.get_layout(), refresh_per_second=1, screen=True) as live:
            while True:
                latest_snapshot = {
                    "is_healthy": probe.is_healthy,
                    "memory_rss_mb": tailer.get_latest_behavior().get("memory_rss_mb", 0)
                }
                alerter.check(list(tailer.behavior_entries), list(tailer.errors_entries), latest_snapshot)
                
                live.update(dashboard.get_layout())
                await asyncio.sleep(1)
    except asyncio.CancelledError:
        pass
    except KeyboardInterrupt:
        pass

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
