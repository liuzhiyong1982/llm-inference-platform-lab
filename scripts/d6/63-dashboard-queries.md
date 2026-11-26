# D6b dashboard queries

Metric names vary across vLLM versions. Confirm on the live pod:

```bash
kubectl -n kserve-test exec deploy/vllm-raw -- \
  curl -s localhost:8000/metrics | grep '^vllm:' | head -40
```

## Panels

| Panel | PromQL |
|---|---|
| TTFT P50 / P99 | `histogram_quantile(0.50, sum by (le) (rate(vllm:time_to_first_token_seconds_bucket[5m])))` / same with `0.99` |
| TPOT P50 / P99 | `histogram_quantile(0.50, sum by (le) (rate(vllm:time_per_output_token_seconds_bucket[5m])))` / same with `0.99` |
| E2E P99 | `histogram_quantile(0.99, sum by (le) (rate(vllm:e2e_request_latency_seconds_bucket[5m])))` |
| Running / waiting | `sum(vllm:num_requests_running)` / `sum(vllm:num_requests_waiting)` |
| KV cache usage | `avg(vllm:gpu_cache_usage_perc)` |
| CPU tier usage | `avg(vllm:cpu_cache_usage_perc)` |
| Preemptions/s | `sum(rate(vllm:num_preemptions_total[5m]))` |
| Prompt tokens/s | `sum(rate(vllm:prompt_tokens_total[5m]))` |
| Generation tokens/s | `sum(rate(vllm:generation_tokens_total[5m]))` |
| GPU util | `avg(DCGM_FI_DEV_GPU_UTIL)` |
| GPU memory used | `avg(DCGM_FI_DEV_FB_USED)` |
| GPU power | `avg(DCGM_FI_DEV_POWER_USAGE)` |
| XID errors | `max(DCGM_FI_DEV_XID_ERRORS)` |

## Goodput

Goodput is not a vLLM Prometheus metric. Get it from the benchmark:

```bash
vllm bench serve \
  --model qwen3-8b \
  --tokenizer Qwen/Qwen3-8B-AWQ \
  --base-url http://127.0.0.1:8000 \
  --dataset-name random \
  --random-input-len 1024 \
  --random-output-len 256 \
  --num-prompts 100 \
  --max-concurrency 16 \
  --ignore-eos \
  --percentile-metrics ttft,tpot,itl,e2el \
  --metric-percentiles 50,95,99 \
  --goodput ttft:2000 tpot:100
```

Record `request_goodput`, `output_throughput`, `p99_ttft_ms`, `p99_tpot_ms` in `results/d6/summary.md`.

## Dashboard layout

1. **Row 1: SLO** — TTFT P99, TPOT P99, goodput, 5xx/429.
2. **Row 2: saturation** — running/waiting, KV%, preemptions/s, GPU util/mem.
3. **Row 3: traffic** — prompt/generation tok/s, requests/s by model.
4. **Row 4: GPU fleet** — DCGM util, memory, power, XID by node/GPU.
