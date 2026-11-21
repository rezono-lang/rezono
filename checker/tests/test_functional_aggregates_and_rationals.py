"""Focused tests for rezono.rules/2 functional state-bearing aggregates, exact rational comparisons,
transitive functional verification in single-proof check(), and functional witness binding verification."""

from __future__ import annotations

from copy import deepcopy

import pytest

from rezono_canon import canonical_bytes, sha256_hex
from rezono_checker import closure, evaluate, rules as checker_rules
from rezono_checker.canon import encode_key, sha256_json
from rezono_checker.check import _functional_state_ok, check, check_epoch


def _col(name: str, typ: str = "string") -> dict:
    return {"name": name, "type": typ}


def _lit(rel: str, *terms: str, polarity: str = "positive", stratum: str = "0") -> dict:
    return {"relation": rel, "terms": list(terms), "polarity": polarity, "stratum": stratum}


def _rule(rid: str, head_rel: str, head_terms: list[str], body: list[dict], *,
          stratum: str = "1", aggregates: list[dict] | None = None,
          conditions: list[dict] | None = None) -> dict:
    doc = {
        "id": rid,
        "stratum": stratum,
        "head": {"relation": head_rel, "terms": head_terms},
        "body": body,
    }
    if aggregates:
        doc["aggregates"] = aggregates
    if conditions:
        doc["conditions"] = conditions
    return doc


def _ref(relation: str, *parts: str) -> dict:
    return {"relation": relation, "key": encode_key(list(parts))}


def _manifest_and_reader(rows: dict[str, list[list[str]]]):
    snaps = {rel: canonical_bytes([{"key": row} for row in sorted(rs)]) for rel, rs in rows.items()}
    manifest = {
        "id": "m-fn-agg-1",
        "snapshots": [
            {"relation": rel, "role": "all", "complete": True, "uri": rel, "format": "json",
             "sha256": sha256_hex(body)}
            for rel, body in sorted(snaps.items())
        ],
    }
    return manifest, snaps.__getitem__


def _errors(report: dict) -> set[str]:
    return {f["reason"] for f in report["findings"] if f.get("severity", "error") == "error"}


def _member_score_program(*, group_policy: str = "publish", score_policy: str = "publish",
                          group_empty_state: str = "unknown") -> dict:
    """score_val (functional) -> member_score (derived with state column) -> group_total (functional aggregate)."""
    return {
        "format": "rezono.rules/2",
        "pack": "sample",
        "relations": [
            {"name": "item", "role": "base", "key": [_col("id")]},
            {"name": "score_cand", "role": "base", "key": [_col("id"), _col("n", "integer")]},
            {"name": "group_dom", "role": "base", "key": [_col("g")]},
            {"name": "member_of", "role": "base", "key": [_col("g"), _col("id")]},
            {
                "name": "score_val", "role": "functional",
                "key": [_col("id")], "domain": "item",
                "value": _col("value", "integer"), "conflict_policy": score_policy,
            },
            {
                "name": "opt_score", "role": "functional",
                "key": [_col("id")], "domain": "item",
                "value": _col("value", "integer"), "conflict_policy": "publish",
                "empty_state": "not_applicable", "empty_reason": "empty",
            },
            {
                "name": "member_score", "role": "derived",
                "key": [_col("g"), _col("id"), _col("state"), _col("reason"), _col("n", "integer")],
            },
            {
                "name": "member_opt_score", "role": "derived",
                "key": [_col("g"), _col("id"), _col("state"), _col("reason"), _col("n", "integer")],
            },
            {
                "name": "group_total", "role": "functional",
                "key": [_col("g")], "domain": "group_dom",
                "value": _col("value", "integer"), "conflict_policy": group_policy,
                "empty_state": group_empty_state,
            },
            {
                "name": "group_opt_total", "role": "functional",
                "key": [_col("g")], "domain": "group_dom",
                "value": _col("value", "integer"), "conflict_policy": "publish",
            },
        ],
        "rules": [
            _rule("score_val_r", "score_val", ["?id", "?n"],
                  [_lit("item", "?id"), _lit("score_cand", "?id", "?n")], stratum="1"),
            _rule("opt_score_r", "opt_score", ["?id", "?n"],
                  [_lit("item", "?id"), _lit("score_cand", "?id", "?n")], stratum="1"),
            _rule("member_score_r", "member_score", ["?g", "?id", "?st", "?rsn", "?n"],
                  [_lit("member_of", "?g", "?id"), _lit("score_val", "?id", "?st", "?rsn", "?n", stratum="1")],
                  stratum="2"),
            _rule("member_opt_score_r", "member_opt_score", ["?g", "?id", "?st", "?rsn", "?n"],
                  [_lit("member_of", "?g", "?id"), _lit("opt_score", "?id", "?st", "?rsn", "?n", stratum="1")],
                  stratum="2"),
            _rule("group_total_r", "group_total", ["?g", "?total"],
                  [_lit("group_dom", "?g")], stratum="3",
                  aggregates=[{"relation": "member_score", "terms": ["?g", "_", "_", "_", "_"],
                               "function": "sum", "over": "n", "as": "?total", "stratum": "2"}]),
            _rule("group_opt_total_r", "group_opt_total", ["?g", "?total"],
                  [_lit("group_dom", "?g")], stratum="3",
                  aggregates=[{"relation": "member_opt_score", "terms": ["?g", "_", "_", "_", "_"],
                               "function": "sum", "over": "n", "as": "?total", "stratum": "2"}]),
        ],
    }


