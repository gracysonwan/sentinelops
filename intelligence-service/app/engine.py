"""Monitoring loop: metrics -> per-service detection -> root-cause analysis -> alert to remediation."""
from __future__ import annotations

import logging
import math
import threading
import time
from collections import deque
from typing import Callable, Protocol

import httpx

from .config import Settings
from .detector import LEARNING, MONITORING, ServiceDetector, Verdict
from .features import MetricSource

log = logging.getLogger("sentinel.engine")

WARMUP = "WARMUP"
DOWN = "DOWN"
NO_DATA = "NO_DATA"


class AlertSink(Protocol):
    def send(self, alert: dict) -> tuple[int, str]:
        """Deliver an alert; return (HTTP status, message)."""


class HttpAlertSink:
    """POSTs alerts to the remediation engine (Layer 5)."""

    def __init__(self, remediation_url: str, timeout: float = 3.0):
        self.url = remediation_url.rstrip("/") + "/api/remediate"
        self.client = httpx.Client(timeout=timeout)

    def send(self, alert: dict) -> tuple[int, str]:
        try:
            r = self.client.post(self.url, json=alert)
            try:
                message = r.json().get("message", r.text)
            except ValueError:
                message = r.text
            return r.status_code, message
        except httpx.HTTPError as e:
            return 0, f"remediation engine unreachable: {e}"


