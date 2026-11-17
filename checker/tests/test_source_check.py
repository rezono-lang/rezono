"""The check `rezono:sources` (S25) on small synthetic snapshots: the rows, the fields, hidden rows, the files."""
import hashlib
import inspect
import json
from pathlib import Path

import pytest
import yaml
from rezono_canon import canonical_json

from rezono_checker import sources
from rezono_checker.sources import check_role_sources, check_source_sets

ROOT = Path(__file__).resolve().parents[2]
BUNDLE = {"kinds": [{"id": "alpha", "table": "alpha"}, {"id": "beta", "table": "beta"}],
          "arrows": [{"id": "beta.alpha", "table": "beta__alpha"}],
          "attributes": [{"id": "alpha.flag", "table": "alpha__flag"}]}
PACK = {"kind": "pack", "name": "facts/a.yaml", "position": "2"}


def snap(*keys) -> bytes:
    return json.dumps([{"key": list(k)} for k in sorted(keys, key=canonical_json)]).encode()


# The complete epoch: alpha a1, a2 (hidden from the guest), x; beta x (the same text id in another kind).
# The checker gets only the guest's own snapshots; COMPLETE is what a complete role reads.
COMPLETE = {"alpha": snap(["a1"], ["a2"], ["x"]), "alpha__flag": snap(["a1", "true"], ["a2", "false"]),
            "beta": snap(["x"]), "beta__alpha": snap(["x", "a1"]), "enum_state": snap(["low"])}
GUEST = {"alpha": snap(["a1"]), "alpha__flag": snap(["a1", "true"]), "beta": snap(["x"]),
         "beta__alpha": snap(["x", "a1"]), "enum_state": snap(["low"])}


def entry(rel, *key, src=(PACK,), **extra):
    return {"row": {"relation": rel, "key": canonical_json(list(key))}, "sources": list(src), **extra}


def guest_entries(**over):
    """The guest's correct entries, in (relation, key) order; `over` replaces the sources of one relation."""
    rows = [("alpha", "a1"), ("alpha__flag", "a1", "true"), ("beta", "x"), ("beta__alpha", "x", "a1")]
    return [entry(r[0], *r[1:], src=over.get(r[0], (PACK,))) for r in rows]


def check(entries, snapshots=GUEST):
    return check_role_sources(json.dumps(entries).encode(), BUNDLE, snapshots)


def reasons(findings):
    return [f["reason"] for f in findings]


def test_the_entries_of_exactly_the_rows_a_role_reads_pass():
    assert check(guest_entries()) == []
    # A complete role reads every row: it gets every entry, and no id is hidden from it.
    every = [entry("alpha", k) for k in ("a1", "a2", "x")] + [entry("alpha__flag", "a1", "true"), entry("alpha__flag", "a2", "false"),
             entry("beta", "x"), entry("beta__alpha", "x", "a1")]
    assert check(every, COMPLETE) == []
    # Enum rows are schema, not facts: they have no entry and need none.
    assert all(f.get("relation") != "enum_state" for f in check(guest_entries()))


def test_an_entry_for_a_hidden_row_blocks_without_naming_it():
    findings = check(guest_entries() + [entry("alpha", "a2")])
    assert reasons(findings) == ["source_row_not_read"]
    assert "a2" not in json.dumps(findings) and "relation" not in findings[0]


def test_typed_rows_keep_two_kinds_with_one_text_id_apart():
    # beta(x) is the guest's; alpha(x) is not, although its id is the same text.
    assert reasons(check([e for e in guest_entries() if e["row"]["relation"] != "beta"] + [entry("alpha", "x")])) \
        == ["source_missing", "source_row_not_read"]


def test_a_missing_entry_an_empty_entry_and_the_order_block():
    assert reasons(check(guest_entries()[1:])) == ["source_missing"]
    empty = guest_entries()
    empty[0]["sources"] = []
    assert reasons(check(empty)) == ["source_empty"]
    assert reasons(check(list(reversed(guest_entries()))))[0] == "source_order"
    twice = guest_entries()
    assert "source_order" in reasons(check(twice[:1] + twice))
    other = {"kind": "pack", "name": "facts/b.yaml", "position": "1"}
    unsorted = guest_entries(alpha=(other, PACK))
    assert reasons(check(unsorted)) == ["source_order"]
    assert reasons(check(guest_entries(alpha=(PACK, PACK)))) == ["source_order"]
    assert check(guest_entries(alpha=(PACK, other))) == []


@pytest.mark.parametrize("src, field", [
    ({"kind": "git", "name": "o/r", "position": "f.json"}, "revision"),
    ({"kind": "proposal", "name": "p-1", "position": "3"}, "revision"),
    ({"kind": "rumour", "name": "x", "position": "1"}, "kind"),
    ({"kind": "pack", "name": "x"}, "kind"),
    ({"kind": "pack", "name": "x", "position": "1", "colour": "red"}, "shape"),
    ({"kind": "pack", "name": "x", "position": 1}, "shape"),
    ({"kind": "query", "name": "q", "position": "1", "url": "ftp://h/x"}, "url"),
    ({"kind": "query", "name": "q", "position": "1", "retrieved_at": "2026-02-30T00:00:00Z"}, "retrieved_at"),
    ({"kind": "query", "name": "q", "position": "1", "fragment_sha256": "ABC"}, "fragment_sha256"),
    ({"kind": "query", "name": "q", "position": "1", "ownership": "mine"}, "ownership"),
    ({"kind": "query", "name": "q", "position": "1", "ownership": "third_party"}, "third_party"),
    ({"kind": "document", "name": "d", "position": "s1", "url": "https://h/d", "fragment_sha256": "a" * 64,
      "licence": "CC-BY-4.0", "attribution": "A"}, "document"),
])
def test_a_source_without_its_kinds_fields_blocks(src, field):
    findings = check(guest_entries(alpha=(src,)))
    assert [(f["reason"], f.get("field")) for f in findings] == [("source_fields", field)]


