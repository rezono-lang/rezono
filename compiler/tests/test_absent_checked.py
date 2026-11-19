"""A full role still needs a verified source read to publish scoped absence."""

import json
from pathlib import Path
import shutil

import pytest

from rezono_compiler.pack import CompileError
from rezono_publisher import batch, publish, store


MINIMAL = Path(__file__).resolve().parent / "fixtures/minimal"
ROLES = {"checker": "complete", "whole": "may_read", "enumerator": "may_read"}
GRANTS = """
.decl may_read(role: symbol, kind: symbol, element: symbol)
.decl may_read_full(role: symbol, kind: symbol)
may_read_full("whole", "alpha") :- alpha("anchor").
may_read("whole", "alpha", item) :- alpha(item).
may_read("enumerator", "alpha", item) :- alpha(item).
"""

UNWITNESSED = """
.decl in_scope_query(scope: symbol, key: symbol)
in_scope_query("lookup", "missing") :- alpha("anchor").
.decl registered_match(receipt: symbol, key: symbol)
registered_match("unattested", item) :- alpha__title(item, "registered").
.decl absent_checked(source: symbol, scope: symbol, cut: symbol, key: symbol, receipt: symbol)
absent_checked("register", "lookup", "snapshot-17", key, "unattested") :-
    in_scope_query("lookup", key), !registered_match("unattested", key).
"""


class UnwitnessedAbsenceReleased(AssertionError):
    """The role obtained a checked absence from a read with no receipt."""


def published(root, destination):
    epoch = batch.epoch(root, epoch=1, knowledge_time="2026-01-01T00:00:00Z", sources=[])
    bucket = store.FileStore(destination)
    manifest = publish.publish(epoch, bucket, ROLES)
    assert {"name": publish.PROOFS, "status": "green", "violations": 0} in manifest["checks"]
    return epoch, bucket, manifest


def objects(epoch, bucket, role):
    return {name: json.loads(bucket.get(key)) for name, key in
            publish.role_objects(bucket, epoch.pack, "m-1", role).items()}


def test_absent_checked_requires_readable_coverage(tmp_path):
    root = Path(shutil.copytree(MINIMAL, tmp_path / "pack"))
    (root / "facts").mkdir()
    (root / "facts/items.yaml").write_text("alpha: [{id: anchor, title: probe}]\n", encoding="utf-8")
    (root / "rules").mkdir()
    path = root / "rules/access.dl"
    path.write_text(GRANTS, encoding="utf-8")

    epoch, bucket, manifest = published(root, tmp_path / "control")
    full = {item["role"]: item["full"] for item in manifest["snapshots"] if item["relation"] == "alpha"}
    assert full == {"checker": True, "whole": True, "enumerator": False}
    for role in ("whole", "enumerator"):
        assert objects(epoch, bucket, role)["relations/alpha.json"] == [{"key": ["anchor"]}]

    # This authored candidate claims the reserved conclusion from an empty lookup and element rights.
    # It supplies neither a verified receipt nor a trusted input archive.
    path.write_text(GRANTS + UNWITNESSED, encoding="utf-8")
    try:
        epoch, bucket, _ = published(root, tmp_path / "proposed")
    except (CompileError, publish.Blocked) as error:
        assert "absent_checked" in str(error) or "receipt" in str(error)
        return

    partial = objects(epoch, bucket, "enumerator")
    assert partial.get("relations/absent_checked.json", []) == []
    whole = objects(epoch, bucket, "whole")
    rows = whole.get("relations/absent_checked.json", [])
    if rows:
        assert rows == [{"key": ["register", "lookup", "snapshot-17", "missing", "unattested"]}]
        (counterexample,) = [w for w in whole["witnesses.json"]["witnesses"]
                             if w["conclusion"]["relation"] == "absent_checked"]
        assert {premise["row"]["relation"] for premise in counterexample["premises"]} == {
            "in_scope_query", "registered_match",
        }
        raise UnwitnessedAbsenceReleased("full role received absent_checked without a verified read")
    assert all(w["conclusion"]["relation"] != "absent_checked" for w in whole["witnesses.json"]["witnesses"])


