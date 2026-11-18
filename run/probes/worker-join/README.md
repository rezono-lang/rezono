# Flatcar worker registration

This disposable CI experiment starts a controller-only k0s cluster with no
published network ports and verifies that its node list is initially empty.
It installs Cilium with Hubble enabled. The pinned k0smotron v2.3.1 Ignition
provisioner renders the worker document from the temporary controller's
short-lived join capability and the declared worker commands. An independent
Flatcar 4757.2.3 VM receives that document at first boot.

Only the controller API can confirm success. Require an independently named
node, the worker label, Flatcar OS identity, matching kubelet version, Ready
condition and a renewed node lease. The test runner records these fields
without publishing join data. This scope covers boot and registration using
the actual Ignition renderer. Cluster API management-controller reconciliation
is outside this experiment.

The named trial PR performs the experiment once per head. Ordinary checks
validate the shell fixture. The runner removes the temporary VM, controller,
volume and machine document and restores device permissions on exit.

With `--kubevirt`, the trial binds the Ready VMI to its active launcher and
running compute container. It reads the named domain through read-only
libvirt. The active domain must use KVM, retain its UUID and numeric runtime
ID, and show increasing time for an online vCPU while running. The packaged
libvirt selects the KVM accelerator for this domain type. An unavailable
reading leaves acceleration unproven.

CirrOS independently emits a complete serial line containing its NoCloud
instance ID. The trial counts exact matches with the VMI firmware UUID and
reports only the counts and result. It checks the VMI, launcher and compute
container identities again before accepting either observation.

## Running the Ubuntu trials

Dispatch the [Ubuntu worker acceptance workflow](../../../.github/workflows/ubuntu-worker.yml) on `main`. Select `registration` for the worker identity and lease observations. Select `kubevirt` for a fresh worker, its nested guest console and the matching domain's vCPU samples. Each dispatch uses a separate GitHub-hosted runner and records observations in its job summary.

## References

- [K0smotron provisioner](https://github.com/k0sproject/k0smotron/blob/c23391b08842d8b824e40e1324267f08b923f743/internal/provisioner/ignition.go)
- [Controller-only container](https://docs.k0sproject.io/stable/k0s-in-docker/)
- [Flatcar release digest](https://stable.release.flatcar-linux.net/amd64-usr/4757.2.3/flatcar_production_qemu_image.img.bz2.DIGESTS)
- [KubeVirt NoCloud instance ID](https://github.com/kubevirt/kubevirt/blob/c3d19093f9c7b843b3879b18dc088911c081c39e/pkg/cloud-init/cloud-init.go)
- [KubeVirt serial line handling](https://github.com/kubevirt/kubevirt/blob/c3d19093f9c7b843b3879b18dc088911c081c39e/cmd/virt-tail/main.go)
- [CirrOS 0.5.2 user data](https://github.com/cirros-dev/cirros/blob/77a944c1e65f57ec145e8502eec1a02bd7e99a84/src/sbin/cirros-userdata)
- [KubeVirt launcher diagnostics](https://kubevirt.io/user-guide/debug_virt_stack/virsh-commands/)
- [KubeVirt domain naming](https://github.com/kubevirt/kubevirt/blob/c3d19093f9c7b843b3879b18dc088911c081c39e/pkg/virt-launcher/virtwrap/api/schema.go#L1533-L1538)
- [Libvirt domain statistics](https://libvirt.org/manpages/virsh.html#domstats)
- [Libvirt 11.10 accelerator selection](https://github.com/libvirt/libvirt/blob/v11.10.0/src/qemu/qemu_command.c#L7328-L7359)
- [Libvirt 12.4 accelerator selection](https://github.com/libvirt/libvirt/blob/v12.4.0/src/qemu/qemu_command.c#L7417-L7448)
