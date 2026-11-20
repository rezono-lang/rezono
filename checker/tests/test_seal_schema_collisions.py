"""Regression tests for seal schema validation in access.check_role / rules.load_seals
and may_read_full calc-dependency rejection in rules.check_calc_bindings."""

from __future__ import annotations

import copy
import json

import pytest

from rezono_checker.access import check_role
from rezono_checker.rules import check_calc_bindings, load_rules, load_seals


def _snap(rows: list[list[str]]) -> bytes:
    return json.dumps([{"key": row} for row in rows]).encode("utf-8")


BASE_BUNDLE = {
    "kinds": [
        {"id": "public"},
        {"id": "secret"},
        {"id": "run"},
        {"id": "step"},
        {"id": "substep"},
        {"id": "period_close"},
    ],
    "arrows": [
        {"table": "secret__link", "kind": "public", "target": "secret"},
        {"table": "step__run", "kind": "step", "target": "run"},
        {"table": "substep__step", "kind": "substep", "target": "step"},
    ],
    "attributes": [
        {"table": "run__month", "kind": "run"},
        {"table": "public__note", "kind": "public"},
    ],
    "enums": [
        {"id": "status_enum", "values": ["open", "closed"]},
    ],
}

VALID_SEAL = {
    "kind": "run",
    "period": "run__month",
    "row_sha256": "run__row_sha256",
    "tables": ["run__month"],
    "closed_until": "period_close__closed_until",
    "covers": "period_close__covers",
    "element": "closed_run__element",
    "sha256": "closed_run__sha256",
    "refused": "run__refused",
    "accepted": "run__accepted",
    "parts": [
        {
            "kind": "step",
            "arrow": "step__run",
            "owner": "run",
            "tables": ["step__run"],
            "accepted": "step__accepted",
        },
    ],
}


def _doc_with_seals(seals: list[dict]) -> dict:
    return {
        "format": "rezono.rules/1",
        "pack": "toy",
        "seals": seals,
        "relations": [{"name": "may_read", "role": "derived", "key": []}],
        "rules": [],
    }


def _assert_malformed_bundle(bundle: dict, seals: list[dict], complete: dict | None = None,
                             mine: dict | None = None) -> None:
    full, findings = check_role(
        "reader",
        complete if complete is not None else {},
        mine if mine is not None else {},
        None,
        bundle,
        _doc_with_seals(seals),
    )
    assert full == frozenset()
    assert findings
    assert all(f["severity"] == "error" for f in findings)
    assert any(f["reason"] == "malformed_bundle" for f in findings), findings


def test_seal_row_sha256_colliding_with_arrow_table_fails_closed():
    """A forged doc['seals'] entry naming an existing arrow table as row_sha256 must not
    overwrite its (public, secret) column kinds and leak secret rows."""
    forged_seal = {
        **copy.deepcopy(VALID_SEAL),
        "kind": "public",
        "row_sha256": "secret__link",
        "parts": [],
    }
    complete = {
        "public": _snap([["p1"]]),
        "secret": _snap([["s1"]]),
        "secret__link": _snap([["p1", "s1"]]),
        "may_read": _snap([["reader", "public", "p1"]]),
    }
    leaked = {
        "public": _snap([["p1"]]),
        "secret": _snap([]),
        "secret__link": _snap([["p1", "s1"]]),
    }
    _assert_malformed_bundle(BASE_BUNDLE, [forged_seal], complete=complete, mine=leaked)


@pytest.mark.parametrize("field,colliding_table", [
    ("refused", "secret__link"),
    ("accepted", "public__note"),
    ("row_sha256", "run"),
    ("accepted", "status_enum"),
])
def test_seal_tables_colliding_with_existing_schema_tables_fail_closed(field: str, colliding_table: str):
    seal = copy.deepcopy(VALID_SEAL)
    seal[field] = colliding_table
    _assert_malformed_bundle(BASE_BUNDLE, [seal])


def test_seal_part_accepted_colliding_with_existing_schema_table_fails_closed():
    seal = copy.deepcopy(VALID_SEAL)
    seal["parts"][0]["accepted"] = "secret__link"
    _assert_malformed_bundle(BASE_BUNDLE, [seal])


def test_seal_unknown_kind_fails_closed():
    seal = copy.deepcopy(VALID_SEAL)
    seal["kind"] = "ghost_kind"
    _assert_malformed_bundle(BASE_BUNDLE, [seal])


def test_seal_without_period_close_kind_in_bundle_fails_closed():
    bundle_without_close = copy.deepcopy(BASE_BUNDLE)
    bundle_without_close["kinds"] = [k for k in bundle_without_close["kinds"] if k["id"] != "period_close"]
    _assert_malformed_bundle(bundle_without_close, [copy.deepcopy(VALID_SEAL)])


def test_seal_unknown_part_kind_fails_closed():
    seal = copy.deepcopy(VALID_SEAL)
    seal["parts"][0]["kind"] = "ghost_part"
    _assert_malformed_bundle(BASE_BUNDLE, [seal])


