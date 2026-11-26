#!/usr/bin/env bash
# D6 VM bootstrap: k3s + NVIDIA container toolkit + device plugin.
# Target: fresh Ubuntu 22.04 KVM VM with NVIDIA driver already installed.
set -euxo pipefail

K3S_VERSION="${K3S_VERSION:-v1.37.2+k3s1}"
DEVICE_PLUGIN_VERSION="${DEVICE_PLUGIN_VERSION:-v0.20.2}"

# 1. NVIDIA container toolkit
if ! command -v nvidia-container-runtime >/dev/null 2>&1; then
  curl -fsSL https://nvidia.github.io/libnvidia-container/gpgkey \
    | gpg --batch --yes --dearmor -o /usr/share/keyrings/nvidia-container-toolkit-keyring.gpg
  curl -fsSL https://nvidia.github.io/libnvidia-container/stable/deb/nvidia-container-toolkit.list \
    | sed 's#deb https://#deb [signed-by=/usr/share/keyrings/nvidia-container-toolkit-keyring.gpg] https://#g' \
    > /etc/apt/sources.list.d/nvidia-container-toolkit.list
  apt-get update
  DEBIAN_FRONTEND=noninteractive apt-get install -y nvidia-container-toolkit
fi

# 2. k3s v1.37 会自动探测 nvidia-container-runtime 并写入 nvidia runtime；
#    不要再写 config.toml.tmpl，否则 TOML 表会重复（table nvidia already exists）。
rm -f /var/lib/rancher/k3s/agent/etc/containerd/config.toml.tmpl

# 3. k3s (disable traefik/servicelb so Envoy Gateway can own 80/443)
curl -sfL https://get.k3s.io | \
  INSTALL_K3S_VERSION="${K3S_VERSION}" \
  INSTALL_K3S_EXEC="server --write-kubeconfig-mode=644 --disable=traefik --disable=servicelb --default-runtime nvidia" \
  sh - || true
systemctl restart k3s

# 4. Wait for node, label GPU, install device plugin
export KUBECONFIG=/etc/rancher/k3s/k3s.yaml
for i in $(seq 1 60); do
  kubectl get node >/dev/null 2>&1 && break
  sleep 3
done
kubectl wait --for=condition=Ready node --all --timeout=180s
kubectl label node "$(hostname)" nvidia.com/gpu.present=true --overwrite
kubectl apply -f "https://raw.githubusercontent.com/NVIDIA/k8s-device-plugin/${DEVICE_PLUGIN_VERSION}/deployments/static/nvidia-device-plugin.yml"

# 5. Wait for nvidia.com/gpu capacity
for i in $(seq 1 60); do
  cap=$(kubectl get node "$(hostname)" -o jsonpath='{.status.capacity.nvidia\.com/gpu}' 2>/dev/null || true)
  [ "${cap:-0}" -ge 1 ] && break
  sleep 3
done
kubectl get node -o wide
kubectl get node "$(hostname)" -o jsonpath='{.status.capacity.nvidia\.com/gpu}{"\n"}'
kubectl -n kube-system get pods -l name=nvidia-device-plugin-ds -o wide
