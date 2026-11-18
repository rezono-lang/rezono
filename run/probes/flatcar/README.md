# Disposable Flatcar host trial

On the dedicated trial pull request, CI boots a Flatcar 4757.2.3 QEMU image
with KVM and one Ignition file. The guest installs k0s v1.36.6+k0s.0, Cilium
1.20.5 with Hubble relay, and KubeVirt v1.9.1. The trial requires an available
operator, positive schedulable KVM capacity, a ready VMI on the inspected
node, a guest serial login prompt, and an open KVM vCPU handle belonging to
QEMU inside the Flatcar host. A capacity probe alone cannot satisfy these
conditions. A timeout or missing observation fails the trial.

The outer runner verifies artifact digests, serves files on loopback, and
destroys the temporary host and disk on exit. No cloud account or remote
cluster is used. Local validation and ordinary PRs check the input lock
without starting a machine. The active trial runs on the named PR head;
the merge-group run avoids duplicating the experiment.

Sources for the pinned inputs include the [Flatcar release digests](https://stable.release.flatcar-linux.net/amd64-usr/4757.2.3/flatcar_production_qemu_image.img.bz2.DIGESTS),
[k0s release](https://github.com/k0sproject/k0s/releases/tag/v1.36.6%2Bk0s.0),
[Cilium chart index](https://helm.cilium.io/index.yaml),
[KubeVirt release](https://github.com/kubevirt/kubevirt/releases/tag/v1.9.1)
and [upstream ephemeral guest specification](https://github.com/kubevirt/kubevirt/blob/c3d19093f9c7b843b3879b18dc088911c081c39e/examples/vmi-ephemeral.yaml).
