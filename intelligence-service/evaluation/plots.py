"""Figures for the report from evaluation/results/results.json and example traces.

Usage:  python -m evaluation.plots [--results evaluation/results] [--out evaluation/results/figures]
Needs matplotlib (pip install -r requirements-dev.txt).
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

from app.detector import ServiceDetector  # noqa: E402
from app.simulator import PROFILES, generate_trace  # noqa: E402

# Validated categorical palette (fixed order) + recessive ink for text/axes.
BLUE, ORANGE, AQUA, YELLOW = "#2a78d6", "#eb6834", "#1baf7a", "#eda100"
INK, INK2, GRID = "#0b0b0b", "#52514e", "#e4e3df"
METHOD_STYLE = {
    "sentinelops": ("SentinelOps (Isolation Forest)", BLUE),
    "zscore": ("Robust z-score", ORANGE),
    "early-threshold": ("Static early-warning threshold", AQUA),
}

plt.rcParams.update({
    "font.family": "DejaVu Sans", "font.size": 10.5, "axes.edgecolor": GRID, "axes.labelcolor": INK2,
    "xtick.color": INK2, "ytick.color": INK2, "axes.grid": True, "grid.color": GRID, "grid.linewidth": 0.8,
    "axes.spines.top": False, "axes.spines.right": False, "legend.frameon": False, "savefig.dpi": 200,
})


def timeline(scenario: str, feature: str, label: str, scale: float, unit: str, out: Path, seed: int = 7) -> None:
    trace = generate_trace(PROFILES["payment-service"], scenario, duration_s=1200, seed=seed)
    det = ServiceDetector("payment-service", baseline_target=60)
    t, value, score, thr = [], [], [], []
    detected = None
    for s in trace:
        v = det.observe(s, s["t"])
        t.append((s["t"] - 600) / 60)
        value.append(s[feature] * scale)
        score.append(v.score)
        thr.append(v.threshold)
        if v.confirmed and detected is None and s["label"]:
            detected = (s["t"] - 600) / 60
    failed = next(((s["t"] - 600) / 60 for s in trace if s["failed"]), None)

    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(8, 4.6), sharex=True, gridspec_kw={"height_ratios": [1.2, 1]})
    ax1.plot(t, value, color=BLUE, linewidth=2)
    ax1.set_ylabel(f"{label} ({unit})")
    ax2.plot(t, score, color=BLUE, linewidth=2, label="anomaly score")
    ax2.plot(t, thr, color=INK2, linewidth=1.2, linestyle=(0, (5, 4)), label="learned threshold")
    ax2.set_ylabel("anomaly score")
    ax2.set_xlabel("minutes relative to fault injection")
    ax2.legend(loc="upper left", ncol=2, fontsize=9)
    for ax in (ax1, ax2):
        ax.axvline(0, color=INK2, linewidth=1, linestyle=":")
        if detected is not None:
            ax.axvline(detected, color=BLUE, linewidth=1.2)
        if failed is not None:
            ax.axvline(failed, color=ORANGE, linewidth=1.2)
    top = ax1.get_ylim()[1]
    ax1.text(0, top, " fault injected", color=INK2, va="top", fontsize=9)
    if detected is not None:
        ax1.text(detected, top * 0.82, " AI confirms", color=INK, va="top", fontsize=9)
    if failed is not None:
        ax1.text(failed, top * 0.64, " reactive alert\n would fire", color=INK, va="top", fontsize=9)
    ax2.set_xlim(-5, (failed or detected or 2) + 2.5)
    fig.tight_layout()
    fig.savefig(out)
    plt.close(fig)


def lead_bars(results: dict, out: Path) -> None:
    scen = [("latency_ramp", "Latency creep"), ("error_burst", "Error burst"), ("memory_leak", "Memory leak")]
    methods = list(METHOD_STYLE)
    fig, ax = plt.subplots(figsize=(8, 3.6))
    width = 0.26
    for i, m in enumerate(methods):
        name, color = METHOD_STYLE[m]
        vals = [results["faults"][s][m]["mean_lead_s"] or 0 for s, _ in scen]
        xs = [j + (i - 1) * (width + 0.02) for j in range(len(scen))]
        bars = ax.bar(xs, vals, width=width, color=color, label=name, zorder=3)
        for b, v in zip(bars, vals):
            ax.text(b.get_x() + b.get_width() / 2, v + 2, f"{v:.0f}", ha="center", va="bottom", fontsize=8.5, color=INK2)
    ax.set_xticks(range(len(scen)), [s[1] for s in scen])
    ax.set_ylabel("mean warning before failure (s)")
    ax.legend(loc="upper left", fontsize=9)
    ax.grid(axis="x", visible=False)
    ax.set_ylim(0, ax.get_ylim()[1] * 1.12)
    fig.tight_layout()
    fig.savefig(out)
    plt.close(fig)


def ramp_sweep(results: dict, out: Path) -> None:
    ramps = sorted(results["ramp_sweep"], key=float)
    fig, ax = plt.subplots(figsize=(8, 3.4))
    # z-score drawn wide and dashed underneath so SentinelOps stays visible where the two coincide
    styles = {"early-threshold": dict(linewidth=2), "zscore": dict(linewidth=4, linestyle=(0, (4, 3)), alpha=0.85),
              "sentinelops": dict(linewidth=2)}
    for m in ("early-threshold", "zscore", "sentinelops"):
        name, color = METHOD_STYLE[m]
        vals = [results["ramp_sweep"][r][m]["mean_lead_s"] or 0 for r in ramps]
        ax.plot([float(r) for r in ramps], vals, color=color, marker="o", markersize=6,
                markeredgecolor="white", markeredgewidth=1.5, label=name, zorder=3, **styles[m])
    ax.set_xscale("log", base=2)
    ax.set_xticks([float(r) for r in ramps], [f"{r} ms/s" for r in ramps])
    ax.set_xlabel("speed of latency degradation")
    ax.set_ylabel("warning before failure (s)")
    ax.legend(loc="upper right", fontsize=9)
    fig.tight_layout()
    fig.savefig(out)
    plt.close(fig)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--results", default="evaluation/results")
    ap.add_argument("--out", default="evaluation/results/figures")
    args = ap.parse_args()
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    results = json.loads((Path(args.results) / "results.json").read_text())
    timeline("memory_leak", "heap_ratio", "heap floor", 100, "% of max heap", out / "timeline_memory_leak.png")
    timeline("latency_ramp", "p95_ms", "p95 latency", 1, "ms", out / "timeline_latency.png")
    lead_bars(results, out / "lead_time_by_scenario.png")
    ramp_sweep(results, out / "lead_time_vs_speed.png")
    print(f"figures written to {out}")


if __name__ == "__main__":
    main()
