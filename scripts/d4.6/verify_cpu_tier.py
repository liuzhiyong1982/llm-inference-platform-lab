#!/usr/bin/env python3
"""Verify vLLM CPU-tier store / load / reset on one replica.

Run it against a port-forward to a single tiered vLLM pod:

  kubectl port-forward -n d46 pod/<vllm-pod> 18000:8000 >/tmp/pf.log 2>&1 &
  python3 scripts/d4.6/verify_cpu_tier.py --base-url http://127.0.0.1:18000

The test:
  1. resets the external (CPU) tier;
  2. sends a unique target prefix (cold);
  3. floods N unique prefixes to evict the target from HBM;
  4. re-sends the target and expects external cache hits + CPU load > 0;
  5. resets the external tier and expects the target to miss again.

This is the controlled check behind D4.6 §6.3. The full 128-request run is the
main benchmark; this script only proves the mechanism on one pod.
"""

from __future__ import annotations

import argparse
import json
import random
import time
import urllib.request


VOCAB = (
    "alpha beta gamma delta epsilon zeta eta theta iota kappa lambda mu nu xi "
    "omicron pi rho sigma tau upsilon phi chi psi omega kubernetes vllm router "
    "cache tensor gpu host block prefix suffix token latency throughput queue "
    "batch decode prefill attention layer head dim weight quant fp16 int8"
).split()


def post(base: str, path: str, payload: dict | None = None) -> dict:
    data = json.dumps(payload).encode() if payload is not None else b""
    request = urllib.request.Request(
        base + path,
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=180) as response:
        return json.loads(response.read())


def metric(base: str, name: str) -> float:
    total = 0.0
    with urllib.request.urlopen(base + "/metrics", timeout=30) as response:
        for line in response.read().decode().splitlines():
            if line.startswith(name + "{") or line.startswith(name + " "):
                total += float(line.rsplit(" ", 1)[1])
    return total


def snapshot(base: str) -> tuple[float, float, float]:
    return (
        metric(base, "vllm:external_prefix_cache_hits_total"),
        metric(base, "vllm:kv_offload_load_bytes_total"),
        metric(base, "vllm:kv_offload_store_bytes_total"),
    )


def unique_prompt(seed: str, words: int) -> str:
    rng = random.Random(seed)
    return " ".join(rng.choices(VOCAB, k=words))


def ask(base: str, model: str, prompt: str, max_tokens: int) -> float:
    started = time.perf_counter()
    post(
        base,
        "/v1/completions",
        {
            "model": model,
            "prompt": prompt,
            "max_tokens": max_tokens,
            "temperature": 0,
        },
    )
    return time.perf_counter() - started


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default="http://127.0.0.1:18000")
    parser.add_argument("--model", default="qwen3-4b")
    parser.add_argument("--words", type=int, default=3000)
    parser.add_argument("--flood", type=int, default=10)
    parser.add_argument("--max-tokens", type=int, default=1)
    args = parser.parse_args()
    base = args.base_url.rstrip("/")

    print(f"reset external: {post(base, '/reset_prefix_cache?reset_external=true')}")
    time.sleep(3)

    target = unique_prompt("target", args.words)
    h0, l0, s0 = snapshot(base)
    print(f"start hits={h0:.0f} load={l0 / 2**20:.1f}MiB store={s0 / 2**20:.1f}MiB")

    print(f"target #1 (cold): {ask(base, args.model, target, args.max_tokens):.2f}s")
    h1, l1, s1 = snapshot(base)
    print(
        f"  hits +{h1 - h0:.0f} load +{(l1 - l0) / 2**20:.1f}MiB "
        f"store +{(s1 - s0) / 2**20:.1f}MiB"
    )

    print(f"flood {args.flood} unique prefixes")
    for index in range(args.flood):
        ask(base, args.model, unique_prompt(f"flood-{index}", args.words), args.max_tokens)
    h2, l2, s2 = snapshot(base)
    print(
        f"  hits +{h2 - h1:.0f} load +{(l2 - l1) / 2**20:.1f}MiB "
        f"store +{(s2 - s1) / 2**20:.1f}MiB"
    )

    print(f"target #2 (expect CPU hit): {ask(base, args.model, target, args.max_tokens):.2f}s")
    h3, l3, s3 = snapshot(base)
    hit_ok = (h3 - h2) > 0 and (l3 - l2) > 0
    print(
        f"  hits +{h3 - h2:.0f} load +{(l3 - l2) / 2**20:.1f}MiB "
        f"store +{(s3 - s2) / 2**20:.1f}MiB  {'PASS' if hit_ok else 'FAIL'}"
    )

    print(f"reset external: {post(base, '/reset_prefix_cache?reset_external=true')}")
    time.sleep(3)
    print(f"target #3 (expect cold): {ask(base, args.model, target, args.max_tokens):.2f}s")
    h4, l4, s4 = snapshot(base)
    reset_ok = (h4 - h3) == 0 and (l4 - l3) == 0
    print(
        f"  hits +{h4 - h3:.0f} load +{(l4 - l3) / 2**20:.1f}MiB "
        f"store +{(s4 - s3) / 2**20:.1f}MiB  {'PASS' if reset_ok else 'FAIL'}"
    )

    if hit_ok and reset_ok:
        print("OK: CPU tier store/load and external reset both work")
        return 0
    print("FAIL: check that the pod is the tiered arm and OffloadingConnector is enabled")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
