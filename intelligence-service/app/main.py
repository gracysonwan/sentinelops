"""FastAPI service exposing the intelligence layer.

GET  /health                    liveness
GET  /status                    current verdict for every service (used by the control panel)
GET  /alerts                    alerts sent to the remediation engine (newest first)
GET  /metrics                   Prometheus metrics (anomaly score, threshold, flags) for Grafana
POST /model/reset               forget all baselines and learn again
POST /model/retrain/{service}   refit one service on its recent normal window
"""
from __future__ import annotations

import logging
import math
import threading
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException
from fastapi.responses import Response
from prometheus_client import CONTENT_TYPE_LATEST, CollectorRegistry, Gauge, generate_latest

from .config import Settings
from .detector import LEARNING, MONITORING
from .engine import DOWN, WARMUP, HttpAlertSink, MonitorEngine
from .features import FEATURES, PrometheusSource

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s - %(message)s")

STATE_CODES = {LEARNING: 0, MONITORING: 1, WARMUP: 2, DOWN: 3}

registry = CollectorRegistry()
g_score = Gauge("sentinel_anomaly_score", "Isolation Forest anomaly score (higher = more anomalous)",
                ["service"], registry=registry)
g_threshold = Gauge("sentinel_anomaly_threshold", "Decision threshold learned from normal behaviour",
                    ["service"], registry=registry)
g_anomalous = Gauge("sentinel_anomaly_flag", "1 = anomalous window, 2 = confirmed anomaly", ["service"],
                    registry=registry)
g_state = Gauge("sentinel_detector_state", "0 learning, 1 monitoring, 2 warm-up, 3 down", ["service"],
                registry=registry)
g_progress = Gauge("sentinel_baseline_progress", "Share of baseline samples collected (0..1)", ["service"],
                   registry=registry)
g_eta = Gauge("sentinel_failure_eta_seconds", "Forecast seconds until a failure limit is crossed",
              ["service"], registry=registry)
g_z = Gauge("sentinel_feature_zscore", "Deviation of each feature from normal (robust z-score)",
            ["service", "feature"], registry=registry)
g_alerts = Gauge("sentinel_alerts_sent", "Alerts sent to the remediation engine", registry=registry)


def export_metrics(status: dict[str, dict]) -> None:
    for svc, s in status.items():
        g_state.labels(svc).set(STATE_CODES.get(s.get("state"), -1))
        target = s.get("baseline_target") or 1
        g_progress.labels(svc).set(min(1.0, (s.get("baseline_progress") or 0) / target))
        g_score.labels(svc).set(s["score"] if s.get("score") is not None else math.nan)
        g_threshold.labels(svc).set(s["threshold"] if s.get("threshold") is not None else math.nan)
        g_anomalous.labels(svc).set(2 if s.get("confirmed") else 1 if s.get("anomalous") else 0)
        forecast = s.get("forecast") or {}
        g_eta.labels(svc).set(min(forecast.values()) if forecast else math.nan)
        for f in FEATURES:
            z = (s.get("zscores") or {}).get(f)
            g_z.labels(svc, f).set(z if z is not None else math.nan)


settings = Settings.from_env()
engine = MonitorEngine(settings, PrometheusSource(settings.prometheus_url, settings.services),
                       HttpAlertSink(settings.remediation_url))
engine.listeners.append(export_metrics)
_stop = threading.Event()


@asynccontextmanager
async def lifespan(_: FastAPI):
    worker = threading.Thread(target=engine.run_forever, args=(_stop,), name="monitor-loop", daemon=True)
    worker.start()
    yield
    _stop.set()


app = FastAPI(title="SentinelOps Intelligence Service", version="1.0.0", lifespan=lifespan)


@app.get("/health")
def health():
    return {"status": "UP", "ticks": engine.ticks, "metricsError": engine.last_error}


@app.get("/status")
def status():
    return {
        "services": engine.status,
        "alerts_sent": engine.alerts_sent,
        "ticks": engine.ticks,
        "metrics_error": engine.last_error,
        "settings": {
            "poll_interval": settings.poll_interval, "baseline_samples": settings.baseline_samples,
            "consecutive": settings.consecutive, "z_gate": settings.z_gate,
        },
    }


@app.get("/alerts")
def alerts():
    return list(engine.alerts)


@app.get("/metrics")
def metrics():
    g_alerts.set(engine.alerts_sent)
    return Response(generate_latest(registry), media_type=CONTENT_TYPE_LATEST)


@app.post("/model/reset")
def reset_models():
    engine.reset_models()
    return {"message": "baselines cleared - learning again", "samples_needed": settings.baseline_samples}


@app.post("/model/retrain/{service}")
def retrain(service: str):
    if service not in engine.detectors:
        raise HTTPException(404, f"unknown service {service}")
    if not engine.retrain(service):
        raise HTTPException(409, "not enough normal samples collected yet")
    det = engine.detectors[service]
    return {"service": service, "fit_count": det.fit_count, "threshold": det.threshold}
