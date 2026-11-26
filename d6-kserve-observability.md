# D6 学习文档：KServe 服务抽象 + 推理可观测性（KServe + vLLM + OTel）

> 状态：**planned（2026-11-26 合并原 D6/D7；尚未在 Vast 执行）**。本文把原计划的 **D6（KServe 服务抽象）** 和 **D7（Inference Observability）** 合成一个 lab，按内容分成两段：**D6a KServe（3h）** + **D6b 观测（2–3h）**。两段用同一台 VM、同一套 manifest，**不重跑 D1–D4**。
>
> 性质：**B 线 serving 抽象 + 平台可观测性 lab**，不是 A 线引擎性能 lab。D5 回答“谁能拿 GPU”，D6 回答“模型怎么被部署、怎么被观测”。
>
> 版本基线：**KServe `v0.21.0`**、k3s `v1.37.2+k3s1`、Kubernetes `v1.37`（KServe 要求 ≥1.32）、vLLM `v0.34.0`、Qwen3-8B-AWQ、OTel Collector `0.166.0`、DCGM exporter `4.9.0`。
>
> 机器：优先复用 **D5 的单卡 VM（显存 ≥12GB 时）**；新租选 1×RTX 4090 24GB。**canary 需要 2 张卡；单卡改为 dark launch 或跳过**（见 §8.4）。**不要按 L4 VM 租**：Vast 的 L4 只有容器，k3s 起不来。
>
> 预算：2×3060 `$0.2615/h` × 5–6h ≈ **`$1.5–1.8`（含 buffer）**；实际账单写进 `results/d6/cost.txt`，不要用估算替代。

---

## 0. 先看结论（执行前先记住）

1. **KServe 是控制面，不是更快的引擎。** 它把 Deployment / Service / Ingress / HPA / revision 收成一个 `InferenceService` CRD；TTFT/TPOT 不会因为装了 KServe 就变好。
2. **LLM 优先 Standard/RawDeployment，不优先 Serverless。** Knative 的 scale-to-zero 对长驻 LLM 通常不划算；Standard mode 本身也**不支持 HTTP 0→1**。
3. **`InferenceService` 和 `LLMInferenceService` 不是二选一。** 前者是通用 serving 抽象（HuggingFace runtime + vLLM backend）；后者是 GenAI 专用 CRD，底层组合 llm-d/EPP。
4. **D6b 不是再装一套 Prometheus。** 微服务 obs 的骨架不变，补的是 TTFT/TPOT、KV cache、goodput、prefix 命中、$/1M tokens 这些推理语义。
5. **不重跑 D4。** D6b 把 D4 的 EPP/vLLM manifest 当被观测对象，跑 10 分钟负载即可；EPP trace 是 optional。
6. **D6 的验收是证据，不是“装好了”**：KServe Ready + raw vs KServe 冷启动表 + 1 张 dashboard + 1 条 trace + 1 条告警 + 1 次 game day。

---

## 1. 学习目标与验收

### 1.1 三个证据

| # | 证据 | 说明 |
|---|---|---|
| 1 | **raw vs KServe 冷启动表** | 镜像拉取 / 权重下载 / 引擎初始化 / Ready；同一模型、同一 vLLM 镜像 |
| 2 | **KServe 运维行为** | canary Deployment 10%、HPA 1→2、rollback；scale-to-zero 的限制 |
| 3 | **推理 dashboard + trace + alert** | TTFT/TPOT/goodput/KV/GPU；一条 `gateway→vLLM` trace；一条 SLO 告警 |

### 1.2 B 线交付物

- 一个 `InferenceService`（READY=True）+ 一个 raw Deployment 对照；
- 一张 dashboard 截图 + PromQL 清单；
- 一条 OTel trace（`gen_ai.*` attributes）；
- 一条 TTFT P99 或 KV > 90% 告警；
- `results/d6/summary.md` + `cost.txt` + `game-day.md`。

### 1.3 时间盒

**D6a（3h）**

| 时间 | 动作 | 判据 |
|---|---|---|
| 0:00–0:25 | 复用 D5 VM；确认 k3s/GPU/镜像 | `nvidia.com/gpu=1`；canary 另需 2 卡，按 §8.4 跳过或 dark launch |
| 0:25–0:55 | 装 cert-manager/Gateway API/Envoy/KServe | `kserve` pod 全 Ready |
| 0:55–1:35 | raw Deployment + benchmark | `/v1/models` 200；记录冷启动 |
| 1:35–2:15 | `InferenceService` + benchmark | `READY=True`；同一 workload |
| 2:15–2:45 | canary / HPA | stable + canary Deployment；副本 1→2 |
| 2:45–3:00 | 记录 | `results/d6/` |

**D6b（2–3h）**

