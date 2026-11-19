# Derive the run cluster's shape from observed machines

The run passes through the loop twice. After the order, addresses and disks come back as observations. From those observations the model derives which machine is a node, in which role, in which cluster, and which disk it gives to Ceph. One converter per file format turns those relations into the installation's files. This decision fixes the relations, the converters and their exact output so that each piece can be built and checked on its own. The host choice is in the [Ubuntu outer worker decision](ubuntu-outer-worker.md); nothing here depends on how the bootstrap reaches the machine.

## Disk identity

A machine reports its block devices as the JSON output of `lsblk --json --output NAME,TYPE,FSTYPE,MOUNTPOINTS` and a map from each name in `/dev/disk/by-id/` to the kernel name its link resolves to. `run/disk_observation.py:disks(lsblk_bytes, by_id) -> (boot, data)` reads both.

- Only entries of type `disk` are candidates. Partitions, LVM volumes and other children are searched recursively.
- The boot disk is the one disk with `/` among the mount points of itself or any descendant.
- The data disk is the one other disk that is free: no children, no file system type and no mount point.
  Unknown is not free: a disk counts as free only when `fstype` is present (a string or null) and `mountpoints` is present as a list. `children` may be absent, as lsblk omits it for a device without children, but when present it must be an empty list.
- Each is named by `/dev/disk/by-id/` plus the smallest link name, in code-point order, whose target is that disk itself. A link to a partition never names a disk.
- Raise `ValueError` for bytes that are not this JSON, no root disk or more than one, zero or several free disks, or a chosen disk without a link.

A provider's own disk label is not an identity: it can change between boots and does not prove that the disk is empty.

## Cluster shape

The pack `run/packs/cluster-shape` has no facts of its own. Its input records are:

| Record | Slots |
| --- | --- |
| `Cluster` | `id`, `plan_hash` |
| `Line` | `id`, `cluster`, `sku`, `role` (`controller` or `worker`), `quantity` (integer) |
| `Machine` | `id`, `plan_hash`, `sku`, `address`, `boot_disk`, `data_disk` |

A line is the cluster's demand for one SKU in one role, matching the plan line that ordered it. A machine belongs to a cluster through the plan hash it was ordered under.

A machine of the cluster's plan is *valid* when it has exactly one value for each slot, its boot and data disks differ, and neither disk identity appears on another machine of that plan. The pack derives `shape_problem(cluster, reason)` with these reasons:

| Reason | When |
| --- | --- |
| `invalid_machine` | A machine of the plan is not valid. |
| `count` | For some line, the number of valid machines of the plan with its SKU differs from its quantity. |
| `unassigned` | A valid machine of the plan has a SKU that no line of the cluster names. |
| `ambiguous_line` | Two lines of the cluster name the same SKU. |
| `no_controller` | No line of the cluster has the role `controller`. |

Only a cluster without any problem has a shape. For such a cluster the pack derives `member(cluster, machine, role)` for each valid machine, `ceph_device(cluster, machine, data_disk)` for each member, and `api_address(cluster, address)` for each controller member. A cluster with a problem derives none of the three, so no installation file can be rendered from a partial shape. Machines of other plans never contribute.

## Converters

Every converter returns UTF-8 JSON with sorted keys, the separators `,` and `:`, and one final newline. JSON is valid YAML, so each file can be read where YAML is expected. Each converter raises `ValueError` on invalid input. Identical repeated rows coalesce.

- **Node names.** The Kubernetes node name and the host name equal the machine ID, which must be a DNS-1123 label: 1 to 63 lowercase letters, digits or `-`, starting and ending with a letter or digit. `run/nocloud_meta.py:meta_data(machine_id)` returns the NoCloud meta-data `instance-id: <id>\nlocal-hostname: <id>\n`. This file is plain YAML, not JSON.
- **k0s.** `run/k0s_config.py:render(cluster, controllers)` takes `(cluster, machine, address)` rows and returns a `k0s.k0sproject.io/v1beta1` `ClusterConfig` named after the cluster. `spec.api.address` is the controller's IP address and `spec.api.sans` lists it. `spec.network.provider` is `custom`, because Cilium is installed separately. The bounded run has exactly one controller; zero or several, a row for another cluster, or an address that is not an IP address is an error.
- **Ceph.** `run/ceph_storage.py:render(cluster, namespace, image, devices)` takes `(cluster, machine, disk)` rows and returns a Rook `ceph.rook.io/v1` `CephCluster` named after the cluster in that namespace. The image must be pinned by `@sha256:` and 64 lowercase hexadecimal characters. `dataDirHostPath` is `/var/lib/rook`. The monitor count is 3 with three or more nodes and 1 otherwise, never several per node. Storage uses neither all nodes nor all devices; it lists each node once, by name in code-point order, with its one device. A device outside `/dev/disk/by-id/`, a second device on a node, one device on two nodes, an invalid node name, a row for another cluster or no rows at all is an error.

Expectations in the tests are written by hand from this decision, not from a run of the converters.

## Alternatives

Choosing controllers by sorting machine IDs would make the role depend on identifiers the provider assigns. Taking the role from the line that ordered the machine keeps it in the plan the owner approved. Letting Rook use all devices could hand the boot disk to Ceph. Rendering YAML text by hand would add a second, ambiguous encoding for the same data.
