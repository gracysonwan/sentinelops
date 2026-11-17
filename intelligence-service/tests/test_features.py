import math

import httpx

from app.features import FEATURES, QUERIES, UP_QUERY, PrometheusSource, build_features, parse_vector


def vector(label, values):
    return {"status": "success", "data": {"resultType": "vector", "result": [
        {"metric": {label: k}, "value": [1730000000.0, str(v)]} for k, v in values.items()]}}


def test_parse_vector_handles_nan_and_labels():
    payload = vector("application", {"order-service": 1.5, "payment-service": "NaN"})
    out = parse_vector(payload, "application")
    assert out["order-service"] == 1.5
    assert math.isnan(out["payment-service"])


def test_build_features_converts_units():
    f = build_features({"req_rate": 10.0, "err_rate": 0.5, "p95_s": 0.12, "lat_sum": 0.4,
                        "heap_used": 64e6, "heap_max": 256e6, "cpu": 0.05, "gc_s": 0.002, "threads": 33})
    assert f["p95_ms"] == 120.0
    assert abs(f["mean_ms"] - 40.0) < 1e-9
    assert f["error_ratio"] == 0.05
    assert f["heap_ratio"] == 0.25
    assert f["gc_ms_per_s"] == 2.0
    assert set(f) == set(FEATURES)


def test_build_features_without_traffic_gives_no_latency():
    f = build_features({"req_rate": 0.0, "heap_used": 1, "heap_max": 2, "cpu": 0.1, "threads": 30})
    assert math.isnan(f["p95_ms"]) and math.isnan(f["mean_ms"])
    assert f["error_ratio"] == 0.0


def test_prometheus_source_builds_snapshot_from_http_api():
    answers = {
        QUERIES["req_rate"]: vector("application", {"order-service": 10}),
        QUERIES["err_rate"]: vector("application", {"order-service": 1}),
        QUERIES["p95_s"]: vector("application", {"order-service": 0.2}),
        QUERIES["lat_sum"]: vector("application", {"order-service": 0.8}),
        QUERIES["heap_used"]: vector("application", {"order-service": 100}),
        QUERIES["heap_max"]: vector("application", {"order-service": 400}),
        QUERIES["cpu"]: vector("application", {"order-service": 0.07}),
        QUERIES["gc_s"]: vector("application", {"order-service": 0.001}),
        QUERIES["threads"]: vector("application", {"order-service": 40}),
        QUERIES["start_time"]: vector("application", {"order-service": 1729990000}),
        UP_QUERY: vector("job", {"order-service": 1, "payment-service": 0}),
    }

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/v1/query"
        return httpx.Response(200, json=answers[request.url.params["query"]])

    src = PrometheusSource("http://prom:9090", ["order-service", "payment-service"])
    src.client = httpx.Client(transport=httpx.MockTransport(handler))
    snap = src.fetch()
    order = snap["order-service"]
    assert order["p95_ms"] == 200.0 and order["error_ratio"] == 0.1 and order["heap_ratio"] == 0.25
    assert order["up"] == 1 and order["start_time"] == 1729990000
    assert snap["payment-service"]["up"] == 0
