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