| 时间 | 动作 | 判据 |
|---|---|---|
| 0:00–0:30 | Prometheus/Grafana/DCGM（复用 D3 最好） | GPU 指标可见 |
| 0:30–1:00 | vLLM PodMonitor + dashboard | TTFT/TPOT/KV/队列有曲线 |
| 1:00–1:30 | OTel Collector + vLLM trace | 1 条 trace |
| 1:30–2:00 | 告警 + game day | 告警触发/恢复有记录 |
| 2:00–2:30 | 记录/清理 | `summary.md` |

### 1.4 不做什么

- 不装完整 Knative/Serverless（除非专门测 0→1，额外 30–45 min）；
- 不做 `LLMInferenceService` 的性能/PD 实验（optional，见 §10）；
- 不做 Kubeflow Pipelines / MLflow / OpenShift AI；
- 不做 MIG/DRA/Dragonfly；
- 不重跑 D1–D4 的全量对比。

---

## 2. 环境、版本、预算

### 2.1 机器

| 方案 | 说明 |
|---|---|
| **复用 D5 单卡 VM** | 推荐（显存 ≥12GB 时）；D5 只占位 GPU，D6 直接换模型；canary 改为 dark launch 或跳过；增量 5–6h |
| 1×RTX 4090 24GB | 单卡更宽裕；按 Vast 实时价 |
| 1×L4 VM | **不可行**：Vast L4 只有容器，k3s 需要 VM |

### 2.2 版本矩阵

| 组件 | 版本 | 备注 |
|---|---|---|
| KServe | `v0.21.0` | 2026-09-25 发布；K8s ≥1.32 |
| k3s | `v1.37.2+k3s1` | D3/D5 已验证 |
| Kubernetes | `v1.37` | 满足 KServe 要求 |
| cert-manager | `v1.17.0` | KServe 要求 ≥1.15 |
| Gateway API | `v1.2.1` | Standard 文档；LLMISvc 依赖可能更高 |
| Envoy Gateway | `v1.8.1` | KServe Standard 的 GatewayClass |
| vLLM | `v0.34.0` | raw 与 custom runtime 对齐 |
| 模型 | `Qwen/Qwen3-8B-AWQ` | 约 5.7GB，12GB 卡可跑 |
| OTel Collector | `0.166.0` | `otel/opentelemetry-collector-contrib` |
| DCGM exporter | `4.9.0` | GPU 指标 |
| KServe 内置 runtime | `kserve-vllmserver` | 镜像是 `vllm/vllm-openai:v0.21.0`；本文用 custom runtime 对齐 v0.34.0 |

### 2.3 六个版本/路径坑

1. **KServe v0.21 的 runtime 清单叫 `kserve-cluster-resources.yaml`**，不是老文档里的 `kserve-runtimes.yaml`。
2. **Standard mode 不支持 HTTP scale-to-zero。** KServe 文档明确写了；要测 0→1 必须 Knative/Serverless。
3. **`InferenceService` 是 `serving.kserve.io/v1beta1`；`LLMInferenceService` 是 `serving.kserve.io/v1alpha2`。** 不要把 v1alpha1 的旧示例直接抄到 v0.21。
4. **不要把 `InferenceService` 建在 `kserve` 控制面 namespace。** KServe 会跳过 storage-initializer 注入，Pod 报 `/mnt/models` 不存在。
5. **内置 `kserve-vllmserver` 的 vLLM 版本和 D1–D4 的 `v0.34.0` 不一致。** 要比 TTFT/TPOT，用本文的 custom `ClusterServingRuntime`；否则只比冷启动/运维行为，并明确 confound。
6. **Standard mode 的 canary 用 `spec.canary`，不是 `canaryTrafficPercent`。** 后者是 Knative 字段，在 Standard mode 会被静默忽略；v0.20+ 用 `spec.canary`（`predictor.name` + `trafficPercent`）。

### 2.4 预算

| 项 | 金额 |
|---|---|
| 2×3060 5–6h | `$1.31–1.57` |
| buffer | `$0.20` |
| 合计 | **≈ `$1.5–1.8`** |

执行后把 Vast 实际账单写进 `results/d6/cost.txt`。

---

## 3. 概念：KServe 在栈里的位置

### 3.1 两层，不是二选一

```text
KServe InferenceService（控制面：CRD、Deployment、Service、Ingress、HPA、revision）
  └─ vLLM（engine：continuous batching、KV cache、OpenAI API）

KServe LLMInferenceService（GenAI 控制面）
  └─ llm-d / GAIE / EPP（路由：prefix cache 感知、PD、flow control）
       └─ vLLM workers
```

- **KServe + vLLM**：企业标准路径；KServe 管部署/流量/生命周期，vLLM 管推理。
- **KServe + llm-d + vLLM**：`LLMInferenceService` 的 advanced 路径；KServe 生成 Gateway/HTTPRoute/InferencePool/EPP。
- **llm-d + vLLM（无 KServe）**：D4 已做；不是必须套 KServe。

### 3.2 核心对象

