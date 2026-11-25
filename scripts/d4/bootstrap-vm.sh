#!/usr/bin/env bash
# GPU lab VM bootstrap: Ubuntu 22.04 + N GPU -> k3s + NVIDIA runtime/device plugin + Helm.
#
# 设计前提：
#   - 每天实验独立；不假设上一次的 k3s / namespace / device plugin / 镜像缓存还在。
#   - 必须在任何 apt-get 之前停掉 unattended-upgrades / apt-daily，否则 dpkg lock
#     和 NVIDIA 用户态驱动升级会让 nvidia-smi 报 driver/library mismatch。
#   - 只装环境，不下载权重、不跑 vLLM/bench、不碰共享 UAT 集群。
#
# 用法：
#   sudo bash bootstrap-vm.sh
#   sudo NAMESPACE=d4 K3S_VERSION=v1.37.2+k3s1 bash bootstrap-vm.sh
#
# 退出码：0 成功；1 一般失败；2 NVIDIA driver/library mismatch（先 reboot 再重跑）。

set -euo pipefail

NAMESPACE="${NAMESPACE:-d4}"
K3S_VERSION="${K3S_VERSION:-v1.37.2+k3s1}"
DEVICE_PLUGIN_VERSION="${DEVICE_PLUGIN_VERSION:-v0.18.0}"
CUDA_SMOKE_IMAGE="${CUDA_SMOKE_IMAGE:-nvidia/cuda:12.4.1-base-ubuntu22.04}"
EXPECTED_GPUS="${EXPECTED_GPUS:-2}"
EXPECTED_GPU_NAME="${EXPECTED_GPU_NAME:-}"
LOG_FILE="${LOG_FILE:-/var/log/d4-bootstrap.log}"
APT_LOCK_TIMEOUT="${APT_LOCK_TIMEOUT:-900}"

CURRENT_STEP="init"

usage() {
  cat <<'EOF'
GPU lab VM bootstrap (Ubuntu 22.04 + systemd + cgroup v2 + N GPU)

Usage:
  sudo bash bootstrap-vm.sh
  sudo bash bootstrap-vm.sh --help

Environment overrides:
  EXPECTED_GPUS          expected GPU count, positive integer (default: 2)
  EXPECTED_GPU_NAME      optional case-insensitive substring, e.g. "RTX 3060";
                         empty means any NVIDIA GPU (default: empty)
  NAMESPACE              Kubernetes namespace for the bench/smoke Pod (default: d4)
  K3S_VERSION            k3s version to install if k3s is absent (default: v1.37.2+k3s1)
  DEVICE_PLUGIN_VERSION  NVIDIA k8s-device-plugin version (default: v0.18.0)
  CUDA_SMOKE_IMAGE       GPU smoke-test image (default: nvidia/cuda:12.4.1-base-ubuntu22.04)
  LOG_FILE               bootstrap log path (default: /var/log/d4-bootstrap.log)
  APT_LOCK_TIMEOUT       max seconds to wait for apt/dpkg locks (default: 900)

Examples:
  sudo bash bootstrap-vm.sh
  sudo EXPECTED_GPUS=1 NAMESPACE=d1 bash bootstrap-vm.sh
  sudo EXPECTED_GPUS=4 NAMESPACE=d45 bash bootstrap-vm.sh
  sudo EXPECTED_GPUS=2 EXPECTED_GPU_NAME='RTX 3060' bash bootstrap-vm.sh

What it does:
  1. preflight: root/systemd/cgroup v2/Ubuntu 22.04
  2. stop + disable + mask unattended-upgrades / apt-daily (before any apt-get)
  3. wait for apt/dpkg locks (never deletes locks)
  4. GPU preflight (EXPECTED_GPUS, nvidia-smi) + install base packages
  5. install NVIDIA container toolkit
  6. configure standalone containerd if present; otherwise rely on k3s embedded containerd
  7. install/start k3s, copy kubeconfig, wait for node Ready
  8. verify k3s containerd config contains nvidia
  9. install NVIDIA device plugin, patch runtimeClassName, ensure RuntimeClass/nvidia
 10. install Helm if absent
 11. create namespace, check nvidia.com/gpu=EXPECTED_GPUS, run an EXPECTED_GPUS-GPU gpu-smoke Pod
 12. write ~/d4-versions.txt and print next steps

It does NOT install/upgrade the NVIDIA driver, run vLLM/bench, or reboot the VM.
EOF
}

