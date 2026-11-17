"""Per-service anomaly detector: learns a service's normal behaviour and flags degradation early.

Pipeline for every 5-second feature vector x:

  1. Robust scaling      z = (x - median_normal) / max(spread_normal, floor)
  2. Isolation Forest    score = -score_samples(clip(z))   (higher = more isolated = more anomalous)
  3. Decision            anomalous  if  score > threshold  AND  max(z) >= z_gate
                         (the second condition keeps only deviations in the "unhealthy" direction)
  4. Confirmation        confirmed  if  anomalous for `consecutive` windows in a row
  5. Explanation         root cause = the feature with the largest z, mapped to latency/errors/memory/cpu
  6. Forecast            linear trend of the last minute -> seconds until a failure limit is crossed

Why a reference sample: Isolation Forest only draws split values inside the range of its training
data, so any point beyond that range lands in the same leaf as the most extreme normal point and gets
the same score - a 2-sigma and a 50-sigma latency spike look identical (score saturation). Adding a
sparse uniform reference sample spanning the plausible operating range (-4..+12 robust std-devs)
lets the trees split out there too, so the score keeps rising with the size of the deviation.
The decision threshold is still learned from the normal samples only.

The detector keeps learning: normal-looking samples go into a rolling window and the model is
refitted periodically, so slow, harmless drift (e.g. more traffic) does not cause false alarms.
"""
from __future__ import annotations

import math
from collections import deque
from dataclasses import asdict, dataclass, field
from pathlib import Path

import joblib
import numpy as np
from sklearn.ensemble import IsolationForest

from .features import FAILURE_LIMITS, FEATURE_FLOORS, FEATURES, ROOT_CAUSE

LEARNING = "LEARNING"
MONITORING = "MONITORING"

_FLOORS = np.array([FEATURE_FLOORS[f] for f in FEATURES])
_TRUST_Z = 2.5   # samples with every |z| below this are trusted as normal for re-training
REF_FRACTION = 0.10          # reference points per normal sample
REF_LOW, REF_HIGH = -4.0, 12.0   # range covered by the reference sample (robust std-devs)


@dataclass
class Verdict:
    service: str
    state: str
    timestamp: float
    features: dict[str, float]
    score: float | None = None
    threshold: float | None = None
    anomalous: bool = False
    confirmed: bool = False
    streak: int = 0
    zscores: dict[str, float] = field(default_factory=dict)
    root_cause: str | None = None
    top_features: list[str] = field(default_factory=list)
    forecast: dict[str, float] = field(default_factory=dict)
    baseline_progress: int = 0
    baseline_target: int = 0
    suppressed_by: str | None = None

    def reason(self) -> str:
        parts = []
        for f in self.top_features[:2]:
            parts.append(f"{f}={self.features.get(f, float('nan')):.3g} (z=+{self.zscores.get(f, 0):.1f})")
        text = ", ".join(parts) if parts else "multivariate deviation"
        if self.forecast:
            feat, eta = min(self.forecast.items(), key=lambda kv: kv[1])
            text += f"; forecast to breach {feat} limit in ~{eta:.0f}s"
        return text

    def to_dict(self) -> dict:
        d = asdict(self)
        d["features"] = {k: _clean(v) for k, v in self.features.items()}
        d["reason"] = self.reason() if self.state == MONITORING else None
        return d


def _clean(v):
    return None if v is None or (isinstance(v, float) and not math.isfinite(v)) else round(float(v), 4)


