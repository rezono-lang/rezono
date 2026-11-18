"""Independent examples for decisions/publication-case-pins.md."""

import json

import pyarrow.parquet as pq
import pytest

from rezono_publication import arrow, l0
from rezono_publication.hash import hash_rows
from test_l0 import FIXTURE, merge


SCHEMA_PIN = "s-" + "37" * 32
DATASET_PIN = "d-" + "a9" * 32
IMPORT = {"pack": "regions", "schema": SCHEMA_PIN, "manifest": "m-7", "dataset": DATASET_PIN}
SCHEMA = merge(FIXTURE, {
    "imports": {"r": IMPORT},
    "kinds": {"Host": {"slots": {"zone": {"ref": "r.Zone", "card": "1", "states": ["known"]}}}},
})
TARGET = f"regions@{SCHEMA_PIN}@m-7@{DATASET_PIN}:Zone/dmz"
ROW = {"$kind": "Host", "$id": "h7", "memory_need": "1 GiB", "owner": {"$na": ""}, "tags": [],
       "zone": {"$ref": TARGET}}


def test_pinned_import_is_preserved_across_publication_forms(tmp_path):
    assert l0.read_rows(SCHEMA, [ROW]) == [ROW]
    assert hash_rows(SCHEMA, [ROW])["Host"][0]["zone"] == "dmz"
    tables = arrow.to_arrow(SCHEMA, [ROW])
    arrow.write_parquet(tables, tmp_path)
    for host in (tables["Host"], pq.read_table(tmp_path / "Host.parquet")):
        assert host.column("zone").to_pylist() == ["dmz"]
        metadata = host.schema.field("zone").metadata
        assert metadata[b"ARROW:extension:name"] == b"rezono.ref"
        assert json.loads(metadata[b"ARROW:extension:metadata"]) == {"kind": "Zone", **IMPORT}
    assert arrow.from_arrow(SCHEMA, arrow.read_parquet(tmp_path)) == [ROW]


@pytest.mark.parametrize("patch, error", [
    ({"schema": SCHEMA_PIN[:-1]}, "full schema id"),
    ({"dataset": None}, "epoch pin without hash pin"),
], ids=["S05", "P02"])
def test_invalid_import_schema(patch, error):
    with pytest.raises(l0.L0Error, match=error):
        l0.check_schema(merge(SCHEMA, {"imports": {"r": patch}}))


@pytest.mark.parametrize("target, error", [
    (TARGET.replace("regions@", "sectors@"), "pack and schema differ from the import"),
    (TARGET.replace(DATASET_PIN, "d-" + "b4" * 32), "hash pin differs from the import"),
], ids=["R13", "P04"])
def test_row_reference_must_match_the_import(target, error):
    row = {**ROW, "zone": {"$ref": target}}
    with pytest.raises(l0.L0Error, match=error):
        l0.read_rows(SCHEMA, [row])