def _member_score_rows_and_witnesses() -> tuple[dict[str, list[list[str]]], list[dict]]:
    rows = {
        "item": [["i_ok1"], ["i_ok2"], ["i_empty"], ["i_clash"]],
        "score_cand": [["i_ok1", "10"], ["i_ok2", "20"], ["i_clash", "5"], ["i_clash", "7"]],
        "group_dom": [["g_ok"], ["g_unknown"], ["g_na"], ["g_invalid"]],
        "member_of": [
            ["g_ok", "i_ok1"], ["g_ok", "i_ok2"],
            ["g_unknown", "i_ok1"], ["g_unknown", "i_empty"],
            ["g_na", "i_ok1"], ["g_na", "i_empty"],
            ["g_invalid", "i_ok1"], ["g_invalid", "i_empty"], ["g_invalid", "i_clash"],
        ],
        "score_val": [
            ["i_ok1", "known", "", "10"],
            ["i_ok2", "known", "", "20"],
            ["i_empty", "unknown", "no_value", ""],
            ["i_clash", "invalid", "multiple_values", ""],
        ],
        "opt_score": [
            ["i_ok1", "known", "", "10"],
            ["i_ok2", "known", "", "20"],
            ["i_empty", "not_applicable", "empty", ""],
            ["i_clash", "invalid", "multiple_values", ""],
        ],
        "member_score": [
            ["g_ok", "i_ok1", "known", "", "10"],
            ["g_ok", "i_ok2", "known", "", "20"],
            ["g_unknown", "i_ok1", "known", "", "10"],
            ["g_unknown", "i_empty", "unknown", "no_value", ""],
            ["g_na", "i_ok1", "known", "", "10"],
            ["g_na", "i_empty", "unknown", "no_value", ""],
            ["g_invalid", "i_ok1", "known", "", "10"],
            ["g_invalid", "i_empty", "unknown", "no_value", ""],
            ["g_invalid", "i_clash", "invalid", "multiple_values", ""],
        ],
        "member_opt_score": [
            ["g_ok", "i_ok1", "known", "", "10"],
            ["g_ok", "i_ok2", "known", "", "20"],
            ["g_unknown", "i_ok1", "known", "", "10"],
            ["g_unknown", "i_empty", "not_applicable", "empty", ""],
            ["g_na", "i_ok1", "known", "", "10"],
            ["g_na", "i_empty", "not_applicable", "empty", ""],
            ["g_invalid", "i_ok1", "known", "", "10"],
            ["g_invalid", "i_empty", "not_applicable", "empty", ""],
            ["g_invalid", "i_clash", "invalid", "multiple_values", ""],
        ],
        "group_total": [
            ["g_ok", "known", "", "30"],
            ["g_unknown", "unknown", "no_value", ""],
            ["g_na", "unknown", "no_value", ""],
            ["g_invalid", "invalid", "multiple_values", ""],
        ],
        "group_opt_total": [
            ["g_ok", "known", "", "30"],
            ["g_unknown", "not_applicable", "empty", ""],
            ["g_na", "not_applicable", "empty", ""],
            ["g_invalid", "invalid", "multiple_values", ""],
        ],
    }

    def _score_w(rel: str, rid: str, item_id: str, state: str, reason: str, val: str, cands: list[str]) -> dict:
        return {
            "conclusion": _ref(rel, item_id, state, reason, val),
            "rule_id": rid,
            "bindings": [{"variable": "?id", "value": item_id}],
            "premises": [
                {"row": _ref("item", item_id), "polarity": "positive", "stratum": 0},
                *[{"row": _ref("score_cand", item_id, c), "polarity": "positive", "stratum": 0} for c in sorted(cands)],
            ],
        }

    def _member_w(rel: str, rid: str, src_rel: str, row: list[str]) -> dict:
        g, iid, st, rsn, n = row
        return {
            "conclusion": _ref(rel, *row),
            "rule_id": rid,
            "bindings": [
                {"variable": "?g", "value": g},
                {"variable": "?id", "value": iid},
                {"variable": "?st", "value": st},
                {"variable": "?rsn", "value": rsn},
                {"variable": "?n", "value": n},
            ],
            "premises": [
                {"row": _ref("member_of", g, iid), "polarity": "positive", "stratum": 0},
                {"row": _ref(src_rel, iid, st, rsn, n), "polarity": "positive", "stratum": 1},
            ],
        }

    def _group_w(rel: str, rid: str, agg_rel: str, g: str, state: str, reason: str, val: str) -> dict:
        members = sorted(
            (encode_key(r), f"known:{r[4]}" if r[2] == "known" else r[2])
            for r in rows[agg_rel] if r[0] == g
        )
        agg_result = f"known:{val}" if state == "known" else state
        return {
            "conclusion": _ref(rel, g, state, reason, val),
            "rule_id": rid,
            "bindings": [{"variable": "?g", "value": g}],
            "premises": [{"row": _ref("group_dom", g), "polarity": "positive", "stratum": 0}],
            "aggregates": [{
                "relation": agg_rel,
                "position": 0,
                "group_key": encode_key([g]),
                "count": len(members),
                "contributors_sha256": sha256_json([[k, txt] for k, txt in members]),
                "result": agg_result,
            }],
        }

    cands_map = {"i_ok1": ["10"], "i_ok2": ["20"], "i_empty": [], "i_clash": ["5", "7"]}
    witnesses = [
        *[_score_w("score_val", "score_val_r", r[0], r[1], r[2], r[3], cands_map[r[0]]) for r in rows["score_val"]],
        *[_score_w("opt_score", "opt_score_r", r[0], r[1], r[2], r[3], cands_map[r[0]]) for r in rows["opt_score"]],
        *[_member_w("member_score", "member_score_r", "score_val", r) for r in rows["member_score"]],
        *[_member_w("member_opt_score", "member_opt_score_r", "opt_score", r) for r in rows["member_opt_score"]],
        *[_group_w("group_total", "group_total_r", "member_score", *r) for r in rows["group_total"]],
        *[_group_w("group_opt_total", "group_opt_total_r", "member_opt_score", *r) for r in rows["group_opt_total"]],
    ]
    return rows, witnesses


# --- Finding 1: State-bearing aggregates & 4-state propagation in functional derivations ---

