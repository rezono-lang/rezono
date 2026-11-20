import json
from copy import deepcopy
from hashlib import sha256

import pilot
import pytest
from pilot_sample import TRUTH
from rezono_publisher import pointers, publish, store


@pytest.fixture
def sweep(tmp_path):
    local = store.FileStore(tmp_path)
    source = [{"source_id": "rules", "position": "a" * 40}]

    def put(key, obj):
        body = obj if isinstance(obj, bytes) else json.dumps(obj).encode()
        path = tmp_path / key
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(body)
        return {"uri": local.uri(key), "sha256": sha256(body).hexdigest()}

    def manifest(obj):
        body = json.dumps(obj).encode()
        put(f"example/manifests/{obj['id']}.json", body)
        for key, data in pointers.pointers("example", "manifests", body):
            put(key, data)

    grid = {"name": "size", "kind": "item", "key": "i", "slot": "size", "min": 0, "max": 126, "step": 2, "count": 64}
    manifest({"id": "m-3", "epoch": 3, "sources": source, "checks": [{"name": "check", "status": "green", "violations": 0}],
              "compiled": [{"file": "ir/sweeps.json", **put("example/grid.json", {"sweeps": [grid]})}]})
    variants = []
    for index in range(64):
        value = str(index * 2)
        snapshot = put(f"example/cell-{index}.json", [{"key": ["i", value]}])
        obj = {"id": publish.variant_id("size", index, 4), "epoch": 4, "base_manifest": "m-3", "sources": source,
               "variant": {"sweep": "size", "index": index, "value": value},
               "snapshots": [{"relation": "item__size", "complete": True, "format": "json", **snapshot}]}
        manifest(obj)
        variants.append(obj)
    return local, manifest, put, variants


def test_private_variants_and_the_masked_gate_view(sweep):
    local, _, _, _ = sweep
    grids = pilot.checked_local_grid(local, "example", "a" * 40, 3, 64)
    cells = grids[False][0]["cells"]
    assert [c["value"] for c in cells] == [str(i * 2) for i in range(64)]
    assert all(c["checks"] == [{"name": "check", "status": "unavailable"}] for c in cells)
    seen = {"manifest": {"snapshots": [{"full": False}]}, "sweeps": grids[False]}
    pilot.check_local_sweeps("viewer", seen, grids, False)

    for link in ("manifest", "diagnosis"):
        leaked = deepcopy(seen)
        leaked["sweeps"][0]["cells"][0][link] = "v-size-00-4"
        with pytest.raises(SystemExit, match="exposes a variant"):
            pilot.check_local_sweeps("viewer", leaked, grids, False)
    with pytest.raises(SystemExit, match="exposes a variant"):
        pilot.check_local_sweeps("viewer", {**seen, "sweeps": grids[True]}, grids, False)


def test_a_role_that_reads_all_in_full_sees_each_variant_status(sweep):
    """The fixture gives `propose` every relation of the lab in full: the gate shows it the computed grid."""
    local, manifest, _, variants = sweep
    manifest({**variants[1], "checks": [{"name": "check", "status": "warning", "violations": 1}]})
    grids = pilot.checked_local_grid(local, "example", "a" * 40, 3, 64)
    cells = grids[True][0]["cells"]
    assert cells[1] == {"index": 1, "value": "2", "status": "warning", "checks": [{"name": "check", "status": "warning"}],
                        "manifest": "v-size-01-4"}
    assert all(c["status"] == "green" and c["manifest"] == publish.variant_id("size", c["index"], 4)
               for c in cells if c["index"] != 1)
    pilot.check_local_sweeps("propose", {"sweeps": grids[True]}, grids, True)

    with pytest.raises(SystemExit, match="computed sweep differs"):
        pilot.check_local_sweeps("propose", {"sweeps": grids[False]}, grids, True)
    shown = deepcopy(grids[True])
    shown[0]["cells"][1] = {"index": 1, "value": "2", "status": "not_computed"}
    with pytest.raises(SystemExit, match="computed sweep differs"):
        pilot.check_local_sweeps("propose", {"sweeps": shown}, grids, True)


@pytest.mark.parametrize("field,value", [("base_manifest", "m-2"), ("epoch", 5), ("variant", {"sweep": "size", "index": 0, "value": "2"})])
def test_variant_must_match_its_exact_base_epoch_and_cell(sweep, field, value):
    local, manifest, _, variants = sweep
    manifest({**variants[0], field: value})
    with pytest.raises(SystemExit, match="base and grid cell"):
        pilot.checked_local_grid(local, "example", "a" * 40, 3, 64)


def test_a_matching_variant_must_hold_the_swept_value(sweep):
    local, manifest, put, variants = sweep
    first = variants[0]
    first["snapshots"][0].update(put("example/cell-0.json", [{"key": ["i", "2"]}]))
    manifest(first)
    with pytest.raises(SystemExit, match="does not hold i = 0"):
        pilot.checked_local_grid(local, "example", "a" * 40, 3, 64)


def test_a_variant_pointer_must_bind_its_exact_bytes(sweep):
    local, _, put, _ = sweep
    put("example/epochs/4/manifests/v-size-00-4.json", {"sha256": "1" * 64})
    with pytest.raises(SystemExit, match="wrong manifest pointer"):
        pilot.checked_local_grid(local, "example", "a" * 40, 3, 64)


