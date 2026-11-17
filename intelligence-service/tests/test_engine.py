from app.config import Settings
from app.engine import DOWN, WARMUP, MonitorEngine
from app.simulator import PROFILES, generate_trace


class ReplaySource:
    """Feeds pre-generated traces as if they came from Prometheus."""

    def __init__(self, traces: dict[str, list[dict]]):
        self.traces = traces
        self.i = 0
        self.overrides: dict[str, dict] = {}

    def fetch(self):
        snap = {}
        for svc, trace in self.traces.items():
            s = dict(trace[min(self.i, len(trace) - 1)])
            s.update(up=1.0, start_time=1000.0, req_rate=10.0)
            s.update(self.overrides.get(svc, {}))
            snap[svc] = s
        self.i += 1
        return snap


class RecordingSink:
    def __init__(self):
        self.alerts = []

    def send(self, alert):
        self.alerts.append(alert)
        return 202, "remediation started"


def make_engine(traces, tmp_path, **overrides):
    clock = {"t": 0.0}
    settings = Settings(services=list(traces), model_dir=str(tmp_path), **overrides)
    src, sink = ReplaySource(traces), RecordingSink()
    engine = MonitorEngine(settings, src, sink, clock=lambda: clock["t"])

    def step(n=1):
        for _ in range(n):
            engine.tick()
            clock["t"] += 5.0
    return engine, src, sink, step


def test_fault_on_payment_triggers_one_alert_with_cause(tmp_path):
    traces = {"payment-service": generate_trace(PROFILES["payment-service"], "latency_ramp", 1200, seed=1)}
    engine, _, sink, step = make_engine(traces, tmp_path)
    step(240)
    assert len(sink.alerts) >= 1
    alert = sink.alerts[0]
    assert alert["service"] == "payment-service" and alert["rootCause"] == "latency"
    assert alert["trigger"] == "AI_PREDICTION" and alert["detectedAt"] >= 600
    assert (tmp_path / "payment-service.joblib").exists()  # baseline model persisted


def test_dependency_fault_is_blamed_on_callee_not_caller(tmp_path):
    payment = generate_trace(PROFILES["payment-service"], "latency_ramp", 1200, seed=2)
    order = generate_trace(PROFILES["order-service"], "latency_ramp", 1200, seed=3)  # slow because payment is slow
    engine, _, sink, step = make_engine({"order-service": order, "payment-service": payment}, tmp_path)
    step(240)
    services = {a["service"] for a in sink.alerts}
    assert "payment-service" in services
    assert "order-service" not in services


def test_restart_triggers_warmup_and_down_triggers_alert(tmp_path):
    traces = {"inventory-service": generate_trace(PROFILES["inventory-service"], "normal", 1200, seed=4)}
    engine, src, sink, step = make_engine(traces, tmp_path, down_alert_after=10)
    step(70)
    src.overrides["inventory-service"] = {"up": 0.0}
    step(4)
    assert engine.status["inventory-service"]["state"] == DOWN
    assert sink.alerts and sink.alerts[-1]["trigger"] == "SERVICE_DOWN"
    src.overrides["inventory-service"] = {"start_time": 2000.0}  # back up with a new JVM
    step(1)
    assert engine.status["inventory-service"]["state"] == WARMUP


def test_metrics_outage_keeps_last_status(tmp_path):
    traces = {"payment-service": generate_trace(PROFILES["payment-service"], "normal", 600, seed=5)}
    engine, src, _, step = make_engine(traces, tmp_path)
    step(3)

    def broken():
        raise ConnectionError("prometheus down")
    src.fetch = broken
    status = engine.tick()
    assert engine.last_error and "prometheus down" in engine.last_error
    assert "payment-service" in status


def test_no_alerts_while_learning(tmp_path):
    traces = {"payment-service": generate_trace(PROFILES["payment-service"], "error_burst", 600, fault_start_s=60, seed=6)}
    _, _, sink, step = make_engine(traces, tmp_path)
    step(55)
    assert sink.alerts == []