def test_state_key_recognizes_derived_and_functional_unconstrained_state():
    doc = _member_score_program()
    loaded = checker_rules.load_rules(doc)
    # Derived relation `member_score` has unconstrained `state` string column at index 2.
    assert loaded["group_total_r"].aggregates[0].state_key == 2
    assert loaded["group_opt_total_r"].aggregates[0].state_key == 2

    # Constrained `state` term ("known") is not state-bearing.
    constrained = deepcopy(doc)
    constrained["rules"][4]["aggregates"][0]["terms"] = ["?g", "_", "known", "_", "_"]
    assert checker_rules.load_rules(constrained)["group_total_r"].aggregates[0].state_key is None

    # Direct aggregate over a functional relation with unconstrained `state` (both sum and count).
    direct = deepcopy(doc)
    direct["rules"].extend([
        _rule("direct_sum", "group_total", ["?g", "?total"], [_lit("group_dom", "?g")], stratum="3",
              aggregates=[{"relation": "score_val", "terms": ["_", "_", "_", "_"],
                           "function": "sum", "over": "value", "as": "?total", "stratum": "1"}]),
        _rule("direct_count", "group_opt_total", ["?g", "?cnt"], [_lit("group_dom", "?g")], stratum="3",
              aggregates=[{"relation": "score_val", "terms": ["_", "_", "_", "_"],
                           "function": "count", "as": "?cnt", "stratum": "1"}]),
    ])
    loaded_direct = checker_rules.load_rules(direct)
    assert loaded_direct["direct_sum"].aggregates[0].state_key == 1
    assert loaded_direct["direct_count"].aggregates[0].state_key == 1

    # rezono.rules/1 derived relation with `state` column keeps v1 semantics (state_key is None).
    v1_doc = {
        "format": "rezono.rules/1",
        "relations": [
            {"name": "g", "role": "base", "key": [_col("g")]},
            {"name": "ms", "role": "derived", "key": [_col("g"), _col("state"), _col("n", "integer")]},
            {"name": "tot", "role": "derived", "key": [_col("g"), _col("total", "integer")]},
        ],
        "rules": [
            _rule("ms_r", "ms", ["?g", "known", "1"], [_lit("g", "?g")], stratum="0"),
            _rule("tot_r", "tot", ["?g", "?t"], [_lit("g", "?g")], stratum="1",
                  aggregates=[{"relation": "ms", "terms": ["?g", "_", "_"], "function": "sum",
                               "over": "n", "as": "?t", "stratum": "0"}]),
        ],
    }
    assert checker_rules.load_rules(v1_doc)["tot_r"].aggregates[0].state_key is None


def test_derived_state_bearing_aggregate_propagates_all_four_states_publish():
    doc = _member_score_program(group_policy="publish", score_policy="publish")
    rows, witnesses = _member_score_rows_and_witnesses()
    loaded = checker_rules.load_rules(doc)
    manifest, read = _manifest_and_reader(rows)
    derived = checker_rules.derived_relations(doc, loaded)

    report = check_epoch(witnesses, manifest, loaded, read, derived=derived)
    assert report["valid"], report["findings"]


@pytest.mark.parametrize("forged_state, forged_reason, forged_val", [
    ("unknown", "no_value", ""),
    ("not_applicable", "empty", ""),
    ("known", "", "10"),
])
def test_forged_non_invalid_state_when_aggregate_produces_invalid_is_rejected(
    forged_state: str, forged_reason: str, forged_val: str,
):
    """Fail-closed: forging unknown / not_applicable / known when a state-bearing aggregate
    produces `invalid` MUST be refused with `outcome_state`."""
    doc = _member_score_program(group_policy="publish", score_policy="publish")
    rows, witnesses = _member_score_rows_and_witnesses()
    rows["group_total"] = [
        ["g_invalid", forged_state, forged_reason, forged_val] if r[0] == "g_invalid" else r
        for r in rows["group_total"]
    ]
    for w in witnesses:
        if w["conclusion"]["relation"] == "group_total" and w["bindings"] == [{"variable": "?g", "value": "g_invalid"}]:
            w["conclusion"] = _ref("group_total", "g_invalid", forged_state, forged_reason, forged_val)
            w["aggregates"][0]["result"] = f"known:{forged_val}" if forged_state == "known" else forged_state

    loaded = checker_rules.load_rules(doc)
    manifest, read = _manifest_and_reader(rows)
    report = check_epoch(witnesses, manifest, loaded, read, derived=checker_rules.derived_relations(doc, loaded))
    assert not report["valid"]
    assert "outcome_state" in _errors(report), report["findings"]


def test_conflict_policy_block_rejects_propagated_invalid_aggregate():
    """Under conflict_policy=block, an invalid state propagated from a state-bearing aggregate
    blocks both check_epoch() and single-proof check() with `functional_invalid`."""
    doc = _member_score_program(group_policy="block", score_policy="publish")
    rows, witnesses = _member_score_rows_and_witnesses()
    loaded = checker_rules.load_rules(doc)
    manifest, read = _manifest_and_reader(rows)

    epoch_rep = check_epoch(witnesses, manifest, loaded, read, derived=checker_rules.derived_relations(doc, loaded))
    assert not epoch_rep["valid"]
    assert "functional_invalid" in _errors(epoch_rep), epoch_rep["findings"]

    # Also verify single-proof check() refuses the propagated invalid witness under block policy.
    inv_w = next(
        w for w in witnesses
        if w["conclusion"] == _ref("group_total", "g_invalid", "invalid", "multiple_values", "")
    )
    single_rep = check({"manifest_id": manifest["id"], "root": inv_w["conclusion"], "witnesses": [inv_w]},
                       manifest, loaded, read)
    assert not single_rep["valid"]
    assert "functional_invalid" in _errors(single_rep), single_rep["findings"]


def test_forged_empty_state_when_aggregate_propagates_unknown_is_rejected():
    """When empty_state='not_applicable', an aggregate propagating `unknown` MUST remain `unknown`."""
    doc = _member_score_program(group_policy="publish", group_empty_state="not_applicable")
    rows, witnesses = _member_score_rows_and_witnesses()
    rows["group_total"] = [
        ["g_unknown", "not_applicable", "empty", ""] if r[0] == "g_unknown" else r
        for r in rows["group_total"]
    ]
    for w in witnesses:
        if w["conclusion"]["relation"] == "group_total" and w["bindings"] == [{"variable": "?g", "value": "g_unknown"}]:
            w["conclusion"] = _ref("group_total", "g_unknown", "not_applicable", "empty", "")
            w["aggregates"][0]["result"] = "not_applicable"
    loaded = checker_rules.load_rules(doc)
    manifest, read = _manifest_and_reader(rows)
    rep = check_epoch(witnesses, manifest, loaded, read, derived=checker_rules.derived_relations(doc, loaded))
    assert not rep["valid"]
    assert "outcome_state" in _errors(rep), rep["findings"]


