#!/usr/bin/env bash
set -euo pipefail
exec > /dev/ttyS0 2>&1
export PATH=/opt/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin
assets=$(cat /etc/rezono-probe/assets)
observe() {
    curl --fail --silent --show-error --max-time 4 --retry 1 --data-binary "$*" "$assets/observation" >/dev/null
    echo "HOST-PROBE $*"
}
stage=bootstrap
observe "stage=$stage"
k() { /opt/bin/k0s kubectl --request-timeout=12s "$@"; }
failed() {
    observe "failed=$stage"
    systemctl show k0scontroller -p ActiveState -p SubState -p Result --value | while read -r value; do
        observe "service=$value" || true
    done
    timeout 12 /opt/bin/k0s kubectl get pods -A -o 'custom-columns=NS:.metadata.namespace,POD:.metadata.name,PHASE:.status.phase,REASON:.status.containerStatuses[*].state.waiting.reason' --no-headers |
        head -20 | while read -r ns pod phase reason; do
            observe "pod=$ns/$pod phase=$phase reason=${reason//[^a-zA-Z0-9_-]/}" || true
        done || true
    timeout 10 /opt/bin/k0s kubectl get nodes -o wide || true
    k get pods -A -o wide || true
    k get events -A --field-selector type=Warning | tail -20 || true
    observe "end=failure"
}
trap failed ERR
wait_for() {
    local seconds=$1
    shift
    local deadline=$((SECONDS + seconds))
    until "$@" >/dev/null 2>&1; do
        if (( SECONDS >= deadline )); then return 1; fi
        sleep 3
    done
}
source /etc/os-release
test "$ID" = flatcar
observe "os=$ID version=$VERSION_ID kernel=$(uname -r)"
modprobe kvm_intel || modprobe kvm_amd
modprobe vhost_net
modprobe tun
test -c /dev/kvm
mkdir -p /opt/bin /var/lib/rezono-host
cd /var/lib/rezono-host
observe "stage=local_downloads"
for f in k0s cilium.yaml kubevirt-operator.yaml kubevirt-cr.yaml vmi.yaml; do
    curl -fsS --retry 2 --max-time 45 "$assets/$f" -o "$f"
done
observe "stage=checksums"
timeout 30 sha256sum -c /etc/rezono-probe/checksums
observe "stage=binary_install"
timeout 30 install -m 0755 k0s /opt/bin/k0s
version=$(timeout 15 /opt/bin/k0s version)
observe "k0s=$version"
stage=k0s_install
observe "stage=$stage"
timeout 30 /opt/bin/k0s install controller --single --kubelet-root-dir=/var/lib/kubelet --config=/etc/rezono-probe/k0s.yaml
stage=k0s_start
observe "stage=$stage"
timeout 15 systemctl start --no-block k0scontroller
stage=k0s_api
observe "stage=$stage"
wait_for 130 k get --raw=/readyz
stage=cilium
observe "stage=$stage"
k apply --server-side -f cilium.yaml >/dev/null
wait_for 150 k wait node --all --for=condition=Ready --timeout=3s
k -n kube-system rollout status daemonset/cilium --timeout=100s
k -n kube-system rollout status deployment/hubble-relay --timeout=100s
stage=operator
observe "stage=$stage"
k apply --server-side -f kubevirt-operator.yaml >/dev/null
k -n kubevirt rollout status deployment/virt-operator --timeout=150s
wait_for 80 k apply -f kubevirt-cr.yaml
stage=kubevirt
observe "stage=$stage"
k -n kubevirt wait kubevirt/kubevirt --for=condition=Available --timeout=225s
node=$(k get nodes -o jsonpath='{.items[0].metadata.name}')
capacity=$(k get node "$node" -o jsonpath='{.status.allocatable.devices\.kubevirt\.io/kvm}')
test "${capacity:-0}" -gt 0
observe "node=$node kvm_capacity=$capacity"
stage=vmi
observe "stage=$stage"
k apply -f vmi.yaml
k wait vmi/host-probe --for=condition=Ready --timeout=150s
test "$(k get vmi host-probe -o jsonpath='{.status.nodeName}')" = "$node"
pod=$(k get pods -l kubevirt.io/domain=host-probe -o jsonpath='{.items[0].metadata.name}')
stage=guest_boot
observe "stage=$stage"
guest_ready() { k logs "$pod" -c guest-console-log | grep -E 'login:|Welcome to CirrOS' >/dev/null; }
wait_for 120 guest_ready
accelerated() {
    local entry comm fd
    for entry in /proc/[0-9]*; do
        read -r comm < "$entry/comm" 2>/dev/null || continue
        case "$comm" in qemu*|kvm*) ;; *) continue ;; esac
        for fd in "$entry"/fd/*; do
            if [[ $(readlink "$fd" 2>/dev/null) == *kvm-vcpu* ]]; then return 0; fi
        done
    done
    return 1
}
accelerated
observe "guest=$(k get vmi host-probe -o jsonpath='{.metadata.uid}') phase=Running guest_login=true kvm_vcpu=true"
observe "end=success"
