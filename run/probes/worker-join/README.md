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

- [K0smotron provisioner](https://github.com/k0sproject/k0smotron/blob/c23391b08842d8b824e40e1324267f08b923f743/internal/provisioner/ignition.go)
- [Controller-only container](https://docs.k0sproject.io/stable/k0s-in-docker/)
- [Flatcar release digest](https://stable.release.flatcar-linux.net/amd64-usr/4757.2.3/flatcar_production_qemu_image.img.bz2.DIGESTS)