FORGED_COMPLETE = """
.decl in_scope_query(scope: symbol, key: symbol)
in_scope_query("lookup", "missing") :- alpha("anchor").
.decl registered_match(receipt: symbol, key: symbol)
registered_match("unattested", item) :- alpha__title(item, "registered").
.decl complete(scope: symbol)
complete("lookup") :- alpha("anchor").
.decl absent_checked(source: symbol, scope: symbol, cut: symbol, key: symbol, receipt: symbol)
absent_checked("register", "lookup", "snapshot-17", key, "unattested") :-
    complete("lookup"), in_scope_query("lookup", key), !registered_match("unattested", key).
"""

VERIFIED = (".decl verified_receipt(receipt: symbol, source: symbol, scope: symbol, cut: symbol, "
            "inventory: symbol, content: symbol)\n")
OTHER_RECEIPT = VERIFIED + """
.decl in_scope_query(scope: symbol, key: symbol)
in_scope_query("lookup", "missing") :- alpha("anchor").
.decl registered_match(receipt: symbol, key: symbol)
registered_match("unattested", item) :- alpha__title(item, "registered").
.decl absent_checked(source: symbol, scope: symbol, cut: symbol, key: symbol, receipt: symbol)
absent_checked(s, sc, c, key, r) :-
    verified_receipt(r, s, sc, c, _, _), in_scope_query(sc, key), !registered_match("unattested", key).
"""


def test_absent_checked_refuses_an_authored_receipt_premise(tmp_path):
    """A pack cannot vouch for its own read by declaring and filling `complete` itself (P1 counterexample)."""
    root = Path(shutil.copytree(MINIMAL, tmp_path / "pack"))
    (root / "facts").mkdir()
    (root / "facts/items.yaml").write_text("alpha: [{id: anchor, title: probe}]\n", encoding="utf-8")
    (root / "rules").mkdir()
    (root / "rules/access.dl").write_text(GRANTS + FORGED_COMPLETE, encoding="utf-8")
    with pytest.raises(CompileError, match="absent_checked"):
        published(root, tmp_path / "proposed")


def test_absent_checked_binds_the_lookup_to_the_verified_receipt(tmp_path):
    """The negative lookup must read the contents of the same receipt the positive premise verified."""
    root = Path(shutil.copytree(MINIMAL, tmp_path / "pack"))
    (root / "facts").mkdir()
    (root / "facts/items.yaml").write_text("alpha: [{id: anchor, title: probe}]\n", encoding="utf-8")
    (root / "rules").mkdir()
    (root / "rules/access.dl").write_text(GRANTS + OTHER_RECEIPT, encoding="utf-8")
    with pytest.raises(CompileError, match="absent_checked.*receipt"):
        published(root, tmp_path / "proposed")


MEMBER = ".decl verified_member(receipt: symbol, member: symbol, part: number, value: symbol)\n"
LOOKUP_BASE = VERIFIED + MEMBER + """
.decl in_scope_query(scope: symbol, key: symbol)
in_scope_query("lookup", "missing") :- alpha("anchor").
.decl registered_match(receipt: symbol, key: symbol)
.decl absent_checked(source: symbol, scope: symbol, cut: symbol, key: symbol, receipt: symbol)
"""
LOOKUPS = {
    # The pack narrows its own lookup until it never matches; the receipt contents are never read.
    "empty_lookup": """
registered_match(r, item) :- verified_receipt(r, _, _, _, _, _), alpha__title(item, "never-present").
absent_checked(s, sc, c, key, r) :-
    verified_receipt(r, s, sc, c, _, _), in_scope_query(sc, key), !registered_match(r, key).
""",
    # The lookup reads the receipt contents, but for another key than the concluded one.
    "other_key": """
registered_match(r, key) :- verified_member(r, _, 0, key).
absent_checked(s, sc, c, key, r) :-
    verified_receipt(r, s, sc, c, _, _), in_scope_query(sc, key), !registered_match(r, "zzz").
""",
}


@pytest.mark.parametrize("case", sorted(LOOKUPS))
def test_absent_checked_looks_up_the_concluded_key_in_the_receipt_members(tmp_path, case):
    """The negative lookup is verified_member of the same receipt, on the key the head concludes absent."""
    root = Path(shutil.copytree(MINIMAL, tmp_path / "pack"))
    (root / "facts").mkdir()
    (root / "facts/items.yaml").write_text("alpha: [{id: anchor, title: probe}]\n", encoding="utf-8")
    (root / "rules").mkdir()
    (root / "rules/access.dl").write_text(GRANTS + LOOKUP_BASE + LOOKUPS[case], encoding="utf-8")
    with pytest.raises(CompileError, match="absent_checked.*registered_match"):
        published(root, tmp_path / "proposed")
