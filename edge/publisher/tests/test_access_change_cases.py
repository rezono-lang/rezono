"""Unit and agreement tests for independent access-change checks
(`rezono_checker.access.may_change_access` and `rezono_publisher.difference.withheld`)."""

from __future__ import annotations

import pytest

from rezono_checker import access as checker_access
from rezono_publisher import difference


def _atom(relation: str, *terms: str, polarity: str | None = "positive") -> dict:
    atom: dict = {"relation": relation, "terms": list(terms)}
    if polarity is not None:
        atom["polarity"] = polarity
    return atom


def _assert_both(rules_doc, bundle, delta, expected: bool) -> None:
    checker_verdict = checker_access.may_change_access(rules_doc, bundle, delta)
    publisher_verdict = difference.withheld(rules_doc, bundle, delta)
    assert checker_verdict is expected
    assert publisher_verdict is expected
    assert checker_verdict == publisher_verdict


BASE_BUNDLE = {
    "kinds": [
        {"id": "role"},
        {"id": "item"},
        {"id": "sub_item", "parent": "item"},
        {"id": "grand_item", "parent": "sub_item"},
        {"id": "permit"},
        {"id": "note"},
        {"id": "doc"},
    ],
    "arrows": [],
}


def test_may_read_full_direct_derived_aggregates_negations_seals_and_calc():
    # Direct may_read_full dependency
    direct = {
        "format": "rezono.rules/1",
        "rules": [
            {"id": "r1", "head": _atom("may_read", "?r", "item", "?x"), "body": [_atom("role", "?r"), _atom("item", "?x")]},
            {"id": "r2", "head": _atom("may_read_full", "?r", "item"), "body": [_atom("role", "?r"), _atom("permit", "scope")]},
        ],
    }
    _assert_both(direct, BASE_BUNDLE, {"changes": [{"op": "insert", "kind": "permit"}]}, True)
    _assert_both(direct, BASE_BUNDLE, {"changes": [{"op": "delete", "kind": "permit"}]}, True)
    _assert_both(direct, BASE_BUNDLE, {"changes": [{"op": "set", "kind": "note"}]}, False)

    # Derived helper feeding may_read_full via slot table
    derived = {
        "format": "rezono.rules/1",
        "rules": [
            {"id": "r1", "head": _atom("may_read_full", "?r", "item"), "body": [_atom("has_scope", "?r")]},
            {"id": "r2", "head": _atom("has_scope", "?r"), "body": [_atom("role", "?r"), _atom("permit__flag", "?p", "on")]},
        ],
    }
    _assert_both(derived, BASE_BUNDLE, {"changes": [{"op": "set", "kind": "permit", "slot": "flag"}]}, True)
    _assert_both(derived, BASE_BUNDLE, {"changes": [{"op": "unset", "kind": "permit", "slot": "other"}]}, True)
    _assert_both(derived, BASE_BUNDLE, {"changes": [{"op": "set", "kind": "note"}]}, False)

    # Aggregate in may_read_full
    agg = {
        "format": "rezono.rules/1",
        "rules": [
            {
                "id": "r1",
                "head": _atom("may_read_full", "?r", "item"),
                "body": [_atom("role", "?r")],
                "aggregates": [{"relation": "permit", "terms": ["_"], "function": "count", "as": "?n"}],
            },
        ],
    }
    _assert_both(agg, BASE_BUNDLE, {"changes": [{"op": "insert", "kind": "permit"}]}, True)

    # Negation in may_read_full
    neg = {
        "format": "rezono.rules/1",
        "rules": [
            {
                "id": "r1",
                "head": _atom("may_read_full", "?r", "item"),
                "body": [_atom("role", "?r"), _atom("permit", "blocked", polarity="negative")],
            },
        ],
    }
    _assert_both(neg, BASE_BUNDLE, {"changes": [{"op": "insert", "kind": "permit"}]}, True)

    # Seal output in may_read_full closure
    seal_bundle = {
        "kinds": [
            {"id": "role"},
            {"id": "alpha"},
            {"id": "beta"},
            {"id": "gamma"},
            {"id": "period_close"},
            {"id": "closed_alpha"},
        ],
        "arrows": [
            {"kind": "beta", "target": "alpha", "inlined": False},
            {"kind": "period_close", "target": "closed_alpha", "inlined": True},
            {"kind": "closed_alpha", "target": "alpha", "inlined": False},
        ],
    }
    seal_rules = {
        "format": "rezono.rules/1",
        "seals": [{
            "kind": "alpha",
            "period": "alpha__period",
            "tables": ["alpha__title"],
            "closed_until": "period_close__closed_until",
            "covers": "period_close__covers",
            "element": "closed_alpha__element",
            "sha256": "closed_alpha__sha256",
            "refused": "alpha__refused",
            "accepted": "alpha__accepted",
            "row_sha256": "alpha__row_sha256",
            "parts": [{
                "kind": "beta",
                "owner": "alpha",
                "arrow": "beta__alpha",
                "tables": ["beta__state"],
                "accepted": "beta__accepted",
            }],
        }],
        "rules": [
            {"id": "r1", "head": _atom("may_read_full", "?r", "alpha"), "body": [_atom("role", "?r"), _atom("alpha__refused", "?a", "?c")]},
        ],
    }
    _assert_both(seal_rules, seal_bundle, {"changes": [{"op": "set", "kind": "beta", "slot": "state"}]}, True)
    _assert_both(seal_rules, seal_bundle, {"changes": [{"op": "set", "kind": "period_close", "slot": "closed_until"}]}, True)
    _assert_both(seal_rules, seal_bundle, {"changes": [{"op": "set", "kind": "gamma", "slot": "note"}]}, False)

    # Calc relation in may_read_full closure
    calc_rules = {
        "format": "rezono.rules/1",
        "relations": [{"name": "calc__score", "role": "calc"}],
        "rules": [
            {"id": "r1", "head": _atom("may_read_full", "?r", "item"), "body": [_atom("role", "?r"), _atom("calc__score", "?r", "?v", "known", "")]},
        ],
    }
    _assert_both(calc_rules, BASE_BUNDLE, {"changes": []}, True)


