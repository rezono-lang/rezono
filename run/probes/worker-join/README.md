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

With `--kubevirt`, the trial also checks for a live KVM vCPU in the
confirmed launcher's QEMU process and rechecks the launcher identity.
CirrOS runs the NoCloud script once per instance. It reads its instance ID
and writes a complete line to the first serial port. The trial checks the line against the VMI's firmware UUID,
then checks the VMI and launcher identities again. Console diagnostics report
successful reads, lines in the last successful read and exact marker matches.

- [K0smotron provisioner](https://github.com/k0sproject/k0smotron/blob/c23391b08842d8b824e40e1324267f08b923f743/internal/provisioner/ignition.go)
- [Controller-only container](https://docs.k0sproject.io/stable/k0s-in-docker/)
- [Flatcar release digest](https://stable.release.flatcar-linux.net/amd64-usr/4757.2.3/flatcar_production_qemu_image.img.bz2.DIGESTS)
- [KubeVirt NoCloud instance ID](https://github.com/kubevirt/kubevirt/blob/c3d19093f9c7b843b3879b18dc088911c081c39e/pkg/cloud-init/cloud-init.go)
- [KubeVirt serial line handling](https://github.com/kubevirt/kubevirt/blob/c3d19093f9c7b843b3879b18dc088911c081c39e/cmd/virt-tail/main.go)
- [CirrOS 0.5.2 user data](https://github.com/cirros-dev/cirros/blob/77a944c1e65f57ec145e8502eec1a02bd7e99a84/src/sbin/cirros-userdata)
- [Linux KVM vCPU descriptor](https://github.com/gregkh/linux/blob/85d82e0d7c2dfd3e75d34f35b7ebbf41f45c9c4e/virt/kvm/kvm_main.c)
- [Linux anonymous inode name](https://github.com/gregkh/linux/blob/85d82e0d7c2dfd3e75d34f35b7ebbf41f45c9c4e/fs/anon_inodes.c)
- [KubeVirt QEMU executable names](https://github.com/kubevirt/kubevirt/blob/c3d19093f9c7b843b3879b18dc088911c081c39e/cmd/virt-launcher-monitor/virt-launcher-monitor.go)