| 对象 | 作用 |
|---|---|
| `InferenceService` | 一个模型服务的声明：predictor/transformer/explainer |
| `ServingRuntime` / `ClusterServingRuntime` | 运行时模板：镜像、args、probe、支持的 modelFormat |
| `InferenceGraph` | 多模型编排（本文不做） |
| `LLMInferenceService` | GenAI 专用：vLLM workers + Gateway/HTTPRoute/InferencePool/EPP |
| `LocalModelCache` | 节点本地模型缓存（optional） |

### 3.3 Standard vs Serverless

| | Standard（RawDeployment） | Serverless（Knative） |
|---|---|---|
| 底层 | Deployment + Service + Ingress/Gateway + HPA | Knative Service + Revision |
| scale-to-zero | **不支持 HTTP 0→1** | 支持 |
| 冷启动 | 可预测 | 多一层 Knative/queue-proxy |
| LLM 适配 | **推荐** | 不推荐长驻 LLM |
| 依赖 | cert-manager + Gateway API/Envoy | 额外 Knative + Istio/Kourier |

### 3.4 canary / autoscaling

- **canary（Standard）**：`spec.canary` 列表，每项 `predictor.name` + `trafficPercent`；KServe 创建 `{isvc}-{name}-predictor` Deployment，按比例分流。
- **canary（Serverless）**：才用 `canaryTrafficPercent`；它在 Standard mode 会被静默忽略。
- **HPA**：`minReplicas`/`maxReplicas`；Standard mode 默认按 CPU，LLM 应换 KEDA/Prometheus 按 `num_requests_waiting` 或自定义指标。
- **rollback**：把 canary `trafficPercent` 设回 0 / 删掉 canary entry；记录 stable/canary Deployment。
- **scale-to-zero**：Standard 不支持；LLM 冷启动代价高，生产一般 `minReplicas >= 1`。

### 3.5 推理 observability 的五个增量

| 维度 | 微服务常见 | 推理层补充 |
|---|---|---|
| 延迟 | HTTP P99 | TTFT、TPOT/ITL、E2E、queue/prefill/decode |
| 吞吐 | RPS | input/output tok/s、goodput |
| 饱和度 | CPU/memory | KV cache、running/waiting、preemption |
| 路由 | upstream 5xx | EPP prefix hit、后端倾斜、重试 |
| 成本/质量 | 无 | $/1M tokens、GPU-hours、eval pass |

### 3.6 指标地图

| 层 | 关键指标 | 回答 |
|---|---|---|
| Gateway | RPS、5xx、429、上游延迟 | 入口是否限流/超时？ |
| KServe | `READY`、revision、HPA 副本、reconcile 错误 | 控制面是否正常？ |
| vLLM | TTFT、TPOT、E2E、running/waiting、KV%、prefix hit、preemption | 引擎慢在哪？ |
| GPU/DCGM | util、显存、功耗、XID、throttle | 硬件是否降频/故障？ |
| K8s | Pending、重启、OOMKilled、cold start | 调度/生命周期是否正常？ |

### 3.7 常见误区

- `nvidia-smi` 的 GPU util ≠ `vllm:gpu_cache_usage_perc`；
- 客户端 TTFT ≠ 服务端 TTFT；
- 平均 TPOT 会掩盖长尾，ITL P99 才能看抖动；
- GPU util 40% 不代表空闲，decode 可能已经 KV-bound；
- 不要用 `request_id` / prompt 做 metric label（高基数）；
- 默认不要记录 prompt/completion 原文。

---

## 4. 目标架构

```text
D6a:
  client
    └─ Envoy Gateway (Gateway API)
         └─ InferenceService qwen3-8b
              └─ vLLM (custom ClusterServingRuntime, v0.34.0)

D6b:
  vLLM / KServe / Envoy / DCGM
    ├─ Prometheus (metrics)
    ├─ OTel Collector (traces)
    └─ Grafana (dashboard + alerts)

Optional:
  LLMInferenceService
    └─ Gateway / HTTPRoute / InferencePool / EPP (llm-d)
         └─ vLLM workers
```

---

## 5. Lab 0：VM + k3s + GPU

复用 D5 §5.0–§5.4（NVIDIA runtime、k3s、device plugin）。确认：

```bash
kubectl get nodes -o wide
kubectl describe node | grep -A2 'nvidia.com/gpu'
nvidia-smi -L
```

预期 `nvidia.com/gpu: 2`。预拉镜像和模型（可选，省冷启动）：

```bash
sudo k3s ctr images pull docker.io/vllm/vllm-openai:v0.34.0
export HF_HOME=/workspace/hf
python3 - <<'PY'
from huggingface_hub import snapshot_download
snapshot_download("Qwen/Qwen3-8B-AWQ")
PY
```

> 如果复用 D5 VM，先删 D5 的占位 Job，释放 GPU；Kueue/Kyverno 可以保留，但 D6 的 `kserve-test` namespace 不要被 Kyverno 的 GPU 策略误伤。D6 是独立 lab，建议先 `kubectl delete -f scripts/d5/jobs` 或删 namespace。