log() {
  printf '[%s] [bootstrap] %s\n' "$(date -Is)" "$*"
}

die() {
  local msg="$1"
  local next="${2:-}"
  local code="${3:-1}"
  printf '[%s] [bootstrap] FATAL: %s\n' "$(date -Is)" "$msg" >&2
  if [[ -n "$next" ]]; then
    printf '[%s] [bootstrap] 下一步: %s\n' "$(date -Is)" "$next" >&2
  fi
  printf '[%s] [bootstrap] 日志: %s\n' "$(date -Is)" "$LOG_FILE" >&2
  exit "$code"
}

on_err() {
  local rc=$?
  printf '[%s] [bootstrap] ERROR: step "%s" failed at line %s (exit %s)\n' \
    "$(date -Is)" "$CURRENT_STEP" "$LINENO" "$rc" >&2
  printf '[%s] [bootstrap] 修复后重跑同一命令（脚本幂等）；日志: %s\n' \
    "$(date -Is)" "$LOG_FILE" >&2
}

step() {
  CURRENT_STEP="$1"
  log "===== $1 ====="
}

apt_get() {
  DEBIAN_FRONTEND=noninteractive apt-get -o DPkg::Lock::Timeout=600 "$@"
}

lock_held() {
  local f="$1"
  [[ -e "$f" ]] || return 1

  if command -v fuser >/dev/null 2>&1; then
    fuser -s "$f" >/dev/null 2>&1
    return $?
  fi
  if command -v lsof >/dev/null 2>&1; then
    lsof -- "$f" >/dev/null 2>&1
    return $?
  fi
  if command -v python3 >/dev/null 2>&1; then
    python3 - "$f" <<'PY'
import fcntl
import os
import sys

path = sys.argv[1]
try:
    fd = os.open(path, os.O_RDWR)
except OSError:
    sys.exit(1)

try:
    fcntl.lockf(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
except OSError:
    sys.exit(0)  # held by another process
else:
    fcntl.lockf(fd, fcntl.LOCK_UN)
    sys.exit(1)  # free
PY
    return $?
  fi
  return 1
}

wait_k3s_active() {
  local i
  for ((i = 0; i < 60; i++)); do
    if systemctl is-active --quiet k3s; then
      return 0
    fi
    sleep 2
  done
  return 1
}

wait_node_ready() {
  local i
  for ((i = 0; i < 90; i++)); do
    if kubectl get nodes --no-headers 2>/dev/null \
      | awk '$2 == "Ready" { found = 1 } END { exit !found }'; then
      return 0
    fi
    sleep 2
  done
  return 1
}

case "${1:-}" in
  -h | --help)
    usage
    exit 0
    ;;
  "")
    ;;
  *)
    printf 'unknown argument: %s\n' "$1" >&2
    usage >&2
    exit 64
    ;;
esac

if ! [[ "$EXPECTED_GPUS" =~ ^[1-9][0-9]*$ ]]; then
  printf 'EXPECTED_GPUS must be a positive integer, got: %s\n' "$EXPECTED_GPUS" >&2
  exit 64
fi

if [[ "$(id -u)" -ne 0 ]]; then
  printf '[bootstrap] ERROR: must run as root (id -u = %s)\n' "$(id -u)" >&2
  exit 1
fi

mkdir -p "$(dirname "$LOG_FILE")"
touch "$LOG_FILE"
exec > >(tee -a "$LOG_FILE") 2>&1

trap 'on_err' ERR

log "GPU lab VM bootstrap start (pid $$, log $LOG_FILE)"

# ---------------------------------------------------------------------------
# 1. preflight
# ---------------------------------------------------------------------------
step "1/12 preflight"

if [[ "$(ps -p 1 -o comm=)" != "systemd" ]]; then
  die "PID 1 不是 systemd（拿到的是普通容器？）" \
    "停止；用 vms_enabled=true 的 VM 重建，不要在容器里装 k3s"
fi
log "init: systemd"

if [[ ! -r /etc/os-release ]]; then
  die "读不到 /etc/os-release" "确认这是 Ubuntu 22.04 VM"
fi
# shellcheck disable=SC1091
. /etc/os-release
if [[ "${ID:-}" != "ubuntu" || "${VERSION_ID:-}" != "22.04" ]]; then
  die "只支持 Ubuntu 22.04；当前 ID=${ID:-?} VERSION_ID=${VERSION_ID:-?}" \
    "换 Ubuntu 22.04 VM，或手工按 d3-k8s-vllm-learning.md §5 适配"
