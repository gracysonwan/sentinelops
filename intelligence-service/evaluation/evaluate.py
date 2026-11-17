"""Offline evaluation of the SentinelOps detector on labelled synthetic metric traces.

Usage:  python -m evaluation.evaluate [--seeds 20] [--out evaluation/results]

For every service profile x fault scenario x seed, a 20-minute trace is generated (fault injected
at minute 10), and four detectors are run over it sample by sample:

  reactive-threshold   Generation-1 alert: fires when a failure limit is crossed
                       (p95 > 2 s, error ratio > 50 %, heap floor > 92 %)
  early-threshold      static "early warning" thresholds (p95 > 500 ms, errors > 10 %, heap > 70 %)
  zscore               any feature > 3 robust std-devs above normal, 3 windows in a row
  sentinelops          Isolation Forest + direction gate (z >= 3) + 3-window confirmation (app.detector)
  sentinelops-gate2    ablation: same detector with a relaxed gate (z >= 2)

Reported per method and scenario: detection rate, delay after fault onset, lead time before the
reactive failure point, and false alarms per hour on fault-free traces.
"""
from __future__ import annotations

import argparse
import json
import math
from pathlib import Path

import numpy as np

from app.detector import ServiceDetector
from app.features import FAILURE_LIMITS, FEATURE_FLOORS, FEATURES
from app.simulator import PROFILES, STEP, generate_trace

FAULT_AT = 600.0
BASELINE = 60
EARLY_LIMITS = {"p95_ms": 500.0, "error_ratio": 0.10, "heap_ratio": 0.70}
SCENARIOS = {
    "latency_ramp": {"scenario": "latency_ramp"},
    "error_burst": {"scenario": "error_burst"},
    "memory_leak": {"scenario": "memory_leak"},
    "gray_failure": {"scenario": "gray_failure"},
}


class ThresholdDetector:
    def __init__(self, limits: dict[str, float], consecutive: int = 1):
        self.limits, self.consecutive, self.streak = limits, consecutive, 0

    def step(self, s: dict) -> bool:
        hit = any(s[f] >= lim for f, lim in self.limits.items())
        self.streak = self.streak + 1 if hit else 0
        return self.streak >= self.consecutive


class ZScoreDetector:
    """Same robust scaling as SentinelOps, but no Isolation Forest: |z| > 3 on any feature."""

    def __init__(self, gate: float = 3.0, consecutive: int = 3):
        self.gate, self.consecutive = gate, consecutive
        self.buf: list[list[float]] = []
        self.center = self.scale = None
        self.streak = 0

    def step(self, s: dict) -> bool:
        x = np.array([s[f] for f in FEATURES])
        if self.center is None:
            self.buf.append(list(x))
            if len(self.buf) >= BASELINE:
                X = np.array(self.buf)
                self.center = np.median(X, axis=0)
                mad = 1.4826 * np.median(np.abs(X - self.center), axis=0)
                floors = np.array([FEATURE_FLOORS[f] for f in FEATURES])
                self.scale = np.maximum(np.maximum(mad, X.std(axis=0)), floors)
            return False
        z = (x - self.center) / self.scale
        self.streak = self.streak + 1 if z.max() >= self.gate else 0
        return self.streak >= self.consecutive


class SentinelDetector:
    def __init__(self, service: str, z_gate: float = 3.0):
        self.det = ServiceDetector(service, baseline_target=BASELINE, z_gate=z_gate)
        self.last = None

    def step(self, s: dict) -> bool:
        self.last = self.det.observe(s, s["t"])
        return self.last.confirmed


def make_detectors(service: str) -> dict:
    return {
        "reactive-threshold": ThresholdDetector(FAILURE_LIMITS),
        "early-threshold": ThresholdDetector(EARLY_LIMITS, consecutive=1),
        "zscore": ZScoreDetector(),
        "sentinelops": SentinelDetector(service),
        "sentinelops-gate2": SentinelDetector(service, z_gate=2.0),
    }


def run_trace(service: str, trace: list[dict]) -> dict[str, dict]:
    detectors = make_detectors(service)
    out = {name: {"first_alarm": None, "false_alarms": 0, "tp": 0, "fp": 0, "fn": 0, "tn": 0} for name in detectors}
    failure_t = next((s["t"] for s in trace if s["failed"]), None)
    in_alarm = {name: False for name in detectors}
    for s in trace:
        for name, d in detectors.items():
            alarm = d.step(s)
            r = out[name]
            if s["t"] < BASELINE * STEP:  # baseline-learning period is not scored
                continue
            label = s["label"] == 1
            r["tp" if alarm and label else "fp" if alarm else "fn" if label else "tn"] += 1
            if alarm and not label and not in_alarm[name]:
                r["false_alarms"] += 1  # count alarm episodes, not samples
            if alarm and label and r["first_alarm"] is None:
                r["first_alarm"] = s["t"]
            in_alarm[name] = alarm
    for r in out.values():
        r["failure_t"] = failure_t
    return out