---

## 6. Lab 1：安装 KServe v0.21.0（Standard）

### 6.1 用官方 install script

```bash
git clone --depth 1 --branch v0.21.0 https://github.com/kserve/kserve.git
cd kserve
./hack/kserve-install.sh \
  --kserve-version v0.21.0 \
  --standard \
  --type kserve
```

脚本会装 cert-manager、Gateway API、Envoy Gateway 和 KServe。等待：

```bash
kubectl -n kserve rollout status deploy/kserve-controller-manager --timeout=5m
kubectl -n kserve get pods
kubectl get crd | grep -E 'inferenceservice|servingruntime|llminferenceservice'
kubectl -n kserve get gateway
```

预期能看到 `kserve-ingress-gateway`（或类似名字）和 `kserve-controller-manager` Ready。

### 6.2 检查 runtime

```bash
kubectl get clusterservingruntime | grep -E 'vllm|huggingface'
kubectl get clusterservingruntime kserve-vllmserver -o yaml | head -40
```

内置 `kserve-vllmserver` 的镜像是 `vllm/vllm-openai:v0.21.0`。本文用 `scripts/d6/20-clusterservingruntime.yaml` 的 `kserve-vllmserver-d6`（v0.34.0）对齐 D1–D4。

### 6.3 如果 install script 失败

手动路径（仅排障用）：

```bash
# cert-manager
kubectl apply -f https://github.com/cert-manager/cert-manager/releases/download/v1.17.0/cert-manager.yaml
# Gateway API
kubectl apply -f https://github.com/kubernetes-sigs/gateway-api/releases/download/v1.2.1/standard-install.yaml
# Envoy Gateway（Helm）
helm install eg oci://docker.io/envoyproxy/gateway-helm \
  --version v1.8.1 -n envoy-gateway-system --create-namespace
# KServe
helm install kserve-crd oci://ghcr.io/kserve/charts/kserve-crd \
  --version v0.21.0 -n kserve --create-namespace
helm install kserve oci://ghcr.io/kserve/charts/kserve-resources \
  --version v0.21.0 -n kserve \
  --set kserve.controller.deploymentMode=Standard \
  --set kserve.controller.gateway.ingressGateway.enableGatewayApi=true \
  --set kserve.controller.gateway.ingressGateway.createGateway=true
kubectl apply --server-side -f \
  https://github.com/kserve/kserve/releases/download/v0.21.0/kserve-cluster-resources.yaml
```

> `--server-side` 是必须的：`InferenceService` CRD 很大，client-side apply 可能 annotation 过大。

---

## 7. Lab 2：raw Deployment 控制组

```bash
kubectl apply -f scripts/d6/10-raw-vllm.yaml
kubectl -n kserve-test rollout status deploy/vllm-raw --timeout=15m
kubectl -n kserve-test get pods -o wide
```

验证：

```bash
kubectl -n kserve-test port-forward svc/vllm-raw 8000:8000
curl -s http://127.0.0.1:8000/v1/models | jq
curl -s http://127.0.0.1:8000/v1/chat/completions \
  -H 'Content-Type: application/json' \
  -d '{"model":"qwen3-8b","messages":[{"role":"user","content":"hello"}],"max_tokens":32}' | jq
```

### 7.1 冷启动分解

```bash
# 记录删除到 Ready 的总时间
kubectl -n kserve-test delete deploy vllm-raw --wait=true
kubectl apply -f scripts/d6/10-raw-vllm.yaml
time kubectl -n kserve-test rollout status deploy/vllm-raw --timeout=15m

# 分阶段：镜像拉取 / 模型下载 / 引擎初始化 / CUDA graph / Ready
kubectl -n kserve-test describe pod -l app=vllm-raw | sed -n '/Events:/,$p'
kubectl -n kserve-test logs deploy/vllm-raw | grep -E 'Loading|model|KV|CUDA|Started|ready'
```

记录到 `results/d6/cold-start.csv`：

```csv
path,image_pull_s,model_download_s,engine_init_s,total_ready_s
raw,,,, 
kserve,,,, 
```

> raw 的 vLLM 直接从 HF 下载；KServe 的 storage initializer 先下载到 `/mnt/models`，再启动 vLLM。两者阶段不同，报告里要写清。

### 7.2 benchmark