fi
log "os: ${PRETTY_NAME:-Ubuntu 22.04}"

if [[ "$(stat -fc %T /sys/fs/cgroup)" != "cgroup2fs" ]]; then
  die "cgroup 不是 v2（stat -fc %T /sys/fs/cgroup = $(stat -fc %T /sys/fs/cgroup)）" \
    "换支持 cgroup v2 的 Ubuntu 22.04 VM；不要在同一台机器上硬改"
fi
log "cgroup: v2"
log "kernel: $(uname -r)"
log "disk: $(df -h / | awk 'NR==2 {print $4 " free"}')"
log "ram: $(free -g | awk 'NR==2 {print $2 " GiB"}')"

# ---------------------------------------------------------------------------
# 2. stop auto-upgrades BEFORE any apt-get
# ---------------------------------------------------------------------------
step "2/12 停自动升级（在任何 apt-get 之前）"

auto_units=(
  unattended-upgrades.service
  apt-daily.service
  apt-daily-upgrade.service
  apt-daily.timer
  apt-daily-upgrade.timer
)

for unit in "${auto_units[@]}"; do
  if systemctl cat "$unit" >/dev/null 2>&1; then
    systemctl stop "$unit" 2>/dev/null || true
    systemctl disable "$unit" 2>/dev/null || true
    systemctl mask "$unit" 2>/dev/null || true
    log "stopped/disabled/masked: $unit"
  else
    log "unit not present: $unit"
  fi
done

for unit in "${auto_units[@]}"; do
  if systemctl is-active --quiet "$unit" 2>/dev/null; then
    die "$unit 仍在 active" \
      "不要 kill -9；先 systemctl stop $unit，确认没有 dpkg/apt 在跑，再重跑"
  fi
done
log "自动升级已停用（未删除任何 lock，未 kill 进程）"

# ---------------------------------------------------------------------------
# 3. wait for apt/dpkg locks
# ---------------------------------------------------------------------------
step "3/12 等 apt/dpkg lock"

apt_locks=(
  /var/lib/dpkg/lock-frontend
  /var/lib/dpkg/lock
  /var/lib/apt/lists/lock
  /var/cache/apt/archives/lock
)

if ! command -v fuser >/dev/null 2>&1 \
  && ! command -v lsof >/dev/null 2>&1 \
  && ! command -v python3 >/dev/null 2>&1; then
  log "WARN: fuser/lsof/python3 都没有，只能用 apt DPkg::Lock::Timeout 兜底"
fi

