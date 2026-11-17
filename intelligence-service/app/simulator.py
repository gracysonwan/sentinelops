"""Synthetic metric traces for offline evaluation and tests.

The generator mimics what Prometheus reports for one Spring Boot service every 5 seconds under a
steady load (~10 requests/s), and can overlay the same faults the chaos module injects:

  latency_ramp  - extra latency grows by `ramp` ms every second (default 20) (/chaos/latency)
  error_burst   - error probability starts at 5% and grows 1% per second  (/chaos/errors)
  memory_leak   - 1 MB of heap is retained every second, up to 200 MB      (/chaos/memory-leak)
  gray_failure  - several signals drift a little at once (slower requests, more busy threads,
                  a few more errors) without any single metric crossing an alarm limit - e.g.
                  connection-pool contention. Reactive thresholds never fire on this.
  load_surge    - traffic doubles (benign change - should NOT be flagged)

Every sample carries `label` (1 after the fault started) and `failed` (1 once a Generation-1
reactive threshold is crossed), which the evaluation uses as ground truth.
"""
from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np

from .features import FAILURE_LIMITS

STEP = 5.0  # seconds between samples


@dataclass(frozen=True)
class Profile:
    name: str
    mean_latency_ms: float
    rps: float = 10.0
    heap_mb: float = 256.0
    live_mb: float = 55.0
    young_mb: float = 45.0
    alloc_mb_per_s: float = 3.0
    cpu: float = 0.05
    threads: float = 34.0


PROFILES = {
    "order-service": Profile("order-service", 70.0, cpu=0.07, alloc_mb_per_s=4.0, threads=38),
    "payment-service": Profile("payment-service", 33.0),
    "inventory-service": Profile("inventory-service", 14.0, cpu=0.04, alloc_mb_per_s=2.2),
}


def generate_trace(profile: Profile, scenario: str = "normal", duration_s: float = 900.0,
                   fault_start_s: float = 600.0, seed: int = 0, ramp: float = 20.0,
                   leak_mb_per_s: float = 1.0) -> list[dict]:
    rng = np.random.default_rng(seed)
    young_used = rng.uniform(0, profile.young_mb)
    gc_events: list[tuple[float, float]] = []
    heap_recent: list[float] = []
    samples: list[dict] = []
    t = 0.0
    failed = False
    while t < duration_s:
        active = scenario != "normal" and t >= fault_start_s
        dt = t - fault_start_s if active else 0.0
        rps = profile.rps * (2.0 if scenario == "load_surge" and active else 1.0)

        # --- memory: young generation fills with allocations, a GC empties it (sawtooth)
        leaked = min(leak_mb_per_s * dt, 200.0) if scenario == "memory_leak" and active else 0.0
        live = profile.live_mb + leaked
        free_for_young = max(4.0, profile.heap_mb - live)
        young_cap = min(profile.young_mb, free_for_young)
        young_used += profile.alloc_mb_per_s * (rps / profile.rps) * STEP * rng.uniform(0.8, 1.2)
        while young_used >= young_cap:
            young_used -= young_cap
            pause = 4.0 + 30.0 * (live / profile.heap_mb) ** 4 + rng.normal(0, 0.8)
            gc_events.append((t, max(1.0, pause)))
        gc_events = [(et, p) for et, p in gc_events if t - et < 30.0]
        gc_ms_per_s = sum(p for _, p in gc_events) / 30.0
        heap_now = min(1.0, (live + young_used) / profile.heap_mb)
        heap_recent = (heap_recent + [heap_now])[-6:]
        heap_ratio = min(heap_recent)  # 30-second heap floor, same as the PromQL feature

        # --- latency (log-normal noise); memory pressure slows requests via GC pauses
        base_ms = profile.mean_latency_ms * math.exp(rng.normal(0, 0.07))
        if scenario == "load_surge" and active:
            base_ms *= 1.12
        base_ms += gc_ms_per_s * 0.6
        gray = min(dt / 300.0, 1.0) if scenario == "gray_failure" and active else 0.0
        base_ms *= 1.0 + 0.45 * gray
        extra = min(ramp * dt, 8000.0) if scenario == "latency_ramp" and active else 0.0
        mean_ms = base_ms + extra
        p95_ms = base_ms * rng.normal(1.75, 0.08) + extra * 1.15  # chaos latency has +/-15% jitter

        # --- errors (binomial over the requests of this window)
        n = max(1, int(rps * STEP))
        p_err = 0.002 + 0.012 * gray
        if scenario == "error_burst" and active:
            p_err = min(1.0, 0.05 + 0.01 * dt)
        if heap_now > 0.97:
            p_err = max(p_err, 0.6)  # OutOfMemoryError territory
        error_ratio = rng.binomial(n, p_err) / n

        cpu = max(0.005, profile.cpu * (rps / profile.rps) + rng.normal(0, 0.008) + gc_ms_per_s / 1000.0)
        busy = rps * mean_ms / 1000.0
        threads = profile.threads + round(busy) + int(rng.integers(0, 2)) + round(5 * gray)

        sample = {
            "t": t,
            "p95_ms": p95_ms, "mean_ms": mean_ms, "error_ratio": error_ratio, "heap_ratio": heap_ratio,
            "cpu": cpu, "gc_ms_per_s": gc_ms_per_s, "threads": float(threads),
            "label": int(active and scenario != "load_surge"),
        }
        failed = failed or any(sample[f] >= lim for f, lim in FAILURE_LIMITS.items())
        sample["failed"] = int(failed)
        samples.append(sample)
        t += STEP
    return samples