def test_functional_state_priority_lattice():
    """Verify full priority: invalid > conflict > unknown > not_applicable > known > empty_state."""
    func_unk = checker_rules.FunctionalSpec("f", 1, "dom", "value", "integer", "publish", "unknown", "no_value")
    func_na = checker_rules.FunctionalSpec("f", 1, "dom", "value", "integer", "publish", "not_applicable", "empty")

    # invalid beats everything (known, conflict, unknown, not_applicable).
    assert _functional_state_ok(func_unk, {"10"}, "invalid", "broken", "", {"invalid"})
    assert not _functional_state_ok(func_unk, {"10"}, "known", "", "10", {"invalid"})
    assert not _functional_state_ok(func_unk, set(), "unknown", "no_value", "", {"invalid", "unknown"})

    # conflict (>1 distinct known values) yields invalid even alongside unknown / not_applicable.
    assert _functional_state_ok(func_unk, {"10", "20"}, "invalid", "multiple_values", "", {"unknown"})
    assert not _functional_state_ok(func_unk, {"10", "20"}, "unknown", "no_value", "", {"unknown"})

    # unknown beats not_applicable and known (and ignores empty_state='not_applicable').
    assert _functional_state_ok(func_na, {"10"}, "unknown", "no_value", "", {"unknown", "not_applicable"})
    assert not _functional_state_ok(func_na, {"10"}, "known", "", "10", {"unknown"})
    assert not _functional_state_ok(func_na, set(), "not_applicable", "empty", "", {"unknown"})

    # not_applicable beats known (and ignores empty_state='unknown').
    assert _functional_state_ok(func_unk, {"10"}, "not_applicable", "empty", "", {"not_applicable"})
    assert not _functional_state_ok(func_unk, {"10"}, "known", "", "10", {"not_applicable"})
    assert not _functional_state_ok(func_unk, set(), "unknown", "no_value", "", {"not_applicable"})

    # single known value without propagated non-known state -> known.
    assert _functional_state_ok(func_unk, {"10"}, "known", "", "10", set())
    assert not _functional_state_ok(func_unk, {"10"}, "unknown", "no_value", "", set())

    # truly empty -> empty_state and empty_reason.
    assert _functional_state_ok(func_unk, set(), "unknown", "no_value", "", set())
    assert not _functional_state_ok(func_unk, set(), "not_applicable", "empty", "", set())
    assert _functional_state_ok(func_na, set(), "not_applicable", "empty", "", set())


def test_direct_count_and_malformed_state_cell_fail_closed():
    """`count` with over=None over a state-bearing relation propagates states; malformed state text fails closed."""
    doc = {
        "format": "rezono.rules/2",
        "relations": [
            {"name": "g", "role": "base", "key": [_col("g")]},
            {"name": "ms", "role": "derived", "key": [_col("g"), _col("id"), _col("state")]},
            {"name": "cnt", "role": "functional", "key": [_col("g")], "domain": "g",
             "value": _col("value", "integer"), "conflict_policy": "publish"},
        ],
        "rules": [
            _rule("ms_r", "ms", ["?g", "x", "known"], [_lit("g", "?g")], stratum="1"),
            _rule("cnt_r", "cnt", ["?g", "?n"], [_lit("g", "?g")], stratum="2",
                  aggregates=[{"relation": "ms", "terms": ["?g", "_", "_"], "function": "count",
                               "as": "?n", "stratum": "1"}]),
        ],
    }
    loaded = checker_rules.load_rules(doc)
    spec = loaded["cnt_r"].aggregates[0]
    assert spec.state_key == 2

    # Direct cells + _fold with malformed state string must fail closed as invalid.
    bad_members = [(("g1", "x", "bogus_state"), {})]
    assert evaluate._fold("count", evaluate.cells(spec, bad_members), "rezono.rules/2") == "invalid"
    unk_members = [(("g1", "x", "known"), {}), (("g1", "y", "unknown"), {})]
    assert evaluate._fold("count", evaluate.cells(spec, unk_members), "rezono.rules/2") == "unknown"


# --- Finding 2: Rational order and equality comparisons in evaluate._holds ---

@pytest.mark.parametrize("op, left, right, want", [
    # Canonical rational order and equality.
    ("lt", "1/3", "1/2", True),
    ("lt", "1/2", "1/3", False),
    ("le", "1/2", "1/2", True),
    ("ge", "3/2", "3/2", True),
    ("gt", "3/2", "1", True),
    ("gt", "1", "3/2", False),
    ("lt", "-3/2", "-4/3", True),
    ("gt", "-1/2", "-2/3", True),
    ("eq", "1/2", "1/2", True),
    ("ne", "3/2", "2", True),
    # Textual equality for eq/ne (ordinary string columns containing "2/4" vs "1/2").
    ("eq", "2/4", "1/2", False),
    ("ne", "2/4", "1/2", True),
    ("eq", "4/2", "2", False),
    ("ne", "4/2", "2", True),
    # Non-canonical fractions fail closed in order comparisons.
    ("le", "1/2", "2/4", False),
    ("ge", "2/4", "1/2", False),
    ("lt", "2/4", "1", False),
    ("lt", "4/2", "3", False),
    ("lt", "0/5", "1", False),
    ("lt", "2/1", "3", False),
    ("lt", "1/0", "2", False),
    ("lt", "1/-2", "1/2", False),
    ("lt", "1.5", "2", False),
    ("eq", "-0", "0", False),
    ("ne", "-0", "0", True),
    ("eq", "abc", "abc", True),
    ("ne", "abc", "def", True),
    ("lt", "abc", "def", False),
])
def test_evaluate_holds_rational_order_and_equality(op: str, left: str, right: str, want: bool):
    assert evaluate._holds(op, left, right) is want


def test_evaluate_holds_compare_as_keeps_typed_semantics():
    assert evaluate._holds("eq", "2/4", "1/2", compare_as="binary_text") is False
    assert evaluate._holds("lt", "abc", "def", compare_as="binary_text") is True


