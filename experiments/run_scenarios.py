"""Live chaos experiments against the running SentinelOps stack (standard library only).

For each fault scenario it injects the fault, then measures on the real system:

  t_suspect   first 5-second window the AI found anomalous
  t_detect    anomaly confirmed (3 windows) -> alert sent
  t_fail      a Generation-1 reactive limit was crossed (p95 > 2 s, errors > 50 %, heap > 92 %, or DOWN)
              before healing started (a planned restart is not counted as a failure)
  t_heal_start  remediation engine started acting
  t_recover   remediation engine reports the service healthy again
  order impact  worst order-service error ratio while the incident lasted (from Prometheus)

Modes:
  --mode auto      autonomous remediation ON  (SentinelOps behaviour)
  --mode observe   autonomous remediation OFF (detection only - shows what happens without self-healing)

Usage (stack must be running and the AI must have finished learning, ~5 min after start):
  python experiments/run_scenarios.py --mode auto
  python experiments/run_scenarios.py --mode observe --scenarios latency
Results go to experiments/results/ as CSV, JSON and a Markdown table.
"""
from __future__ import annotations

import argparse
import csv
import json
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

PANEL = "http://localhost:8090"
AI = "http://localhost:8000"
PROM = "http://localhost:9090"

SCENARIOS = {
    "latency": ("payment-service", "latency", {"baseMs": 0, "rampMsPerSec": 20}),
    "errors": ("inventory-service", "errors", {"rate": 0.05, "rampPerSec": 0.01}),
    "memory": ("payment-service", "memory-leak", {"mbPerSec": 1, "maxMb": 200}),
}
LIMITS = {"p95_ms": 2000.0, "error_ratio": 0.5, "heap_ratio": 0.92}


def http(method: str, url: str, timeout: float = 5.0):
    req = urllib.request.Request(url, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read() or b"{}")
    except urllib.error.HTTPError as e:
        try:
            return json.loads(e.read() or b"{}")
        except ValueError:
            return {"error": e.code}
    except (urllib.error.URLError, TimeoutError, ConnectionError) as e:
        return {"error": str(e)}


def ai_status(service: str) -> dict:
    return http("GET", f"{AI}/status").get("services", {}).get(service, {})


def wait_until_ready(service: str, timeout: float = 600) -> None:
    print(f"  waiting for {service} to be healthy and monitored...", flush=True)
    deadline = time.time() + timeout
    calm = 0
    while time.time() < deadline:
        s = ai_status(service)
        if s.get("state") == "MONITORING" and not s.get("anomalous"):
            calm += 1
            if calm >= 6:  # 30 s of normal behaviour
                return
        else:
            calm = 0
        time.sleep(5)
    raise SystemExit(f"{service} did not become ready - is the stack running and has the AI finished learning?")


def failed(status: dict) -> bool:
    if status.get("state") == "DOWN":
        return True
    f = status.get("features") or {}
    return any((f.get(k) or 0) >= lim for k, lim in LIMITS.items())


def order_error_peak(start: float, end: float) -> float | None:
    q = ('sum(rate(http_server_requests_seconds_count{application="order-service",outcome="SERVER_ERROR",'
         'uri!~"/actuator.*"}[30s])) / sum(rate(http_server_requests_seconds_count{application="order-service",'
         'uri!~"/actuator.*"}[30s]))')
    params = urllib.parse.urlencode({"query": q, "start": start, "end": max(end, start + 10), "step": "5"})
    data = http("GET", f"{PROM}/api/v1/query_range?{params}")
    try:
        values = [float(v[1]) for v in data["data"]["result"][0]["values"] if v[1] not in ("NaN", "+Inf")]
        return round(max(values), 4) if values else 0.0
    except (KeyError, IndexError, TypeError):
        return None