def test_self_granting_insert_exception_and_boundaries():
    plain = {
        "format": "rezono.rules/1",
        "rules": [
            {"id": "r1", "head": _atom("may_read", "?r", "item", "?x"), "body": [_atom("role", "?r"), _atom("item", "?x")]},
        ],
    }
    # Insert into item or subkind grants only the inserted element
    _assert_both(plain, BASE_BUNDLE, {"changes": [{"op": "insert", "kind": "item"}]}, False)
    _assert_both(plain, BASE_BUNDLE, {"changes": [{"op": "insert", "kind": "sub_item"}]}, False)
    _assert_both(plain, BASE_BUNDLE, {"changes": [{"op": "insert", "kind": "grand_item"}]}, False)
    # Delete is never exempt
    _assert_both(plain, BASE_BUNDLE, {"changes": [{"op": "delete", "kind": "item"}]}, True)
    _assert_both(plain, BASE_BUNDLE, {"changes": [{"op": "delete", "kind": "grand_item"}]}, True)
    # Set/unset on item with no item__* slot in closure keeps membership
    _assert_both(plain, BASE_BUNDLE, {"changes": [{"op": "set", "kind": "item"}]}, False)

    # Slot table in closure blocks even insert/set
    with_slot = {
        "format": "rezono.rules/1",
        "rules": [
            {"id": "r1", "head": _atom("may_read", "?r", "item", "?x"), "body": [_atom("role", "?r"), _atom("item", "?x"), _atom("item__tag", "?x", "pub")]},
        ],
    }
    _assert_both(with_slot, BASE_BUNDLE, {"changes": [{"op": "insert", "kind": "item"}]}, True)
    _assert_both(with_slot, BASE_BUNDLE, {"changes": [{"op": "set", "kind": "sub_item"}]}, True)

    # may_read feeding may_read_full (ACCESS in closure) disables self-granting insert
    feeds_full = {
        "format": "rezono.rules/1",
        "rules": [
            {"id": "r1", "head": _atom("may_read", "?r", "item", "?x"), "body": [_atom("role", "?r"), _atom("item", "?x")]},
            {"id": "r2", "head": _atom("may_read_full", "?r", "doc"), "body": [_atom("may_read", "?r", "item", "?x")]},
        ],
    }
    _assert_both(feeds_full, BASE_BUNDLE, {"changes": [{"op": "insert", "kind": "item"}]}, True)

    # item also used directly in may_read_full disables self-granting insert
    direct_full = {
        "format": "rezono.rules/1",
        "rules": [
            {"id": "r1", "head": _atom("may_read", "?r", "item", "?x"), "body": [_atom("role", "?r"), _atom("item", "?x")]},
            {"id": "r2", "head": _atom("may_read_full", "?r", "doc"), "body": [_atom("role", "?r"), _atom("item", "?x")]},
        ],
    }
    _assert_both(direct_full, BASE_BUNDLE, {"changes": [{"op": "insert", "kind": "item"}]}, True)

    # Aggregate over item in may_read disables self-granting insert
    agg_item = {
        "format": "rezono.rules/1",
        "rules": [
            {
                "id": "r1",
                "head": _atom("may_read", "?r", "item", "?x"),
                "body": [_atom("item", "?x")],
                "aggregates": [{"relation": "item", "terms": ["_"], "function": "count", "as": "?n"}],
            },
        ],
    }
    _assert_both(agg_item, BASE_BUNDLE, {"changes": [{"op": "insert", "kind": "item"}]}, True)