def test_rules_2_rational_order_conditions_in_check_and_closure():
    """rezono.rules/2 rational lt/le/gt/ge conditions hold in witness verification and closure."""
    doc = {
        "format": "rezono.rules/2",
        "relations": [
            {"name": "item", "role": "base", "key": [_col("id")]},
            {"name": "ratio", "role": "base", "key": [_col("id"), _col("r", "rational")]},
            {"name": "above_half", "role": "derived", "key": [_col("id"), _col("r", "rational")]},
            {"name": "cap_ratio", "role": "functional", "key": [_col("id")], "domain": "item",
             "value": _col("value", "rational"), "conflict_policy": "publish"},
        ],
        "rules": [
            _rule("above_half_r", "above_half", ["?id", "?r"],
                  [_lit("ratio", "?id", "?r")], stratum="1",
                  conditions=[{"op": "gt", "left": "?r", "right": "1/2"},
                              {"op": "le", "left": "?r", "right": "3/2"}]),
            _rule("cap_ratio_r", "cap_ratio", ["?id", "?r"],
                  [_lit("item", "?id"), _lit("ratio", "?id", "?r")], stratum="1",
                  conditions=[{"op": "ge", "left": "?r", "right": "-1/2"},
                              {"op": "lt", "left": "?r", "right": "2"}]),
        ],
    }
    loaded = checker_rules.load_rules(doc)
    rows = {
        "item": [["a"], ["b"], ["c"]],
        "ratio": [["a", "3/2"], ["b", "1/3"], ["c", "-3/2"]],
        "above_half": [["a", "3/2"]],
        "cap_ratio": [
            ["a", "known", "", "3/2"],
            ["b", "known", "", "1/3"],
            ["c", "unknown", "no_value", ""],
        ],
    }
    witnesses = [
        {
            "conclusion": _ref("above_half", "a", "3/2"),
            "rule_id": "above_half_r",
            "bindings": [{"variable": "?id", "value": "a"}, {"variable": "?r", "value": "3/2"}],
            "premises": [{"row": _ref("ratio", "a", "3/2"), "polarity": "positive", "stratum": 0}],
        },
        {
            "conclusion": _ref("cap_ratio", "a", "known", "", "3/2"),
            "rule_id": "cap_ratio_r",
            "bindings": [{"variable": "?id", "value": "a"}],
            "premises": [
                {"row": _ref("item", "a"), "polarity": "positive", "stratum": 0},
                {"row": _ref("ratio", "a", "3/2"), "polarity": "positive", "stratum": 0},
            ],
        },
        {
            "conclusion": _ref("cap_ratio", "b", "known", "", "1/3"),
            "rule_id": "cap_ratio_r",
            "bindings": [{"variable": "?id", "value": "b"}],
            "premises": [
                {"row": _ref("item", "b"), "polarity": "positive", "stratum": 0},
                {"row": _ref("ratio", "b", "1/3"), "polarity": "positive", "stratum": 0},
            ],
        },
        {
            "conclusion": _ref("cap_ratio", "c", "unknown", "no_value", ""),
            "rule_id": "cap_ratio_r",
            "bindings": [{"variable": "?id", "value": "c"}],
            "premises": [{"row": _ref("item", "c"), "polarity": "positive", "stratum": 0}],
        },
    ]
    manifest, read = _manifest_and_reader(rows)
    derived = checker_rules.derived_relations(doc, loaded)
    assert check_epoch(witnesses, manifest, loaded, read, derived=derived)["valid"]

    # Negative: forged witness claiming 1/3 > 1/2 fails with condition_false.
    bad_rows = deepcopy(rows)
    bad_rows["above_half"].append(["b", "1/3"])
    bad_w = {
        "conclusion": _ref("above_half", "b", "1/3"),
        "rule_id": "above_half_r",
        "bindings": [{"variable": "?id", "value": "b"}, {"variable": "?r", "value": "1/3"}],
        "premises": [{"row": _ref("ratio", "b", "1/3"), "polarity": "positive", "stratum": 0}],
    }
    bad_manifest, bad_read = _manifest_and_reader(bad_rows)
    bad_rep = check({"manifest_id": bad_manifest["id"], "root": bad_w["conclusion"], "witnesses": [bad_w]},
                    bad_manifest, loaded, bad_read)
    assert not bad_rep["valid"]
    assert "condition_false" in _errors(bad_rep), bad_rep["findings"]

    # Closure detects a missing row whose rational condition holds.
    missing_rows = deepcopy(rows)
    missing_rows["above_half"] = []
    missing_findings = closure.check(
        loaded,
        lambda rel: {encode_key(r): (tuple(r), {}) for r in missing_rows.get(rel, [])},
        read={"above_half"},
    )
    assert [(f["reason"], f["relation"], f["key"]) for f in missing_findings] == [
        ("underived_row", "above_half", encode_key(["a", "3/2"]))
    ]


# --- Finding 3: Single-proof check() transitive functional verification & aggregate binding checks ---

