#!/usr/bin/env bash
set -Eeuo pipefail
umask 077

if (( $# > 1 )) || [[ $# == 1 && ${1:-} != --kubevirt ]]; then
    echo "usage: trial.sh [--kubevirt]" >&2
    exit 2
fi

sources=$(cd "$(dirname "$0")" && pwd)
scratch=$(mktemp -d)
name=rezono-join-${GITHUB_RUN_ID:-$$}-${GITHUB_RUN_ATTEMPT:-1}
vm_pid=
acl_changed=false
created=false
observe() {
    printf 'WORKER-PROBE %s\n' "$1"
    if [[ -n ${GITHUB_STEP_SUMMARY:-} ]]; then
        printf -- '- Worker trial: `%s`\n' "$1" >> "$GITHUB_STEP_SUMMARY"
    fi
}
cleanup() {
    if [[ -n $vm_pid ]]; then
        kill "$vm_pid" 2>/dev/null || true
        wait "$vm_pid" 2>/dev/null || true
    fi
    if $created; then docker rm -fv "$name" >/dev/null; fi
    if $acl_changed; then sudo -n setfacl --restore="$scratch/kvm.acl"; fi
    rm -rf -- "$scratch"
}
trap cleanup EXIT
trap 'exit 124' TERM INT
cd "$scratch"

control() { docker exec "$name" k0s kubectl --request-timeout=10s "$@"; }
fetch() {
    curl -fsSL --retry 2 --max-time 150 -o "$3" "$1"
    echo "$2  $3" | "${4:-sha256sum}" -c -
}
ready_api() {
    for ((i=0; i<50; i++)); do
        if control get --raw=/readyz >/dev/null 2>&1; then return 0; fi
        sleep 2
    done
    return 1
}
controller_image='docker.io/k0sproject/k0s@sha256:8ad1df78508f82b82891009bb6c75865be57cd20cfede64cd924c891a3a61b17'
source_revision=c23391b08842d8b824e40e1324267f08b923f743
observe "stage=bootstrap-inputs"
fetch 'https://stable.release.flatcar-linux.net/amd64-usr/4757.2.3/flatcar_production_qemu_image.img.bz2' \
    9a9858f45d9c00774f865f38cba856e866f937a49cebaae8a69c4849275dc347edb51499dd145a8a9ac49098ced8ff6f2b66f65242f8b85cb06910c3b9c38e4f host.img.bz2 sha512sum
fetch 'https://helm.cilium.io/cilium-1.20.5.tgz' \
    0c7592eb75179ecf46dd3ec22145916f0164c4401214ea15afb5b230b1d11a21 cilium.tgz
git init -q renderer
git -C renderer fetch -q --depth=1 https://github.com/k0sproject/k0smotron.git "$source_revision"
test "$(git -C renderer rev-parse FETCH_HEAD)" = "$source_revision"
git -C renderer checkout -q --detach FETCH_HEAD
cp "$sources/render.go" renderer/probe.go
(cd renderer && go build -mod=readonly -o "$scratch/render" probe.go)
if ! command -v qemu-system-x86_64 >/dev/null || ! command -v getfacl >/dev/null; then
    sudo -n apt-get update -qq
    sudo -n apt-get install -y -qq --no-install-recommends acl qemu-system-x86 qemu-utils
fi
bzip2 -dc host.img.bz2 > host.img
qemu-img resize host.img 20G
if [[ ! -w /dev/kvm ]]; then
    getfacl -p /dev/kvm > kvm.acl
    sudo -n setfacl -m "u:$(id -u):rw" /dev/kvm
    acl_changed=true
fi

observe "stage=isolated-control-plane"
docker create --name "$name" --read-only --tmpfs /run --tmpfs /tmp \
    -v /var/lib/k0s -v "$sources/controller.yaml:/etc/k0s/probe.yaml:ro" \
    "$controller_image" k0s controller --config=/etc/k0s/probe.yaml >/dev/null
created=true
docker start "$name" >/dev/null
ready_api
test "$(control get nodes -o json | jq '.items | length')" = 0
observe "controller_ready=true nodes_before=0"
helm template cilium cilium.tgz --namespace kube-system --kube-version 1.36.6 \
    --set operator.replicas=1 --set hubble.enabled=true --set hubble.relay.enabled=true \
    --set 'ipam.operator.clusterPoolIPv4PodCIDRList[0]=10.244.0.0/16' > cilium.yaml
docker exec -i "$name" k0s kubectl apply --server-side -f - < cilium.yaml >/dev/null
# The bootstrap capability exists only for this temporary controller. Pipe it
# directly into the renderer; the private machine document is removed on exit.
docker exec "$name" k0s token create --role worker --expiry 12m | ./render "$@" > worker.ign
observe "ignition_rendered=true"
qemu-system-x86_64 -machine q35,accel=kvm -cpu host -m 7G -smp 3 \
    -display none -monitor none -no-reboot -serial "file:$scratch/serial.log" \
    -drive "file=$scratch/host.img,if=virtio,format=qcow2" \
    -netdev user,id=net -device virtio-net-pci,netdev=net \
    -fw_cfg "name=opt/org.flatcar-linux/config,file=$scratch/worker.ign" &
vm_pid=$!
registered=false
last_stage=
deadline=$((SECONDS + 510))
while (( SECONDS < deadline )); do
    kill -0 "$vm_pid"
    if [[ -f serial.log ]]; then
        stage=$(grep -aoE 'WORKER-STAGE-(first_boot|binary_verified|worker_installed)' serial.log | tail -1 || true)
        if [[ $stage && $stage != "$last_stage" ]]; then observe "$stage"; last_stage=$stage; fi
    fi
    if control get node proof-worker -o json > node.json 2>/dev/null; then
        if ! $registered; then observe "node_registered=proof-worker"; registered=true; fi
        if jq -e 'any(.status.conditions[]; .type == "Ready" and .status == "True")' node.json >/dev/null; then
            break
        fi
    fi
    sleep 4
done
if ! $registered; then
    observe "node_registered=false"
    exit 1
fi
observe "$(jq -r '.status.conditions[] | select(.type == "Ready") | "node_condition=Ready status=\(.status) reason=\(.reason)"' node.json)"
if ! jq -e 'any(.status.conditions[]; .type == "Ready" and .status == "True")' node.json >/dev/null; then
    control -n kube-system get pods -o json |
        jq -r '.items[] | "pod=\(.metadata.name) phase=\(.status.phase) waiting=\([.status.containerStatuses[]?.state.waiting.reason // empty]|join(","))"' |
        while read -r row; do observe "$row"; done
fi
jq -e '.metadata.labels["probe.rezono.org/role"] == "joined-worker" and
    (.status.nodeInfo.osImage | contains("Flatcar")) and
    (.status.nodeInfo.kubeletVersion | startswith("v1.36.6")) and
    any(.status.conditions[]; .type == "Ready" and .status == "True")' node.json >/dev/null
# The kubelet normally heartbeats every 10 seconds. Allow two intervals.
control -n kube-node-lease get lease proof-worker -o json > first-lease.json
sleep 20
control -n kube-node-lease get lease proof-worker -o json > second-lease.json
lease_evidence=$(python3 - <<'PY'
from datetime import datetime
import json
from pathlib import Path
from uuid import UUID


def sample(lease, node):
    metadata, spec = lease["metadata"], lease["spec"]
    if (metadata["namespace"] != "kube-node-lease" or
            metadata["name"] != node["name"] or spec["holderIdentity"] != node["name"] or
            not any(owner["kind"] == "Node" and owner["apiVersion"] == "v1" and
                    owner["name"] == node["name"] and owner["uid"] == node["uid"]
                    for owner in metadata["ownerReferences"])):
        raise ValueError("lease does not belong to the Ready node")
    # Kubernetes serializes MicroTime as UTC with six fractional digits.
    renewed = datetime.strptime(spec["renewTime"], "%Y-%m-%dT%H:%M:%S.%fZ")
    return UUID(metadata["uid"]), renewed


def read(name):
    return json.loads(Path(name).read_text())


node = read("node.json")["metadata"]
uid, first = sample(read("first-lease.json"), node)
later_uid, second = sample(read("second-lease.json"), node)
if uid != later_uid or second <= first:
    raise SystemExit("expected a later renewal of the same Lease")
print(f"lease_uid={uid} renew_time_first={first.isoformat(timespec='microseconds')}Z "
      f"renew_time_second={second.isoformat(timespec='microseconds')}Z")
PY
)
observe "$lease_evidence"
observe "$(jq -r '"node=\(.metadata.name) uid=\(.metadata.uid) os=\(.status.nodeInfo.osImage) kubelet=\(.status.nodeInfo.kubeletVersion) ready=true lease=true"' node.json)"

if (( $# == 0 )); then
    exit 0
fi

fetch 'https://raw.githubusercontent.com/kubernetes-client/python/5b23a44aa06010ac6ffe423d7b0e090caf7882ff/kubernetes/utils/quantity.py' 3c568e71032e144568280cb21af64d78dc23c526f7a4e05d2e3f53cdd0315a5d quantity.py
stage=operator
diagnose() {
    local status=$?
    observe "failed_stage=$stage status=$status"
    control -n kubevirt get pods -o wide || true
    control get events -A --field-selector type=Warning -o custom-columns=Reason:.reason,Message:.message | tail -20 || true
    exit "$status"
}
trap diagnose ERR
base=https://github.com/kubevirt/kubevirt/releases/download/v1.9.1
fetch "$base/kubevirt-operator.yaml" 9ac45a436c49d32e6fc21d542bcb7600b970705297b9e6752f3ef9b0a1d292da operator.yaml
fetch "$base/kubevirt-cr.yaml" 43106136dbce3312bdbfdeae612aacafc6c12da518d233f90645b4685d84a2af cr.yaml
apply() { docker exec -i "$name" k0s kubectl apply --server-side -f - < "$1"; }
await_condition() { docker exec "$name" k0s kubectl "$@"; }
apply operator.yaml
# The disposable controller runs outside Kubernetes and has no node object.
# Place infrastructure on the only enrolled worker using its verified label.
control -n kubevirt patch deployment virt-operator --type=json -p \
    '[{"op":"replace","path":"/spec/template/spec/affinity/nodeAffinity/requiredDuringSchedulingIgnoredDuringExecution/nodeSelectorTerms","value":[{"matchExpressions":[{"key":"probe.rezono.org/role","operator":"In","values":["joined-worker"]}]}]}]'
await_condition -n kubevirt rollout status deployment/virt-operator --timeout=240s
stage=kubevirt-availability
cat >> cr.yaml <<'YAML'
  infra:
    replicas: 1
    nodePlacement:
      nodeSelector:
        probe.rezono.org/role: joined-worker
YAML
apply cr.yaml
await_condition -n kubevirt wait kubevirt/kubevirt --for=condition=Available --timeout=360s
stage=kvm-allocation
raw_capacity=$(control get node proof-worker -o json | jq -er '.status.allocatable["devices.kubevirt.io/kvm"]')
observe "node=proof-worker raw_kvm_capacity=$raw_capacity"
capacity=$(python3 "$sources/../flatcar/capacity.py" quantity.py "$raw_capacity")
observe "kubevirt_available=true node=proof-worker kvm_capacity=$capacity"
stage=guest-readiness
apply "$sources/../flatcar/vmi.yaml"
await_condition wait vmi/host-probe --for=condition=Ready --timeout=240s
control get vmi host-probe -o json | jq -e '.status.phase == "Running" and .status.nodeName == "proof-worker"'
pod=$(control get pods -l kubevirt.io/domain=host-probe -o jsonpath='{.items[0].metadata.name}')
stage=guest-console
for ((attempt=0; attempt<48; attempt++)); do
    control logs "$pod" -c guest-console-log > console.log && grep -Eq 'login:|Welcome to CirrOS' console.log && break
    sleep 2
done
grep -Eq 'login:|Welcome to CirrOS' console.log
stage=live-kvm-vcpu
control exec "$pod" -c compute -- sh -ec 'for fd in /proc/[0-9]*/fd/*; do case "$(readlink "$fd")" in *kvm-vcpu*) exit 0;; esac; done; exit 1'
observe "guest_uid=$(control get vmi host-probe -o jsonpath='{.metadata.uid}') guest_console_ready=true kvm_vcpu=true"