def test_inlined_arrows_are_followed_transitively():
    bundle = {
        "kinds": [
            {"id": "role"},
            {"id": "branch"},
            {"id": "sub_branch", "parent": "branch"},
            {"id": "location"},
            {"id": "address", "parent": "location"},
            {"id": "geo_point"},
            {"id": "external_ref"},
            {"id": "unrelated"},
        ],
        "arrows": [
            {"kind": "branch", "target": "address", "inlined": True},
            {"kind": "location", "target": "geo_point", "inlined": True},
            {"kind": "branch", "target": "external_ref", "inlined": False},
        ],
    }

    # Direct inlined target kind in closure
    rules_target_kind = {
        "format": "rezono.rules/1",
        "rules": [
            {"id": "r1", "head": _atom("may_read", "?r", "address", "?a"), "body": [_atom("role", "?r"), _atom("address", "?a")]},
        ],
    }
    for op in ("insert", "delete", "set", "unset"):
        _assert_both(rules_target_kind, bundle, {"changes": [{"op": op, "kind": "branch"}]}, True)
        _assert_both(rules_target_kind, bundle, {"changes": [{"op": op, "kind": "sub_branch"}]}, True)
    _assert_both(rules_target_kind, bundle, {"changes": [{"op": "set", "kind": "unrelated"}]}, False)

    # Inlined target slot table in closure
    rules_target_slot = {
        "format": "rezono.rules/1",
        "rules": [
            {"id": "r1", "head": _atom("may_read", "?r", "branch", "?b"), "body": [_atom("role", "?r"), _atom("address__city", "?a", "x")]},
        ],
    }
    _assert_both(rules_target_slot, bundle, {"changes": [{"op": "set", "kind": "branch"}]}, True)
    _assert_both(rules_target_slot, bundle, {"changes": [{"op": "unset", "kind": "sub_branch"}]}, True)

    # Transitive inlined target (sub_branch -> branch -> address -> location -> geo_point)
    rules_transitive = {
        "format": "rezono.rules/1",
        "rules": [
            {"id": "r1", "head": _atom("may_read_full", "?r", "branch"), "body": [_atom("role", "?r"), _atom("geo_point__zone", "?g", "eu")]},
        ],
    }
    _assert_both(rules_transitive, bundle, {"changes": [{"op": "set", "kind": "branch"}]}, True)
    _assert_both(rules_transitive, bundle, {"changes": [{"op": "unset", "kind": "sub_branch"}]}, True)
    _assert_both(rules_transitive, bundle, {"changes": [{"op": "set", "kind": "unrelated"}]}, False)

    # Non-inlined arrow does NOT withhold edits on owner when only target is in closure
    rules_non_inlined = {
        "format": "rezono.rules/1",
        "rules": [
            {"id": "r1", "head": _atom("may_read_full", "?r", "branch"), "body": [_atom("role", "?r"), _atom("external_ref__code", "?e", "ok")]},
        ],
    }
    _assert_both(rules_non_inlined, bundle, {"changes": [{"op": "set", "kind": "branch"}]}, False)