class ServiceDetector:
    def __init__(self, service: str, baseline_target: int = 60, consecutive: int = 3,
                 retrain_every: int = 120, window_size: int = 720, z_gate: float = 3.0,
                 score_margin: float = 0.0, n_estimators: int = 300, seed: int = 42,
                 threshold_quantile: float = 0.99):
        self.service = service
        self.baseline_target = baseline_target
        self.consecutive = consecutive
        self.retrain_every = retrain_every
        self.z_gate = z_gate
        self.score_margin = score_margin
        self.n_estimators = n_estimators
        self.seed = seed
        self.threshold_quantile = threshold_quantile

        self.state = LEARNING
        self.baseline: list[np.ndarray] = []
        self.window: deque[np.ndarray] = deque(maxlen=window_size)
        self.history: deque[tuple[float, dict[str, float]]] = deque(maxlen=24)
        self.model: IsolationForest | None = None
        self.center: np.ndarray | None = None
        self.scale: np.ndarray | None = None
        self.threshold: float | None = None
        self.streak = 0
        self.since_retrain = 0
        self.fit_count = 0

    # ------------------------------------------------------------------ learning

    def fit(self, X: np.ndarray) -> None:
        """Fit scaling statistics, the Isolation Forest and the decision threshold on normal data."""
        center = np.median(X, axis=0)
        mad = 1.4826 * np.median(np.abs(X - center), axis=0)
        spread = np.maximum(np.maximum(mad, X.std(axis=0)), _FLOORS)
        Z = np.clip((X - center) / spread, REF_LOW, REF_HIGH)
        rng = np.random.default_rng(self.seed + self.fit_count)
        reference = rng.uniform(REF_LOW, REF_HIGH, size=(max(8, int(REF_FRACTION * len(Z))), Z.shape[1]))
        model = IsolationForest(n_estimators=self.n_estimators, contamination="auto",
                                random_state=self.seed).fit(np.vstack([Z, reference]))
        train_scores = -model.score_samples(Z)
        self.center, self.scale, self.model = center, spread, model
        self.threshold = float(np.quantile(train_scores, self.threshold_quantile) + self.score_margin)
        self.state = MONITORING
        self.since_retrain = 0
        self.fit_count += 1

    def reset(self) -> None:
        """Forget everything and learn the baseline again."""
        self.__init__(self.service, self.baseline_target, self.consecutive, self.retrain_every,
                      self.window.maxlen or 720, self.z_gate, self.score_margin, self.n_estimators, self.seed,
                      self.threshold_quantile)

    def retrain_now(self) -> bool:
        if len(self.window) >= self.baseline_target:
            self.fit(np.array(self.window))
            return True
        return False

    def warmup(self) -> None:
        """Called after the service restarted: clear the streak and the trend history."""
        self.streak = 0
        self.history.clear()

    # ------------------------------------------------------------------ scoring

    def _vector(self, sample: dict[str, float]) -> np.ndarray:
        return np.array([sample.get(f, math.nan) if sample.get(f) is not None else math.nan for f in FEATURES],
                        dtype=float)

    def observe(self, sample: dict[str, float], ts: float) -> Verdict:
        x = self._vector(sample)
        features = {f: float(x[i]) for i, f in enumerate(FEATURES)}

        if self.state == LEARNING:
            if np.all(np.isfinite(x)):
                self.baseline.append(x)
            if len(self.baseline) >= self.baseline_target:
                X = np.array(self.baseline)
                self.window.extend(self.baseline)
                self.baseline = []
                self.fit(X)
            return Verdict(self.service, LEARNING if self.state == LEARNING else MONITORING, ts, features,
                           baseline_progress=len(self.baseline) if self.state == LEARNING else self.baseline_target,
                           baseline_target=self.baseline_target)

        self.history.append((ts, features))
        filled = np.where(np.isfinite(x), x, self.center)
        z = (filled - self.center) / self.scale
        score = float(-self.model.score_samples(np.clip(z, REF_LOW, REF_HIGH).reshape(1, -1))[0])
        top_idx = int(np.argmax(z))
        anomalous = score > self.threshold and z[top_idx] >= self.z_gate

        self.streak = self.streak + 1 if anomalous else 0
        confirmed = self.streak >= self.consecutive

        if not anomalous and np.all(np.abs(z) < _TRUST_Z):
            self.window.append(filled)
            self.since_retrain += 1
            if self.since_retrain >= self.retrain_every:
                self.retrain_now()

        zscores = {f: round(float(z[i]), 2) for i, f in enumerate(FEATURES)}
        ranked = [f for f in sorted(FEATURES, key=lambda f: -zscores[f]) if zscores[f] >= 2.0]
        return Verdict(
            service=self.service, state=MONITORING, timestamp=ts, features=features,
            score=round(score, 4), threshold=round(self.threshold, 4),
            anomalous=bool(anomalous), confirmed=bool(confirmed), streak=self.streak,
            zscores=zscores, root_cause=ROOT_CAUSE[FEATURES[top_idx]] if anomalous else None,
            top_features=ranked, forecast=self.forecast(),
            baseline_progress=self.baseline_target, baseline_target=self.baseline_target,
        )

    def forecast(self, horizon_s: float = 600.0) -> dict[str, float]:
        """Seconds until each failure limit is crossed if the last minute's trend continues."""
        out: dict[str, float] = {}
        recent = list(self.history)[-12:]
        if len(recent) < 6:
            return out
        for feat, limit in FAILURE_LIMITS.items():
            pts = [(t, v[feat]) for t, v in recent if math.isfinite(v.get(feat, math.nan))]
            if len(pts) < 6:
                continue
            t = np.array([p[0] for p in pts]) - pts[-1][0]
            y = np.array([p[1] for p in pts])
            slope, intercept = np.polyfit(t, y, 1)
            if slope <= 0 or intercept >= limit:
                continue
            eta = (limit - intercept) / slope
            # Only meaningful when the metric is already clearly above normal (2 spreads) and still
            # climbing faster than one normal spread per minute - otherwise it is just noise.
            idx = FEATURES.index(feat)
            above_normal = intercept > self.center[idx] + 2 * self.scale[idx]
            if eta <= horizon_s and above_normal and slope * 60 > self.scale[idx]:
                out[feat] = round(float(eta), 1)
        return out

    # ------------------------------------------------------------------ persistence

    def save(self, directory: str | Path) -> None:
        if self.state != MONITORING:
            return
        path = Path(directory)
        path.mkdir(parents=True, exist_ok=True)
        joblib.dump({
            "center": self.center, "scale": self.scale, "model": self.model, "threshold": self.threshold,
            "window": list(self.window), "fit_count": self.fit_count, "features": FEATURES,
        }, path / f"{self.service}.joblib")

    def load(self, directory: str | Path) -> bool:
        file = Path(directory) / f"{self.service}.joblib"
        if not file.exists():
            return False
        data = joblib.load(file)
        if data.get("features") != FEATURES:
            return False
        self.center, self.scale, self.model = data["center"], data["scale"], data["model"]
        self.threshold, self.fit_count = data["threshold"], data["fit_count"]
        self.window.extend(data["window"])
        self.state = MONITORING
        return True