```bash
kubectl -n kserve-test run bench --rm -it --restart=Never \
  --image=vllm/vllm-openai:v0.34.0 -- \
  vllm bench serve \
  --model qwen3-8b \
  --tokenizer Qwen/Qwen3-8B-AWQ \
  --base-url http://vllm-raw.kserve-test.svc:8000 \
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

保存 JSON 到 `results/d6/raw-bench.json`。

---

## 8. Lab 3：KServe InferenceService

### 8.1 应用 custom runtime + ISVC

> 2×3060 上 raw 和 ISVC 各占 1 卡，可以同时跑；1×4090 上先删 raw 再跑 ISVC。冷启动对比要顺序跑，避免 CPU/网络互相干扰。

```bash
kubectl apply -f scripts/d6/20-clusterservingruntime.yaml
kubectl apply -f scripts/d6/30-inferenceservice.yaml
kubectl -n kserve-test get inferenceservice qwen3-8b -w
```

预期：

```text
NAME        URL                                      READY   PREV   LATEST   ...
qwen3-8b    http://qwen3-8b.kserve-test.example.com  True    ...
```

首次会拉 storage-initializer 下载模型，5–15 分钟取决于网络/缓存。

### 8.2 访问

```bash
kubectl -n kserve get svc
# 找到 envoy-... 的 Service，port-forward 8080:80
kubectl -n kserve port-forward svc/<envoy-svc> 8080:80
SERVICE_HOSTNAME=$(kubectl -n kserve-test get inferenceservice qwen3-8b \
  -o jsonpath='{.status.url}' | cut -d/ -f3)
curl -s -H "Host: ${SERVICE_HOSTNAME}" \
  http://127.0.0.1:8080/openai/v1/chat/completions \
  -H 'Content-Type: application/json' \
  -d '{"model":"qwen3-8b","messages":[{"role":"user","content":"hello"}],"max_tokens":32}' | jq
```

> 如果 DNS 不通，用 `status.url` 的 host + port-forward；不要直接访问 ClusterIP。

### 8.3 冷启动 + benchmark

```bash
kubectl -n kserve-test delete pod -l serving.kserve.io/inferenceservice=qwen3-8b
time kubectl -n kserve-test wait --for=condition=Ready pod \
  -l serving.kserve.io/inferenceservice=qwen3-8b --timeout=15m
```

用同一个 bench 命令，把 `--base-url` 换成 KServe 的 Service/网关；保存 `results/d6/kserve-bench.json`。

### 8.4 canary

```bash
kubectl apply -f scripts/d6/40-canary.yaml
kubectl -n kserve-test get inferenceservice qwen3-8b
kubectl -n kserve-test get deploy
```

> Standard mode 没有 Knative `Revision` 对象；canary 的 PREV/LATEST 看 `InferenceService` status 列，底层是两个 Deployment。不要用 `kubectl get revisions`（那是 Serverless/Knative）。
>
> canary 会额外占 1 张 GPU：2×3060 才能同时跑 stable + canary；1×4090 上把 `trafficPercent` 设 0 做 dark launch，或跳过 canary。

观察：

- `spec.canary[].trafficPercent: 10`；
- `qwen3-8b-predictor` 和 `qwen3-8b-canary-predictor` 两个 Deployment 都在；
- 用 10–20 个请求看是否大约 1–2 个命中 canary（不要用 2 个请求下结论）。

### 8.5 HPA / 扩缩

```bash
kubectl -n kserve-test get hpa
kubectl -n kserve-test describe hpa -l serving.kserve.io/inferenceservice=qwen3-8b
```

> `30-inferenceservice.yaml` 已带 `serving.kserve.io/autoscalerClass: hpa`；Standard mode 默认就是 HPA，但显式写出来更好讲。

Standard mode 默认 HPA 按 CPU；LLM 更合理的是 KEDA/Prometheus 按 `vllm:num_requests_waiting`。D6 只验证 1→2 的机制；不要用 CPU HPA 得出“LLM 该这么扩”的结论。

### 8.6 scale-to-zero

**Standard mode 不支持 HTTP 0→1。** 如果你要测：

1. 另装 Knative/Serverless（`./hack/kserve-install.sh --serverless ...`），30–45 min；
2. 或只讲结论：LLM 冷启动 = 权重加载 + KV cache 重建，生产用 `minReplicas >= 1`。

### 8.7 可选：LocalModelCache

```yaml
apiVersion: serving.kserve.io/v1alpha1
kind: LocalModelCache
metadata:
  name: qwen3-8b
spec:
  sourceModelUri: hf://Qwen/Qwen3-8B-AWQ
  modelSize: 10Gi
  nodeGroups: [workers]
```

> `nodeGroups` 必须匹配已存在的 `LocalModelNodeGroup`；这是 optional，D6 核心不验收。没有 group 就跳过，别让 optional 卡住主线。

需要 `localmodel` 组件：

```bash
./hack/kserve-install.sh --kserve-version v0.21.0 --standard --type localmodel
```

对比“第二次 Pod 启动是否还下载模型”。D3 已做过 initContainer vs node-local PV；这里是 KServe 原生版。

---

## 9. Lab 4：推理可观测性（D6b）

> 原 D7/D4.7 的内容合并到这里。**不重跑 D4**；如果只看 KServe，观测对象是 `InferenceService` + vLLM + Envoy；如果要看 EPP，复用 D4 的 manifest 跑 10 分钟负载。

### 9.1 监控栈

优先复用 D3 的 Prometheus/Grafana。没有就装：

```bash
helm repo add prometheus-community https://prometheus-community.github.io/helm-charts
helm install monitoring prometheus-community/kube-prometheus-stack \
  -n monitoring --create-namespace