def test_a_complete_document_and_third_party_source_pass():
    doc = {"kind": "document", "name": "d", "position": "s1", "url": "https://h/d", "fragment_sha256": "a" * 64,
           "licence": "CC-BY-4.0", "attribution": "A", "retrieved_at": "2026-01-01T00:00:00Z", "ownership": "third_party"}
    assert check(guest_entries(alpha=(doc,))) == []


def test_hidden_rows_change_nothing_a_role_gets_or_is_told():
    """Two worlds that differ only in rows the guest does not read: hidden B/3 and B/x, and a hidden alpha a2.
    The guest's entries, which name a line 3 and the text x, check the same in both (S25 made precise by the
    owner, 08-11-2026): a source follows its readable row, and equal text is no access relation."""
    src = {"kind": "git", "name": "o/x", "revision": "c0ffee", "position": "rows.json#3 a2 x"}
    entries = guest_entries(alpha=(src,), beta=(src,))
    assert check(entries) == []
    hidden = GUEST | {"enum_state": snap(["low"])}  # the guest's own bytes stay the same; the epoch grows
    assert check_role_sources(json.dumps(entries).encode(), BUNDLE | {"kinds": BUNDLE["kinds"] + [{"id": "gamma", "table": "gamma"}]},
                              hidden) == []
    # The checker is given only the role's own snapshots: what is hidden cannot decide its outcome.
    assert list(inspect.signature(check_role_sources).parameters) == ["data", "bundle", "snapshots"]


def test_the_other_fields_of_a_source_follow_the_row_unsearched():
    url = {"kind": "query", "name": "q", "position": "1", "url": "https://h/a2", "revision": "a2"}
    assert check(guest_entries(alpha=(url,))) == []


def test_unreadable_input_blocks():
    assert reasons(check_role_sources(b"{", BUNDLE, GUEST)) == ["sources_unreadable"]
    assert reasons(check_role_sources(b"{}", BUNDLE, GUEST)) == ["sources_unreadable"]
    assert set(reasons(check([{"row": {"relation": "alpha"}, "sources": [PACK]}]))) == {"source_entry_shape", "source_missing"}
    assert "source_entry_shape" in reasons(check([guest_entries()[0] | {"extra": 1}]))


def test_each_role_has_exactly_one_source_set_with_the_hash_of_its_bytes():
    objects = {"s3://b/m-1/guest/sources.json": b"[]\n", "s3://b/m-1/checker/sources.json": b"[1]\n"}
    sha = lambda b: hashlib.sha256(b).hexdigest()
    good = [{"role": "checker", "uri": "s3://b/m-1/checker/sources.json", "sha256": sha(b"[1]\n")},
            {"role": "guest", "uri": "s3://b/m-1/guest/sources.json", "sha256": sha(b"[]\n")}]
    assert check_source_sets(good, {"checker", "guest"}, objects.get) == []
    wrong = [good[0], good[1] | {"sha256": sha(b"[1]\n")}]
    assert reasons(check_source_sets(wrong, {"checker", "guest"}, objects.get)) == ["source_set_hash"]
    assert reasons(check_source_sets(good[:1], {"checker", "guest"}, objects.get)) == ["source_set_missing"]
    assert reasons(check_source_sets(good + [good[1]], {"checker", "guest"}, objects.get)) == ["source_set_twice"]
    assert reasons(check_source_sets(good, {"guest"}, objects.get)) == ["source_set_role"]
    assert reasons(check_source_sets(good[:1] + [good[1] | {"uri": "s3://b/x"}], {"checker", "guest"}, objects.get)) \
        == ["source_set_hash"]
    assert reasons(check_source_sets([{"role": "guest"}], {"guest"}, objects.get)) == ["source_set_shape"]


def test_the_restated_rules_are_the_contracts():
    doc = yaml.safe_load((ROOT / "contracts" / "source.yaml").read_text("utf-8"))
    assert sources.KINDS == set(doc["enums"]["SourceKind"]["permissible_values"])
    assert sources.OWNERSHIP == set(doc["enums"]["SourceOwnership"]["permissible_values"])
    assert sources.FIELDS == set(doc["classes"]["Source"]["attributes"])
    attrs = doc["classes"]["Source"]["attributes"]
    assert sources.URL.pattern == attrs["url"]["pattern"] and sources.SHA256.pattern == attrs["fragment_sha256"]["pattern"]
    assert sources.INSTANT.pattern == doc["types"]["UTCInstant"]["pattern"]
