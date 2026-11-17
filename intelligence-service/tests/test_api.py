import os

os.environ.setdefault("PROMETHEUS_URL", "http://127.0.0.1:9")   # nothing listens here: ticks fail safely
os.environ.setdefault("REMEDIATION_URL", "http://127.0.0.1:9")

from fastapi.testclient import TestClient  # noqa: E402

from app.main import app, export_metrics  # noqa: E402


def test_health_status_and_metrics_endpoints():
    with TestClient(app) as client:
        assert client.get("/health").json()["status"] == "UP"
        body = client.get("/status").json()
        assert body["settings"]["baseline_samples"] > 0
        export_metrics({"payment-service": {"state": "MONITORING", "score": 0.51, "threshold": 0.46,
                                            "anomalous": True, "confirmed": True, "forecast": {"p95_ms": 42.0},
                                            "zscores": {"p95_ms": 9.5}, "baseline_progress": 60,
                                            "baseline_target": 60}})
        metrics = client.get("/metrics").text
        assert 'sentinel_anomaly_score{service="payment-service"} 0.51' in metrics
        assert 'sentinel_anomaly_flag{service="payment-service"} 2.0' in metrics
        assert 'sentinel_failure_eta_seconds{service="payment-service"} 42.0' in metrics


def test_retrain_unknown_service_is_404():
    with TestClient(app) as client:
        assert client.post("/model/retrain/nope").status_code == 404
        assert client.post("/model/reset").status_code == 200
