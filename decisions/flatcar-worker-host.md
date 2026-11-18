# Flatcar worker bootstrap and virtualization acceptance

Use one Ignition document per Flatcar machine. Install k0s under the writable
`/opt/bin`. Keep virtual workers in a separate network zone. Use the same OS
and distribution on hosts and guests if both compatibility gates pass. Keep
Ubuntu LTS with cloud-init as the alternative after a demonstrated
incompatibility. Missing infrastructure leaves the choice provisional.

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
