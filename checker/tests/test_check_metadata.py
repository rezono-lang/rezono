"""Decision E11: the check metadata the engine loaded is exactly what the schema bundle gives."""

import pytest

from rede_checker import check_epoch, metadata

BUNDLE = {
    "format": "rede.schema-bundle/1", "checks": [],
    "kinds": [{"id": "alpha", "table": "alpha"}, {"id": "beta", "table": "beta"},
              {"id": "gamma", "table": "gamma", "parent": "beta"}],
    "arrows": [{"kind": "beta", "name": "alpha", "required": True, "multivalued": False, "target": "alpha"}],
    "attributes": [
        {"kind": "alpha", "name": "size", "multivalued": False, "minimum": "0", "maximum": "9", "constant": "4"},
        {"kind": "beta", "name": "state", "required": False, "multivalued": True, "enum": "state",
         "minimum_cardinality": "1", "maximum_cardinality": "2"},
        {"kind": "alpha", "name": "title", "required": True, "multivalued": False, "constant": "t"},
    ],
}
LOADED = {
    "rede__is_a": [("gamma", "beta")],
    "rede__required": [("alpha", "title"), ("beta", "alpha")],
    "rede__single": [("alpha", "size"), ("alpha", "title"), ("beta", "alpha")],
    "rede__arrow": [("beta", "alpha", "alpha")],
    "rede__enum": [("beta", "state", "state")],
    "rede__minimum": [("alpha", "size", "0")],
    "rede__maximum": [("alpha", "size", "9")],
    "rede__constant": [("alpha", "size", "4"), ("alpha", "title", "t")],
    "rede__minimum_cardinality": [("beta", "state", "1")],
    "rede__maximum_cardinality": [("beta", "state", "2")],
}


def reasons(loaded, bundle=BUNDLE):
    return sorted((f["reason"], f.get("relation", "")) for f in metadata.check(bundle, loaded))


def test_the_bundle_gives_every_facet():
    assert metadata.expected(BUNDLE) == {t: sorted(rs) for t, rs in LOADED.items()}
    assert reasons(LOADED) == []
    assert reasons({t: list(reversed(rs)) for t, rs in LOADED.items()}) == []  # order does not matter


@pytest.mark.parametrize("table, rows", [
    ("rede__required", [("alpha", "title")]),                                   # a required slot switched off
    ("rede__required", LOADED["rede__required"] + [("beta", "state")]),         # one switched on
    ("rede__single", LOADED["rede__single"] + [("alpha", "size")]),             # a row twice
    ("rede__maximum", [("alpha", "size", "99")]),                               # another bound
    ("rede__arrow", [("beta", "alpha", "gamma")]),                              # another target
    ("rede__is_a", []),
])
def test_a_difference_blocks(table, rows):
    assert reasons(LOADED | {table: rows}) == [("check_metadata_mismatch", table)]


def test_a_missing_or_unknown_table_blocks():
    assert reasons({t: rs for t, rs in LOADED.items() if t != "rede__enum"}) == [("check_metadata_mismatch", "rede__enum")]
    assert reasons(LOADED | {"rede__other": []}) == [("malformed_check_metadata", "rede__other")]


def test_a_malformed_row_or_table_is_refused_not_a_crash():
    assert reasons(LOADED | {"rede__required": [None]}) == [("malformed_check_metadata", "rede__required")]
    assert reasons(LOADED | {"rede__required": [("alpha",)]}) == [("malformed_check_metadata", "rede__required")]
    assert reasons(LOADED | {1: []}) == [("malformed_check_metadata", "1")]
    assert reasons(LOADED, dict(BUNDLE, arrows=[{"kind": "delta", "name": "x"}])) == [("malformed_check_metadata", "")]


def test_fail_closed():
    assert reasons(None) == [("malformed_check_metadata", "")]
    assert reasons(LOADED, {"kinds": []}) == [("malformed_check_metadata", "")]  # not a compiled bundle
    assert reasons({}, dict(BUNDLE, kinds=[], arrows=[], attributes=[])) == []   # no kinds, no metadata
    assert reasons(LOADED, dict(BUNDLE, kinds=[], arrows=[], attributes=[])) != []


def test_check_epoch_blocks_on_it():
    manifest = {"id": "m-1", "snapshots": []}
    ok = check_epoch([], manifest, {}, lambda uri: b"", derived=set(), bundle=BUNDLE, check_metadata=LOADED)
    assert ok["valid"], ok["findings"]
    bad = check_epoch([], manifest, {}, lambda uri: b"", derived=set(), bundle=BUNDLE,
                      check_metadata=LOADED | {"rede__required": []})
    assert not bad["valid"] and [f["reason"] for f in bad["findings"]] == ["check_metadata_mismatch"]
    alone = check_epoch([], manifest, {}, lambda uri: b"", derived=set(), check_metadata=LOADED)
    assert not alone["valid"]  # metadata without the bundle to compare with is refused
