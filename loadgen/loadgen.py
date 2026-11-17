"""Steady synthetic traffic for the order service (standard library only).

Sends RPS order requests per second (random product and quantity) using a few worker threads,
and prints throughput / error / latency stats every 10 seconds.
"""
import json
import os
import random
import threading
import time
import urllib.error
import urllib.request

ORDER_URL = os.getenv("ORDER_URL", "http://localhost:8081").rstrip("/")
RPS = float(os.getenv("RPS", "10"))
WORKERS = int(os.getenv("WORKERS", "8"))
PRODUCTS = ["P-100", "P-200", "P-300", "P-400", "P-500"]

stats_lock = threading.Lock()
stats = {"ok": 0, "pending": 0, "error": 0, "latency_ms": []}


def place_order() -> None:
    body = json.dumps({"productId": random.choice(PRODUCTS), "quantity": random.randint(1, 3)}).encode()
    req = urllib.request.Request(f"{ORDER_URL}/orders", data=body, method="POST",
                                 headers={"Content-Type": "application/json"})
    started = time.perf_counter()
    outcome = "error"
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            order = json.loads(resp.read())
            outcome = "ok" if order.get("status") == "PAID" else "pending"
    except (urllib.error.URLError, TimeoutError, ConnectionError, ValueError):
        outcome = "error"
    elapsed = (time.perf_counter() - started) * 1000
    with stats_lock:
        stats[outcome] += 1
        stats["latency_ms"].append(elapsed)


def worker(interval: float) -> None:
    next_at = time.monotonic() + random.uniform(0, interval)
    while True:
        delay = next_at - time.monotonic()
        if delay > 0:
            time.sleep(delay)
        place_order()
        next_at = max(next_at + interval, time.monotonic())


def reporter() -> None:
    while True:
        time.sleep(10)
        with stats_lock:
            lat = sorted(stats["latency_ms"])
            total = stats["ok"] + stats["pending"] + stats["error"]
            p95 = lat[int(0.95 * (len(lat) - 1))] if lat else 0
            print(f"[loadgen] last 10s: {total} orders | paid {stats['ok']} | payment pending {stats['pending']} "
                  f"| failed {stats['error']} | p95 {p95:.0f} ms", flush=True)
            stats.update(ok=0, pending=0, error=0, latency_ms=[])


if __name__ == "__main__":
    print(f"[loadgen] sending ~{RPS:.0f} orders/s to {ORDER_URL} with {WORKERS} workers", flush=True)
    per_worker_interval = WORKERS / RPS
    for _ in range(WORKERS):
        threading.Thread(target=worker, args=(per_worker_interval,), daemon=True).start()
    reporter()
