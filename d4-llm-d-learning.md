# D4 学习文档：llm-d 路由 + request-driven 0→1

> 状态：**draft（2026-11-24）**。本文件先落 D4 的 gateway / scale-to-zero 实验（Lab 0）；llm-d 的 EPP prefix-cache 路由实验后续补。
>
> 前置：D3 已完成到 §8.6；D3 §8.7 证明了 Prometheus 队列指标在 0 副本时接不住请求。本 Lab 用 KEDA HTTP Add-on 的 interceptor 补上这一层，让一个真实 HTTP 请求把 vLLM 从 0 拉到 1。
>
> 计划中的位置：`ai-cloud-native-week-plan.md` 的 D4（llm-d 日）与 Q2（Gateway/路由）。Lab 0 是 D4 的入口实验，不是 llm-d 本身。

## 1. 这个实验回答什么

D3 §8.7 的负结果：

```text
minReplicaCount: 0
  → Service 没有 endpoint
  → 直接 curl 失败
  → vLLM 没有 Pod，也没有 vllm:num_requests_waiting
  → KEDA 没有信号，0→1 不会发生
```

Lab 0 要证明：

1. **请求可以触发 0→1**：不是靠 Prometheus 队列指标，而是靠 interceptor 接住 HTTP 请求并报告并发数；
2. **请求不丢**：interceptor 在 vLLM 冷启动期间 hold 住连接，Pod Ready 后再转发；
3. **代价可量化**：从 `curl` 发出到拿到响应，主要时间仍是 vLLM 冷启动（D3 §8.6 实测约 116s）；
4. **和 Knative 的区别**：KEDA HTTP Add-on 不是 Knative，也不需要 Knative；它只是 KEDA 生态里的 interceptor + external-push scaler。

## 2. 架构

```text
curl / 业务客户端
  → Service vllm-qwen3-8b-proxy（ExternalName）
  → KEDA HTTP Add-on interceptor（keda namespace）
  → 匹配 InterceptorRoute
  → 后端 0 副本：hold request，上报 concurrency
  → KEDA ScaledObject（external-push）
  → HPA keda-hpa-vllm-http
  → Deployment vllm-qwen3-8b: 0 → 1
  → Pod Ready 后 interceptor 转发
  → vLLM 返回 /v1/models 或 /v1/completions
```

关键角色：

| 组件 | 作用 |
|---|---|
| `InterceptorRoute` | 路由规则 + 冷启动策略 + 上报给 KEDA 的 concurrency 指标 |
| `ScaledObject`（`external-push`） | 让 KEDA 用 HTTP Add-on 的 scaler，而不是 Prometheus 查询 |
| interceptor | 真正接住请求、hold 到后端 Ready，再转发 |
| `ExternalName` Service | 让业务仍用 `vllm-qwen3-8b-proxy` 这个名字，不直接依赖 `keda` namespace |

## 3. 前提

- D3 集群已跑通：k3s、NVIDIA device plugin、vLLM Deployment/Service；
- KEDA 已安装（本机 KEDA `2.21.1`）；
- vLLM 当前是 `4 CPU / 20Gi`，2 张 4090；
- D3 §8.6 的冷启动基线：HPA 决策到 Ready 约 **116s**；
- 客户端和 interceptor 的超时必须大于这个时间，否则请求在 Pod Ready 前就被切断。

> 本文按 **KEDA HTTP Add-on 0.16 / `InterceptorRoute` v1beta1** 写。0.16 里 `HTTPScaledObject` 已标记 deprecated，旧教程里的 `HTTPScaledObject` 不要照抄；安装前先确认 chart 版本和 CRD 字段。

## 4. 安装 KEDA HTTP Add-on

```bash
helm repo add kedacore https://kedacore.github.io/charts
helm repo update

# 目的：确认 chart 版本和 KEDA 2.21 兼容
helm search repo kedacore/keda-add-ons-http --versions | head

# 目的：装到 KEDA 同一个 namespace；release 名用 http-add-on
helm install http-add-on kedacore/keda-add-ons-http -n keda

kubectl -n keda get pods
```

