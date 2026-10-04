import time
from typing import Dict, Any, List
from rich.console import Console
from rich.text import Text

class AlertEngine:
    """Engine to check metrics against thresholds and trigger alerts."""
    
    def __init__(self, config: Dict[str, Any]):
        self.config = config.get("alerts", {})
        self.latency_warn_ms = self.config.get("latency_warn_ms", 500)
        self.latency_critical_ms = self.config.get("latency_critical_ms", 2000)
        self.error_rate_threshold = self.config.get("error_rate_threshold_per_minute", 10)
        self.memory_warn_mb = self.config.get("memory_warn_mb", 256)
        self.memory_critical_mb = self.config.get("memory_critical_mb", 512)

        self.console = Console()
        self.last_alerts: Dict[str, float] = {}
        self.dedup_window_sec = 60.0

    def _should_alert(self, alert_key: str) -> bool:
        now = time.time()
        if alert_key not in self.last_alerts or (now - self.last_alerts[alert_key]) > self.dedup_window_sec:
            self.last_alerts[alert_key] = now
            return True
        return False

    def _fire_alert(self, message: str, level: str):
        prefix = "🟡 WARN:" if level == "warn" else "🔴 CRITICAL:"
        style = "bold yellow" if level == "warn" else "bold red"
        self.console.print(Text(f"{prefix} {message}", style=style))

    def check(self, behavior_entries: List[Dict[str, Any]], errors_entries: List[Dict[str, Any]], latest_snapshot: Dict[str, Any]):
        now_ms = time.time() * 1000
        
        # Latency checks
        if behavior_entries:
            p99_latency = self._calculate_percentile([e.get("duration_ms", 0) for e in behavior_entries], 99)
            if p99_latency >= self.latency_critical_ms and self._should_alert("latency_critical"):
                self._fire_alert(f"p99 Latency critical: {p99_latency:.1f}ms >= {self.latency_critical_ms}ms", "critical")
            elif p99_latency >= self.latency_warn_ms and self._should_alert("latency_warn"):
                self._fire_alert(f"p99 Latency warning: {p99_latency:.1f}ms >= {self.latency_warn_ms}ms", "warn")

        # Memory checks
        mem = latest_snapshot.get("memory_rss_mb", 0)
        if mem >= self.memory_critical_mb and self._should_alert("memory_critical"):
            self._fire_alert(f"Memory critical: {mem:.1f}MB >= {self.memory_critical_mb}MB", "critical")
        elif mem >= self.memory_warn_mb and self._should_alert("memory_warn"):
            self._fire_alert(f"Memory warning: {mem:.1f}MB >= {self.memory_warn_mb}MB", "warn")

        # Error rate checks
        now = time.time()
        recent_errors = [e for e in errors_entries if e.get("timestamp", 0) >= now - 60]
        if len(recent_errors) >= self.error_rate_threshold and self._should_alert("error_rate"):
            self._fire_alert(f"High Error Rate: {len(recent_errors)} errors in last minute", "critical")

        # Health probe failure
        if not latest_snapshot.get("is_healthy", True) and self._should_alert("health_down"):
            self._fire_alert("Health probe failed! Server is DOWN", "critical")

    def _calculate_percentile(self, data: List[float], percentile: int) -> float:
        if not data:
            return 0.0
        data_sorted = sorted(data)
        idx = int((percentile / 100.0) * len(data_sorted))
        idx = min(idx, len(data_sorted) - 1)
        return data_sorted[idx]
