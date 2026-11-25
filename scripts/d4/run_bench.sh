#!/usr/bin/env bash
# Wrapper so the same Pod template can run the direct-Service arm (with
# --force-close) and the EPP arms (keep-alive).
set -euo pipefail

args=(
  python3 -u /scripts/bench_prefix.py
  --url "${URL}"
  --model "${MODEL:-qwen3-4b}"
  --sessions "${SESSIONS:-32}"
  --turns "${TURNS:-4}"
  --prefix-words "${PREFIX_WORDS:-1100}"
  --suffix-words "${SUFFIX_WORDS:-80}"
  --max-tokens "${MAX_TOKENS:-128}"
  --concurrency "${CONCURRENCY:-16}"
  --seed "${SEED:-42}"
  --warmup "${WARMUP:-0}"
  --pod-urls "${POD_URLS:-}"
  --output "/results/${ARM}-run${RUN}.json"
)

if [[ "${FORCE_CLOSE:-0}" == "1" ]]; then
  args+=(--force-close)
fi

exec "${args[@]}"
