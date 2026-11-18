#!/usr/bin/env bash
set -euo pipefail
exec > /dev/ttyS0 2>&1
export PATH=/opt/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin
stage=bootstrap
k() { /opt/bin/k0s kubectl --request-timeout=12s "$@"; }
failed() {
    echo "HOST-PROBE FAILED stage=$stage"
    k get nodes -o wide || true
    k get pods -A -o wide || true
    k get events -A --field-selector type=Warning | tail -20 || true
    echo "HOST-PROBE END failure"
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
echo "HOST-PROBE os=$ID version=$VERSION_ID kernel=$(uname -r)"
modprobe kvm_intel || modprobe kvm_amd
modprobe vhost_net
modprobe tun
test -c /dev/kvm
mkdir -p /opt/bin /var/lib/rezono-host
cd /var/lib/rezono-host
assets=$(cat /etc/rezono-probe/assets)
for f in k0s cilium.yaml kubevirt-operator.yaml kubevirt-cr.yaml vmi.yaml; do
    curl -fsS --retry 3 "$assets/$f" -o "$f"
done
sha256sum -c /etc/rezono-probe/checksums
install -m 0755 k0s /opt/bin/k0s
/opt/bin/k0s version
stage=k0s
/opt/bin/k0s install controller --single --kubelet-root-dir=/var/lib/kubelet --config=/etc/rezono-probe/k0s.yaml
systemctl start k0scontroller
wait_for 130 k get --raw=/readyz
stage=cilium
k -n kube-system apply --server-side -f cilium.yaml >/dev/null
wait_for 150 k wait node --all --for=condition=Ready --timeout=3s
k -n kube-system rollout status daemonset/cilium --timeout=100s
k -n kube-system rollout status deployment/hubble-relay --timeout=100s
stage=operator
k apply --server-side -f kubevirt-operator.yaml >/dev/null
k -n kubevirt rollout status deployment/virt-operator --timeout=150s
wait_for 80 k apply -f kubevirt-cr.yaml
stage=kubevirt
k -n kubevirt wait kubevirt/kubevirt --for=condition=Available --timeout=225s
node=$(k get nodes -o jsonpath='{.items[0].metadata.name}')
capacity=$(k get node "$node" -o jsonpath='{.status.allocatable.devices\.kubevirt\.io/kvm}')
test "${capacity:-0}" -gt 0
echo "HOST-PROBE node=$node kvm_capacity=$capacity"
stage=vmi
k apply -f vmi.yaml
k wait vmi/host-probe --for=condition=Ready --timeout=150s
test "$(k get vmi host-probe -o jsonpath='{.status.nodeName}')" = "$node"
pod=$(k get pods -l kubevirt.io/domain=host-probe -o jsonpath='{.items[0].metadata.name}')
stage=guest_boot
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
echo "HOST-PROBE guest=$(k get vmi host-probe -o jsonpath='{.metadata.uid}') phase=Running guest_login=true kvm_vcpu=true"
echo "HOST-PROBE END success"
