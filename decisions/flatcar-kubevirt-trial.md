# Disposable Flatcar KubeVirt host trial

The owner can run the Flatcar KubeVirt trial workflow manually. Its temporary
k0s control plane runs in a container. A separate Flatcar VM joins it using
the worker provisioning path. Both run on the same Ubuntu runner. By default
the script stops after worker enrollment. The host workflow passes `--kubevirt`
to prepare the worker for KubeVirt and continue past enrollment. Regular PR
checks do not launch these VMs.

The trial first requires a Flatcar worker with a Ready condition and a renewed
node lease. The upstream KubeVirt v1.9.1 operator selects control-plane nodes,
so this single-worker trial explicitly places its infrastructure on the joined
worker. The host passes only when KubeVirt becomes Available, the node
advertises allocatable KVM, and a Running and Ready VMI on that node produces
a console login prompt or welcome banner with a live KVM vCPU visible in its
compute container. The console check observes boot without signing in.
The outer VM and controller are removed when the script exits.

## Observations

The first run verified Flatcar 4757.2.3 and kubelet v1.36.6+k0s on the Ready
worker and observed its lease. The operator manifest and custom resource
matched their expected digests. The deployment reported zero of two replicas
available and timed out after four minutes. Its required affinity selected
control-plane or master nodes. The disposable controller had no node object,
and the trial had enrolled only the worker. KubeVirt availability, KVM
allocation and inner guest execution were not reached.
[First job](https://github.com/rezono-lang/rezono/actions/runs/44224420177/job/134533960916)

On commit `58336e476e5d4b86df798723651150a184978620`, the second run
again observed the Ready worker with a lease. The operator rolled out.
KubeVirt reported Available, and the API, controller, handler and both
operator pods were each Ready and Running on `proof-worker`. Its allocatable
`devices.kubevirt.io/kvm` was `1k`, the Kubernetes representation of 1000
device allocations. The trial passed that value to jq's numeric parser,
which rejected it. Execution stopped before VMI creation.
[Second job](https://github.com/rezono-lang/rezono/actions/runs/44225502916/job/134537567539)

Keep the host installation provisional. The trial now uses the Kubernetes
Python client quantity parser pinned by commit and SHA-256. A future manual run should reach VMI submission,
then verify placement, Ready and Running, the CirrOS login banner, and a live
KVM vCPU. Those guest observations are still outstanding.

The subsequent trial observed two renewals of the same Lease 20.467573 seconds
apart, KubeVirt Available, 1000 allocatable KVM devices, and a Ready, Running
VMI on `proof-worker`. The domain label query then returned an empty pod list.
No console or live vCPU check ran. [Trial job](https://github.com/rezono-lang/rezono/actions/runs/44244406887/job/134599763328)

The corrected lookup uses the VMI's active pod UID for its node, the pod's
controlling VMI owner reference, namespace, node, Running phase and container
names. It checks the same identities again after observing the console and
vCPU. KubeVirt documents the active map as pod UID to node name, creates the
launcher with a VMI controller reference and creates the console logger as a
restartable sidecar.
[KubeVirt VMI status](https://github.com/kubevirt/kubevirt/blob/c3d19093f9c7b843b3879b18dc088911c081c39e/staging/src/kubevirt.io/api/core/v1/types.go#L304-L306),
[launcher template](https://github.com/kubevirt/kubevirt/blob/c3d19093f9c7b843b3879b18dc088911c081c39e/pkg/virt-controller/services/template.go#L718-L724),
[serial console sidecar](https://github.com/kubevirt/kubevirt/blob/c3d19093f9c7b843b3879b18dc088911c081c39e/pkg/virt-controller/services/serialconsolelog.go).

### Launcher identified; guest console unconfirmed

On 2026-11-18 the disposable CI worker reported Flatcar 4757.2.3, kubelet
v1.36.6+k0s and Ready with reason KubeletReady. Two samples of the same
node-owned Lease renewed at 06:39:29.411898 and 06:39:49.558801 UTC, 20.146903
seconds apart. The operator rolled out, KubeVirt became Available, and
`proof-worker` advertised 1000 allocatable KVM devices (`1k`).
[Job at revision 7496834](https://github.com/rezono-lang/rezono/actions/runs/44252183769/job/134625269003)

The API reported `host-probe` Ready and Running on that worker. Its active
launcher was `virt-launcher-host-probe-hlddd`. The probe checked the active
pod UID, the controlling VMI UID, namespace and node before it emitted the
launcher identity. The selected record retains the checked association and
the two Kubernetes renewal times separately from the job timestamps.
[Recorded observations](../run/fixtures/flatcar-kubevirt-host.json) and
[probe at the tested revision](https://github.com/rezono-lang/rezono/blob/7496834442da3995b19fde11eb9abe9c488bbba3/run/probes/worker-join/trial.sh#L209-L235)

The console check exited with status 1 at 06:43:51 UTC. The trial did not
confirm a login prompt or welcome banner. Its live KVM vCPU check and final
launcher identity recheck were never reached. The cause of the missing
console observation is unknown. Keep host acceptance open. This job measured
a disposable CI VM; provider hardware and a Flatcar inner guest remain untested.

The trial pinned k0smotron v2.3.1 at `c23391b08842d8b824e40e1324267f08b923f743`,
the worker binary at v1.36.6+k0s.0, the Cilium chart at 1.20.5, and KubeVirt
at v1.9.1. The guest image was the CirrOS container disk at
`sha256:ebdb8d8b9b480f6ee7664ed3fdde8428767664f507d98f94090edeff04d7ebf2`.
[Bootstrap inputs](https://github.com/rezono-lang/rezono/tree/7496834442da3995b19fde11eb9abe9c488bbba3/run/probes/worker-join)
and [guest manifest](https://github.com/rezono-lang/rezono/blob/7496834442da3995b19fde11eb9abe9c488bbba3/run/probes/flatcar/vmi.yaml)