@pytest.mark.parametrize(
    ("rules_doc", "bundle", "delta"),
    [
        # Unknown kind in delta
        (None, BASE_BUNDLE, {"changes": [{"op": "set", "kind": "ghost"}]}),
        # Dangling parent in bundle["kinds"]
        (None, {"kinds": [{"id": "a", "parent": "missing"}]}, {"changes": [{"op": "set", "kind": "a"}]}),
        # Parent cycle in unmodified kind
        (None, {"kinds": [{"id": "ok"}, {"id": "a", "parent": "b"}, {"id": "b", "parent": "a"}]}, {"changes": [{"op": "set", "kind": "ok"}]}),
        # Duplicate kind id
        (None, {"kinds": [{"id": "a"}, {"id": "a"}]}, {"changes": []}),
        # Invalid arrows structure / non-bool inlined / unknown arrow kind or target
        (None, {"kinds": [{"id": "a"}], "arrows": "bad"}, {"changes": []}),
        (None, {"kinds": [{"id": "a"}], "arrows": [{"kind": "a", "target": "missing", "inlined": True}]}, {"changes": []}),
        (None, {"kinds": [{"id": "a"}], "arrows": [{"kind": "missing", "target": "a", "inlined": True}]}, {"changes": []}),
        (None, {"kinds": [{"id": "a"}], "arrows": [{"kind": "a", "target": "a", "inlined": "yes"}]}, {"changes": []}),
        (None, {"kinds": [{"id": "a"}], "arrows": [{"kind": "a", "target": "a", "inlined": 1}]}, {"changes": []}),
        # Unknown rules_doc format
        ({"format": "rezono.rules/2", "rules": []}, BASE_BUNDLE, {"changes": []}),
        ({"format": 1, "rules": []}, BASE_BUNDLE, {"changes": []}),
        # Malformed seals, rules, relations, body, aggregates, polarity
        ({"seals": "bad"}, BASE_BUNDLE, {"changes": []}),
        ({"seals": [{"kind": "item"}]}, BASE_BUNDLE, {"changes": []}),
        ({"rules": "bad"}, BASE_BUNDLE, {"changes": []}),
        ({"rules": [{"head": "bad"}]}, BASE_BUNDLE, {"changes": []}),
        ({"rules": [{"head": _atom("may_read", "?r", "item", "?x"), "body": "bad"}]}, BASE_BUNDLE, {"changes": []}),
        ({"rules": [{"head": _atom("may_read", "?r", "item", "?x"), "body": [_atom("item", "?x", polarity="maybe")]}]}, BASE_BUNDLE, {"changes": []}),
        ({"rules": [{"head": _atom("may_read", "?r", "item", "?x"), "body": [{"relation": "item", "terms": ["?x"], "polarity": 1}]}]}, BASE_BUNDLE, {"changes": []}),
        ({"rules": [{"head": _atom("may_read", "?r", "item", "?x"), "body": [], "aggregates": "bad"}]}, BASE_BUNDLE, {"changes": []}),
        ({"rules": [{"head": _atom("may_read", "?r", "item", "?x"), "body": [], "aggregates": [{"relation": ""}]}]}, BASE_BUNDLE, {"changes": []}),
        ({"relations": "bad"}, BASE_BUNDLE, {"changes": []}),
        ({"relations": [{"role": "calc"}]}, BASE_BUNDLE, {"changes": []}),
        # may_read / may_read_full declared as calc directly (even with no rules)
        ({"relations": [{"name": "may_read", "role": "calc"}], "rules": []}, BASE_BUNDLE, {"changes": []}),
        ({"relations": [{"name": "may_read_full", "role": "calc"}], "rules": []}, BASE_BUNDLE, {"changes": []}),
        # Malformed / unhashable op or missing delta/bundle
        (None, BASE_BUNDLE, {"changes": [{"op": ["set"], "kind": "item"}]}),
        (None, BASE_BUNDLE, {"changes": [{"op": 123, "kind": "item"}]}),
        (None, BASE_BUNDLE, {"changes": [{"op": "rename", "kind": "item"}]}),
        (None, BASE_BUNDLE, None),
        (None, None, {"changes": []}),
        ("bad", BASE_BUNDLE, {"changes": []}),
    ],
)
def test_malformed_inputs_fail_closed_and_agree(rules_doc, bundle, delta):
    _assert_both(rules_doc, bundle, delta, True)
