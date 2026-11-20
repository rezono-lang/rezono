"""Publication boundary for `personal` slots and the `rezono:personal` check (decisions/personal-data-handling.md).

Verifies two properties on a neutral pack with a person-bearing kind (`Alpha`, carrying a `personal` slot
`display_name` with an opaque random ID and sentinel personal value) alongside a non-personal public kind (`Note`):
1. Publishing for a public role that reads only `Note` succeeds with `rezono:personal` green and zero personal
   slot values or person IDs anywhere in the public role's snapshots, witnesses, sources, form, or bundle.
2. Publishing when a public role is granted read access to the person-bearing kind is blocked by `rezono:personal`
   before anything is written to the store.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest
import yaml

pytest.importorskip("duckdb")
pytest.importorskip("rezono_compiler")

from rezono_publisher import batch, publish, store  # noqa: E402

ROOT = Path(__file__).resolve().parents[3]
MINIMAL = ROOT / "compiler" / "tests" / "fixtures" / "minimal"
ROLES = {"checker": "complete", "public": "may_read"}
TOOL_SIDECAR = {"default": {"kind": "tool", "name": "Fixture loader", "position": "run 1"}}
OPAQUE_PERSON_ID = "id-9f4c2a1e"
PERSONAL_SENTINEL = "SENTINEL-PERSONAL-NAME-42"
PUBLIC_HEADING = "public-announcement"


def _build_pack(directory: Path, access_rules: str) -> Path:
    shutil.copytree(MINIMAL, directory)
    schema_path = directory / "schema" / "minimal.yaml"
    schema = yaml.safe_load(schema_path.read_text(encoding="utf-8"))
    schema["classes"]["Alpha"]["attributes"]["display_name"] = {
        "range": "string",
        "annotations": {"personal": True},
    }
    schema["classes"]["Note"] = {
        "attributes": {
            "id": {"identifier": True},
            "heading": {"required": True},
        }
    }
    schema_path.write_text(yaml.safe_dump(schema, sort_keys=False), encoding="utf-8", newline="\n")

    labels_path = directory / "labels" / "nl.yaml"
    labels_path.write_text(
        labels_path.read_text(encoding="utf-8")
        + "alpha.display_name: persoonlijke naam\n"
        + "note: bericht\n"
        + "note.heading: kop\n",
        encoding="utf-8",
        newline="\n",
    )

    (directory / "facts").mkdir()
    (directory / "facts" / "rows.yaml").write_text(
        yaml.safe_dump(
            {
                "alpha": [
                    {
                        "id": OPAQUE_PERSON_ID,
                        "title": "record-a",
                        "size": 1,
                        "display_name": PERSONAL_SENTINEL,
                    }
                ],
                "note": [{"id": "n1", "heading": PUBLIC_HEADING}],
            },
            sort_keys=False,
        ),
        encoding="utf-8",
        newline="\n",
    )
    (directory / "facts" / "rows.sources.yaml").write_text(
        yaml.safe_dump(TOOL_SIDECAR, sort_keys=True), encoding="utf-8", newline="\n"
    )
    (directory / "rules").mkdir()
    (directory / "rules" / "access.dl").write_text(access_rules, encoding="utf-8", newline="\n")
    return directory


def _store_key(uri: str) -> str:
    return uri.split("://", 1)[1].split("/", 1)[1] if "://" in uri else uri


@pytest.mark.xfail(
    strict=True,
    raises=AssertionError,
    reason=(
        "extra: decisions/personal-data-handling.md: Waits for compiler/tests/test_personal_slots.py--"
        "test_rule_reading_personal_slot_is_refused. Then exclude `personal` slot tables from filtered/public "
        "role snapshots and publication forms, and emit the `rezono:personal` check in "
        "edge/publisher/rezono_publisher/publish.py (and checker)."
    ),
)
def test_pack_with_personal_slot_publishes_zero_personal_values_for_public_role(tmp_path: Path):
    pack_dir = _build_pack(
        tmp_path / "pack",
        '.decl may_read(role: symbol, kind: symbol, element: symbol)\n'
        'may_read("public", "note", x) :- note(x).\n',
    )
    st = store.FileStore(tmp_path / "store")
    ep = batch.epoch(pack_dir, epoch=1, knowledge_time="2026-01-01T00:00:00Z", sources=[("rules", "e1")])
    manifest = publish.publish(ep, st, ROLES, None, forms=True)

    # 1. Manifest reports rezono:personal green with 0 violations.
    assert {"name": "rezono:personal", "status": "green", "violations": 0} in manifest["checks"], manifest["checks"]

    # 2. Public role snapshots never include the personal slot table.
    public_snaps = [s for s in manifest["snapshots"] if s["role"] == "public"]
    assert all(s["relation"] != "alpha__display_name" for s in public_snaps), public_snaps

    # 3. Collect every byte served to the public role (snapshots, witnesses, fact_sources, publication form, bundle).
    public_blobs: dict[str, bytes] = {}
    for entry in public_snaps:
        key = _store_key(entry["uri"])
        public_blobs[f"snapshot:{entry['relation']}"] = st.get(key) or b""
    for section in ("witnesses", "fact_sources"):
        for entry in manifest.get(section, []):
            if entry["role"] == "public":
                key = _store_key(entry["uri"])
                public_blobs[f"{section}:{entry['role']}"] = st.get(key) or b""
    for entry in manifest.get("compiled", []):
        if entry["file"] == "bundle/schema-bundle.json":
            public_blobs["bundle"] = st.get(_store_key(entry["uri"])) or b""
    for key in st.list("minimal/m-1/public/publication/"):
        public_blobs[key] = st.get(key) or b""

    assert public_blobs, "expected published objects for public role"
    for label, data in public_blobs.items():
        assert PERSONAL_SENTINEL.encode("utf-8") not in data, f"personal slot value leaked in {label}"
        assert OPAQUE_PERSON_ID.encode("utf-8") not in data, f"person ID leaked in {label}"

    # 4. Public form contains the public Note row and omits the personal slot from its schema.
    rows_doc = json.loads(public_blobs["minimal/m-1/public/publication/rows.json"])
    assert rows_doc["$rows"] == [{"$kind": "Note", "$id": "n1", "heading": PUBLIC_HEADING}]
    schema_doc = json.loads(public_blobs["minimal/m-1/public/publication/schema.json"])
    alpha_slots = schema_doc.get("kinds", {}).get("Alpha", {}).get("slots", {})
    assert "display_name" not in alpha_slots, alpha_slots


@pytest.mark.xfail(
    strict=True,
    raises=AssertionError,
    reason=(
        "extra: decisions/personal-data-handling.md: Waits for compiler/tests/test_personal_slots.py--"
        "test_rule_reading_personal_slot_is_refused. Then enforce the `rezono:personal` check in "
        "edge/publisher/rezono_publisher/publish.py so any person ID or personal row reachable by a public role "
        "blocks publication before any object is written."
    ),
)
def test_public_role_reading_person_id_or_personal_row_is_blocked(tmp_path: Path):
    pack_dir = _build_pack(
        tmp_path / "pack",
        '.decl may_read(role: symbol, kind: symbol, element: symbol)\n'
        'may_read("public", "alpha", x) :- alpha(x).\n'
        'may_read("public", "note", x) :- note(x).\n',
    )
    st = store.FileStore(tmp_path / "store")
    ep = batch.epoch(pack_dir, epoch=1, knowledge_time="2026-01-01T00:00:00Z", sources=[("rules", "e1")])

    try:
        publish.publish(ep, st, ROLES, None, forms=True)
    except publish.Blocked as blocked:
        message = str(blocked)
        assert "rezono:personal" in message, message
        assert PERSONAL_SENTINEL not in message and OPAQUE_PERSON_ID not in message, message
        assert st.list("minimal/") == [], "blocked publication must write nothing to the store"
    else:
        raise AssertionError(
            "publishing a person-bearing kind to a public role must raise publish.Blocked with rezono:personal"
        )