期望看到 operator、interceptor、external scaler 三类 Pod 都是 `Running`。如果 KEDA 不在 `keda` namespace，把后面的 `keda` 全部换成实际 namespace。

验证 CRD：

```bash
kubectl get crd | grep -E 'interceptorroutes|httpscaledobjects'
kubectl explain interceptorroute.spec | head -40
```

## 5. 先停掉 D3 的队列 autoscaler

一个 Deployment 只能有一个 autoscaler；D3 的 `ScaledObject/vllm-scaler` 还在用 Prometheus 队列指标，会和 Lab 0 的 `vllm-http` 打架。

```bash
kubectl delete scaledobject vllm-scaler --ignore-not-found

# 目的：确认旧 HPA 已删除，避免两个 HPA 同时改 replicas
kubectl get hpa
# 应该看不到 keda-hpa-vllm-scaler
```

删除 ScaledObject 不会自动把 Deployment 缩到 0；先保持 1 副本，后面再手动缩。

## 6. 创建 InterceptorRoute

```bash
cat <<'EOF' | kubectl apply -f -
apiVersion: http.keda.sh/v1beta1
kind: InterceptorRoute
metadata:
  name: vllm-qwen3-8b
  namespace: default
spec:
  target:
    service: vllm-qwen3-8b
    port: 8000
  rules:
  - hosts:
    - vllm-qwen3-8b-proxy
    - vllm-qwen3-8b-proxy.default.svc.cluster.local
  scalingMetric:
    concurrency:
      targetValue: 1
  coldStart:
    maxPendingRequests: 100
  timeouts:
    readiness: 5m
    request: 5m
    responseHeader: 5m
EOF

kubectl get interceptorroute vllm-qwen3-8b
kubectl describe interceptorroute vllm-qwen3-8b
```

字段解释：

| 字段 | 值 | 意义 |
|---|---|---|
| `target.service` / `port` | `vllm-qwen3-8b` / `8000` | interceptor 最终把请求转给哪个 Service |
| `rules[].hosts` | `vllm-qwen3-8b-proxy` | 按 HTTP `Host` 匹配；客户端必须带这个 Host |
| `scalingMetric.concurrency.targetValue` | `1` | 每个副本目标 1 个并发请求；一个 pending 请求就够触发 0→1 |
| `coldStart.maxPendingRequests` | `100` | 每个 interceptor 副本最多 hold 100 个请求；超过后按 `overflow` 处理 |
| `timeouts.readiness` | `5m` | 等后端 Ready 的最长时间；必须大于 vLLM 冷启动 116s |
| `timeouts.request` | `5m` | 整个请求生命周期上限 |
| `timeouts.responseHeader` | `5m` | 后端开始响应后，等响应头的上限 |

> `readiness` 是最容易踩的坑：默认值通常只有几十秒，vLLM 冷启动 116s 会在 Pod Ready 前被 interceptor 切断，客户端看到 503。这里显式设成 `5m`。

## 7. 创建 external-push ScaledObject

先有 `InterceptorRoute`，再建 `ScaledObject`；顺序反了，KEDA 可能拿不到 metric spec，HPA 会退化成 CPU 指标。

```bash
cat <<'EOF' | kubectl apply -f -
apiVersion: keda.sh/v1alpha1
kind: ScaledObject
metadata:
  name: vllm-http
  namespace: default
spec:
  scaleTargetRef:
    name: vllm-qwen3-8b
  minReplicaCount: 0
  maxReplicaCount: 2
  cooldownPeriod: 300
  triggers:
  - type: external-push
    metadata:
      scalerAddress: keda-add-ons-http-external-scaler.keda:9090
      interceptorRoute: vllm-qwen3-8b
EOF

kubectl get scaledobject vllm-http
kubectl get hpa
```

关键字段：

