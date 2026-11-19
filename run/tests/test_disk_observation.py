"""Stable boot and data disk identities, from decisions/run-cluster-shape.md."""

import copy
import json

import pytest

from offline_cases import implementation


BOOT = "nvme-eui.0000000000000001"
DATA = "nvme-SAMPLE_SERIAL_B"


def observed():
    devices = {"blockdevices": [
        {"name": "loop0", "type": "loop", "fstype": "squashfs", "mountpoints": ["/snap/core/1"]},
        {"name": "nvme1n1", "type": "disk", "fstype": None, "mountpoints": [None]},
        {"name": "nvme0n1", "type": "disk", "fstype": None, "mountpoints": [None], "children": [
            {"name": "nvme0n1p1", "type": "part", "fstype": "vfat", "mountpoints": ["/boot/efi"]},
            {"name": "nvme0n1p2", "type": "part", "fstype": "ext4", "mountpoints": ["/"]},
        ]},
    ]}
    links = {f"{BOOT}-part1": "nvme0n1p1", f"{BOOT}-part2": "nvme0n1p2", BOOT: "nvme0n1",
             "nvme-eui.0000000000000002": "nvme1n1", DATA: "nvme1n1"}
    return devices, links


def encoded(devices):
    return json.dumps(devices).encode()


def test_disk_observation():
    disks = implementation("disk_observation.py", "disks")
    devices, links = observed()
    expected = (f"/dev/disk/by-id/{BOOT}", f"/dev/disk/by-id/{DATA}")
    assert disks(encoded(devices), links) == expected

    # Root on a logical volume inside a partition still marks the whole disk as boot.
    nested = copy.deepcopy(devices)
    nested["blockdevices"][2]["children"][1] = {
        "name": "nvme0n1p2", "type": "part", "fstype": "LVM2_member", "mountpoints": [None],
        "children": [{"name": "vg-root", "type": "lvm", "fstype": "ext4", "mountpoints": ["/"]}]}
    assert disks(encoded(nested), links) == expected

    def changed(edit):
        candidate = copy.deepcopy(devices)
        edit(candidate["blockdevices"])
        return encoded(candidate)

    second_free = {"name": "sda", "type": "disk", "fstype": None, "mountpoints": [None]}
    rejected = [
        changed(lambda d: d[1].update(fstype="ceph_bluestore")),
        changed(lambda d: d[1].update(mountpoints=["/srv"])),
        changed(lambda d: d[1].update(children=[{"name": "nvme1n1p1", "type": "part", "fstype": None,
                                                  "mountpoints": [None]}])),
        changed(lambda d: d.append(second_free)),
        changed(lambda d: d[2]["children"][1].update(mountpoints=["/var"])),
        changed(lambda d: d[1]["mountpoints"].__setitem__(0, "/")),
        b"not json",
    ]
    for raw in rejected:
        with pytest.raises(ValueError):
            disks(raw, links)
    # A disk is never named by a partition link, and a disk without its own link has no identity.
    for missing in (DATA, BOOT):
        partial = {name: target for name, target in links.items()
                   if target != links[missing]}
        with pytest.raises(ValueError):
            disks(encoded(devices), partial)
