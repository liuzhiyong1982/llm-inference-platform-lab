#!/usr/bin/env python3
"""Summarize D4.6 tiered-KV results.

Reads results/d4.6/{hbm,tiered}-runN.json plus the per-run vLLM/EPP metric
snapshots written by scripts/d4.6/run_arm.sh, and prints Markdown tables.

Usage:
  python3 scripts/d4.6/analyze.py [--results-dir results/d4.6]
"""

from __future__ import annotations

import argparse
import glob
import json
import os
import re
import statistics
from pathlib import Path

ARMS = ("hbm", "tiered")


def percentile(values: list[float], p: float) -> float:
    ordered = sorted(values)
    k = (len(ordered) - 1) * p / 100.0
    lo = int(k)
    hi = min(lo + 1, len(ordered) - 1)
    return ordered[lo] + (ordered[hi] - ordered[lo]) * (k - lo)


def stats(values: list[float]) -> dict[str, float]:
    if not values:
        return {}
    return {
        "n": len(values),
        "p50": percentile(values, 50),
        "p95": percentile(values, 95),
        "p99": percentile(values, 99),
        "mean": sum(values) / len(values),
    }


def load_run(path: str) -> dict:
    with open(path, encoding="utf-8") as handle:
        return json.load(handle)


def metric_totals(path: str) -> dict[str, float]:
    totals: dict[str, float] = {}
    with open(path, encoding="utf-8", errors="ignore") as handle:
        for line in handle:
            if line.startswith("#"):
                continue
            match = re.match(r"^([a-zA-Z0-9_:]+)(\{[^}]*\})?\s+([0-9.eE+-]+)", line)
            if match:
                totals[match.group(1)] = totals.get(match.group(1), 0.0) + float(
                    match.group(3)
                )
    return totals


def run_metric_delta(before: str) -> dict[str, float]:
    after = before.replace("-before-", "-after-")
    if not os.path.exists(after):
        return {}
    b, a = metric_totals(before), metric_totals(after)
    keys = {
        "prefix_queries": "vllm:prefix_cache_queries_total",
        "prefix_hits": "vllm:prefix_cache_hits_total",
        "ext_queries": "vllm:external_prefix_cache_queries_total",
        "ext_hits": "vllm:external_prefix_cache_hits_total",
        "store_bytes": "vllm:kv_offload_store_bytes_total",
        "load_bytes": "vllm:kv_offload_load_bytes_total",
        "store_time": "vllm:kv_offload_store_time_total",
        "load_time": "vllm:kv_offload_load_time_total",
        "preemptions": "vllm:num_preemptions_total",
    }
    return {name: a.get(metric, 0.0) - b.get(metric, 0.0) for name, metric in keys.items()}


def epp_index(path: str) -> dict[str, dict[str, float]]:
    result: dict[str, dict[str, float]] = {}
    if not os.path.exists(path):
        return result
    with open(path, encoding="utf-8", errors="ignore") as handle:
        for line in handle:
            match = re.match(
                r"^llm_d_epp_prefix_indexer_(size|hit_ratio_sum|hit_ratio_count)"
                r"\{([^}]*)\}\s+([0-9.eE+-]+)",
                line,
            )
            if not match:
                continue
            plugin = re.search(r'plugin_name="([^"]+)"', match.group(2))
            name = plugin.group(1) if plugin else "?"
            result.setdefault(name, {})[match.group(1)] = float(match.group(3))
    return result


