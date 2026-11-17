import numpy as np

from app.detector import LEARNING, MONITORING, ServiceDetector
from app.simulator import PROFILES, generate_trace


def run(scenario, seed=0, **kw):
    trace = generate_trace(PROFILES["payment-service"], scenario, duration_s=1200, seed=seed, **kw)
    det = ServiceDetector("payment-service", baseline_target=60)
    verdicts = [det.observe(s, s["t"]) for s in trace]
    return trace, det, verdicts


def first_confirmed(trace, verdicts):
    return next((s["t"] for s, v in zip(trace, verdicts) if v.confirmed), None)


def test_learns_baseline_then_monitors():
    trace, det, verdicts = run("normal")
    assert verdicts[0].state == LEARNING
    assert verdicts[58].baseline_progress == 59
    assert verdicts[59].state == MONITORING
    assert det.threshold is not None


def test_no_false_alarm_on_normal_traffic():
    for seed in range(3):
        trace, _, verdicts = run("normal", seed=seed)
        assert first_confirmed(trace, verdicts) is None


def test_benign_load_surge_is_not_an_incident():
    trace, _, verdicts = run("load_surge", seed=4)
    assert first_confirmed(trace, verdicts) is None


def test_latency_ramp_is_detected_before_failure_with_root_cause():
    trace, _, verdicts = run("latency_ramp", seed=1)
    detected = first_confirmed(trace, verdicts)
    failed = next(s["t"] for s in trace if s["failed"])
    assert detected is not None and 600 <= detected < failed
    v = next(v for v in verdicts if v.confirmed)
    assert v.root_cause == "latency"
    assert "p95_ms" in v.top_features


def test_memory_leak_is_attributed_to_memory_and_forecast():
    trace, _, verdicts = run("memory_leak", seed=2)
    v = next(v for v in verdicts if v.confirmed)
    assert v.root_cause == "memory"
    failed = next(s["t"] for s in trace if s["failed"])
    assert v.timestamp < failed
    assert any(vv.forecast.get("heap_ratio") for vv in verdicts if vv.confirmed)


def test_error_burst_is_attributed_to_errors():
    _, _, verdicts = run("error_burst", seed=3)
    assert next(v for v in verdicts if v.confirmed).root_cause == "errors"


def test_score_grows_with_deviation_size():
    """Regression test for Isolation Forest score saturation (fixed with the reference sample)."""
    _, det, _ = run("normal")
    base = dict(zip(["p95_ms", "mean_ms", "error_ratio", "heap_ratio", "cpu", "gc_ms_per_s", "threads"],
                    det.center))
    scores = []
    for extra in (0, 60, 150, 400):
        sample = dict(base, p95_ms=base["p95_ms"] + extra, mean_ms=base["mean_ms"] + extra * 0.6)
        scores.append(det.observe(sample, 0).score)
    assert scores == sorted(scores) and scores[-1] - scores[0] > 0.08


def test_save_and_load_roundtrip(tmp_path):
    _, det, _ = run("normal")
    det.save(tmp_path)
    fresh = ServiceDetector("payment-service", baseline_target=60)
    assert fresh.load(tmp_path)
    x = {f: float(v) for f, v in zip(
        ["p95_ms", "mean_ms", "error_ratio", "heap_ratio", "cpu", "gc_ms_per_s", "threads"], det.center)}
    assert np.isclose(fresh.observe(x, 0).score, det.observe(x, 0).score)


def test_reset_returns_to_learning():
    _, det, _ = run("normal")
    det.reset()
    assert det.state == LEARNING and det.model is None
