"""The epoch statement names the proof of why it exists (decisions/loop-engine-epoch.md, section 4).

On the collection of l0.md section 3.1 (case R01 with the fixture schema), laid out as the publisher lays out a
role's form, with one more object: `allowed.json`, the role's proof of `publish_allowed`. The expectations are the
decision's: a form that holds it gets a version 3 statement whose `allowed` is its SHA-256, the verifier holds that
hash to the subject and the proved row to the statement's role and epoch, and a form without it is unchanged.
"""
import hashlib
import json
from pathlib import Path

import pytest
import yaml

from rezono_publication import l0
from rezono_publication import statement as st
from rezono_publication.hash import hashes

ROOT = Path(__file__).resolve().parents[2]
CASES = ROOT / "docs" / "publication" / "cases"
CONTRACT = ROOT / "contracts" / "statement.yaml"
SCHEMA = json.loads((CASES / "fixture.schema.json").read_text("utf-8"))
ROWS = yaml.safe_load((CASES / "R01.yaml").read_text("utf-8"))["input"]["$rows"]
ALLOWED = "allowed.json"


class MissingAllowedField(AssertionError):
    """The epoch statement has no version that names the proof of why it exists."""


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def proof_object(role="guest", epoch="3") -> bytes:
    """The role's allowed.json as section 4 lays it out; the proof itself is a fixed sample here."""
    document = {
        "format": "rezono.epoch-allowed/1",
        "relation": "publish_allowed",
        "row": ["epoch-3", epoch, role, f"form-{role}"],
        "proof": {"root": {"relation": "publish_allowed", "key": json.dumps(["epoch-3", epoch, role, f"form-{role}"])},
                  "manifest_id": "m-3", "witnesses": []},
        "rows": {},
        "definition": "1" * 64,
        "rules": "2" * 64,
        "engine": {"version": "0.1.0", "wheel_sha256": "3" * 64, "commit": "4" * 40},
    }
    return json.dumps(document, sort_keys=True, separators=(",", ":")).encode()


def published(allowed: bytes | None) -> tuple[bytes, dict, dict[str, bytes]]:
    """A role's form of R01 with or without allowed.json: the objects, the statement, the index naming both."""
    rows = l0.read_collection(SCHEMA, {"$schema": l0.check_schema(SCHEMA), "$rows": ROWS})
    h = hashes(SCHEMA, rows)
    objects = {
        "schema.json": json.dumps(SCHEMA, sort_keys=True, separators=(",", ":")).encode(),
        "rows.json": json.dumps({"$schema": h["schema"], "$rows": ROWS}, sort_keys=True).encode(),
        "hashes.json": json.dumps(h, sort_keys=True).encode(),
    }
    if allowed is not None:
        objects[ALLOWED] = allowed
    index = {
        "pack": "toy", "role": "guest", "schema": h["schema"], "dataset": h["dataset"],
        "manifest": {"id": "m-3", "epoch": 3, "knowledge_time": "2026-01-01T01:00:00+01:00",
                     "definition_sha256": "a" * 64,
                     "compiled": [{"file": "bundle/schema-bundle.json", "sha256": "b" * 64}], "role": "guest"},
        "sources": [{"relation": "host", "sha256": "c" * 64}, {"relation": "host__tags", "sha256": "e" * 64}],
        "objects": [{"name": n, "sha256": sha(b)} for n, b in objects.items()],
    }
    data = st.dumps(st.make(index, objects, SCHEMA, rows))
    index["objects"].append({"name": st.NAME, "sha256": sha(data)})
    return data, index, objects


@pytest.mark.xfail(
    strict=True,
    raises=MissingAllowedField,
    reason=(
        "extra: decisions/loop-engine-epoch.md: section 4. Waits for edge/publisher/tests/test_role_epoch_diffs.py--"
        "test_role_epoch_diff_is_empty_and_statement_changes_only_chain_fields_on_other_role_change. Then version 3 "
        "of the epoch statement (https://rezono.org/epoch-statement/v3, rezono.epoch-statement/3) keeps every field "
        "of version 2 and adds the Sha256 field allowed to EpochPredicate in contracts/statement.yaml; "
        "rezono_publication.statement names it ALLOWED = 'allowed.json', make writes version 3 with allowed = the "
        "SHA-256 of that object when the form holds it and leaves a form without it unchanged, and verify holds "
        "allowed to the subject's digest and the proved row to the statement's role and epoch."
    ),
)
def test_the_statement_names_why_it_exists():
    if getattr(st, "ALLOWED", None) != ALLOWED:
        raise MissingAllowedField("rezono_publication.statement has no ALLOWED = 'allowed.json'")
    predicate = yaml.safe_load(CONTRACT.read_text("utf-8"))["classes"]["EpochPredicate"]["attributes"]
    assert "allowed" in predicate, sorted(predicate)

    allowed = proof_object()
    data, index, objects = published(allowed)
    assert st.verify(data, index, objects) == []
    statement = json.loads(data)
    assert statement["predicateType"] == "https://rezono.org/epoch-statement/v3"
    assert statement["predicate"]["format"] == "rezono.epoch-statement/3"
    assert statement["predicate"]["allowed"] == sha(allowed)
    assert {"name": ALLOWED, "digest": {"sha256": sha(allowed)}} in statement["subject"]

    # Another proof under the same name: the subject and the predicate no longer name its bytes.
    changed = {**objects, ALLOWED: proof_object(epoch="4")}
    assert any("allowed" in problem or ALLOWED in problem for problem in st.verify(data, index, changed))

    # A proof of another role in this role's form: the proved row names the wrong role. `make` may refuse it at
    # once; if it writes the statement, the verifier names it.
    try:
        stranger = published(proof_object(role="auditor"))
    except ValueError as error:
        assert "allowed" in str(error), error
    else:
        assert any("allowed" in problem for problem in st.verify(*stranger))

    # A form without allowed.json keeps the statement it has today.
    plain, plain_index, plain_objects = published(None)
    assert st.verify(plain, plain_index, plain_objects) == []
    assert "allowed" not in json.loads(plain)["predicate"]