def median_of(values: list[float]) -> float:
    return statistics.median(values)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--results-dir", default="results/d4.6")
    args = parser.parse_args()
    root = Path(args.results_dir)

    runs: dict[str, list[dict]] = {}
    for arm in ARMS:
        files = sorted(glob.glob(str(root / f"{arm}-run*.json")))
        runs[arm] = [load_run(path) for path in files]

    print("## 总体（每轮 128 请求，c=4）\n")
    print("| arm | run | ok | TTFT P50 | TTFT P95 | TTFT P99 | TPOT P95 | goodput | output tok/s | wall |")
    print("|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|")
    for arm in ARMS:
        for index, run in enumerate(runs[arm], 1):
            summary = run["summary"]
            print(
                f"| {arm} | {index} | {summary['ok']}/{summary['requests']} "
                f"| {summary['ttft_ms']['p50']:.0f} | {summary['ttft_ms']['p95']:.0f} "
                f"| {summary['ttft_ms']['p99']:.0f} | {summary['tpot_ms']['p95']:.1f} "
                f"| {summary['goodput_req_s']:.3f} | {summary['output_tok_s']:.1f} "
                f"| {summary['wall_time_s']:.1f}s |"
            )
        if runs[arm]:
            summaries = [run["summary"] for run in runs[arm]]
            print(
                f"| **{arm} 中位数** | 3 | — "
                f"| {median_of([s['ttft_ms']['p50'] for s in summaries]):.0f} "
                f"| {median_of([s['ttft_ms']['p95'] for s in summaries]):.0f} "
                f"| {median_of([s['ttft_ms']['p99'] for s in summaries]):.0f} "
                f"| {median_of([s['tpot_ms']['p95'] for s in summaries]):.1f} "
                f"| {median_of([s['goodput_req_s'] for s in summaries]):.3f} "
                f"| {median_of([s['output_tok_s'] for s in summaries]):.1f} "
                f"| {median_of([s['wall_time_s'] for s in summaries]):.1f}s |"
            )

    print("\n## 按 turn 拆 TTFT（turn 1 = 冷启动，turn 2–4 = 复用）\n")
    print("| arm | 轮次 | turn | n | P50 | P95 | P99 |")
    print("|---|---:|---|---:|---:|---:|---:|")
    for arm in ARMS:
        for index, run in enumerate(runs[arm], 1):
            results = run["results"]
            for label, predicate in (
                ("1", lambda r: r["turn"] == 1),
                ("2–4", lambda r: r["turn"] > 1),
            ):
                values = [
                    r["ttft_ms"]
                    for r in results
                    if predicate(r) and r["ttft_ms"] is not None
                ]
                if not values:
                    continue
                s = stats(values)
                print(
                    f"| {arm} | {index} | {label} | {s['n']} | {s['p50']:.0f} "
                    f"| {s['p95']:.0f} | {s['p99']:.0f} |"
                )

    print("\n## vLLM offload / cache 指标（两个副本求和，单轮增量）\n")
    print("| arm | run | CPU store GiB | CPU load GiB | CPU hit | HBM hit | preemptions | store s | load s |")
    print("|---|---:|---:|---:|---:|---:|---:|---:|---:|")
    for arm in ARMS:
        for index in range(1, len(runs[arm]) + 1):
            files = sorted(
                glob.glob(str(root / f"metrics-{arm}-run{index}-before-*.txt"))
            )
            if not files:
                continue
            deltas = [run_metric_delta(path) for path in files]
            total = {
                key: sum(delta.get(key, 0.0) for delta in deltas)
                for key in deltas[0]
            }
            cpu_hit = (
                total["ext_hits"] / total["ext_queries"] * 100
                if total["ext_queries"]
                else 0.0
            )
            hbm_hit = (
                total["prefix_hits"] / total["prefix_queries"] * 100
                if total["prefix_queries"]
                else 0.0
            )
            print(
                f"| {arm} | {index} | {total['store_bytes'] / 2**30:.2f} "
                f"| {total['load_bytes'] / 2**30:.2f} | {cpu_hit:.1f}% | {hbm_hit:.1f}% "
                f"| {total['preemptions']:.0f} | {total['store_time']:.2f} "
                f"| {total['load_time']:.2f} |"
            )

    print("\n## EPP prefix 索引（每轮结束后）\n")
    print("| arm | run | GPU index | GPU hit | CPU index | CPU hit |")
    print("|---|---:|---:|---:|---:|---:|")
    for arm in ARMS:
        for index in range(1, len(runs[arm]) + 1):
            data = epp_index(str(root / f"epp-{arm}-run{index}-after.txt"))
            values = []
            for plugin in ("gpu-prefix-cache-producer", "cpu-prefix-cache-producer"):
                item = data.get(plugin, {})
                hit_sum = item.get("hit_ratio_sum", 0.0)
                hit_count = item.get("hit_ratio_count", 0.0)
                hit = hit_sum / hit_count * 100 if hit_count else 0.0
                values.append((item.get("size", 0.0), hit))
            print(
                f"| {arm} | {index} | {values[0][0]:.0f} | {values[0][1]:.1f}% "
                f"| {values[1][0]:.0f} | {values[1][1]:.1f}% |"
            )


if __name__ == "__main__":
    main()
