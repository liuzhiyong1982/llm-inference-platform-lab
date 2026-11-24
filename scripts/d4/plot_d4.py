#!/usr/bin/env python3
"""Plot TTFT P50/P95/P99 from D4 bench_prefix.py JSON files.

Usage:
  python3 scripts/d4/plot_d4.py \
    /results/direct-run1.json /results/random-run1.json /results/precise-run1.json \
    --out /results/d4-ttft.png

Requires matplotlib (install on the host, not in the vLLM image).
"""
from __future__ import annotations

import argparse
import json
import os

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("files", nargs="+")
    parser.add_argument("--out", default="d4-ttft.png")
    args = parser.parse_args()

    labels = []
    p50 = []
    p95 = []
    p99 = []
    for path in args.files:
        with open(path, encoding="utf-8") as handle:
            summary = json.load(handle)["summary"]
        labels.append(os.path.basename(path).replace(".json", ""))
        p50.append(summary["ttft_ms"]["p50"] or 0)
        p95.append(summary["ttft_ms"]["p95"] or 0)
        p99.append(summary["ttft_ms"]["p99"] or 0)

    x = range(len(labels))
    width = 0.25
    fig, ax = plt.subplots(figsize=(8, 4.5))
    ax.bar([i - width for i in x], p50, width, label="P50")
    ax.bar(list(x), p95, width, label="P95")
    ax.bar([i + width for i in x], p99, width, label="P99")
    ax.set_ylabel("TTFT (ms)")
    ax.set_title("D4: round-robin vs llm-d EPP")
    ax.set_xticks(list(x))
    ax.set_xticklabels(labels, rotation=15, ha="right")
    ax.legend()
    fig.tight_layout()
    fig.savefig(args.out, dpi=160)
    print(f"saved {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