class MonitorEngine:
    def __init__(self, settings: Settings, source: MetricSource, sink: AlertSink,
                 clock: Callable[[], float] = time.time):
        self.settings = settings
        self.source = source
        self.sink = sink
        self.clock = clock
        self.lock = threading.Lock()
        self.detectors: dict[str, ServiceDetector] = {}
        for svc in settings.services:
            det = ServiceDetector(svc, baseline_target=settings.baseline_samples,
                                  consecutive=settings.consecutive, retrain_every=settings.retrain_every,
                                  window_size=settings.window_size, z_gate=settings.z_gate,
                                  score_margin=settings.score_margin, seed=settings.seed)
            if det.load(settings.model_dir):
                log.info("Loaded saved baseline model for %s", svc)
            self.detectors[svc] = det
        self.status: dict[str, dict] = {}
        self.last_start: dict[str, float] = {}
        self.warmup_until: dict[str, float] = {}
        self.down_since: dict[str, float] = {}
        self.last_alert: dict[str, float] = {}
        self.fit_counts = {svc: d.fit_count for svc, d in self.detectors.items()}
        self.alerts: deque[dict] = deque(maxlen=100)
        self.alerts_sent = 0
        self.ticks = 0
        self.last_error: str | None = None
        self.listeners: list[Callable[[dict[str, dict]], None]] = []

    # ------------------------------------------------------------------ main step

    def tick(self) -> dict[str, dict]:
        now = self.clock()
        try:
            snapshot = self.source.fetch()
            self.last_error = None
        except Exception as e:  # Prometheus down or unreachable: keep the last status, retry next tick
            self.last_error = f"metrics unavailable: {e}"
            log.warning(self.last_error)
            return self.status

        with self.lock:
            verdicts: dict[str, Verdict] = {}
            states: dict[str, str] = {}
            for svc in self.settings.services:
                data = snapshot.get(svc, {})
                state = self._availability(svc, data, now)
                states[svc] = state
                if state in (DOWN, NO_DATA, WARMUP):
                    self.status[svc] = self._status_without_verdict(svc, state, data, now)
                    continue
                verdict = self.detectors[svc].observe(data, now)
                verdicts[svc] = verdict
                states[svc] = verdict.state

            self._root_cause_analysis(verdicts, states)

            for svc, v in verdicts.items():
                if v.confirmed and v.suppressed_by is None:
                    self._alert(svc, v, now)
                self.status[svc] = v.to_dict() | {"availability": "UP", "req_rate": _r(snapshot[svc].get("req_rate"))}

            for svc in self.settings.services:
                if states[svc] == DOWN and now - self.down_since.get(svc, now) >= self.settings.down_alert_after:
                    self._alert_down(svc, now)

            self._persist_new_models()
            self.ticks += 1
            status = dict(self.status)
        for listener in self.listeners:
            listener(status)
        return status

    # ------------------------------------------------------------------ helpers

    def _availability(self, svc: str, data: dict, now: float) -> str:
        up = data.get("up", math.nan)
        if up is None or not math.isfinite(up):
            return NO_DATA
        if up < 1:
            self.down_since.setdefault(svc, now)
            return DOWN
        self.down_since.pop(svc, None)
        start = data.get("start_time", math.nan)
        if math.isfinite(start):
            previous = self.last_start.get(svc)
            if previous is not None and abs(start - previous) > 1:
                # The JVM restarted (by us or by Docker): give it time to warm up before judging it.
                self.warmup_until[svc] = now + self.settings.warmup_seconds
                self.detectors[svc].warmup()
                log.info("%s restarted - warm-up for %ss", svc, self.settings.warmup_seconds)
            self.last_start[svc] = start
        if now < self.warmup_until.get(svc, 0):
            return WARMUP
        return MONITORING

    def _root_cause_analysis(self, verdicts: dict[str, Verdict], states: dict[str, str]) -> None:
        """If a caller and one of its dependencies are both unhealthy, blame the dependency."""
        for svc, v in verdicts.items():
            if not v.anomalous:
                continue
            for dep in self.settings.dependencies.get(svc, []):
                dep_v = verdicts.get(dep)
                dep_unhealthy = states.get(dep) in (DOWN, WARMUP) or (dep_v is not None and dep_v.streak > 0)
                if dep_unhealthy:
                    v.suppressed_by = dep
                    break

    def _alert(self, svc: str, v: Verdict, now: float) -> None:
        if now - self.last_alert.get(svc, -1e9) < self.settings.alert_cooldown:
            return
        alert = {
            "service": svc, "score": v.score, "rootCause": v.root_cause, "reason": v.reason(),
            "detectedAt": now, "features": {k: _r(val) for k, val in v.features.items()},
            "trigger": "AI_PREDICTION",
        }
        self._deliver(svc, alert, now)

    def _alert_down(self, svc: str, now: float) -> None:
        if now - self.last_alert.get(svc, -1e9) < self.settings.alert_cooldown:
            return
        alert = {"service": svc, "score": 1.0, "rootCause": "unavailable",
                 "reason": f"no successful scrape for {now - self.down_since[svc]:.0f}s",
                 "detectedAt": now, "features": {}, "trigger": "SERVICE_DOWN"}
        self._deliver(svc, alert, now)

    def _deliver(self, svc: str, alert: dict, now: float) -> None:
        code, message = self.sink.send(alert)
        self.last_alert[svc] = now
        self.alerts_sent += 1
        record = dict(alert, response_code=code, response=message)
        self.alerts.appendleft(record)
        log.warning("ALERT %s cause=%s score=%s -> remediation %s %s",
                    svc, alert["rootCause"], alert["score"], code, message)

    def _status_without_verdict(self, svc: str, state: str, data: dict, now: float) -> dict:
        det = self.detectors[svc]
        return {
            "service": svc, "state": state, "timestamp": now, "availability": "DOWN" if state == DOWN else state,
            "anomalous": False, "confirmed": False, "score": None, "threshold": det.threshold,
            "features": {}, "zscores": {}, "forecast": {}, "reason": None,
            "baseline_progress": len(det.baseline) if det.state == LEARNING else det.baseline_target,
            "baseline_target": det.baseline_target, "req_rate": _r(data.get("req_rate")),
            "warmup_remaining": max(0.0, round(self.warmup_until.get(svc, 0) - now, 1)),
        }

    def _persist_new_models(self) -> None:
        for svc, det in self.detectors.items():
            if det.fit_count != self.fit_counts.get(svc) and det.state == MONITORING:
                try:
                    det.save(self.settings.model_dir)
                    log.info("Saved model for %s (fit #%d, threshold %.3f)", svc, det.fit_count, det.threshold)
                except OSError as e:
                    log.warning("Could not save model for %s: %s", svc, e)
                self.fit_counts[svc] = det.fit_count

    # ------------------------------------------------------------------ control

    def reset_models(self) -> None:
        with self.lock:
            for det in self.detectors.values():
                det.reset()
            self.fit_counts = {svc: 0 for svc in self.detectors}

    def retrain(self, svc: str) -> bool:
        with self.lock:
            return self.detectors[svc].retrain_now()

    def run_forever(self, stop: threading.Event) -> None:
        log.info("Monitoring %s every %.0fs (Prometheus %s)", self.settings.services,
                 self.settings.poll_interval, self.settings.prometheus_url)
        while not stop.is_set():
            started = time.monotonic()
            try:
                self.tick()
            except Exception:  # never let one bad tick kill the loop
                log.exception("tick failed")
            stop.wait(max(0.0, self.settings.poll_interval - (time.monotonic() - started)))


def _r(v):
    if v is None:
        return None
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return round(f, 4) if math.isfinite(f) else None
