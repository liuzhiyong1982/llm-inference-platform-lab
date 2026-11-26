# D6 scripts：KServe + 推理可观测性

配合 [`d6-kserve-observability.md`](../../d6-kserve-observability.md) 使用。D6 分两段：**D6a KServe**（3h）和 **D6b observability**（2–3h），同一台 VM。

## 版本

- KServe `v0.21.0`（K8s ≥1.32）
- k3s `v1.37.2+k3s1`
- vLLM `v0.34.0`（raw 和 custom runtime 对齐）
- 模型 `Qwen/Qwen3-8B-AWQ`
- OTel Collector `0.166.0`
- DCGM exporter `4.9.0`

## 执行顺序

```bash
# 0) 前提：k3s + NVIDIA device plugin；核心 1 卡，并行对比/canary 需 2 卡
kubectl apply -f scripts/d6/00-namespace.yaml
kubectl apply -f scripts/d6/05-models-pvc.yaml   # hostPath /workspace/models -> PVC

# 1) D6a 控制组：raw Deployment + Service
kubectl apply -f scripts/d6/10-raw-vllm.yaml
kubectl -n kserve-test rollout status deploy/vllm-raw --timeout=15m

# 单卡：跑完 raw benchmark 后先删，释放 GPU 给 ISVC；2 卡可保留做并行对比
kubectl delete -f scripts/d6/10-raw-vllm.yaml

# 2) D6a：custom runtime（与 raw 同 vLLM 镜像）
kubectl apply -f scripts/d6/20-clusterservingruntime.yaml
kubectl get clusterservingruntime kserve-vllmserver-d6

# 3) D6a：InferenceService
kubectl apply -f scripts/d6/30-inferenceservice.yaml
kubectl -n kserve-test get inferenceservice qwen3-8b -w
# READY=True 后，URL 在 status.url

# 4) D6a 可选：canary 10%
kubectl apply -f scripts/d6/40-canary.yaml
kubectl -n kserve-test get inferenceservice qwen3-8b

# 5) D6b：PodMonitor + 告警 + dashboard（需要 Prometheus Operator/Grafana）
kubectl apply -f scripts/d6/60-podmonitor.yaml
kubectl apply -f scripts/d6/61-prometheusrule.yaml
kubectl apply -f scripts/d6/64-grafana-dashboard.yaml

# 6) D6b：OTel Collector
kubectl apply -f scripts/d6/62-otel-collector.yaml

# 7) D6 可选：LLMInferenceService + llm-d
# 先安装 llmisvc controller：
#   ./hack/kserve-install.sh --kserve-version v0.21.0 --standard --type llmisvc
kubectl apply -f scripts/d6/50-llminferenceservice.yaml
```

## 访问

```bash
# raw
kubectl -n kserve-test port-forward svc/vllm-raw 8000:8000
curl -s http://127.0.0.1:8000/v1/models | jq

# KServe：直接 port-forward predictor Service（不需要 Envoy）
kubectl -n kserve-test get svc
kubectl -n kserve-test port-forward svc/qwen3-8b-predictor 8080:80
curl -s http://127.0.0.1:8080/v1/models | jq
curl -s http://127.0.0.1:8080/v1/chat/completions \
  -H 'Content-Type: application/json' \
  -d '{"model":"qwen3-8b","messages":[{"role":"user","content":"hello"}],"max_tokens":32}' | jq

# 可选：如果装了 Envoy Gateway，才用 status.url 的 Host + /openai 前缀
# kubectl get svc -A | grep -i envoy
# kubectl -n <ns> port-forward svc/<actual-envoy-svc> 8080:80
```

## 常见问题

| 现象 | 原因 | 处理 |
|---|---|---|
| `InferenceService` 一直 `False` | cert-manager / Gateway / storage initializer 未就绪 | `kubectl describe isvc`，看 Events；先确认 `kserve` pod 全 Ready |
| `No such file or directory: /mnt/models` | 把 ISVC 建在 `kserve` 控制面 namespace | 用 `kserve-test` 等业务 namespace |
| `401` / gated model | HF token 未配置 | 建 `hf-secret` + `ClusterStorageContainer`，或换公开模型 |
| `Insufficient nvidia.com/gpu` | 两张卡都被占 | 先删 raw 或 ISVC；单卡机器顺序跑 |
| storage-initializer `OOMKilled` | KServe 默认 `memoryLimit: 1Gi` | 用 PVC 直挂，或调大 `inferenceservice-config` 的 `storageInitializer.memoryLimit` |
| `exec: "python": executable file not found` | custom runtime 写了 `python`，镜像里是 `python3` | 把 `command` 改成 `python3` |
| `README` 里 `kserve-runtimes.yaml` 404 | v0.21 已改为 `kserve-cluster-resources.yaml` | 用 release 里的新文件名 |
| PodMonitor 不生效 | Prometheus 没选 `release: monitoring` | 改 label 或 Prometheus `podMonitorSelector` |
| 没有 OTel trace | vLLM 没开 OTLP 或 Collector 地址错 | 加 `--otlp-traces-endpoint`，看 Collector debug 日志 |
| `LLMInferenceService` CRD 不存在 | 没装 `llmisvc` | `./hack/kserve-install.sh --type llmisvc` |

## 注意

- **Standard mode 不支持 HTTP scale-to-zero**；要测 0→1 需装 Knative/Serverless，或在文档里只讲“LLM 不适合 scale-to-zero”。
- 不要让 raw 和 ISVC 同时抢同一张卡；2×3060 上顺序跑，或各绑一张卡。
- Standard mode 的 canary 用 `spec.canary`；`canaryTrafficPercent` 是 Knative 字段，在 Standard 会被忽略。生产要配合模型版本、指标和回滚。
- `LocalModelCache`、Dragonfly、MIG/DRA 不在 D6 核心范围，见文档 §12。