helm repo add gpu-helm-charts https://nvidia.github.io/dcgm-exporter/helm-charts
helm install dcgm-exporter gpu-helm-charts/dcgm-exporter -n monitoring
```

确认：

```bash
kubectl -n monitoring get pods | grep -E 'prometheus|grafana|dcgm'
kubectl -n monitoring port-forward svc/monitoring-grafana 3000:80
```

### 9.2 vLLM PodMonitor

```bash
kubectl apply -f scripts/d6/60-podmonitor.yaml
```

如果 Prometheus 没选 `release: monitoring`，改 label 或：

```bash
kubectl -n monitoring get prometheus -o yaml | grep -A5 podMonitorSelector
```

在 Prometheus UI 确认 `vllm:time_to_first_token_seconds_bucket` 有数据。

### 9.3 指标语义

| 指标 | 回答 | 注意 |
|---|---|---|
| `vllm:time_to_first_token_seconds` | 排队 + prefill + 首 token | 客户端 TTFT 还含网关/网络 |
| `vllm:time_per_output_token_seconds` | decode 速度 | 平均会掩盖长尾 |
| `vllm:e2e_request_latency_seconds` | 端到端 | 流式/非流式口径不同 |
| `vllm:num_requests_running` | 正在 decode 的序列 | 接近 `max_num_seqs` 说明 batch 满 |
| `vllm:num_requests_waiting` | 排队 | 比 RPS 更适合 HPA |
| `vllm:gpu_cache_usage_perc` | KV 块使用率 | 不是 GPU util |
| `vllm:cpu_cache_usage_perc` | CPU tier | D4.6 的 tiered KV |
| `vllm:num_preemptions_total` | KV 压力 | 增长说明序列被换出/重算 |
| prefix cache hit/query | 前缀复用 | 名字随版本变 |
| `DCGM_FI_DEV_GPU_UTIL` | kernel 活跃时间 | decode 可能低 util 但 KV 满 |
| `DCGM_FI_DEV_XID_ERRORS` | 硬件/驱动错误 | 出现即 critical |

PromQL 和 dashboard 面板见 `scripts/d6/63-dashboard-queries.md`。

### 9.4 OTel trace

装 Collector：

```bash
kubectl apply -f scripts/d6/62-otel-collector.yaml
kubectl -n monitoring rollout status deploy/otel-collector
```

让 vLLM 发 trace（custom runtime 的 args 加）：

```yaml
- --otlp-traces-endpoint=http://otel-collector.monitoring.svc:4317
```

> flag 以 `vllm serve --help | grep otlp` 为准；不同版本可能还要 `--collect-detailed-traces`。

期望一条 trace：

```text
POST /v1/chat/completions
  └─ vllm.generate
       ├─ queue
       ├─ prefill (TTFT)
       └─ decode (TPOT)
```

OTel GenAI 属性：`gen_ai.system`、`gen_ai.request.model`、`gen_ai.usage.input_tokens`、`gen_ai.usage.output_tokens`、`gen_ai.response.finish_reasons`。

如果要做 `gateway → EPP → vLLM`：

1. 复用 D4 的 `scripts/d4/`，起 EPP + vLLM；
2. Envoy/Gateway 开 OTel tracing，Collector 收 OTLP；
3. 把 D4 的 10 分钟 workload 跑一遍；
4. 保存 `results/d6/trace-epp.json`。

**不要为了 trace 重跑 D4 的 4h 对比。**

### 9.5 告警

```bash
kubectl apply -f scripts/d6/61-prometheusrule.yaml
kubectl -n monitoring get prometheusrule d6-inference-slo
```

至少验证一条：

- TTFT P99 > 2s 持续 10m；
- KV > 90% 持续 10m；
- waiting > 10；
- preemption > 0；
- GPU XID > 0。

### 9.6 game day

```bash
# 1) kill 一个 vLLM pod，观察 5xx / 恢复时间
kubectl -n kserve-test delete pod -l serving.kserve.io/inferenceservice=qwen3-8b