def run(name: str, mode: str, max_wait: float) -> dict:
    service, chaos_type, params = SCENARIOS[name]
    print(f"\n=== {name}: {chaos_type} on {service} (mode={mode})", flush=True)
    wait_until_ready(service)
    before = http("GET", f"{PANEL}/api/events?limit=50")
    known_events = {e["id"] for e in before} if isinstance(before, list) else set()

    t0 = time.time()
    http("POST", f"{PANEL}/api/chaos/{service}/{chaos_type}?{urllib.parse.urlencode(params)}")
    r = {"scenario": name, "service": service, "mode": mode, "t_inject": round(t0, 1),
         "t_suspect": None, "t_detect": None, "t_fail": None, "t_heal_start": None, "t_recover": None,
         "root_cause": None,
         "remediation_status": None, "remediation_steps": None}

    while time.time() - t0 < max_wait:
        now = time.time()
        s = ai_status(service)
        if s.get("anomalous") and r["t_suspect"] is None:
            r["t_suspect"] = now
        if s.get("confirmed") and r["t_detect"] is None:
            r["t_detect"], r["root_cause"] = now, s.get("root_cause")
            print(f"  +{now - t0:5.1f}s anomaly confirmed (cause: {s.get('root_cause')}) - {s.get('reason')}", flush=True)
        # A planned restart makes the service briefly DOWN - only count failures before healing began.
        if r["t_heal_start"] is None and failed(s) and r["t_fail"] is None:
            r["t_fail"] = now
            print(f"  +{now - t0:5.1f}s reactive failure limit crossed", flush=True)
        events = http("GET", f"{PANEL}/api/events?limit=10")
        if isinstance(events, list):
            for e in events:
                if e["id"] in known_events or e["service"] != service:
                    continue
                if r["t_heal_start"] is None:
                    r["t_heal_start"] = e["startedAt"]
                    print(f"  +{e['startedAt'] - t0:5.1f}s remediation started", flush=True)
                if e["status"] != "IN_PROGRESS":
                    r["t_recover"] = e["finishedAt"] if e["status"] == "RECOVERED" else None
                    r["remediation_status"], r["remediation_steps"] = e["status"], " | ".join(e["steps"])
                    print(f"  +{time.time() - t0:5.1f}s remediation {e['status']}: {r['remediation_steps']}", flush=True)
        if r["remediation_status"] or (mode == "observe" and r["t_fail"] and time.time() - r["t_fail"] > 20):
            break
        time.sleep(1)

    end = time.time()
    http("POST", f"{PANEL}/api/chaos/{service}/reset")
    r["order_error_peak"] = order_error_peak(t0, end)
    for k in ("t_suspect", "t_detect", "t_fail", "t_heal_start", "t_recover"):
        r[k.replace("t_", "s_to_")] = round(r[k] - t0, 1) if r[k] else None
    r["lead_time_s"] = round(r["t_fail"] - r["t_detect"], 1) if r["t_fail"] and r["t_detect"] else None
    r["failure_prevented"] = bool(r["t_recover"] and not r["t_fail"])
    print(f"  result: detect {r['s_to_detect']}s, fail {r['s_to_fail']}s, recovered {r['s_to_recover']}s, "
          f"order error peak {r['order_error_peak']}", flush=True)
    return r


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--mode", choices=["auto", "observe"], default="auto")
    ap.add_argument("--scenarios", default="latency,errors,memory")
    ap.add_argument("--repeat", type=int, default=1)
    ap.add_argument("--max-wait", type=float, default=420)
    ap.add_argument("--pause", type=float, default=90, help="seconds between runs (cool-down + JVM warm-up)")
    args = ap.parse_args()

    original = http("GET", f"{PANEL}/api/settings").get("autoRemediation", True)
    http("POST", f"{PANEL}/api/settings?autoRemediation={'true' if args.mode == 'auto' else 'false'}")
    results = []
    try:
        for i in range(args.repeat):
            for name in args.scenarios.split(","):
                results.append(run(name.strip(), args.mode, args.max_wait))
                print(f"  cooling down {args.pause:.0f}s...", flush=True)
                time.sleep(args.pause)
    finally:
        http("POST", f"{PANEL}/api/settings?autoRemediation={'true' if original else 'false'}")

    out = Path(__file__).parent / "results"
    out.mkdir(exist_ok=True)
    stamp = time.strftime("%Y%m%d-%H%M%S")
    (out / f"live_{args.mode}_{stamp}.json").write_text(json.dumps(results, indent=2))
    cols = ["scenario", "service", "mode", "root_cause", "s_to_suspect", "s_to_detect", "s_to_fail",
            "s_to_heal_start", "s_to_recover",
            "lead_time_s", "failure_prevented", "order_error_peak", "remediation_status", "remediation_steps"]
    with open(out / f"live_{args.mode}_{stamp}.csv", "w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=cols, extrasaction="ignore")
        w.writeheader()
        w.writerows(results)
    lines = ["| " + " | ".join(cols[:-1]) + " |", "|" + "---|" * (len(cols) - 1)]
    lines += ["| " + " | ".join(str(r.get(c, "")) for c in cols[:-1]) + " |" for r in results]
    (out / f"live_{args.mode}_{stamp}.md").write_text("\n".join(lines) + "\n")
    print(f"\nSaved results to {out}")


if __name__ == "__main__":
    main()