def test_single_proof_check_verifies_transitive_functional_dependencies():
    """Single-proof check() must verify every functional relation in closure.dependencies(rules, domains)."""
    doc = _member_score_program(group_policy="publish", score_policy="publish")
    rows, witnesses = _member_score_rows_and_witnesses()
    loaded = checker_rules.load_rules(doc)

    ok_w = next(w for w in witnesses if w["conclusion"] == _ref("group_total", "g_ok", "known", "", "30"))
    manifest, read = _manifest_and_reader(rows)
    ok_rep = check({"manifest_id": manifest["id"], "root": ok_w["conclusion"], "witnesses": [ok_w]},
                   manifest, loaded, read)
    assert ok_rep["valid"], ok_rep["findings"]

    # 1. Forged intermediate functional snapshot (`score_val` claims i_ok1=999 instead of 10),
    #    with consistent downstream `member_score` and `group_total` -> MUST fail with outcome_state!
    forged_rows = deepcopy(rows)
    forged_rows["score_val"] = [
        ["i_ok1", "known", "", "999"] if r[0] == "i_ok1" else r for r in forged_rows["score_val"]
    ]
    forged_rows["member_score"] = [
        [r[0], r[1], r[2], r[3], "999"] if r[1] == "i_ok1" else r for r in forged_rows["member_score"]
    ]
    forged_rows["group_total"] = [
        ["g_ok", "known", "", "1019"] if r[0] == "g_ok" else r for r in forged_rows["group_total"]
    ]
    members = sorted(
        (encode_key(r), f"known:{r[4]}" if r[2] == "known" else r[2])
        for r in forged_rows["member_score"] if r[0] == "g_ok"
    )
    forged_w = {
        "conclusion": _ref("group_total", "g_ok", "known", "", "1019"),
        "rule_id": "group_total_r",
        "bindings": [{"variable": "?g", "value": "g_ok"}],
        "premises": [{"row": _ref("group_dom", "g_ok"), "polarity": "positive", "stratum": 0}],
        "aggregates": [{
            "relation": "member_score", "position": 0, "group_key": encode_key(["g_ok"]),
            "count": len(members), "contributors_sha256": sha256_json([[k, txt] for k, txt in members]),
            "result": "known:1019",
        }],
    }
    f_manifest, f_read = _manifest_and_reader(forged_rows)
    f_rep = check({"manifest_id": f_manifest["id"], "root": forged_w["conclusion"], "witnesses": [forged_w]},
                  f_manifest, loaded, f_read)
    assert not f_rep["valid"]
    assert "outcome_state" in _errors(f_rep), f_rep["findings"]

    # 2. Incomplete intermediate functional snapshot (dropped `i_empty` from `score_val`) -> MUST fail with outcome_total!
    incomp_rows = deepcopy(rows)
    incomp_rows["score_val"] = [r for r in incomp_rows["score_val"] if r[0] != "i_empty"]
    incomp_rows["member_score"] = [r for r in incomp_rows["member_score"] if r[1] != "i_empty"]
    i_manifest, i_read = _manifest_and_reader(incomp_rows)
    i_rep = check({"manifest_id": i_manifest["id"], "root": ok_w["conclusion"], "witnesses": [ok_w]},
                  i_manifest, loaded, i_read)
    assert not i_rep["valid"]
    assert "outcome_total" in _errors(i_rep), i_rep["findings"]

    # 3. Upstream functional with conflict_policy=block and an invalid row -> MUST fail with functional_invalid!
    block_doc = _member_score_program(group_policy="publish", score_policy="block")
    block_loaded = checker_rules.load_rules(block_doc)
    b_rep = check({"manifest_id": manifest["id"], "root": ok_w["conclusion"], "witnesses": [ok_w]},
                  manifest, block_loaded, read)
    assert not b_rep["valid"]
    assert "functional_invalid" in _errors(b_rep), b_rep["findings"]


def test_functional_witness_rejects_forged_aggregate_bindings():
    """_check_functional_witness must verify witness bindings against matching_insts rather than
    trusting arbitrary non-key variables supplied in `theta`."""
    doc = {
        "format": "rezono.rules/2",
        "relations": [
            {"name": "dom", "role": "base", "key": [_col("k")]},
            {"name": "link", "role": "base", "key": [_col("k"), _col("g")]},
            {"name": "score", "role": "base", "key": [_col("g"), _col("row"), _col("n", "integer")]},
            {
                "name": "total", "role": "functional",
                "key": [_col("k")], "domain": "dom",
                "value": _col("value", "integer"), "conflict_policy": "publish",
            },
        ],
        "rules": [
            _rule("total_r", "total", ["?k", "?s"],
                  [_lit("dom", "?k"), _lit("link", "?k", "?g")], stratum="1",
                  aggregates=[{"relation": "score", "terms": ["?g", "_", "_"],
                               "function": "sum", "over": "n", "as": "?s", "stratum": "0"}]),
        ],
    }
    loaded = checker_rules.load_rules(doc)
    rows = {
        "dom": [["k1"], ["k_empty"]],
        "link": [["k1", "g_real"]],
        # Both g_real and g_forged sum to 10, so the forged aggregate has the exact same numeric result!
        "score": [["g_real", "r1", "10"], ["g_forged", "r1", "4"], ["g_forged", "r2", "6"]],
        "total": [["k1", "known", "", "10"], ["k_empty", "unknown", "no_value", ""]],
    }
    manifest, read = _manifest_and_reader(rows)
    derived = checker_rules.derived_relations(doc, loaded)

    def _agg_entry(g: str) -> dict:
        members = sorted((encode_key(r), f"known:{r[2]}") for r in rows["score"] if r[0] == g)
        return {
            "relation": "score", "position": 0, "group_key": encode_key([g]),
            "count": len(members), "contributors_sha256": sha256_json([[k, v] for k, v in members]),
            "result": "known:10",
        }

    empty_w = {
        "conclusion": _ref("total", "k_empty", "unknown", "no_value", ""),
        "rule_id": "total_r",
        "bindings": [{"variable": "?k", "value": "k_empty"}],
        "premises": [{"row": _ref("dom", "k_empty"), "polarity": "positive", "stratum": 0}],
    }
    honest_full_w = {
        "conclusion": _ref("total", "k1", "known", "", "10"),
        "rule_id": "total_r",
        "bindings": [{"variable": "?k", "value": "k1"}, {"variable": "?g", "value": "g_real"}],
        "premises": [
            {"row": _ref("dom", "k1"), "polarity": "positive", "stratum": 0},
            {"row": _ref("link", "k1", "g_real"), "polarity": "positive", "stratum": 0},
        ],
        "aggregates": [_agg_entry("g_real")],
    }
    honest_key_only_w = {**honest_full_w, "bindings": [{"variable": "?k", "value": "k1"}]}

    # Both honest forms pass check() and check_epoch().
    for w in (honest_full_w, honest_key_only_w):
        assert check({"manifest_id": manifest["id"], "root": w["conclusion"], "witnesses": [w]},
                     manifest, loaded, read)["valid"]
        assert check_epoch([w, empty_w], manifest, loaded, read, derived=derived)["valid"]

    # Forged witness binding `?g = g_forged` with matching `g_forged` aggregate MUST fail!
    forged_w = {
        **honest_full_w,
        "bindings": [{"variable": "?k", "value": "k1"}, {"variable": "?g", "value": "g_forged"}],
        "aggregates": [_agg_entry("g_forged")],
    }
    rep_single = check({"manifest_id": manifest["id"], "root": forged_w["conclusion"], "witnesses": [forged_w]},
                       manifest, loaded, read)
    assert not rep_single["valid"]
    assert {"premise_mismatch", "aggregate_mismatch"} <= _errors(rep_single), rep_single["findings"]

    rep_epoch = check_epoch([forged_w, empty_w], manifest, loaded, read, derived=derived)
    assert not rep_epoch["valid"]
    assert {"premise_mismatch", "aggregate_mismatch"} <= _errors(rep_epoch), rep_epoch["findings"]

    # Forged non-key binding on an empty-state witness MUST also fail!
    forged_empty_w = {
        **empty_w,
        "bindings": [{"variable": "?k", "value": "k_empty"}, {"variable": "?g", "value": "g_forged"}],
        "aggregates": [_agg_entry("g_forged")],
    }
    rep_empty = check_epoch([honest_full_w, forged_empty_w], manifest, loaded, read, derived=derived)
    assert not rep_empty["valid"]
    assert "premise_mismatch" in _errors(rep_empty), rep_empty["findings"]