# 2) 如果装了 LLMInferenceService/EPP，kill EPP，观察路由/队列
# 3) 记录时间线：t0 故障、t1 告警、t2 恢复
```

保存 `results/d6/game-day.md`。

### 9.7 常见坑

| 现象 | 原因 | 处理 |
|---|---|---|
| 没有 vLLM 指标 | PodMonitor selector/port 不匹配 | `kubectl get pod --show-labels`；确认 port 名 `http` |
| 有指标但 dashboard 空 | PromQL 指标名/标签不对 | 在 Prometheus UI 先查原始序列 |
| GPU 指标缺失 | DCGM exporter 没跑/没权限 | `kubectl -n monitoring logs ds/dcgm-exporter` |
| trace 为空 | vLLM 没开 OTLP 或 Collector 地址错 | 看 vLLM 启动日志和 Collector debug |
| 告警不触发 | `for` 太长/阈值不合适 | 先用手动查询验证表达式 |
| 高基数慢查询 | 用 request_id/prompt 做 label | 只保留 model/tenant/status 等低基数标签 |

---

## 10. 可选 Lab 5：LLMInferenceService + llm-d

时间：+1.5h；不进入 D6 验收。

```bash
./hack/kserve-install.sh \
  --kserve-version v0.21.0 \
  --standard \
  --type llmisvc

kubectl apply -f scripts/d6/50-llminferenceservice.yaml
kubectl -n kserve-test get llminferenceservice
kubectl -n kserve-test get deploy,svc,gateway,httproute,inferencepool
```

观察 KServe 生成的：

- vLLM worker Deployment；
- Gateway / HTTPRoute；
- InferencePool；
- EPP（Endpoint Picker）。

结论：**`LLMInferenceService` 不是“另一个 vLLM”，它把 llm-d/GIE/EPP 组合成一个 CRD。** 如果只看单模型高吞吐，`InferenceService` + vLLM 就够了；要多模型/prefix 感知/PD，再看 LLMISvc。

---

## 11. 故障与排障

| 现象 | 可能原因 | 排查 |
|---|---|---|
| `InferenceService` READY=False | cert-manager/Gateway/storage initializer | `kubectl describe isvc`，看 Events |
| `/mnt/models` 不存在 | 建在 `kserve` 控制面 namespace | 换 `kserve-test` |
| 401 / gated model | HF token 未配 | `hf-secret` + `ClusterStorageContainer` |
| `ImagePullBackOff` | 镜像/网络/凭据 | `kubectl describe pod` |
| `Insufficient nvidia.com/gpu` | 两张卡被占 | 顺序跑；删 raw/ISVC |
| HPA 不扩 | metrics-server/CPU 指标/上限 | `kubectl describe hpa` |
| canary 没流量 | 没有 canary entry / 比例太小 | 确认 `spec.canary` 已生效；多发请求；检查 HTTPRoute 权重 |
| Gateway 502 | Envoy/Gateway 未 Ready / Host 错 | `kubectl -n kserve get gateway,svc` |
| PodMonitor 不生效 | label/port/namespaceSelector | 对照 Prometheus 配置 |
| OTel 无 trace | flag/endpoint/采样 | vLLM 日志 + Collector debug |

---

## 12. 成本、清理、验收

### 12.1 成本

| 项 | 金额 |
|---|---|
| 2×3060 5–6h | `$1.31–1.57` |
| buffer | `$0.20` |
| 合计 | **≈ `$1.5–1.8`** |

实际账单写 `results/d6/cost.txt`。

### 12.2 清理

```bash
kubectl delete -f scripts/d6/50-llminferenceservice.yaml --ignore-not-found
kubectl delete -f scripts/d6/30-inferenceservice.yaml --ignore-not-found
kubectl delete -f scripts/d6/10-raw-vllm.yaml --ignore-not-found
kubectl delete -f scripts/d6/40-canary.yaml --ignore-not-found
kubectl delete -f scripts/d6/00-namespace.yaml --ignore-not-found

# KServe 卸载（脚本会处理依赖；按需保留 cert-manager/Envoy）
cd kserve
./hack/kserve-install.sh --uninstall

# 监控栈按需删
helm uninstall monitoring -n monitoring
helm uninstall dcgm-exporter -n monitoring
```

VM 先 `scp` 结果回本地并 push，再 Destroy。

### 12.3 结果目录

```text
results/d6/
  summary.md
  cold-start.csv
  raw-bench.json
  kserve-bench.json
  dashboard.png
  trace.json
  alerts.txt
  game-day.md
  cost.txt
