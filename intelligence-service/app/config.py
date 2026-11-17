"""Runtime settings, read from environment variables (set in docker-compose.yml)."""
from __future__ import annotations

import os
from dataclasses import dataclass, field


def _int(name: str, default: int) -> int:
    return int(os.getenv(name, str(default)))


def _float(name: str, default: float) -> float:
    return float(os.getenv(name, str(default)))


def _list(name: str, default: str) -> list[str]:
    return [s.strip() for s in os.getenv(name, default).split(",") if s.strip()]


def _deps(raw: str) -> dict[str, list[str]]:
    """'order-service:payment-service|inventory-service' -> {'order-service': ['payment-service', 'inventory-service']}"""
    graph: dict[str, list[str]] = {}
    for part in raw.split(";"):
        if ":" in part:
            svc, deps = part.split(":", 1)
            graph[svc.strip()] = [d.strip() for d in deps.split("|") if d.strip()]
    return graph


@dataclass
class Settings:
    prometheus_url: str = "http://localhost:9090"
    remediation_url: str = "http://localhost:8090"
    services: list[str] = field(default_factory=lambda: ["order-service", "payment-service", "inventory-service"])
    # Call graph used for root-cause analysis: a caller's anomaly is a symptom if a callee is also anomalous.
    dependencies: dict[str, list[str]] = field(
        default_factory=lambda: {"order-service": ["payment-service", "inventory-service"]})
    poll_interval: float = 5.0          # seconds between metric snapshots (matches Prometheus scrape interval)
    baseline_samples: int = 60          # normal samples needed before monitoring starts (60 x 5 s = 5 min)
    consecutive: int = 3                # anomalous windows in a row needed to confirm (filters one-off spikes)
    retrain_every: int = 120            # refit on recent normal data every N monitoring samples (10 min)
    window_size: int = 720              # rolling window of trusted normal samples (1 hour)
    z_gate: float = 3.0                 # a feature must be >= 3 robust std-devs worse than normal
    score_margin: float = 0.0           # added to the 99th percentile of training scores
    warmup_seconds: int = 60            # ignore a service for this long after it (re)starts
    down_alert_after: int = 15          # seconds a service may be unreachable before a SERVICE_DOWN alert
    alert_cooldown: int = 60            # do not re-alert the same service more often than this
    model_dir: str = "models"
    seed: int = 42

    @classmethod
    def from_env(cls) -> "Settings":
        return cls(
            prometheus_url=os.getenv("PROMETHEUS_URL", cls.prometheus_url),
            remediation_url=os.getenv("REMEDIATION_URL", cls.remediation_url),
            services=_list("SERVICES", "order-service,payment-service,inventory-service"),
            dependencies=_deps(os.getenv("DEPENDENCIES", "order-service:payment-service|inventory-service")),
            poll_interval=_float("POLL_INTERVAL", cls.poll_interval),
            baseline_samples=_int("BASELINE_SAMPLES", cls.baseline_samples),
            consecutive=_int("CONSECUTIVE", cls.consecutive),
            retrain_every=_int("RETRAIN_EVERY", cls.retrain_every),
            window_size=_int("WINDOW_SIZE", cls.window_size),
            z_gate=_float("Z_GATE", cls.z_gate),
            score_margin=_float("SCORE_MARGIN", cls.score_margin),
            warmup_seconds=_int("WARMUP_SECONDS", cls.warmup_seconds),
            down_alert_after=_int("DOWN_ALERT_AFTER", cls.down_alert_after),
            alert_cooldown=_int("ALERT_COOLDOWN", cls.alert_cooldown),
            model_dir=os.getenv("MODEL_DIR", cls.model_dir),
        )
