"""Feature definitions and the Prometheus client that builds one feature vector per service.

Each 5-second snapshot turns raw Micrometer metrics into 7 health features. All features are
oriented so that a HIGHER value means a LESS healthy service, which lets the detector check the
direction of a deviation (a service getting faster is not an incident).
"""
from __future__ import annotations

import math
from typing import Protocol

import httpx

FEATURES: list[str] = [
    "p95_ms",        # 95th percentile request latency (ms)
    "mean_ms",       # mean request latency (ms)
    "error_ratio",   # share of requests answered with HTTP 5xx
    "heap_ratio",    # heap floor: lowest heap use in the last 30 s (what survives GC) / heap max
    "cpu",           # process CPU usage (0..1)
    "gc_ms_per_s",   # time spent in GC pauses (ms per second)
    "threads",       # live JVM threads (grows when requests pile up)
]

# Smallest spread assumed for each feature when scaling. Without a floor, a very stable baseline
# (e.g. a constant thread count) would make tiny harmless changes look like huge deviations.
FEATURE_FLOORS: dict[str, float] = {
    "p95_ms": 15.0,
    "mean_ms": 8.0,
    "error_ratio": 0.02,
    "heap_ratio": 0.04,
    "cpu": 0.03,
    "gc_ms_per_s": 3.0,
    "threads": 3.0,
}

# Which kind of fault a deviating feature points to (used for explanation and remediation choice).
ROOT_CAUSE: dict[str, str] = {
    "p95_ms": "latency",
    "mean_ms": "latency",
    "threads": "latency",
    "error_ratio": "errors",
    "heap_ratio": "memory",
    "gc_ms_per_s": "memory",
    "cpu": "cpu",
}

# Generation-1 "reactive" failure thresholds: the point where a classic alert would fire and the
# service is effectively failing for users. Used for forecasting and for measuring lead time.
FAILURE_LIMITS: dict[str, float] = {
    "p95_ms": 2000.0,
    "error_ratio": 0.5,
    "heap_ratio": 0.92,
}

_EXCLUDE = 'uri!~"/actuator.*|/chaos.*|/admin.*"'

QUERIES: dict[str, str] = {
    "req_rate": f"sum by (application) (rate(http_server_requests_seconds_count{{{_EXCLUDE}}}[30s]))",
    "err_rate": f'sum by (application) (rate(http_server_requests_seconds_count{{{_EXCLUDE},outcome="SERVER_ERROR"}}[30s]))',
    "p95_s": f"histogram_quantile(0.95, sum by (application, le) (rate(http_server_requests_seconds_bucket{{{_EXCLUDE}}}[30s])))",
    "lat_sum": f"sum by (application) (rate(http_server_requests_seconds_sum{{{_EXCLUDE}}}[30s]))",
    # Minimum over 30 seconds removes the garbage-collection sawtooth and leaves the memory that
    # survives GC - the signal that grows steadily during a leak.
    "heap_used": 'min_over_time((sum by (application) (jvm_memory_used_bytes{area="heap"}))[30s:5s])',
    "heap_max": 'sum by (application) (jvm_memory_max_bytes{area="heap"} > 0)',
    "cpu": "max by (application) (process_cpu_usage)",
    "gc_s": "sum by (application) (rate(jvm_gc_pause_seconds_sum[30s]))",
    "threads": "max by (application) (jvm_threads_live_threads)",
    "start_time": "max by (application) (process_start_time_seconds)",
}
# Scrape health is labelled by Prometheus job (job names equal service names in prometheus.yml).
UP_QUERY = "max by (job) (up)"


class MetricSource(Protocol):
    def fetch(self) -> dict[str, dict[str, float]]:
        """Return {service: {feature/raw name: value}} for the current moment."""


def _to_float(raw: str) -> float:
    try:
        return float(raw)
    except (TypeError, ValueError):
        return math.nan


def parse_vector(payload: dict, label: str) -> dict[str, float]:
    """Prometheus instant-vector JSON -> {label value: float}."""
    out: dict[str, float] = {}
    for item in payload.get("data", {}).get("result", []):
        key = item.get("metric", {}).get(label)
        if key is not None:
            out[key] = _to_float(item.get("value", [None, None])[1])
    return out


def build_features(raw: dict[str, float]) -> dict[str, float]:
    """Combine raw query results for one service into the model features."""
    req = raw.get("req_rate", math.nan)
    has_traffic = math.isfinite(req) and req > 0.01
    err = raw.get("err_rate", 0.0)
    heap_used, heap_max = raw.get("heap_used", math.nan), raw.get("heap_max", math.nan)
    gc_s = raw.get("gc_s", math.nan)
    return {
        "p95_ms": raw.get("p95_s", math.nan) * 1000 if has_traffic else math.nan,
        "mean_ms": raw.get("lat_sum", math.nan) / req * 1000 if has_traffic else math.nan,
        "error_ratio": (err if math.isfinite(err) else 0.0) / req if has_traffic else 0.0,
        "heap_ratio": heap_used / heap_max if heap_max and math.isfinite(heap_max) and heap_max > 0 else math.nan,
        "cpu": raw.get("cpu", math.nan),
        "gc_ms_per_s": gc_s * 1000 if math.isfinite(gc_s) else 0.0,
        "threads": raw.get("threads", math.nan),
    }


class PrometheusSource:
    """Queries Prometheus' HTTP API once per tick (one query per raw metric, all services at once)."""

    def __init__(self, base_url: str, services: list[str], timeout: float = 3.0):
        self.base_url = base_url.rstrip("/")
        self.services = services
        self.client = httpx.Client(timeout=timeout)

    def _query(self, promql: str) -> dict:
        r = self.client.get(f"{self.base_url}/api/v1/query", params={"query": promql})
        r.raise_for_status()
        return r.json()

    def fetch(self) -> dict[str, dict[str, float]]:
        raw: dict[str, dict[str, float]] = {svc: {} for svc in self.services}
        for name, promql in QUERIES.items():
            for svc, value in parse_vector(self._query(promql), "application").items():
                if svc in raw:
                    raw[svc][name] = value
        up = parse_vector(self._query(UP_QUERY), "job")
        snapshot: dict[str, dict[str, float]] = {}
        for svc in self.services:
            values = build_features(raw[svc]) if raw[svc] else {}
            values["req_rate"] = raw[svc].get("req_rate", math.nan)
            values["start_time"] = raw[svc].get("start_time", math.nan)
            values["up"] = up.get(svc, math.nan)
            snapshot[svc] = values
        return snapshot