def test_non_functional_derived_count_over_derived_state_column_stays_plain_count():
    """A non-functional derived rule counting over a derived relation with a `state: string` column
    keeps state_key=None and produces known:N (not four-state propagation)."""
    doc = {
        "format": "rezono.rules/2",
        "relations": [
            {"name": "g", "role": "base", "key": [_col("g")]},
            {"name": "raw", "role": "base", "key": [_col("g"), _col("id"), _col("state")]},
            {"name": "ms", "role": "derived", "key": [_col("g"), _col("id"), _col("state")]},
            {"name": "cnt", "role": "derived", "key": [_col("g"), _col("n", "integer")]},
        ],
        "rules": [
            _rule("ms_r", "ms", ["?g", "?id", "?st"], [_lit("raw", "?g", "?id", "?st")], stratum="0"),
            _rule("cnt_r", "cnt", ["?g", "?n"], [_lit("g", "?g")], stratum="1",
                  aggregates=[{"relation": "ms", "terms": ["?g", "_", "_"], "function": "count",
                               "as": "?n", "stratum": "0"}]),
        ],
    }
    loaded = checker_rules.load_rules(doc)
    assert loaded["cnt_r"].aggregates[0].state_key is None

    rows = {
        "g": [["g1"]],
        "raw": [["g1", "a", "open"], ["g1", "b", "unknown"]],
        "ms": [["g1", "a", "open"], ["g1", "b", "unknown"]],
        "cnt": [["g1", "2"]],
    }
    members = sorted(encode_key(r) for r in rows["ms"])
    witnesses = [
        {
            "conclusion": _ref("ms", "g1", "a", "open"), "rule_id": "ms_r",
            "bindings": [{"variable": "?g", "value": "g1"}, {"variable": "?id", "value": "a"},
                         {"variable": "?st", "value": "open"}],
            "premises": [{"row": _ref("raw", "g1", "a", "open"), "polarity": "positive", "stratum": 0}],
        },
        {
            "conclusion": _ref("ms", "g1", "b", "unknown"), "rule_id": "ms_r",
            "bindings": [{"variable": "?g", "value": "g1"}, {"variable": "?id", "value": "b"},
                         {"variable": "?st", "value": "unknown"}],
            "premises": [{"row": _ref("raw", "g1", "b", "unknown"), "polarity": "positive", "stratum": 0}],
        },
        {
            "conclusion": _ref("cnt", "g1", "2"), "rule_id": "cnt_r",
            "bindings": [{"variable": "?g", "value": "g1"}, {"variable": "?n", "value": "2"}],
            "premises": [{"row": _ref("g", "g1"), "polarity": "positive", "stratum": 0}],
            "aggregates": [{
                "relation": "ms", "position": 0, "group_key": encode_key(["g1"]),
                "count": 2, "contributors_sha256": sha256_json([[k] for k in members]), "result": "known:2",
            }],
        },
    ]
    manifest, read = _manifest_and_reader(rows)
    rep = check_epoch(witnesses, manifest, loaded, read, derived=checker_rules.derived_relations(doc, loaded))
    assert rep["valid"], rep["findings"]


def test_empty_min_max_non_state_bearing_vs_state_bearing_in_functional_derivation():
    """Empty min/max over a non-state-bearing base relation drops the candidate (falling back to
    empty_state or another firing rule), whereas empty min/max over a state-bearing relation
    propagates `not_applicable`."""
    doc = {
        "format": "rezono.rules/2",
        "relations": [
            {"name": "g", "role": "base", "key": [_col("g")]},
            {"name": "plain_score", "role": "base", "key": [_col("g"), _col("id"), _col("n", "integer")]},
            {"name": "fallback_val", "role": "base", "key": [_col("g"), _col("n", "integer")]},
            {"name": "state_score", "role": "derived",
             "key": [_col("g"), _col("id"), _col("state"), _col("n", "integer")]},
            {"name": "min_plain", "role": "functional", "key": [_col("g")], "domain": "g",
             "value": _col("value", "integer"), "conflict_policy": "publish", "empty_state": "unknown"},
            {"name": "min_state", "role": "functional", "key": [_col("g")], "domain": "g",
             "value": _col("value", "integer"), "conflict_policy": "publish", "empty_state": "unknown"},
        ],
        "rules": [
            _rule("state_score_r", "state_score", ["?g", "?id", "known", "?n"],
                  [_lit("plain_score", "?g", "?id", "?n")], stratum="1"),
            _rule("min_plain_agg", "min_plain", ["?g", "?m"], [_lit("g", "?g")], stratum="2",
                  aggregates=[{"relation": "plain_score", "terms": ["?g", "_", "_"],
                               "function": "min", "over": "n", "as": "?m", "stratum": "0"}]),
            _rule("min_plain_fb", "min_plain", ["?g", "?m"],
                  [_lit("g", "?g"), _lit("fallback_val", "?g", "?m")], stratum="2"),
            _rule("min_state_agg", "min_state", ["?g", "?m"], [_lit("g", "?g")], stratum="2",
                  aggregates=[{"relation": "state_score", "terms": ["?g", "_", "_", "_"],
                               "function": "min", "over": "n", "as": "?m", "stratum": "1"}]),
        ],
    }
    loaded = checker_rules.load_rules(doc)
    assert loaded["min_plain_agg"].aggregates[0].state_key is None
    assert loaded["min_state_agg"].aggregates[0].state_key == 2

    rows = {
        "g": [["g_empty"], ["g_fallback"]],
        "plain_score": [],
        "fallback_val": [["g_fallback", "42"]],
        "state_score": [],
        # Non-state-bearing empty min drops candidate: g_empty -> empty_state (unknown), g_fallback -> fallback (42).
        "min_plain": [
            ["g_empty", "unknown", "no_value", ""],
            ["g_fallback", "known", "", "42"],
        ],
        # State-bearing empty min propagates not_applicable even though empty_state="unknown".
        "min_state": [
            ["g_empty", "not_applicable", "empty", ""],
            ["g_fallback", "not_applicable", "empty", ""],
        ],
    }
    empty_digest = sha256_json([])
    witnesses = [
        {
            "conclusion": _ref("min_plain", "g_empty", "unknown", "no_value", ""),
            "rule_id": "min_plain_fb",
            "bindings": [{"variable": "?g", "value": "g_empty"}],
            "premises": [{"row": _ref("g", "g_empty"), "polarity": "positive", "stratum": 0}],
        },
        {
            "conclusion": _ref("min_plain", "g_fallback", "known", "", "42"),
            "rule_id": "min_plain_fb",
            "bindings": [{"variable": "?g", "value": "g_fallback"}],
            "premises": [
                {"row": _ref("g", "g_fallback"), "polarity": "positive", "stratum": 0},
                {"row": _ref("fallback_val", "g_fallback", "42"), "polarity": "positive", "stratum": 0},
            ],
        },
        {
            "conclusion": _ref("min_state", "g_empty", "not_applicable", "empty", ""),
            "rule_id": "min_state_agg",
            "bindings": [{"variable": "?g", "value": "g_empty"}],
            "premises": [{"row": _ref("g", "g_empty"), "polarity": "positive", "stratum": 0}],
            "aggregates": [{
                "relation": "state_score", "position": 0, "group_key": encode_key(["g_empty"]),
                "count": 0, "contributors_sha256": empty_digest, "result": "not_applicable",
            }],
        },
        {
            "conclusion": _ref("min_state", "g_fallback", "not_applicable", "empty", ""),
            "rule_id": "min_state_agg",
            "bindings": [{"variable": "?g", "value": "g_fallback"}],
            "premises": [{"row": _ref("g", "g_fallback"), "polarity": "positive", "stratum": 0}],
            "aggregates": [{
                "relation": "state_score", "position": 0, "group_key": encode_key(["g_fallback"]),
                "count": 0, "contributors_sha256": empty_digest, "result": "not_applicable",
            }],
        },
    ]
    manifest, read = _manifest_and_reader(rows)
    rep = check_epoch(witnesses, manifest, loaded, read, derived=checker_rules.derived_relations(doc, loaded))
    assert rep["valid"], rep["findings"]