def test_duplicate_seal_table_names_within_and_across_seals_fail_closed():
    # Duplicate within one seal: accepted == refused
    same_in_seal = copy.deepcopy(VALID_SEAL)
    same_in_seal["accepted"] = same_in_seal["refused"]
    _assert_malformed_bundle(BASE_BUNDLE, [same_in_seal])
    with pytest.raises(ValueError, match="duplicate seal table"):
        load_seals({"seals": [same_in_seal]})

    # Duplicate between seal and its part: part.accepted == seal.accepted
    same_as_part = copy.deepcopy(VALID_SEAL)
    same_as_part["parts"][0]["accepted"] = same_as_part["accepted"]
    _assert_malformed_bundle(BASE_BUNDLE, [same_as_part])
    with pytest.raises(ValueError, match="duplicate seal table"):
        load_seals({"seals": [same_as_part]})

    # Duplicate across two parts of the same seal
    dup_parts = copy.deepcopy(VALID_SEAL)
    dup_parts["parts"].append({
        "kind": "substep",
        "arrow": "substep__step",
        "owner": "step",
        "tables": ["substep__step"],
        "accepted": "step__accepted",
    })
    _assert_malformed_bundle(BASE_BUNDLE, [dup_parts])
    with pytest.raises(ValueError, match="duplicate seal table"):
        load_seals({"seals": [dup_parts]})

    # Duplicate across two distinct seal entries
    second_seal = {
        **copy.deepcopy(VALID_SEAL),
        "kind": "public",
        "period": "public__note",
        "tables": ["public__note"],
        "refused": "public__refused",
        "accepted": "public__accepted",
        "row_sha256": "run__row_sha256",
    }
    del second_seal["parts"]
    _assert_malformed_bundle(BASE_BUNDLE, [copy.deepcopy(VALID_SEAL), second_seal])
    with pytest.raises(ValueError, match="duplicate seal table"):
        load_seals({"seals": [copy.deepcopy(VALID_SEAL), second_seal]})


def test_valid_seal_passes_schema_derivation_and_load_seals():
    loaded = load_seals({"seals": [copy.deepcopy(VALID_SEAL)]})
    assert len(loaded) == 1
    complete = {
        "public": _snap([["p1"]]),
        "may_read": _snap([["reader", "public", "p1"]]),
    }
    mine = {"public": _snap([["p1"]])}
    _, findings = check_role("reader", complete, mine, None, BASE_BUNDLE, _doc_with_seals([copy.deepcopy(VALID_SEAL)]))
    assert [f for f in findings if f.get("relation") != "may_read"] == []


def _col(name: str, typ: str = "string") -> dict:
    return {"name": name, "type": typ}


def _calc_doc(rules: list[dict], extra_relations: list[dict] | None = None) -> dict:
    return {
        "format": "rezono.rules/1",
        "relations": [
            {"name": "role", "role": "base", "key": [_col("id")]},
            {"name": "item", "role": "base", "key": [_col("id")]},
            {
                "name": "calc__score",
                "role": "calc",
                "world": "open",
                "key": [
                    _col("subject"),
                    _col("value", "integer"),
                    _col("state"),
                    _col("reason"),
                ],
            },
            {"name": "may_read_full", "role": "derived", "key": [_col("role"), _col("kind")]},
            *(extra_relations or []),
        ],
        "rules": rules,
    }


CALC_IR = {
    "format": "rezono.calc-ir/1",
    "subject": "item",
    "rules": [{"view": "calc__score", "type": "number"}],
    "facts": [],
    "versions": [],
}


def test_check_calc_bindings_rejects_may_read_full_depending_directly_on_calc():
    doc = _calc_doc([
        {
            "id": "grant_full_direct",
            "stratum": "1",
            "head": {"relation": "may_read_full", "terms": ["?r", "item"]},
            "body": [
                {"relation": "role", "terms": ["?r"], "polarity": "positive", "stratum": "0"},
                {"relation": "calc__score", "terms": ["?s", "?v", "known", ""], "polarity": "positive", "stratum": "0"},
            ],
        },
    ])
    with pytest.raises(ValueError, match="may_read_full cannot depend"):
        check_calc_bindings(doc, load_rules(doc), CALC_IR)


def test_check_calc_bindings_rejects_may_read_full_depending_transitively_on_calc():
    doc = _calc_doc(
        [
            {
                "id": "scored_r",
                "stratum": "1",
                "head": {"relation": "scored", "terms": ["?s"]},
                "body": [
                    {"relation": "calc__score", "terms": ["?s", "?v", "known", ""], "polarity": "positive", "stratum": "0"},
                ],
            },
            {
                "id": "grant_full_indirect",
                "stratum": "1",
                "head": {"relation": "may_read_full", "terms": ["?r", "item"]},
                "body": [
                    {"relation": "role", "terms": ["?r"], "polarity": "positive", "stratum": "0"},
                    {"relation": "scored", "terms": ["?s"], "polarity": "positive", "stratum": "1"},
                ],
            },
        ],
        extra_relations=[{"name": "scored", "role": "derived", "world": "open", "key": [_col("id")]}],
    )
    with pytest.raises(ValueError, match="may_read_full cannot depend"):
        check_calc_bindings(doc, load_rules(doc), CALC_IR)


def test_check_calc_bindings_allows_may_read_full_independent_of_calc():
    doc = _calc_doc(
        [
            {
                "id": "scored_r",
                "stratum": "1",
                "head": {"relation": "scored", "terms": ["?s"]},
                "body": [
                    {"relation": "calc__score", "terms": ["?s", "?v", "known", ""], "polarity": "positive", "stratum": "0"},
                ],
            },
            {
                "id": "grant_full_ok",
                "stratum": "1",
                "head": {"relation": "may_read_full", "terms": ["?r", "item"]},
                "body": [
                    {"relation": "role", "terms": ["?r"], "polarity": "positive", "stratum": "0"},
                ],
            },
        ],
        extra_relations=[{"name": "scored", "role": "derived", "world": "open", "key": [_col("id")]}],
    )
    check_calc_bindings(doc, load_rules(doc), CALC_IR)