def summarise(rows: list[dict]) -> dict:
    detected = [r for r in rows if r["first_alarm"] is not None]
    before_failure = [r for r in detected if r["failure_t"] is None or r["first_alarm"] <= r["failure_t"]]
    delays = [r["first_alarm"] - FAULT_AT for r in detected]
    leads = [r["failure_t"] - r["first_alarm"] for r in detected if r["failure_t"] is not None]
    tp, fp, fn = (sum(r[k] for r in rows) for k in ("tp", "fp", "fn"))
    precision = tp / (tp + fp) if tp + fp else math.nan
    recall = tp / (tp + fn) if tp + fn else math.nan
    return {
        "runs": len(rows),
        "detection_rate": len(detected) / len(rows),
        "detected_before_failure": len(before_failure) / len(rows),
        "mean_delay_s": float(np.mean(delays)) if delays else None,
        "mean_lead_s": float(np.mean(leads)) if leads else None,
        "median_lead_s": float(np.median(leads)) if leads else None,
        "precision": precision, "recall": recall,
        "f1": 2 * precision * recall / (precision + recall) if precision + recall else math.nan,
    }


def evaluate(seeds: int, out_dir: Path) -> dict:
    services = list(PROFILES)
    methods = list(make_detectors(services[0]))
    results: dict = {"faults": {}, "normal": {}, "ramp_sweep": {}, "config": {
        "seeds": seeds, "baseline_samples": BASELINE, "step_s": STEP, "fault_at_s": FAULT_AT,
        "failure_limits": FAILURE_LIMITS, "early_limits": EARLY_LIMITS}}

    for scen, kwargs in SCENARIOS.items():
        per_method = {m: [] for m in methods}
        for svc in services:
            for seed in range(seeds):
                trace = generate_trace(PROFILES[svc], duration_s=1500, fault_start_s=FAULT_AT, seed=seed, **kwargs)
                for m, r in run_trace(svc, trace).items():
                    per_method[m].append(r)
        results["faults"][scen] = {m: summarise(rows) for m, rows in per_method.items()}
        print(f"done {scen}")

    # False alarms: fault-free and benign load-surge traces (1 hour each)
    for scen in ("normal", "load_surge"):
        per_method = {m: {"alarms": 0, "hours": 0.0, "fp_samples": 0, "samples": 0} for m in methods}
        for svc in services:
            for seed in range(max(3, seeds // 4)):
                trace = generate_trace(PROFILES[svc], scen, duration_s=3600, fault_start_s=1200, seed=1000 + seed)
                for m, r in run_trace(svc, trace).items():
                    per_method[m]["alarms"] += r["false_alarms"]
                    per_method[m]["fp_samples"] += r["fp"]
                    per_method[m]["samples"] += r["fp"] + r["tn"]
                    per_method[m]["hours"] += (3600 - BASELINE * STEP) / 3600
        results["normal"][scen] = {m: {"false_alarms_per_hour": v["alarms"] / v["hours"],
                                       "false_positive_rate": v["fp_samples"] / max(1, v["samples"])}
                                   for m, v in per_method.items()}
        print(f"done {scen}")

    # Lead time vs. speed of degradation (latency ramp on payment-service)
    for ramp in (5, 10, 20, 40, 80):
        rows = {m: [] for m in methods}
        for seed in range(seeds):
            trace = generate_trace(PROFILES["payment-service"], "latency_ramp", duration_s=1200,
                                   fault_start_s=FAULT_AT, seed=seed, ramp=ramp)
            for m, r in run_trace("payment-service", trace).items():
                rows[m].append(r)
        results["ramp_sweep"][str(ramp)] = {m: summarise(v) for m, v in rows.items()}
    print("done ramp sweep")

    out_dir.mkdir(parents=True, exist_ok=True)
    results = _clean(results)
    (out_dir / "results.json").write_text(json.dumps(results, indent=2))
    return results


def _clean(o):
    """Replace NaN with None so the file is valid JSON."""
    if isinstance(o, dict):
        return {k: _clean(v) for k, v in o.items()}
    if isinstance(o, list):
        return [_clean(v) for v in o]
    if isinstance(o, float) and math.isnan(o):
        return None
    return o


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--seeds", type=int, default=20)
    ap.add_argument("--out", default="evaluation/results")
    args = ap.parse_args()
    evaluate(args.seeds, Path(args.out))
