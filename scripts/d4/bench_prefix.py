#!/usr/bin/env python3
"""
D4 prefix-reuse benchmark for llm-d / vLLM.

It sends interleaved multi-turn sessions through an OpenAI-compatible endpoint,
streams the responses, and records TTFT, TPOT, end-to-end latency, token usage,
output throughput and SLO goodput.

Run it inside the vLLM image (aiohttp is already installed):

  python3 bench_prefix.py \
    --url http://d4-router-epp/v1/completions \
    --model qwen3-4b \
    --sessions 32 --turns 4 \
    --prefix-words 1100 --suffix-words 80 \
    --max-tokens 128 --concurrency 16 \
    --pod-urls http://10.42.0.10:8000,http://10.42.0.11:8000 \
    --output /results/precise-run1.json

Why sessions: each session has its own long system prefix. Requests from the
same session are interleaved with other sessions, so a random router loses the
prefix affinity between turns while a prefix-aware router can keep the session
on the pod that already cached it.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import math
import os
import random
import sys
import time
from dataclasses import dataclass
from typing import Any

try:
    import aiohttp
except ImportError:
    sys.exit("aiohttp is required; run inside vllm/vllm-openai or pip install aiohttp")


SENTENCES = [
    "Kubernetes schedules pods onto nodes and the scheduler does not understand GPU memory fragmentation.",
    "A model server keeps a KV cache so that a repeated prompt prefix does not have to be prefilled again.",
    "The router should send a request to the replica that already holds the prompt prefix in its KV cache.",
    "A queueing delay at one replica is not visible in GPU utilization but it is visible in the tail latency.",
    "The inference gateway uses an external processor to pick an endpoint before the proxy forwards the request.",
    "A pool of model servers is described by a selector and a target port in the inference pool resource.",
    "The endpoint picker watches the pool, the pods and the model server metrics to make a routing decision.",
    "Prefix caching trades memory for compute, and the trade only pays off when the prefix is reused.",
    "A cold start is dominated by image pull, weight download, weight load and engine initialization.",
    "Graceful shutdown needs a preStop delay, a drain window and a termination grace period that is large enough.",
    "The tokenizer turns text into token IDs, and the router needs the exact IDs to look up cached blocks.",
    "A block size mismatch between the engine and the router makes every cache lookup miss silently.",
    "The scheduler should prefer the cache warm replica until that replica becomes saturated.",
    "Load-aware routing spreads requests when the cache warm replica is close to its prefill limit.",
    "A single endpoint picker is a deliberate choice when its in-flight accounting is process local.",
    "Observability needs both the router view and the model server view to explain a routing decision.",
    "The client sees time to first token and inter token latency, not the internal queue depth.",
    "A good benchmark holds the model, the hardware, the input length and the output length constant.",
    "The control arm and the treatment arm must see the same request sequence and the same cache state.",
    "A result without a cache reset is not a routing result, because the previous run warmed the cache.",
    "The gateway can fail open and load balance across the pool when the endpoint picker is unavailable.",
    "The gateway can fail close and reject requests when the endpoint picker is unavailable.",
    "Multi-tenant isolation starts with namespaces and quotas, not with a routing algorithm.",
    "Capacity planning should use the concurrency that meets the SLO, not the maximum GPU utilization.",
    "A model rollout should use a new weight directory and a new deployment revision, not an in-place overwrite.",
]


@dataclass
class Session:
    sid: int
    system: str
    history: list[tuple[str, str]]


def make_prefix(rng: random.Random, words: int) -> str:
    out: list[str] = []
    while len(out) < words:
        out.extend(rng.choice(SENTENCES).split())
    return " ".join(out[:words])


def build_requests(args: argparse.Namespace) -> list[tuple[int, int, str]]:
    """Return (session_id, turn, prompt) in an interleaved, deterministic order."""
    rng = random.Random(args.seed)
    sessions: list[Session] = []
    for sid in range(args.sessions):
        system = "You are a helpful assistant. " + make_prefix(rng, args.prefix_words)
        sessions.append(Session(sid=sid, system=system, history=[]))

    sequence: list[tuple[int, int, str]] = []
    for turn in range(1, args.turns + 1):
        order = list(range(args.sessions))
        rng.shuffle(order)
        for sid in order:
            session = sessions[sid]
            question = (
                f"Turn {turn}: state the key constraint in one sentence. "
                + make_prefix(rng, args.suffix_words)
            )
            parts = [session.system, ""]
            for user, assistant in session.history:
                parts.append(f"User: {user}")
                parts.append(f"Assistant: {assistant}")
            parts.append(f"User: {question}")
            parts.append("Assistant:")
            sequence.append((sid, turn, "\n".join(parts)))
            session.history.append(
                (question, "The key constraint is the capacity and latency trade-off.")
            )
    return sequence


def percentile(values: list[float], p: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    k = (len(ordered) - 1) * (p / 100.0)
    lo = math.floor(k)
    hi = math.ceil(k)
    if lo == hi:
        return ordered[int(k)]
    return ordered[lo] + (ordered[hi] - ordered[lo]) * (k - lo)


def stats(values: list[float]) -> dict[str, float | None]:
    if not values:
        return {"p50": None, "p95": None, "p99": None, "mean": None}
    return {
        "p50": percentile(values, 50),
        "p95": percentile(values, 95),
        "p99": percentile(values, 99),
        "mean": sum(values) / len(values),
    }


async def reset_caches(http: aiohttp.ClientSession, pod_urls: list[str]) -> None:
    for base in pod_urls:
        # reset_external=true also clears the connector-managed tier (e.g. the
        # CPU tier behind vLLM's OffloadingConnector). Without it, only the HBM
        # prefix cache is reset, so a second run starts with a warm CPU tier.
        url = base.rstrip("/") + "/reset_prefix_cache?reset_external=true"
        try:
            async with http.post(
                url, timeout=aiohttp.ClientTimeout(total=15)
            ) as response:
                body = await response.text()
                print(
                    f"[reset] {base}: HTTP {response.status} {body[:160]}",
                    flush=True,
                )
        except Exception as exc:  # noqa: BLE001 - report and continue
            print(f"[reset] {base}: {type(exc).__name__}: {exc}", flush=True)
    await asyncio.sleep(2)


async def one_request(
    http: aiohttp.ClientSession,
    args: argparse.Namespace,
    sem: asyncio.Semaphore,
    sid: int,
    turn: int,
    prompt: str,
    idx: int,
    max_tokens: int | None = None,
) -> dict[str, Any]:
    async with sem:
        start = time.perf_counter()
        first: float | None = None
        usage: dict[str, Any] | None = None
        status: int | None = None
        error: str | None = None
        chunks = 0

        payload = {
            "model": args.model,
            "prompt": prompt,
            "max_tokens": max_tokens or args.max_tokens,
            "temperature": 0,
            "stream": True,
            "stream_options": {"include_usage": True},
            "ignore_eos": not args.no_ignore_eos,
        }

        try:
            async with http.post(
                args.url,
                json=payload,
                timeout=aiohttp.ClientTimeout(total=args.request_timeout),
            ) as response:
                status = response.status
                if status != 200:
                    body = await response.text()
                    error = f"HTTP {status}: {body[:300]}"
                else:
                    while True:
                        raw = await response.content.readline()
                        if not raw:
                            break
                        line = raw.decode("utf-8", "ignore").strip()
                        if not line or not line.startswith("data:"):
                            continue
                        data = line[5:].strip()
                        if data == "[DONE]":
                            break
                        try:
                            obj = json.loads(data)
                        except json.JSONDecodeError:
                            continue
                        if obj.get("usage"):
                            usage = obj["usage"]
                        choices = obj.get("choices") or []
                        if choices:
                            choice = choices[0]
                            text = choice.get("text")
                            if text is None:
                                text = (choice.get("delta") or {}).get("content")
                            if text:
                                chunks += 1
                                if first is None:
                                    first = time.perf_counter()
        except Exception as exc:  # noqa: BLE001 - record the failure
            error = f"{type(exc).__name__}: {exc}"

        end = time.perf_counter()
        latency_ms = (end - start) * 1000.0
        ttft_ms = (first - start) * 1000.0 if first is not None else None

        prompt_tokens = None
        completion_tokens = None
        if usage:
            if usage.get("prompt_tokens") is not None:
                prompt_tokens = int(usage["prompt_tokens"])
            if usage.get("completion_tokens") is not None:
                completion_tokens = int(usage["completion_tokens"])

        tpot_ms = None
        if ttft_ms is not None and completion_tokens and completion_tokens > 1:
            tpot_ms = (latency_ms - ttft_ms) / (completion_tokens - 1)

        if status == 200 and error is None and first is None:
            error = "no content chunk received"

        return {
            "idx": idx,
            "session": sid,
            "turn": turn,
            "status": status,
            "error": error,
            "ttft_ms": ttft_ms,
            "latency_ms": latency_ms,
            "tpot_ms": tpot_ms,
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
            "chunks": chunks,
        }


async def run_warmup(
    http: aiohttp.ClientSession, args: argparse.Namespace
) -> None:
    rng = random.Random(args.seed + 1)
    sem = asyncio.Semaphore(max(1, min(args.concurrency, args.warmup)))
    tasks = []
    for i in range(args.warmup):
        prompt = make_prefix(rng, 256) + "\n\nUser: warmup\nAssistant:"
        tasks.append(one_request(http, args, sem, -1, 0, prompt, i, max_tokens=1))
    results = await asyncio.gather(*tasks)
    ok = sum(1 for r in results if r["status"] == 200 and not r["error"])
    print(f"[warmup] {ok}/{len(results)} ok", flush=True)


async def main_async(args: argparse.Namespace) -> int:
    sequence = build_requests(args)
    pod_urls = [item.strip() for item in args.pod_urls.split(",") if item.strip()]

    connector = aiohttp.TCPConnector(
        limit=max(16, args.concurrency * 2), force_close=args.force_close
    )
    async with aiohttp.ClientSession(connector=connector) as http:
        if args.warmup > 0 and not pod_urls:
            print(
                "[warn] warmup is enabled but --pod-urls is empty; "
                "the prefix cache will not be reset",
                flush=True,
            )
        if args.warmup > 0:
            await run_warmup(http, args)

        if pod_urls:
            await reset_caches(http, pod_urls)

        sem = asyncio.Semaphore(args.concurrency)
        started = time.perf_counter()
        results = await asyncio.gather(
            *[
                one_request(http, args, sem, sid, turn, prompt, idx)
                for idx, (sid, turn, prompt) in enumerate(sequence)
            ]
        )
        wall_time = time.perf_counter() - started

    ok_results = [r for r in results if r["status"] == 200 and not r["error"]]
    ttfts = [r["ttft_ms"] for r in ok_results if r["ttft_ms"] is not None]
    tpots = [r["tpot_ms"] for r in ok_results if r["tpot_ms"] is not None]
    latencies = [r["latency_ms"] for r in ok_results if r["latency_ms"] is not None]
    good = [
        r
        for r in ok_results
        if r["ttft_ms"] is not None
        and r["ttft_ms"] <= args.slo_ttft_ms
        and r["tpot_ms"] is not None
        and r["tpot_ms"] <= args.slo_tpot_ms
    ]

    output_tokens = sum(
        r["completion_tokens"] or 0 for r in ok_results
    )
    summary = {
        "config": {
            "url": args.url,
            "model": args.model,
            "sessions": args.sessions,
            "turns": args.turns,
            "prefix_words": args.prefix_words,
            "suffix_words": args.suffix_words,
            "max_tokens": args.max_tokens,
            "concurrency": args.concurrency,
            "seed": args.seed,
            "force_close": args.force_close,
            "warmup": args.warmup,
        },
        "wall_time_s": wall_time,
        "requests": len(results),
        "ok": len(ok_results),
        "errors": len(results) - len(ok_results),
        "ttft_ms": stats(ttfts),
        "tpot_ms": stats(tpots),
        "latency_ms": stats(latencies),
        "output_tokens": output_tokens,
        "output_tok_s": output_tokens / wall_time if wall_time > 0 else None,
        "req_s": len(results) / wall_time if wall_time > 0 else None,
        "good": len(good),
        "goodput_req_s": len(good) / wall_time if wall_time > 0 else None,
        "goodput_frac": len(good) / len(results) if results else None,
        "slo": {
            "ttft_ms": args.slo_ttft_ms,
            "tpot_ms": args.slo_tpot_ms,
        },
    }

    os.makedirs(os.path.dirname(os.path.abspath(args.output)), exist_ok=True)
    with open(args.output, "w", encoding="utf-8") as handle:
        json.dump(
            {"summary": summary, "results": results},
            handle,
            indent=2,
            ensure_ascii=False,
        )

    print(json.dumps(summary, indent=2, ensure_ascii=False), flush=True)
    print(f"[saved] {args.output}", flush=True)

    if not ok_results:
        return 1
    return 0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", required=True, help="OpenAI-compatible completions URL")
    parser.add_argument("--model", default="qwen3-4b")
    parser.add_argument("--sessions", type=int, default=32)
    parser.add_argument("--turns", type=int, default=4)
    parser.add_argument("--prefix-words", type=int, default=1100)
    parser.add_argument("--suffix-words", type=int, default=80)
    parser.add_argument("--max-tokens", type=int, default=128)
    parser.add_argument("--concurrency", type=int, default=16)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--request-timeout", type=float, default=300.0)
    parser.add_argument(
        "--pod-urls",
        default="",
        help="comma-separated vLLM pod base URLs for /reset_prefix_cache",
    )
    parser.add_argument(
        "--warmup",
        type=int,
        default=0,
        help="number of warmup requests with max_tokens=1 before the measured run",
    )
    parser.add_argument(
        "--force-close",
        action="store_true",
        help="open a new TCP connection per request (use for the direct Service arm)",
    )
    parser.add_argument(
        "--no-ignore-eos",
        action="store_true",
        help="do not send ignore_eos=true; output length may vary",
    )
    parser.add_argument("--slo-ttft-ms", type=float, default=2000.0)
    parser.add_argument("--slo-tpot-ms", type=float, default=100.0)
    parser.add_argument("--output", required=True)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    return asyncio.run(main_async(args))


if __name__ == "__main__":
    raise SystemExit(main())
