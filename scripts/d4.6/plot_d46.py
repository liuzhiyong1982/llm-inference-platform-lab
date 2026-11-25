#!/usr/bin/env python3
"""Plot D4.6 HBM-only vs tiered-KV results (median of 3 runs)."""

from __future__ import annotations

import glob
import json
import statistics
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt

ROOT = Path(__file__).resolve().parents[2]
RESULTS = ROOT / "results" / "d4.6"
OUT = RESULTS / "d4.6-tiered-vs-hbm.png"

ARMS = ("hbm", "tiered")
LABELS = {"hbm": "HBM-only", "tiered": "HBM + 16GiB CPU tier"}
COLORS = {"hbm": "#8c8c8c", "tiered": "#2f6db3"}


def median(values: list[float]) -> float:
    return statistics.median(values)


def load_runs(arm: str) -> list[dict]:
    return [
        json.load(open(path, encoding="utf-8"))
        for path in sorted(glob.glob(str(RESULTS / f"{arm}-run*.json")))
    ]


def main() -> None:
    runs = {arm: load_runs(arm) for arm in ARMS}
    fig, axes = plt.subplots(1, 3, figsize=(13.5, 4.4))

    # (a) overall TTFT percentiles
    ax = axes[0]
    percentiles = ("p50", "p95", "p99")
    x = range(len(percentiles))
    width = 0.36
    for offset, arm in zip((-width / 2, width / 2), ARMS):
        values = [
            median([run["summary"]["ttft_ms"][p] for run in runs[arm]])
            for p in percentiles
        ]
        bars = ax.bar(
            [i + offset for i in x],
            values,
            width,
            label=LABELS[arm],
            color=COLORS[arm],
        )
        for bar, value in zip(bars, values):
            ax.text(
                bar.get_x() + bar.get_width() / 2,
                value + 30,
                f"{value:.0f}",
                ha="center",
                va="bottom",
                fontsize=8,
            )
    ax.set_xticks(list(x))
    ax.set_xticklabels(["P50", "P95", "P99"])
    ax.set_ylabel("TTFT (ms)")
    ax.set_title("(a) Overall TTFT (incl. cold turn 1)")
    ax.legend(frameon=False, fontsize=8)
    ax.set_ylim(0, 3150)
    ax.grid(axis="y", alpha=0.25)

    # (b) P50 by turn: cold vs reuse
    ax = axes[1]
    groups = ("turn 1 (cold)", "turn 2-4 (reuse)")
    x = range(len(groups))
    for offset, arm in zip((-width / 2, width / 2), ARMS):
        values = []
        for turn in ("cold", "reuse"):
            per_run = []
            for run in runs[arm]:
                ttft = [
                    item["ttft_ms"]
                    for item in run["results"]
                    if item["ttft_ms"] is not None
                    and (
                        (turn == "cold" and item["turn"] == 1)
                        or (turn == "reuse" and item["turn"] > 1)
                    )
                ]
                per_run.append(statistics.median(ttft))
            values.append(median(per_run))
        bars = ax.bar(
            [i + offset for i in x],
            values,
            width,
            label=LABELS[arm],
            color=COLORS[arm],
        )
        for bar, value in zip(bars, values):
            ax.text(
                bar.get_x() + bar.get_width() / 2,
                value + 25,
                f"{value:.0f}",
                ha="center",
                va="bottom",
                fontsize=8,
            )
    ax.set_xticks(list(x))
    ax.set_xticklabels(groups)
    ax.set_ylabel("TTFT P50 (ms)")
    ax.set_title("(b) Cold start vs reuse (P50)")
    ax.set_ylim(0, 1700)
    ax.grid(axis="y", alpha=0.25)

    # (c) goodput
    ax = axes[2]
    values = [median([run["summary"]["goodput_req_s"] for run in runs[arm]]) for arm in ARMS]
    bars = ax.bar(
        [LABELS[arm] for arm in ARMS],
        values,
        color=[COLORS[arm] for arm in ARMS],
        width=0.55,
    )
    for bar, value in zip(bars, values):
        ax.text(
            bar.get_x() + bar.get_width() / 2,
            value + 0.025,
            f"{value:.2f}",
            ha="center",
            va="bottom",
            fontsize=9,
        )
    ax.set_ylabel("goodput (req/s)")
    ax.set_title("(c) SLO goodput (TTFT<=2s, TPOT<=100ms)")
    ax.set_ylim(0, 1.35)
    ax.grid(axis="y", alpha=0.25)
    ax.tick_params(axis="x", labelsize=8)

    fig.suptitle(
        "D4.6  llm-d tiered KV cache vs HBM-only  "
        "(2×RTX 3060 12GB, Qwen3-4B-AWQ, 32 sessions × 4 turns, c=4, median of 3 runs)",
        fontsize=10,
    )
    fig.tight_layout(rect=(0, 0, 1, 0.94))
    fig.savefig(OUT, dpi=160)
    print(f"saved {OUT}")


if __name__ == "__main__":
    main()
