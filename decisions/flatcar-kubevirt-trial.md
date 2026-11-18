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