| 字段 | 值 | 来源 / 意义 |
|---|---|---|
| `minReplicaCount` | `0` | 允许缩到 0；由 HTTP 请求触发 0→1 |
| `maxReplicaCount` | `2` | 本机 2 张 GPU；第三个副本会 Pending |
| `cooldownPeriod` | `300` | 无请求后等 300s 再缩到 0 |
| `triggers[].type` | `external-push` | 使用 HTTP Add-on 的 scaler，不是 Prometheus |
| `scalerAddress` | `keda-add-ons-http-external-scaler.keda:9090` | HTTP Add-on 的 external scaler gRPC 地址 |
| `interceptorRoute` | `vllm-qwen3-8b` | 必须等于 `InterceptorRoute.metadata.name` |

KEDA 会生成 `keda-hpa-vllm-http`。确认：

```bash
kubectl get scaledobject vllm-http
# READY=True
kubectl get hpa keda-hpa-vllm-http
# TARGETS 里应该出现 HTTP concurrency 指标，不是 vllm:num_requests_waiting
```

## 8. 建一个 in-cluster proxy Service

业务客户端不应该直接访问 `keda` namespace 的 interceptor；用 `ExternalName` 包一层：

```bash
cat <<'EOF' | kubectl apply -f -
apiVersion: v1
kind: Service
metadata:
  name: vllm-qwen3-8b-proxy
  namespace: default
spec:
  type: ExternalName
  externalName: keda-add-ons-http-interceptor-proxy.keda.svc.cluster.local
  ports:
  - port: 8080
EOF

kubectl get svc vllm-qwen3-8b-proxy
```

调用方使用：

```text
http://vllm-qwen3-8b-proxy:8080
```

并显式带 Host：

```text
Host: vllm-qwen3-8b-proxy
```

Host 必须匹配 §6 的 `rules[].hosts`，否则 interceptor 不会路由。

## 9. 缩到 0

```bash
kubectl get pods -l app=vllm
kubectl scale deploy vllm-qwen3-8b --replicas=0
kubectl wait --for=delete pod -l app=vllm --timeout=180s

kubectl get pods -l app=vllm
kubectl get endpoints vllm-qwen3-8b
# 期望：没有 Pod；ENDPOINTS 为 <none>
```

> `minReplicaCount: 0` 本身也会在 `cooldownPeriod` 后缩到 0；手动 `scale` 只是为了缩短等待。不要在这里直接 curl `vllm-qwen3-8b`，那样会绕过 interceptor，得到 connection refused。

## 10. 发一个请求，触发 0→1

```bash
kubectl run curl-trigger --rm -it --restart=Never \
  --image=curlimages/curl --command -- \
  curl -v -m 300 \
    -H 'Host: vllm-qwen3-8b-proxy' \
    http://vllm-qwen3-8b-proxy:8080/v1/models
```

参数解释：

- `-m 300`：客户端最多等 300s；必须大于 vLLM 冷启动 116s；
- `-H 'Host: vllm-qwen3-8b-proxy'`：匹配 `InterceptorRoute` 的 host；
- `/v1/models`：最轻的验证请求，Pod Ready 后立即返回；也可以换成 `/v1/completions`。

预期：

1. curl **不会立刻失败**，连接保持；
2. interceptor 把请求 hold 住，KEDA 从 0 拉到 1；
3. vLLM 冷启动约 116s；
4. Pod Ready 后 interceptor 转发，curl 返回 HTTP 200 和模型列表。

## 11. 观测与记录

终端 A 跑 curl，终端 B 观察：

```bash
kubectl get pods -l app=vllm -w
kubectl get hpa keda-hpa-vllm-http -w
kubectl get scaledobject vllm-http -w
kubectl get interceptorroute vllm-qwen3-8b -o yaml

# interceptor 日志：看 hold、backend ready、转发
kubectl -n keda logs deploy/keda-add-ons-http-interceptor --tail=80
```

至少记录四个时间点：

