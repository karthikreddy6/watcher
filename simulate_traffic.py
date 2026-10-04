"""
simulate_traffic.py - Cloudflare Tunnel Attack & Traffic Simulator
Simulates real requests passing through Cloudflare Tunnel with:
  - CF-Connecting-IP
  - CF-IPCountry
  - CF-Ray
"""

import json
import time
import random
import uuid
from pathlib import Path

LOG_DIR = Path("./logs")
LOG_DIR.mkdir(parents=True, exist_ok=True)
BEHAVIOR_LOG = LOG_DIR / "behavior.log"


def write_event(event: dict):
    with open(BEHAVIOR_LOG, "a", encoding="utf-8") as f:
        f.write(json.dumps(event) + "\n")


def generate_normal_traffic():
    """Simulates legitimate users from India and US placing orders."""
    endpoints = [
        ("/api/menu/categories", "GET", 25.0),
        ("/api/menu/items", "GET", 45.0),
        ("/api/orders/active", "GET", 30.0),
        ("/api/orders/checkout", "POST", 90.0),
    ]
    path, method, base_lat = random.choice(endpoints)
    event = {
        "req_id": uuid.uuid4().hex[:8],
        "event": "request_behavior",
        "method": method,
        "path_template": path,
        "status": 200,
        "duration_ms": round(base_lat + random.uniform(-5, 15), 1),
        "in_flight_at_start": 1,
        "in_flight_at_end": 0,
        "memory_rss_mb": round(88.0 + random.uniform(0, 4), 1),
        "cpu_percent": round(random.uniform(1.2, 3.8), 1),
        # Cloudflare Headers
        "client_ip": "127.0.0.1",  # Local tunnel socket
        "cf_connecting_ip": f"49.207.{random.randint(10, 99)}.{random.randint(1, 250)}",  # Real Public IP
        "cf_ipcountry": random.choice(["IN", "US", "SG"]),
        "cf_ray": f"{uuid.uuid4().hex[:16]}-BOM"
    }
    write_event(event)


def simulate_brute_force_attack(attacker_ip: str = "185.220.101.5", country: str = "RU"):
    """Simulates an attacker bot from Russia trying rapid passwords on the login API."""
    print(f"\n[!] Simulating Brute Force Attack via Cloudflare Tunnel from {attacker_ip} [{country}]...")
    for _ in range(7):
        event = {
            "req_id": uuid.uuid4().hex[:8],
            "event": "request_behavior",
            "method": "POST",
            "path_template": "/api/auth/login",
            "status": 401,  # Unauthorized!
            "duration_ms": round(random.uniform(45, 80), 1),
            "in_flight_at_start": 2,
            "in_flight_at_end": 1,
            "memory_rss_mb": 91.0,
            "cpu_percent": 2.5,
            # Cloudflare Headers
            "client_ip": "127.0.0.1",
            "cf_connecting_ip": attacker_ip,
            "cf_ipcountry": country,
            "cf_ray": f"{uuid.uuid4().hex[:16]}-FRA"
        }
        write_event(event)
        time.sleep(0.3)


def simulate_recon_fuzzing(scanner_ip: str = "104.244.76.13", country: str = "NL"):
    """Simulates an automated scanner probing hidden endpoints."""
    probes = ["/.env", "/admin", "/backup.sql", "/config.json", "/.git/config", "/phpmyadmin"]
    print(f"\n[!] Simulating Directory Reconnaissance Scan via Cloudflare from {scanner_ip} [{country}]...")
    for probe in probes:
        event = {
            "req_id": uuid.uuid4().hex[:8],
            "event": "request_behavior",
            "method": "GET",
            "path_template": probe,
            "status": 404,  # Not Found!
            "duration_ms": round(random.uniform(15, 30), 1),
            "in_flight_at_start": 1,
            "in_flight_at_end": 0,
            "memory_rss_mb": 91.5,
            "cpu_percent": 1.8,
            # Cloudflare Headers
            "client_ip": "127.0.0.1",
            "cf_connecting_ip": scanner_ip,
            "cf_ipcountry": country,
            "cf_ray": f"{uuid.uuid4().hex[:16]}-AMS"
        }
        write_event(event)
        time.sleep(0.2)


if __name__ == "__main__":
    print("=" * 65)
    print("🛡️ Cloudflare Tunnel Traffic & Attack Simulator")
    print("   Open another terminal and run 'python watcher.py' to watch!")
    print("=" * 65)

    tick = 0
    try:
        while True:
            generate_normal_traffic()
            time.sleep(0.5)
            tick += 1

            if tick == 10:
                simulate_brute_force_attack()
            elif tick == 20:
                simulate_recon_fuzzing()

            if tick >= 30:
                tick = 0
    except KeyboardInterrupt:
        print("\n[*] Simulator stopped.")