```

### 12.4 验收清单

- [ ] `InferenceService` READY=True；
- [ ] raw vs KServe 冷启动表（4 个阶段）；
- [ ] 同一 workload 的 raw/KServe benchmark；
- [ ] canary 10%（stable + canary Deployment）；
- [ ] HPA 1→2（或说明 Standard HPA 的限制）；
- [ ] dashboard 截图（TTFT/TPOT/KV/GPU）；
- [ ] 1 条 OTel trace；
- [ ] 1 条告警触发/恢复；
- [ ] game day 时间线；
- [ ] `cost.txt`；
- [ ] 一句话结论。

---

## 13. 面试问答（D6 版）

**Q1：KServe 和 raw Deployment 有什么区别？**

> raw 只有 Deployment/Service；KServe 多了模型 CRD、runtime 抽象、storage initializer、revision、canary、HPA、Gateway/Ingress。它不提升单请求性能，提升的是交付/运维抽象。

**Q2：KServe 和 llm-d 是什么关系？**

> KServe 是 serving 控制面；llm-d/EPP 是下面的推理感知路由层。`InferenceService` 可以只配 vLLM；`LLMInferenceService` 才会生成 Gateway/HTTPRoute/InferencePool/EPP。

**Q3：`InferenceService` 和 `LLMInferenceService` 怎么选？**

> 单模型、通用 serving、企业标准：`InferenceService`；要多模型/prefix 感知/PD/llm-d：`LLMInferenceService`。前者是后者的基础，不是替代关系。

**Q4：Standard 和 Serverless 怎么选？**

> LLM 选 Standard：Deployment 可预测、没有 Knative/queue-proxy 一层；Serverless 适合短请求/CPU 模型和 scale-to-zero。Standard 不支持 HTTP 0→1。

**Q5：为什么 LLM 不适合 scale-to-zero？**

> 冷启动要拉镜像、下载权重、初始化引擎、建 KV cache、warmup；几十秒到几分钟，P99 不可接受。生产用 `minReplicas >= 1`，低峰缩到 1。

**Q6：KServe 的 HPA 该看什么指标？**

> 默认 CPU 不适合 LLM；用 KEDA/Prometheus 按 `vllm:num_requests_waiting`、KV cache 或 goodput。CPU 高不等于 GPU 忙，GPU util 也不等于 KV 满。

**Q7：canary 怎么做？**

> Standard mode 用 `spec.canary`（`predictor.name` + `trafficPercent`）；Serverless 才用 `canaryTrafficPercent`。用模型版本、TTFT/TPOT、错误率决定是否全量。

**Q8：推理 observability 和微服务 obs 差在哪？**

> 骨架一样，语义不同：TTFT/TPOT 分解、KV cache 饱和度、prefix 命中、goodput、$/1M tokens；GPU util 不是唯一饱和度，客户端/服务端 TTFT 不能混。

**Q9：怎么证明平台没被滥用？**

> D5 的 Kueue/Kyverno + D6 的 per-tenant token/成本指标；配额、拒绝日志、chargeback 三件套。

**Q10：模型版本怎么回滚？**

> KServe canary（Standard 用 `spec.canary`）+ Deployment 回滚；镜像/模型/配置都要带版本标签；回滚前先看指标和 eval，不要只看 Pod Ready。

---

## 14. 与 D1–D5 的衔接

| 文档 | 关系 |
|---|---|
| D1/D2 | TTFT/TPOT/goodput 的口径；D6 把 CSV 变成 dashboard |
| D3 | k3s/device plugin/冷启动/KEDA；D6 复用 VM 和冷启动方法 |
| D4 | EPP/llm-d 路由；D6b 的 EPP trace 复用 D4 manifest，不重跑 |
| D5 | Kueue/Kyverno 配额/准入；D6 是 serving 抽象 + 观测 |
| D6a | KServe `InferenceService`、canary、HPA、冷启动 |
| D6b | DCGM/vLLM/OTel/Grafana/SLO/game day |

**一句话串起来：**

> D3 证明“能部署”，D4 证明“路由能降 P99”，D5 证明“配额能防抢卡”，D6 证明“服务抽象能交付、指标能解释故障”。四者合起来才是 GPU 推理平台，而不是一个能跑的 Pod。

---

## 15. Sources

- KServe v0.21.0 release：<https://github.com/kserve/kserve/releases/tag/v0.21.0>
- KServe Standard 安装：<https://kserve.github.io/website/docs/admin-guide/kubernetes-deployment>
- KServe `InferenceService` + Qwen：<https://kserve.github.io/website/docs/getting-started/genai-first-isvc>
- KServe `LLMInferenceService`：<https://kserve.github.io/website/docs/model-serving/generative-inference/llmisvc/llmisvc-overview>
- KServe v0.17 LLM 发布说明：<https://kserve.github.io/website/blog/kserve-0.17-release>
- KServe v0.18 多节点/llm-d：<https://kserve.github.io/website/blog/kserve-0.18-release>
- vLLM KServe 集成：<https://docs.vllm.ai/en/stable/deployment/integrations/kserve>
- KServe LocalModelCache 示例：<https://github.com/kserve/kserve/tree/v0.21.0/docs/samples/localmodelcache>
- Gateway API Inference Extension：<https://gateway-api-inference-extension.sigs.k8s.io>
- OTel GenAI semantic conventions：<https://opentelemetry.io/docs/specs/semconv/gen-ai/>
- DCGM exporter：<https://github.com/NVIDIA/dcgm-exporter>
- Prometheus Operator PodMonitor：<https://prometheus-operator.dev/docs/operator/api/#monitoring.coreos.com/v1.PodMonitor>
- KServe 自动扩缩：<https://kserve.github.io/website/docs/model-serving/predictive-inference/autoscaling/hpa-autoscaler>
- KServe canary：<https://kserve.github.io/website/docs/model-serving/predictive-inference/rollout-strategies/canary>
