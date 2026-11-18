"""The profile gate uses all relations in the manifest to decide full visibility."""

import pytest


@pytest.mark.xfail(strict=True, raises=ImportError,
                   reason="Implement reads_all_in_full in deploy/profiles/edge/pilot.py. See test_pilot.py for the manifest contract.")
def test_full_visibility_requires_each_relation():
    from pilot import reads_all_in_full

    manifest = {"snapshots": [
        {"relation": "fruit", "role": "reader", "full": True, "complete": False},
        {"relation": "stock", "role": "inventory", "complete": True},
    ]}
    assert not reads_all_in_full(manifest, "reader")
    manifest["snapshots"].append({"relation": "stock", "role": "reader", "full": True, "complete": False})
    assert reads_all_in_full(manifest, "reader")
    assert not reads_all_in_full({"snapshots": []}, "reader")