| 时间点 | 怎么取 |
|---|---|
| `t_request` | 运行 curl 的时间 |
| `t_pod_created` | `kubectl get pod -o json` 的 `metadata.creationTimestamp` |
| `t_ready` | Pod condition `Ready` 的 `lastTransitionTime` |
| `t_response` | curl 返回的时间 |

模板：

| 场景 | `t_request` | `t_pod_created` | `t_ready` | `t_response` | 总耗时 |
|---|---|---|---|---|---|
| 0→1（HTTP interceptor） | | | | | |

结论要分开写：

- **扩容机制**：请求是否被 hold、是否真的 0→1；
- **冷启动成本**：`t_ready - t_pod_created` 与 `t_ready - t_request`；
- **客户端体验**：curl 等了多久、是否 200、是否 503/超时。

## 12. 常见失败

| 现象 | 原因 | 处理 |
|---|---|---|
| curl 立刻 503 | Host 不匹配、`InterceptorRoute` 不 Ready、或 `maxPendingRequests` 太小 | `kubectl describe interceptorroute`；确认 Host；加大 `maxPendingRequests` |
| curl 30s 左右超时 | `timeouts.readiness` 还是默认值，vLLM 还没 Ready | 设 `readiness: 5m`，curl `-m 300` |
| curl 404 | 路径/Host 没匹配到路由 | 看 `rules[].hosts` 和 `paths` |
| HPA 不出现 / TARGETS 是 CPU | 先建了 ScaledObject、后建 InterceptorRoute | 删除 ScaledObject，先建 InterceptorRoute 再重建 |
| 0→1 后 Pod Pending | 2×4 CPU/20Gi 能放下；如果是 8 CPU 或显存不够 | 回到 D3 §8.3.3 的资源前提 |
| interceptor 日志报 backend timeout | `readiness`/`request` 太短，或 vLLM 启动失败 | 看 vLLM Pod 日志和 `kubectl describe pod` |

## 13. 清理与恢复 D3 队列 autoscaler

```bash
kubectl delete scaledobject vllm-http
kubectl delete interceptorroute vllm-qwen3-8b
kubectl delete svc vllm-qwen3-8b-proxy

# 恢复 1 副本
kubectl scale deploy vllm-qwen3-8b --replicas=1
kubectl rollout status deploy/vllm-qwen3-8b --timeout=15m

# 重新 apply D3 §8.3 的 ScaledObject/vllm-scaler（min=1, max=2）
```

如果不再需要 add-on：

```bash
helm uninstall http-add-on -n keda
# CRD 不会自动删；确认没有 HTTPScaledObject/InterceptorRoute 后再删
kubectl get crd | grep -E 'interceptorroutes|httpscaledobjects'
```

## 14. 这个实验的结论

- **KEDA HTTP Add-on 能做到 request-driven 0→1**：interceptor 接住请求，external-push scaler 触发 HPA，Pod Ready 后转发；
- **不需要 Knative**：Knative 是另一条完整 serverless 路线，自带 activator；两者选一条即可；
- **冷启动仍是主成本**：116s 的 vLLM 启动不会因为 interceptor 变短，只是请求不再立刻失败；
- **chat 仍然建议 `minReplicaCount: 1`**：hold 116s 对同步聊天 SLO 不可接受；scale-to-zero 适合异步/批处理，或前端明确接受等待；
- **D4 的 llm-d 是另一层**：Lab 0 解决“0 副本时请求怎么进来”，llm-d EPP 解决“多副本时请求怎么按 prefix cache 路由”；两者可以叠加，但不是同一个问题。

## 15. 参考

- KEDA HTTP Add-on 安装：<https://keda.sh/http-add-on/0.16/operations/installation/>
- Autoscale an App（InterceptorRoute + ScaledObject）：<https://keda.sh/http-add-on/0.16/user-guide/autoscale-an-app/>
- InterceptorRoute API：<https://keda.sh/http-add-on/0.16/reference/interceptorroute/>
- KEDA HTTP Add-on 架构：<https://keda.sh/http-add-on/0.16/concepts/architecture/>
