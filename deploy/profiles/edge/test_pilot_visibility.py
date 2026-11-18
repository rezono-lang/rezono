"""The profile gate uses all relations in the manifest to decide full visibility."""

from pilot import reads_all_in_full
from pilot_sample import TRUTH


def test_full_visibility_requires_each_relation():
    manifest = {"snapshots": [
        {"relation": "fruit", "role": "reader", "full": True, "complete": False},
        {"relation": "stock", "role": "inventory", "complete": True},
    ]}
    assert not reads_all_in_full(manifest, "reader")
    manifest["snapshots"].append({"relation": "stock", "role": "reader", "full": True, "complete": False})
    assert reads_all_in_full(manifest, "reader")
    assert not reads_all_in_full({"snapshots": []}, "reader")


def test_reads_all_in_full_is_decided_on_the_unscoped_manifest():
    assert reads_all_in_full(TRUTH, "auditor")
    assert not reads_all_in_full(TRUTH, "propose")
    # Its own snapshots alone look full; the store also shows `host`, which it does not read.
    assert reads_all_in_full({"snapshots": TRUTH["snapshots"][1:2]}, "auditor")
    assert not reads_all_in_full({"snapshots": TRUTH["snapshots"][1:2] + TRUTH["snapshots"][3:]}, "auditor")
    assert not reads_all_in_full({"snapshots": []}, "auditor")
