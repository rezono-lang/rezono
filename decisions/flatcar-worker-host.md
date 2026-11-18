# Flatcar worker bootstrap and virtualization acceptance

Use one Ignition document per Flatcar machine. Install k0s under the writable
`/opt/bin`. Keep virtual workers in a separate network zone. Use the same OS
and distribution on hosts and guests if both compatibility gates pass. Keep
Ubuntu LTS with cloud-init as the fallback trial if compatibility fails or
the bounded trial exhausts its attempts. Installation remains provisional.

## Worker boot data

k0smotron v2.3.1 supplies a Flatcar worker template selecting Butane variant
`flatcar`, version `1.1.0`. Its AWS end-to-end suite explicitly selects the
Flatcar flavor. The CI probe runs the pinned k0smotron provisioner with synthetic
worker inputs and inspects its actual Ignition bytes, including the file mode,
content, enabled bootstrap unit and k0s executable path. This tests rendering.
A joined worker additionally requires a working controller and first boot.

- [Worker template](https://github.com/k0sproject/k0smotron/blob/c23391b08842d8b824e40e1324267f08b923f743/e2e/data/infrastructure-aws/cluster-template-ignition-flatcar/k0sworkerconfigtemplate-patch.yaml)
- [End-to-end specification](https://github.com/k0sproject/k0smotron/blob/c23391b08842d8b824e40e1324267f08b923f743/e2e/ignition_provisioning_test.go)
- [Renderer](https://github.com/k0sproject/k0smotron/blob/c23391b08842d8b824e40e1324267f08b923f743/internal/provisioner/ignition.go)

## Virtualization host

The Flatcar kernel sources configure KVM for AMD and Intel, TUN and vhost-net
as modules. KubeVirt advertises host devices through virt-handler. Kernel
configuration alone cannot establish device access inside the launcher, node
readiness, or guest execution. The ordinary CI probe records runner device
access, CPU flags and the nested-virtualization module parameter in the job
summary. A missing runner capability is an infrastructure observation.

Accept the host after a disposable Flatcar node running k0s reports schedulable
KVM capacity, KubeVirt becomes available, and a virtual machine instance on
that node boots with hardware acceleration and reports guest readiness. Record
the host OS and kernel, node and guest identities, component versions and
terminal evidence. A software-emulated guest cannot satisfy this gate.

- [Flatcar x86 kernel configuration](https://github.com/flatcar/scripts/blob/8885e5327cca985240fbc412c17558682cd75cd8/sdk_container/src/third_party/coreos-overlay/sys-kernel/coreos-modules/files/amd64_defconfig-6.18)
- [Flatcar common kernel configuration](https://github.com/flatcar/scripts/blob/8885e5327cca985240fbc412c17558682cd75cd8/sdk_container/src/third_party/coreos-overlay/sys-kernel/coreos-modules/files/commonconfig-6.18)
- [KubeVirt v1.9.1 device controller](https://github.com/kubevirt/kubevirt/blob/c3d19093f9c7b843b3879b18dc088911c081c39e/pkg/virt-handler/device-manager/device_controller.go)

## Recorded outcomes

The worker probe passed against k0smotron v2.3.1. It rendered actual Ignition
bytes for synthetic worker inputs and verified the resulting file, mode,
enabled systemd unit and command. Its scope ends before controller enrollment
or a joined worker. [Worker CI evidence](https://github.com/rezono-lang/rezono/actions/runs/44209377479/job/134483638436)

The capacity probe created an empty VM with KVM API 12 and observed that KVM
can present Intel VT-x to a guest. This qualified the runner for a nested trial.
[Capacity evidence](https://github.com/rezono-lang/rezono/actions/runs/44210786049/job/134489057185)

1. All five downloads passed digest verification. Noninteractive group switching
   required a password, so QEMU never started. [First host trial](https://github.com/rezono-lang/rezono/actions/runs/44212398142/job/134494743447)
2. With temporary device access, QEMU booted Flatcar 4757.2.3 with kernel
   6.12.114-flatcar. Its Ignition unit ran, passed its KVM device check and
   requested all five staged files; the server returned HTTP 200. The last
   recorded stage was bootstrap. There was no stage marker between artifact
   retrieval and k0s API readiness. The overall deadline expired and the
   runner terminated QEMU. The log does not isolate a failing command in that
   interval. It contains no evidence of a ready node, available KubeVirt
   installation, or booted inner guest. [Second host trial](https://github.com/rezono-lang/rezono/actions/runs/44213110846/job/134496263677)

## Conditional installation choice

Select Ubuntu Server 24.04 LTS with NoCloud cloud-init as the next candidate
for a disposable trial. The exhausted Flatcar trial establishes an incomplete
acceptance result. A defect in Flatcar or KubeVirt has not been established.
Neither host choice is approved for a provider run.

For Ubuntu, attach machine-specific NoCloud user-data and instance metadata
on a local seed disk. Use the same k0s, Cilium/Hubble, KubeVirt, inner guest
and hardware-acceleration acceptance criteria. Record markers before and
after checksum validation, binary installation, service startup and API
readiness. Bound each operation and preserve its status before teardown.
A ready control plane, accelerator allocation, a guest login prompt, and
a live KVM vCPU on the inspected node must all be observed. Recheck worker
cloud-init generation independently before adopting this single-OS path.

The candidate amd64 cloud image SHA-256 is
`04e8f2461a16a44e78a370284471f29616cdd9baf1893df25807b71f985b6c94`.
The retrieved catalog SHA-256 is
`0449a33b78dddb301a3ce2b80398984bc3e1f7880e27b86a31e58bdcbd3d3816`.
Verify downloaded bytes before any future trial. This decision records the
published digest; the Ubuntu image has not been booted.
[Canonical release catalog](https://cloud-images.ubuntu.com/releases/noble/release/SHA256SUMS)
and [NoCloud source documentation](https://github.com/canonical/cloud-init/blob/9dfa068353b2d6477276ac675faf4fc5e046b5dc/doc/rtd/reference/datasources/nocloud.rst).

## Independent worker enrollment and host trials

The runner-local registration experiment passed. The controller returned an
empty node list at 02:19:54 UTC on 2026-11-18. It then observed a VM booted
with the actual k0smotron renderer output, registration at 02:20:30, and the
Ready condition set to True with reason KubeletReady at 02:21:03. The node
reported Flatcar 4757.2.3 and kubelet v1.36.6+k0s. The controller also
confirmed a non-null renewTime for that node's lease. The reported timestamps
are the job's observation times; no second lease renewal was measured.
[Live registration job at 5356874](https://github.com/rezono-lang/rezono/actions/runs/44220706584/job/134524226560)

The [offline record](../run/fixtures/registered-flatcar-worker.json) retains
the source revision, timestamps and synthetic node UID. Every ordinary PR CI
run replays the record and checks ordering, identity, readiness and lease
evidence using Python alone. The independently executable worker trial starts
a new controller and VM and obtains fresh observations from the API.
Its named trial PR invokes it; ordinary PRs do not start extra machines.
This verifies worker bootstrap using the renderer, while full management
controller reconciliation remains outside its scope.
[Worker trial source at the tested revision](https://github.com/rezono-lang/rezono/tree/5356874ff2410bda36c0f4a7b8452a2e47a53c11/run/probes/worker-join)

The independent KubeVirt trial did not start its Flatcar guest in either of
its two revised attempts. On revision 7772306 the runner package installation
expired after 120 seconds. On fc8c16e the package manager reported fetching
18.4 MB in 201 seconds; the installation deadline expired at 02:20:48 UTC
after 205 seconds. No KubeVirt availability, inner VM, or guest readiness
observation followed. The underlying reason for the transfer rate is unknown.
[First setup deadline](https://github.com/rezono-lang/rezono/actions/runs/44219541801/job/134518552353)
and [revised setup deadline](https://github.com/rezono-lang/rezono/actions/runs/44220716839/job/134524580287).

Keep the host choice provisional. A follow-up can prepare and verify the VM
tools once, then run the two independently observed guests on that prepared
runner. A reusable cache may hold verified tool packages only; every guest
starts with a fresh disk, cluster state and bootstrap material. Keep the
existing host acceptance criteria. The operator has no action for this CI
verification; the real provider run remains gated on separate approval.
[Host trial and acceptance assertions](https://github.com/rezono-lang/rezono/pull/88)

The [concluding host trial and Ubuntu decision](ubuntu-outer-worker.md) selects
the next worker image for both disposable acceptance trials and records the
remaining live evidence.