def test_generic_sweep_still_requires_computed_status():
    class FullReader:
        def get(self, path):
            assert path == "/example/v-size-00-4/snapshots/item__size"
            return [{"key": ["i", "0"]}]

    pilot.check_sweeps(FullReader(), "viewer", "example", [{"name": "size", "kind": "item", "slot": "size", "key": "i",
                 "cells": [{"status": "green", "manifest": "v-size-00-4", "value": "0"}]}])
    with pytest.raises(SystemExit, match="unavailable"):
        pilot.check_sweeps(None, "viewer", "example", [{"name": "size", "cells": [{"status": "unavailable"}]}])


def test_red_sweep_cell_requires_diagnosis_value_and_coordinates():
    pilot.check_sweeps(None, "viewer", "example", [{
        "name": "size", "kind": "item", "slot": "size", "key": "i",
        "cells": [{"status": "red", "diagnosis": "v-size-00-4", "value": "0"}],
    }])
    for bad_cell in (
        {"status": "red", "value": "0"},
        {"status": "red", "diagnosis": "", "value": "0"},
        {"status": "red", "diagnosis": 123, "value": "0"},
        {"status": "red", "diagnosis": "v-size-00-4"},
        {"status": "red", "diagnosis": "v-size-00-4", "value": 0},
    ):
        with pytest.raises(SystemExit):
            pilot.check_sweeps(None, "viewer", "example", [{
                "name": "size", "kind": "item", "slot": "size", "key": "i",
                "cells": [bad_cell],
            }])
    for missing_field in ("kind", "slot", "key"):
        sweep = {"name": "size", "kind": "item", "slot": "size", "key": "i",
                 "cells": [{"status": "red", "diagnosis": "v-size-00-4", "value": "0"}]}
        for bad_part in (None, ""):
            broken = {**sweep, missing_field: bad_part}
            with pytest.raises(SystemExit, match="kind, slot or key"):
                pilot.check_sweeps(None, "viewer", "example", [broken])


# AUD-E1: the gate shows a check's status only to a role that reads every relation in full; any other
# role gets each check as `unavailable`. The pilot decides who reads in full from the unscoped manifest in the
# store (`truth`), not from the role's own scoped snapshots.
SHOWN = [{"name": "a", "status": "green"}, {"name": "b", "status": "warning"}]
UNAVAILABLE = [{"name": "a", "status": "unavailable"}, {"name": "b", "status": "unavailable"}]


def scoped(role: str, checks: list) -> dict:
    return {"id": "m-1", "snapshots": [s for s in TRUTH["snapshots"] if s["role"] == role], "checks": checks}


def test_a_role_that_reads_in_part_sees_exactly_unavailable():
    pilot.check_statuses("propose", scoped("propose", UNAVAILABLE), TRUTH)
    # The leak AUD-E1 closed: a status of rows the role does not read; and a check left out.
    for checks in (SHOWN, [SHOWN[0], UNAVAILABLE[1]], UNAVAILABLE[:1]):
        with pytest.raises(SystemExit, match="checks"):
            pilot.check_statuses("propose", scoped("propose", checks), TRUTH)


def test_a_full_reader_sees_the_true_statuses_and_never_unavailable():
    pilot.check_statuses("auditor", scoped("auditor", SHOWN), TRUTH)
    # A gate that masks every status would pass an all-or-nothing check; against the store it does not.
    bad = [
        UNAVAILABLE,
        [SHOWN[0], UNAVAILABLE[1]],
        [{"name": "a", "status": "warning"}, {"name": "b", "status": "green"}],
        [{"name": "a", "status": "green", "violations": 0}, SHOWN[1]],
        [{"status": "green"}, SHOWN[1]],
    ]
    for checks in bad:
        with pytest.raises(SystemExit, match="checks"):
            pilot.check_statuses("auditor", scoped("auditor", checks), TRUTH)


def test_the_truth_must_be_the_same_manifest():
    with pytest.raises(SystemExit, match="checked against"):
        pilot.check_statuses("auditor", scoped("auditor", SHOWN), dict(TRUTH, id="m-0"))


def test_without_a_store_only_all_or_nothing():
    # `live` has no store: a role whose own snapshots are all full may see statuses, every role may see
    # every check unavailable, none sees a mix, a count or a status beside a part read.
    pilot.check_statuses("auditor", scoped("auditor", SHOWN), None)
    pilot.check_statuses("auditor", scoped("auditor", UNAVAILABLE), None)
    pilot.check_statuses("propose", scoped("propose", UNAVAILABLE), None)
    for role, checks in (("auditor", [SHOWN[0], UNAVAILABLE[1]]), ("propose", SHOWN),
                         ("auditor", [{"name": "a", "status": "red"}]),
                         ("auditor", [{"name": "a", "status": "green", "violations": 0}])):
        with pytest.raises(SystemExit, match="checks"):
            pilot.check_statuses(role, scoped(role, checks), None)


def test_unhashable_check_status_exits_cleanly_without_store():
    for bad_status in (["green"], {"status": "green"}):
        with pytest.raises(SystemExit, match="checks"):
            pilot.check_statuses("auditor", scoped("auditor", [{"name": "a", "status": bad_status}]), None)