lock_start="$(date +%s)"
while true; do
  busy_locks=()
  for lock_file in "${apt_locks[@]}"; do
    if lock_held "$lock_file"; then
      busy_locks+=("$lock_file")
    fi
  done

  if (( ${#busy_locks[@]} == 0 )); then
    log "apt/dpkg locks free"
    break
  fi

  elapsed=$(( $(date +%s) - lock_start ))
  if (( elapsed >= APT_LOCK_TIMEOUT )); then
    die "apt/dpkg lock 超过 ${APT_LOCK_TIMEOUT}s 仍未释放: ${busy_locks[*]}" \
      "不要删 lock；等 unattended-upgrade/dpkg 自己结束，或 reboot 后重跑" 1
  fi

  log "等待 apt/dpkg lock（${elapsed}s/${APT_LOCK_TIMEOUT}s）: ${busy_locks[*]}"
  sleep 5
done

# ---------------------------------------------------------------------------
# 4. GPU preflight + base packages
# ---------------------------------------------------------------------------
step "4/12 GPU preflight (${EXPECTED_GPUS} GPU) + 基础包"

if ! command -v nvidia-smi >/dev/null 2>&1; then
  die "nvidia-smi 不存在" \
    "确认这是 GPU VM；没有 GPU 就重建 VM，不要盲装 NVIDIA driver"
fi

smi_rc=0
smi_out="$(nvidia-smi 2>&1)" || smi_rc=$?

log "nvidia-smi:"
printf '%s\n' "$smi_out"

if grep -qiE 'Driver/library version mismatch|Failed to initialize NVML' <<<"$smi_out"; then
  die "nvidia-smi 报 driver/library mismatch（通常是 unattended-upgrades 先升级了用户态驱动）" \
    "先 reboot，等 nvidia-smi 正常后再重跑本脚本；不要 kill 进程、不要删 lock" 2
fi

if (( smi_rc != 0 )); then
  die "nvidia-smi 执行失败（exit ${smi_rc}）" \
    "确认 GPU 数与 EXPECTED_GPUS 一致；必要时重建，不要自动装/换 driver" 1
fi

mapfile -t gpu_names < <(nvidia-smi --query-gpu=name --format=csv,noheader)
if (( ${#gpu_names[@]} != EXPECTED_GPUS )); then
  die "nvidia-smi 看到 ${#gpu_names[@]} 张 GPU，期望 ${EXPECTED_GPUS} 张" \
    "按实验拓扑设置 EXPECTED_GPUS（当前 ${EXPECTED_GPUS}）；不要为了凑数改脚本"
fi

if [[ -n "$EXPECTED_GPU_NAME" ]]; then
  for gpu_name in "${gpu_names[@]}"; do
    if [[ "${gpu_name,,}" != *"${EXPECTED_GPU_NAME,,}"* ]]; then
      die "GPU 型号不匹配：看到 '${gpu_name}'，期望包含 '${EXPECTED_GPU_NAME}'" \
        "按实际卡型设置 EXPECTED_GPU_NAME，或留空表示任意 NVIDIA GPU"
    fi
  done
fi
log "GPU: ${gpu_names[*]}"

apt_get update

base_packages=(
  curl
  ca-certificates
  jq
  git
  gnupg
  lsb-release
  tmux
  pciutils
  python3-pip
)

missing_packages=()
for pkg in "${base_packages[@]}"; do
  if ! dpkg -s "$pkg" >/dev/null 2>&1; then
    missing_packages+=("$pkg")
  fi
done

if (( ${#missing_packages[@]} > 0 )); then
  log "安装缺失基础包: ${missing_packages[*]}"
  apt_get install -y --no-install-recommends "${missing_packages[@]}"
else
  log "基础包已安装，跳过"
fi

# ---------------------------------------------------------------------------
# 5. NVIDIA container toolkit
# ---------------------------------------------------------------------------
step "5/12 NVIDIA container toolkit"

if command -v nvidia-ctk >/dev/null 2>&1 \
  && command -v nvidia-container-runtime >/dev/null 2>&1; then
  log "toolkit 已安装: $(nvidia-ctk --version | head -1)"
else
  log "安装 nvidia-container-toolkit"
  install -d -m 0755 /usr/share/keyrings

  curl -fsSL https://nvidia.github.io/libnvidia-container/gpgkey \
    | gpg --dearmor --yes -o /usr/share/keyrings/nvidia-container-toolkit-keyring.gpg

  curl -fsSL https://nvidia.github.io/libnvidia-container/stable/deb/nvidia-container-toolkit.list \
    | sed 's#deb https://#deb [signed-by=/usr/share/keyrings/nvidia-container-toolkit-keyring.gpg] https://#g' \
    | tee /etc/apt/sources.list.d/nvidia-container-toolkit.list >/dev/null

  apt_get update
  apt_get install -y --no-install-recommends nvidia-container-toolkit
fi

nvidia-ctk --version
if ! command -v nvidia-container-runtime >/dev/null 2>&1; then
  die "nvidia-container-runtime 不在 PATH" \
    "确认 nvidia-container-toolkit 安装成功；which nvidia-container-runtime"
fi
log "nvidia-container-runtime: $(command -v nvidia-container-runtime)"

# ---------------------------------------------------------------------------
# 6. standalone containerd (if present)
# ---------------------------------------------------------------------------
step "6/12 containerd runtime"

if systemctl cat containerd.service >/dev/null 2>&1; then
  log "发现独立 containerd.service，配置 nvidia runtime"
  nvidia-ctk runtime configure --runtime=containerd
  systemctl restart containerd
  if ! systemctl is-active --quiet containerd; then
    die "containerd 重启后不是 active" \
      "systemctl status containerd; journalctl -u containerd -n 100"
  fi
  log "containerd nvidia runtime: configured"
else
  log "没有独立 containerd.service；k3s embedded containerd 会探测 nvidia-container-runtime"
fi

# ---------------------------------------------------------------------------
# 7. k3s
# ---------------------------------------------------------------------------
step "7/12 k3s"

if command -v k3s >/dev/null 2>&1; then
  installed_k3s="$(k3s --version | head -1)"
  log "k3s 已安装: $installed_k3s"
  if [[ "$installed_k3s" != *"$K3S_VERSION"* ]]; then
    log "WARN: 请求的 K3S_VERSION=$K3S_VERSION 与已安装版本不同；保持现有版本，不自动升降级"
  fi
else
  log "安装 k3s $K3S_VERSION"
  curl -sfL https://get.k3s.io \
    | INSTALL_K3S_VERSION="$K3S_VERSION" sh -s - --write-kubeconfig-mode 644
fi

systemctl enable --now k3s
if ! wait_k3s_active; then
  die "k3s 未进入 active" \
    "systemctl status k3s; journalctl -u k3s -n 100"
fi
systemctl status k3s --no-pager || true

if ! command -v kubectl >/dev/null 2>&1; then
  ln -sf "$(command -v k3s)" /usr/local/bin/kubectl
fi

install -d -m 0700 /root/.kube
cp /etc/rancher/k3s/k3s.yaml /root/.kube/config
chmod 600 /root/.kube/config
export KUBECONFIG=/root/.kube/config

kubectl get nodes -o wide || true
if ! wait_node_ready; then
  kubectl get nodes -o wide || true
  die "node 未 Ready" \
    "kubectl describe node; journalctl -u k3s -n 100"
fi
log "node Ready"

# ---------------------------------------------------------------------------
# 8. verify k3s containerd has nvidia runtime
# ---------------------------------------------------------------------------
step "8/12 验证 k3s containerd nvidia runtime"

if ! grep -q nvidia /var/lib/rancher/k3s/agent/etc/containerd/config.toml; then
  log "k3s containerd config 没有 nvidia；重启 k3s 后再查"
  systemctl restart k3s
  if ! wait_k3s_active; then
    die "重启后 k3s 未 active" "systemctl status k3s; journalctl -u k3s -n 100"
  fi
  if ! wait_node_ready; then
    die "重启后 node 未 Ready" "kubectl get nodes -o wide; journalctl -u k3s -n 100"
  fi
  if ! grep -q nvidia /var/lib/rancher/k3s/agent/etc/containerd/config.toml; then
    die "k3s containerd config 仍没有 nvidia" \
      "确认 nvidia-container-runtime 在 PATH（/usr/bin 或 /usr/local/bin），再 restart k3s"
  fi
fi
log "k3s containerd config contains nvidia"

# ---------------------------------------------------------------------------
# 9. NVIDIA device plugin + RuntimeClass
# ---------------------------------------------------------------------------
step "9/12 NVIDIA device plugin"

device_plugin_tag="$DEVICE_PLUGIN_VERSION"
if [[ "$device_plugin_tag" != v* ]]; then
  device_plugin_tag="v${device_plugin_tag}"
fi

kubectl apply -f \
  "https://raw.githubusercontent.com/NVIDIA/k8s-device-plugin/${device_plugin_tag}/deployments/static/nvidia-device-plugin.yml"

if ! kubectl get runtimeclass nvidia >/dev/null 2>&1; then
  log "RuntimeClass/nvidia 不存在，创建"
  kubectl apply -f - <<'EOF'
apiVersion: node.k8s.io/v1
kind: RuntimeClass
metadata:
  name: nvidia
handler: nvidia
EOF
fi

kubectl -n kube-system patch ds nvidia-device-plugin-daemonset --type merge \
  -p '{"spec":{"template":{"spec":{"runtimeClassName":"nvidia"}}}}'
kubectl -n kube-system rollout status ds/nvidia-device-plugin-daemonset --timeout=180s
log "device plugin Ready"

# ---------------------------------------------------------------------------
# 10. Helm
# ---------------------------------------------------------------------------
step "10/12 Helm"

if command -v helm >/dev/null 2>&1; then
  log "helm 已安装: $(helm version --short)"
else
  log "安装 Helm（get-helm-3）"
  curl -fsSL https://raw.githubusercontent.com/helm/helm/main/scripts/get-helm-3 | bash
fi
helm version --short

# ---------------------------------------------------------------------------
# 11. namespace + GPU smoke test
# ---------------------------------------------------------------------------
step "11/12 namespace + GPU smoke test"

kubectl create namespace "$NAMESPACE" --dry-run=client -o yaml | kubectl apply -f -

gpu_alloc=""
for ((i = 0; i < 60; i++)); do
  gpu_alloc="$(kubectl get node -o jsonpath='{.items[0].status.allocatable.nvidia\.com/gpu}' 2>/dev/null || true)"
  if [[ "$gpu_alloc" == "$EXPECTED_GPUS" ]]; then
    break
  fi
  sleep 3
done

if [[ "$gpu_alloc" != "$EXPECTED_GPUS" ]]; then
  kubectl get nodes -o wide || true
  kubectl -n kube-system get pods -l name=nvidia-device-plugin-ds -o wide || true
  die "nvidia.com/gpu allocatable=${gpu_alloc:-<empty>}，期望 ${EXPECTED_GPUS}" \
    "看 device plugin 日志；确认 runtimeClassName patch 生效、DS Pod Ready"
fi
log "nvidia.com/gpu allocatable=${EXPECTED_GPUS}"

kubectl delete pod -n "$NAMESPACE" gpu-smoke --ignore-not-found --wait=true --timeout=60s

overrides="$(jq -nc --arg img "$CUDA_SMOKE_IMAGE" --argjson gpus "$EXPECTED_GPUS" \
  '{apiVersion:"v1",spec:{runtimeClassName:"nvidia",containers:[{name:"gpu-smoke",image:$img,command:["bash","-c","nvidia-smi; nvidia-smi -L"],resources:{limits:{"nvidia.com/gpu":$gpus}}}]}}')"

kubectl run gpu-smoke -n "$NAMESPACE" --restart=Never \
  --image="$CUDA_SMOKE_IMAGE" --overrides="$overrides"

if ! kubectl wait --for=jsonpath='{.status.phase}'=Succeeded pod/gpu-smoke \
  -n "$NAMESPACE" --timeout=180s; then
  kubectl describe pod -n "$NAMESPACE" gpu-smoke || true
  kubectl logs -n "$NAMESPACE" gpu-smoke || true
  kubectl delete pod -n "$NAMESPACE" gpu-smoke --ignore-not-found || true
  die "gpu-smoke 没有成功" \
    "看 describe/logs；常见原因是 RuntimeClass 缺失、device plugin 未 Ready、镜像拉取失败"
fi

if ! smoke_log="$(kubectl logs -n "$NAMESPACE" gpu-smoke)"; then
  kubectl delete pod -n "$NAMESPACE" gpu-smoke --ignore-not-found || true
  die "读不到 gpu-smoke 日志" "kubectl describe pod -n $NAMESPACE gpu-smoke"
fi

log "gpu-smoke 输出:"
printf '%s\n' "$smoke_log"

gpu_lines="$(printf '%s\n' "$smoke_log" | grep -cE 'GPU [0-9]+:' || true)"
kubectl delete pod -n "$NAMESPACE" gpu-smoke --ignore-not-found || true

if [[ "$gpu_lines" != "$EXPECTED_GPUS" ]]; then
  die "gpu-smoke 看到 ${gpu_lines} 张 GPU，期望 ${EXPECTED_GPUS} 张" \
    "确认 Pod 请求了 nvidia.com/gpu=${EXPECTED_GPUS}，且 device plugin allocatable=${EXPECTED_GPUS}"
fi
log "gpu-smoke 看到 ${EXPECTED_GPUS} 张 GPU"

# ---------------------------------------------------------------------------
# 12. version record
# ---------------------------------------------------------------------------
step "12/12 版本与功耗记录"

VERSION_FILE="/root/d4-versions.txt"
cuda_version="$(nvidia-smi | grep -oE 'CUDA Version: [0-9.]+' | head -1 || true)"

{
  echo "# GPU lab VM bootstrap versions"
  echo "date: $(date -Is)"
  echo "host: $(hostname)"
  echo "os: ${PRETTY_NAME:-unknown}"
  echo "kernel: $(uname -r)"
  echo "k3s: $(k3s --version | head -1 || true)"
  echo "kubectl: $(kubectl version --client 2>/dev/null | head -1 || true)"
  echo "helm: $(helm version --short || true)"
  echo "nvidia-ctk: $(nvidia-ctk --version | head -1 || true)"
  echo "gpu:"
  nvidia-smi --query-gpu=name,memory.total,driver_version,compute_cap,power.limit --format=csv,noheader
  echo "cuda: ${cuda_version:-unknown}"
} | tee "$VERSION_FILE"

log "版本记录: $VERSION_FILE"

log "bootstrap OK"
log "下一步："
log "  1) 按 d4-llm-d-learning.md §5.2 下载 Qwen/Qwen3-4B-AWQ 到 /models/Qwen3-4B-AWQ"
log "  2) 在仓库根目录：kubectl apply -n ${NAMESPACE} -f scripts/d4/modelserver.yaml"
log "  3) 按 d4-llm-d-learning.md §5.3–§5.8 继续（router / calibration / bench）"
