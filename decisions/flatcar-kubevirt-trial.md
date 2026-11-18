# Disposable Flatcar KubeVirt host trial

The owner can run the Flatcar KubeVirt trial workflow manually. Its temporary
k0s control plane runs in a container. A separate Flatcar VM joins it using
the worker provisioning path. Both run on the same Ubuntu runner. Regular PR
checks do not launch these VMs.

The trial first requires a Flatcar worker with a Ready condition and a renewed
node lease. The upstream KubeVirt v1.9.1 operator selects control-plane nodes,
so this single-worker trial explicitly places its infrastructure on the joined
worker. The host passes only when KubeVirt becomes Available, the node
advertises allocatable KVM, and a Running and Ready VMI on that node produces
a guest login banner with a live KVM vCPU visible in its compute container.
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
