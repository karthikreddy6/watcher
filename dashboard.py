import math
from typing import Dict, Any, List
from rich.layout import Layout
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

class Dashboard:
    def __init__(self, log_tailer, health_probe, metrics_scraper, alert_engine):
        self.log_tailer = log_tailer
        self.health_probe = health_probe
        self.metrics_scraper = metrics_scraper
        self.alert_engine = alert_engine

    def make_layout(self) -> Layout:
        layout = Layout(name="root")
        layout.split(
            Layout(name="header", size=3),
            Layout(name="main", ratio=1),
            Layout(name="footer", size=3)
        )
        layout["main"].split_row(
            Layout(name="left", ratio=1),
            Layout(name="right", ratio=1)
        )
        layout["left"].split_column(
            Layout(name="status_rate"),
            Layout(name="latency_resources")
        )
        layout["right"].split_column(
            Layout(name="endpoints"),
            Layout(name="errors")
        )
        return layout

    def generate_status_panel(self):
        status = "UP" if self.health_probe.is_healthy else "DOWN"
        color = "green" if self.health_probe.is_healthy else "red"
        resp_time = self.health_probe.last_response_time_ms
        
        latest_behavior = self.log_tailer.get_latest_behavior()
        in_flight = latest_behavior.get("in_flight_at_end", 0) if latest_behavior else 0
        
        rate_1m = self.log_tailer.get_request_rate(60)
        rate_5m = self.log_tailer.get_request_rate(300)

        text = Text()
        text.append(f"Server Status: {status} ", style=f"bold {color}")
        text.append(f"(Ping: {resp_time:.1f}ms)\n\n", style="white")
        text.append(f"Req Rate (1m): {rate_1m}/min\n")
        text.append(f"Req Rate (5m): {rate_5m}/5min\n\n")
        text.append(f"In-Flight Requests: {in_flight}\n", style="bold cyan")

        return Panel(text, title="Status & Rate")

    def generate_latency_resources_panel(self):
        latencies = [e.get("duration_ms", 0) for e in self.log_tailer.behavior_entries]
        p50 = self._percentile(latencies, 50)
        p95 = self._percentile(latencies, 95)
        p99 = self._percentile(latencies, 99)

        latest = self.log_tailer.get_latest_behavior()
        mem = latest.get("memory_rss_mb", 0) if latest else 0
        cpu = latest.get("cpu_percent", 0) if latest else 0

        text = Text()
        text.append("Latency (rolling 1000):\n", style="bold")
        text.append(f"  p50: {p50:.1f}ms\n")
        text.append(f"  p95: {p95:.1f}ms\n")
        text.append(f"  p99: {p99:.1f}ms\n\n")
        text.append("Resources (latest):\n", style="bold")
        text.append(f"  Memory: {mem:.1f} MB\n")
        text.append(f"  CPU:    {cpu:.1f} %\n")
        
        return Panel(text, title="Latency & Resources")

    def generate_endpoints_panel(self):
        table = Table(title="Top 10 Endpoints", expand=True)
        table.add_column("Path", style="cyan")
        table.add_column("Count", justify="right", style="magenta")
        table.add_column("Avg Latency", justify="right")

        path_stats = {}
        for e in self.log_tailer.behavior_entries:
            path = e.get("path_template") or e.get("path", "unknown")
            dur = e.get("duration_ms", 0)
            if path not in path_stats:
                path_stats[path] = {"count": 0, "sum": 0}
            path_stats[path]["count"] += 1
            path_stats[path]["sum"] += dur

        sorted_paths = sorted(path_stats.items(), key=lambda x: x[1]["count"], reverse=True)[:10]

        for path, stats in sorted_paths:
            avg = stats["sum"] / stats["count"]
            color = "green" if avg < 100 else "yellow" if avg < 500 else "red"
            table.add_row(path, str(stats["count"]), f"[{color}]{avg:.1f}ms[/{color}]")

        return Panel(table, title="Top Endpoints")

    def generate_errors_panel(self):
        table = Table(title="Recent Errors", expand=True)
        table.add_column("Req ID", style="dim")
        table.add_column("Path")
        table.add_column("Error Type", style="red")

        recent = list(self.log_tailer.errors_entries)[-10:]
        for e in reversed(recent):
            req = e.get("req_id", "unknown")
            path = e.get("path", "")
            err_type = e.get("error_type", "")
            table.add_row(str(req), path, err_type)

        return Panel(table, title="Recent Errors")

    def _percentile(self, data, p):
        if not data:
            return 0.0
        s = sorted(data)
        idx = int((p / 100.0) * len(s))
        return s[min(idx, len(s)-1)]

    def get_layout(self):
        layout = self.make_layout()
        layout["header"].update(Panel(Text("Server Watcher Dashboard", style="bold white on blue", justify="center")))
        layout["status_rate"].update(self.generate_status_panel())
        layout["latency_resources"].update(self.generate_latency_resources_panel())
        layout["endpoints"].update(self.generate_endpoints_panel())
        layout["errors"].update(self.generate_errors_panel())
        return layout