@pytest.mark.parametrize("prop_state, prop_reason", [
    ("unknown", "no_value"),
    ("not_applicable", "empty"),
])
def test_forged_non_propagating_rule_citation_for_propagated_state_is_rejected(
    prop_state: str, prop_reason: str,
):
    """Citing a non-propagating rule for a propagated unknown/not_applicable state must fail
    with `premise_mismatch`."""
    doc = {
        "format": "rezono.rules/2",
        "relations": [
            {"name": "g", "role": "base", "key": [_col("g")]},
            {"name": "extra", "role": "base", "key": [_col("g"), _col("n", "integer")]},
            {"name": "ms", "role": "derived", "key": [_col("g"), _col("id"), _col("state"), _col("n", "integer")]},
            {"name": "raw", "role": "base", "key": [_col("g"), _col("id"), _col("state"), _col("n", "integer")]},
            {"name": "res", "role": "functional", "key": [_col("g")], "domain": "g",
             "value": _col("value", "integer"), "conflict_policy": "publish"},
        ],
        "rules": [
            _rule("ms_r", "ms", ["?g", "?id", "?st", "?n"], [_lit("raw", "?g", "?id", "?st", "?n")], stratum="1"),
            _rule("res_agg", "res", ["?g", "?t"], [_lit("g", "?g")], stratum="2",
                  aggregates=[{"relation": "ms", "terms": ["?g", "_", "_", "_"],
                               "function": "sum", "over": "n", "as": "?t", "stratum": "1"}]),
            _rule("res_other", "res", ["?g", "?n"], [_lit("g", "?g"), _lit("extra", "?g", "?n")], stratum="2"),
        ],
    }
    loaded = checker_rules.load_rules(doc)
    rows = {
        "g": [["g1"]],
        "extra": [],
        "raw": [["g1", "i1", prop_state, ""]],
        "ms": [["g1", "i1", prop_state, ""]],
        "res": [["g1", prop_state, prop_reason, ""]],
    }
    manifest, read = _manifest_and_reader(rows)
    derived = checker_rules.derived_relations(doc, loaded)

    ms_w = {
        "conclusion": _ref("ms", "g1", "i1", prop_state, ""),
        "rule_id": "ms_r",
        "bindings": [{"variable": "?g", "value": "g1"}, {"variable": "?id", "value": "i1"},
                     {"variable": "?st", "value": prop_state}, {"variable": "?n", "value": ""}],
        "premises": [{"row": _ref("raw", "g1", "i1", prop_state, ""), "polarity": "positive", "stratum": 0}],
    }
    honest_w = {
        "conclusion": _ref("res", "g1", prop_state, prop_reason, ""),
        "rule_id": "res_agg",
        "bindings": [{"variable": "?g", "value": "g1"}],
        "premises": [{"row": _ref("g", "g1"), "polarity": "positive", "stratum": 0}],
        "aggregates": [{
            "relation": "ms", "position": 0, "group_key": encode_key(["g1"]),
            "count": 1, "contributors_sha256": sha256_json([[encode_key(["g1", "i1", prop_state, ""]), prop_state]]),
            "result": prop_state,
        }],
    }
    assert check_epoch([ms_w, honest_w], manifest, loaded, read, derived=derived)["valid"]

    # Forged witness cites `res_other` (which did NOT propagate the state!).
    forged_w = {
        "conclusion": _ref("res", "g1", prop_state, prop_reason, ""),
        "rule_id": "res_other",
        "bindings": [{"variable": "?g", "value": "g1"}],
        "premises": [{"row": _ref("g", "g1"), "polarity": "positive", "stratum": 0}],
    }
    rep = check_epoch([ms_w, forged_w], manifest, loaded, read, derived=derived)
    assert not rep["valid"]
    assert "premise_mismatch" in _errors(rep), rep["findings"]

