"""Independent checker parity tests for rezono.rules/2 rational functional derivations:
- In rezono.rules/2 (no rational arithmetic), every rational head value is a base/input fact:
  non-positive denominators (0 or negative) and reduced fractions outside [-BOUND, +BOUND]
  (e.g. -2^63 / 1, +2^63, or d > 2^63 - 1, while -2^63 / 2 reduces to -2^62 / 1 within BOUND)
  are input violations yielding invalid with empty reason (decisions/language-rezono-1-refinements.md
  §3.4C), accepted under publish and rejected under conflict_policy=block (`functional_invalid`).
- Distinct valid rational candidates yield invalid/multiple_values.
- Forged reasons (including invented codes like `invalid_rational`), forged `unknown/beyond_exact_bound`
  or `known` states on out-of-bound base facts, forged downgrades over state-bearing aggregates,
  and omitted premises are rejected.
"""

from __future__ import annotations

from copy import deepcopy

import pytest

from rezono_canon import canonical_bytes, sha256_hex
from rezono_checker import rules as checker_rules
from rezono_checker.canon import encode_key, sha256_json
from rezono_checker.check import check, check_epoch


def _col(name: str, typ: str = "string") -> dict:
    return {"name": name, "type": typ}


def _lit(rel: str, *terms: str, polarity: str = "positive", stratum: str = "0") -> dict:
    return {"relation": rel, "terms": list(terms), "polarity": polarity, "stratum": stratum}


def _rule(rid: str, head_rel: str, head_terms: list[str], body: list[dict], *, stratum: str = "1") -> dict:
    return {"id": rid, "stratum": stratum, "head": {"relation": head_rel, "terms": head_terms}, "body": body}


def _ref(relation: str, *parts: str) -> dict:
    return {"relation": relation, "key": encode_key(list(parts))}


def _rational_program(*, conflict_policy: str = "publish") -> dict:
    return {
        "format": "rezono.rules/2",
        "pack": "sample",
        "relations": [
            {"name": "item", "role": "base", "key": [_col("id")]},
            {"name": "ratio_in", "role": "base", "key": [_col("id"), _col("r", "rational")]},
            {
                "name": "ratio_val", "role": "functional",
                "key": [_col("id")], "domain": "item",
                "value": _col("value", "rational"), "conflict_policy": conflict_policy,
            },
        ],
        "rules": [
            _rule("ratio_val_r", "ratio_val", ["?id", "?r"],
                  [_lit("item", "?id"), _lit("ratio_in", "?id", "?r")], stratum="1"),
        ],
    }


def _manifest_and_reader(rows: dict[str, list[list[str]]]):
    snaps = {rel: canonical_bytes([{"key": row} for row in sorted(rs)]) for rel, rs in rows.items()}
    manifest = {
        "id": "m-rat-parity-1",
        "snapshots": [
            {"relation": rel, "role": "all", "complete": True, "uri": rel, "format": "json",
             "sha256": sha256_hex(body)}
            for rel, body in sorted(snaps.items())
        ],
    }
    return manifest, snaps.__getitem__


def _errors(report: dict) -> set[str]:
    return {f["reason"] for f in report["findings"] if f.get("severity", "error") == "error"}


def _ratio_witness(iid: str, state: str, reason: str, val: str, ratio_premises: list[str], *,
                   rule_id: str = "ratio_val_r", bindings: list[dict] | None = None) -> dict:
    return {
        "conclusion": _ref("ratio_val", iid, state, reason, val),
        "rule_id": rule_id,
        "bindings": bindings if bindings is not None else [{"variable": "?id", "value": iid}],
        "premises": [
            {"row": _ref("item", iid), "polarity": "positive", "stratum": 0},
            *[{"row": _ref("ratio_in", iid, r), "polarity": "positive", "stratum": 0} for r in sorted(ratio_premises)],
        ],
    }


def _full_rows_and_witnesses() -> tuple[dict[str, list[list[str]]], list[dict]]:
    max_bound = str(2**63 - 1)
    min_bound = str(-(2**63 - 1))
    min_i64 = str(-(2**63))
    half_min = str(-(2**62))
    big_den = f"1/{2**63}"
    rows = {
        "item": [
            ["i_ok"],
            ["i_unreduced"],
            ["i_max_bound"],
            ["i_min_bound"],
            ["i_reducible_min"],
            ["i_oob"],
            ["i_oob_den"],
            ["i_mixed_oob"],
            ["i_zero_den"],
            ["i_neg_den"],
            ["i_mixed_bad"],
            ["i_conflict"],
            ["i_conflict_oob"],
            ["i_empty"],
        ],
        "ratio_in": [
            ["i_ok", "3/2"],
            ["i_unreduced", "4/6"],
            ["i_max_bound", max_bound],
            ["i_min_bound", min_bound],
            ["i_reducible_min", f"{min_i64}/2"],
            ["i_oob", min_i64],
            ["i_oob_den", big_den],
            ["i_mixed_oob", "1/2"],
            ["i_mixed_oob", min_i64],
            ["i_zero_den", "1/0"],
            ["i_neg_den", "1/-2"],
            ["i_mixed_bad", "1/2"],
            ["i_mixed_bad", "1/0"],
            ["i_conflict", "1/2"],
            ["i_conflict", "3/4"],
            ["i_conflict_oob", "1/2"],
            ["i_conflict_oob", "3/4"],
            ["i_conflict_oob", min_i64],
        ],
        "ratio_val": [
            ["i_ok", "known", "", "3/2"],
            ["i_unreduced", "known", "", "2/3"],
            ["i_max_bound", "known", "", max_bound],
            ["i_min_bound", "known", "", min_bound],
            ["i_reducible_min", "known", "", half_min],
            ["i_oob", "invalid", "", ""],
            ["i_oob_den", "invalid", "", ""],
            ["i_mixed_oob", "invalid", "", ""],
            ["i_zero_den", "invalid", "", ""],
            ["i_neg_den", "invalid", "", ""],
            ["i_mixed_bad", "invalid", "", ""],
            ["i_conflict", "invalid", "multiple_values", ""],
            # More than one distinct known candidate yields invalid/multiple_values (decisions/language-rezono-1.md §4).
            ["i_conflict_oob", "invalid", "multiple_values", ""],
            ["i_empty", "unknown", "no_value", ""],
        ],
    }
    witnesses = [
        _ratio_witness("i_ok", "known", "", "3/2", ["3/2"]),
        _ratio_witness("i_unreduced", "known", "", "2/3", ["4/6"]),
        _ratio_witness("i_max_bound", "known", "", max_bound, [max_bound]),
        _ratio_witness("i_min_bound", "known", "", min_bound, [min_bound]),
        _ratio_witness("i_reducible_min", "known", "", half_min, [f"{min_i64}/2"]),
        _ratio_witness("i_oob", "invalid", "", "", [min_i64]),
        _ratio_witness("i_oob_den", "invalid", "", "", [big_den]),
        _ratio_witness("i_mixed_oob", "invalid", "", "", ["1/2", min_i64]),
        _ratio_witness("i_zero_den", "invalid", "", "", ["1/0"]),
        _ratio_witness("i_neg_den", "invalid", "", "", ["1/-2"]),
        _ratio_witness("i_mixed_bad", "invalid", "", "", ["1/2", "1/0"]),
        _ratio_witness("i_conflict", "invalid", "multiple_values", "", ["1/2", "3/4"]),
        _ratio_witness("i_conflict_oob", "invalid", "multiple_values", "", ["1/2", "3/4", min_i64]),
        _ratio_witness("i_empty", "unknown", "no_value", "", []),
    ]
    return rows, witnesses


def test_checker_accepts_rational_base_fact_bounds_and_invalid_denominator_under_publish():
    doc = _rational_program(conflict_policy="publish")
    loaded = checker_rules.load_rules(doc)
    rows, witnesses = _full_rows_and_witnesses()
    manifest, read = _manifest_and_reader(rows)
    derived = checker_rules.derived_relations(doc, loaded)

    rep = check_epoch(witnesses, manifest, loaded, read, derived=derived)
    assert rep["valid"], rep["findings"]

    # Single-proof check() also accepts each individual rational witness.
    for w in witnesses:
        single = check({"manifest_id": manifest["id"], "root": w["conclusion"], "witnesses": [w]},
                       manifest, loaded, read)
        assert single["valid"], (w["conclusion"], single["findings"])


@pytest.mark.parametrize("bad_input", [str(-(2**63)), str(2**63), f"1/{2**63}", "1/0", "1/-2"])
def test_checker_block_policy_blocks_out_of_bound_and_bad_denominator_base_facts(bad_input: str):
    doc = _rational_program(conflict_policy="block")
    loaded = checker_rules.load_rules(doc)
    derived = checker_rules.derived_relations(doc, loaded)

    rows = {
        "item": [["i_bad"]],
        "ratio_in": [["i_bad", bad_input]],
        "ratio_val": [["i_bad", "invalid", "", ""]],
    }
    witnesses = [_ratio_witness("i_bad", "invalid", "", "", [bad_input])]
    manifest, read = _manifest_and_reader(rows)
    rep = check_epoch(witnesses, manifest, loaded, read, derived=derived)
    assert not rep["valid"]
    assert _errors(rep) == {"functional_invalid"}, rep["findings"]


def test_checker_block_policy_accepts_exact_bounds_and_reducible_min_i64():
    max_bound = str(2**63 - 1)
    min_bound = str(-(2**63 - 1))
    min_i64 = str(-(2**63))
    half_min = str(-(2**62))
    doc = _rational_program(conflict_policy="block")
    loaded = checker_rules.load_rules(doc)
    derived = checker_rules.derived_relations(doc, loaded)

    rows = {
        "item": [["i_max_bound"], ["i_min_bound"], ["i_reducible_min"]],
        "ratio_in": [
            ["i_max_bound", max_bound],
            ["i_min_bound", min_bound],
            ["i_reducible_min", f"{min_i64}/2"],
        ],
        "ratio_val": [
            ["i_max_bound", "known", "", max_bound],
            ["i_min_bound", "known", "", min_bound],
            ["i_reducible_min", "known", "", half_min],
        ],
    }
    witnesses = [
        _ratio_witness("i_max_bound", "known", "", max_bound, [max_bound]),
        _ratio_witness("i_min_bound", "known", "", min_bound, [min_bound]),
        _ratio_witness("i_reducible_min", "known", "", half_min, [f"{min_i64}/2"]),
    ]
    manifest, read = _manifest_and_reader(rows)
    rep = check_epoch(witnesses, manifest, loaded, read, derived=derived)
    assert rep["valid"], rep["findings"]


@pytest.mark.parametrize("bad_input, forged_state, forged_reason, forged_val", [
    (str(-(2**63)), "unknown", "beyond_exact_bound", ""),
    (str(-(2**63)), "unknown", "no_value", ""),
    (str(-(2**63)), "unknown", "made_up_reason", ""),
    (str(-(2**63)), "unknown", "", ""),
    (str(-(2**63)), "invalid", "invalid_rational", ""),
    (str(-(2**63)), "invalid", "made_up_reason", ""),
    (str(-(2**63)), "invalid", "multiple_values", ""),
    (str(-(2**63)), "known", "", str(-(2**63))),
    ("1/0", "invalid", "invalid_rational", ""),
    ("1/0", "invalid", "made_up_reason", ""),
    ("1/0", "invalid", "multiple_values", ""),
    ("1/0", "unknown", "beyond_exact_bound", ""),
    ("1/-2", "invalid", "invalid_rational", ""),
    ("1/-2", "known", "", "-1/2"),
])
def test_checker_rejects_forged_reason_or_state_on_invalid_rational_base_fact(
    bad_input: str, forged_state: str, forged_reason: str, forged_val: str,
):
    doc = _rational_program(conflict_policy="publish")
    loaded = checker_rules.load_rules(doc)
    derived = checker_rules.derived_relations(doc, loaded)

    rows = {
        "item": [["i_bad"]],
        "ratio_in": [["i_bad", bad_input]],
        "ratio_val": [["i_bad", forged_state, forged_reason, forged_val]],
    }
    witnesses = [_ratio_witness("i_bad", forged_state, forged_reason, forged_val, [bad_input])]
    manifest, read = _manifest_and_reader(rows)

    rep = check_epoch(witnesses, manifest, loaded, read, derived=derived)
    assert not rep["valid"], f"accepted forged row {(bad_input, forged_state, forged_reason, forged_val)!r}"
    assert "outcome_state" in _errors(rep), rep["findings"]


def test_checker_rejects_omitted_premise_forged_rule_citation_and_forged_known_on_out_of_bound_base_fact():
    min_i64 = str(-(2**63))
    doc = _rational_program(conflict_policy="publish")
    doc["relations"].append({"name": "ratio_alt", "role": "base", "key": [_col("id"), _col("r", "rational")]})
    doc["rules"].append(
        _rule("ratio_alt_r", "ratio_val", ["?id", "?r"],
              [_lit("item", "?id"), _lit("ratio_alt", "?id", "?r")], stratum="1")
    )
    loaded = checker_rules.load_rules(doc)
    derived = checker_rules.derived_relations(doc, loaded)

    rows = {
        "item": [["i_oob"]],
        "ratio_in": [["i_oob", min_i64]],
        "ratio_alt": [["i_oob", "1/2"]],
        "ratio_val": [["i_oob", "invalid", "", ""]],
    }
    manifest, read = _manifest_and_reader(rows)

    # Honest witness citing both the valid alt premise and the out-of-bound premise passes.
    honest_w = [{
        "conclusion": _ref("ratio_val", "i_oob", "invalid", "", ""),
        "rule_id": "ratio_val_r",
        "bindings": [{"variable": "?id", "value": "i_oob"}],
        "premises": [
            {"row": _ref("item", "i_oob"), "polarity": "positive", "stratum": 0},
            {"row": _ref("ratio_alt", "i_oob", "1/2"), "polarity": "positive", "stratum": 0},
            {"row": _ref("ratio_in", "i_oob", min_i64), "polarity": "positive", "stratum": 0},
        ],
    }]
    assert check_epoch(honest_w, manifest, loaded, read, derived=derived)["valid"]

    # Omitting the out-of-bound premise fails with premise_mismatch.
    omitted_w = [_ratio_witness("i_oob", "invalid", "", "", [])]
    rep_omitted = check_epoch(omitted_w, manifest, loaded, read, derived=derived)
    assert not rep_omitted["valid"]
    assert "premise_mismatch" in _errors(rep_omitted), rep_omitted["findings"]

    # Citing `ratio_alt_r` without the candidate premises fails with premise_mismatch.
    forged_rule_w = [_ratio_witness("i_oob", "invalid", "", "", [], rule_id="ratio_alt_r")]
    rep_forged = check_epoch(forged_rule_w, manifest, loaded, read, derived=derived)
    assert not rep_forged["valid"]
    assert "premise_mismatch" in _errors(rep_forged), rep_forged["findings"]

    # Forging `known` "1/2" when another rule carries an out-of-bound base fact fails with outcome_state.
    forged_known = deepcopy(rows)
    forged_known["ratio_val"] = [["i_oob", "known", "", "1/2"]]
    forged_known_w = [{
        "conclusion": _ref("ratio_val", "i_oob", "known", "", "1/2"),
        "rule_id": "ratio_alt_r",
        "bindings": [{"variable": "?id", "value": "i_oob"}],
        "premises": [
            {"row": _ref("item", "i_oob"), "polarity": "positive", "stratum": 0},
            {"row": _ref("ratio_alt", "i_oob", "1/2"), "polarity": "positive", "stratum": 0},
        ],
    }]
    m_fk, r_fk = _manifest_and_reader(forged_known)
    rep_fk = check_epoch(forged_known_w, m_fk, loaded, r_fk, derived=derived)
    assert not rep_fk["valid"]
    assert "outcome_state" in _errors(rep_fk), rep_fk["findings"]

    # When >1 distinct known candidates also exist alongside an out-of-bound base fact, empty reason
    # cannot mask `multiple_values` (decisions/language-rezono-1.md §4).
    conflict_rows = {
        "item": [["i_conflict_oob"]],
        "ratio_in": [["i_conflict_oob", "1/2"], ["i_conflict_oob", "3/4"], ["i_conflict_oob", min_i64]],
        "ratio_alt": [],
        "ratio_val": [["i_conflict_oob", "invalid", "", ""]],
    }
    conflict_w = [_ratio_witness("i_conflict_oob", "invalid", "", "", ["1/2", "3/4", min_i64])]
    m_co, r_co = _manifest_and_reader(conflict_rows)
    rep_co = check_epoch(conflict_w, m_co, loaded, r_co, derived=derived)
    assert not rep_co["valid"]
    assert "outcome_state" in _errors(rep_co), rep_co["findings"]


def _state_agg_rational_program(*, conflict_policy: str = "publish") -> dict:
    """Rational functional rule combining a state-bearing count aggregate over `flag_state`
    (yielding `not_applicable` or `unknown`) with a rational head term `?r` from `ratio_in`."""
    return {
        "format": "rezono.rules/2",
        "pack": "sample",
        "relations": [
            {"name": "item", "role": "base", "key": [_col("id")]},
            {"name": "ratio_in", "role": "base", "key": [_col("id"), _col("r", "rational")]},
            {"name": "flag_raw", "role": "base", "key": [_col("id"), _col("tag"), _col("state"), _col("reason")]},
            {"name": "flag_state", "role": "derived", "key": [_col("id"), _col("tag"), _col("state"), _col("reason")]},
            {
                "name": "ratio_val", "role": "functional",
                "key": [_col("id")], "domain": "item",
                "value": _col("value", "rational"), "conflict_policy": conflict_policy,
            },
        ],
        "rules": [
            _rule("flag_state_r", "flag_state", ["?id", "?tag", "?st", "?rsn"],
                  [_lit("flag_raw", "?id", "?tag", "?st", "?rsn")], stratum="1"),
            {
                "id": "ratio_val_r",
                "stratum": "2",
                "head": {"relation": "ratio_val", "terms": ["?id", "?r"]},
                "body": [_lit("item", "?id"), _lit("ratio_in", "?id", "?r")],
                "aggregates": [{
                    "relation": "flag_state",
                    "terms": ["?id", "_", "_", "_"],
                    "function": "count",
                    "as": "?cnt",
                    "stratum": "1",
                }],
            },
        ],
    }


def test_checker_worst_state_combines_non_known_aggregate_with_rational_classification():
    """Regression test: when a rational functional rule has a non-known state-bearing aggregate
    (e.g. `not_applicable` or `unknown`), `_functional_candidates` must still classify the rational
    head term so invalid base facts (`1/0`, `-2^63`) elevate to `invalid/""` matching SQL
    `GREATEST(agg_st, rat_st)`, block under `conflict_policy=block`, and fail closed against
    forged downgrades."""
    min_i64 = str(-(2**63))

    def _flag_w(iid: str, tag: str, st: str, rsn: str) -> dict:
        return {
            "conclusion": _ref("flag_state", iid, tag, st, rsn),
            "rule_id": "flag_state_r",
            "bindings": [
                {"variable": "?id", "value": iid},
                {"variable": "?tag", "value": tag},
                {"variable": "?st", "value": st},
                {"variable": "?rsn", "value": rsn},
            ],
            "premises": [{"row": _ref("flag_raw", iid, tag, st, rsn), "polarity": "positive", "stratum": 0}],
        }

    def _agg_ratio_w(iid: str, state: str, reason: str, val: str, rat: str,
                     agg_row: list[str], agg_result: str) -> dict:
        member_key = encode_key(agg_row)
        return {
            "conclusion": _ref("ratio_val", iid, state, reason, val),
            "rule_id": "ratio_val_r",
            "bindings": [{"variable": "?id", "value": iid}],
            "premises": [
                {"row": _ref("item", iid), "polarity": "positive", "stratum": 0},
                {"row": _ref("ratio_in", iid, rat), "polarity": "positive", "stratum": 0},
            ],
            "aggregates": [{
                "relation": "flag_state",
                "position": 0,
                "group_key": encode_key([iid]),
                "count": 1,
                "contributors_sha256": sha256_json([[member_key, agg_result]]),
                "result": agg_result,
            }],
        }

    # 1. Honest SQL output across all 4 combinations passes under conflict_policy=publish.
    pub_doc = _state_agg_rational_program(conflict_policy="publish")
    pub_loaded = checker_rules.load_rules(pub_doc)
    pub_derived = checker_rules.derived_relations(pub_doc, pub_loaded)
    flags = [
        ["i_na_ok", "t1", "not_applicable", "empty"],
        ["i_na_div0", "t1", "not_applicable", "empty"],
        ["i_na_oob", "t1", "not_applicable", "empty"],
        ["i_unk_oob", "t1", "unknown", "no_value"],
    ]
    rows = {
        "item": [["i_na_ok"], ["i_na_div0"], ["i_na_oob"], ["i_unk_oob"]],
        "ratio_in": [
            ["i_na_ok", "3/2"],
            ["i_na_div0", "1/0"],
            ["i_na_oob", min_i64],
            ["i_unk_oob", min_i64],
        ],
        "flag_raw": flags,
        "flag_state": flags,
        "ratio_val": [
            ["i_na_ok", "not_applicable", "empty", ""],
            ["i_na_div0", "invalid", "", ""],
            ["i_na_oob", "invalid", "", ""],
            ["i_unk_oob", "invalid", "", ""],
        ],
    }
    witnesses = [
        *[_flag_w(*r) for r in flags],
        _agg_ratio_w("i_na_ok", "not_applicable", "empty", "", "3/2", flags[0], "not_applicable"),
        _agg_ratio_w("i_na_div0", "invalid", "", "", "1/0", flags[1], "not_applicable"),
        _agg_ratio_w("i_na_oob", "invalid", "", "", min_i64, flags[2], "not_applicable"),
        _agg_ratio_w("i_unk_oob", "invalid", "", "", min_i64, flags[3], "unknown"),
    ]
    manifest, read = _manifest_and_reader(rows)
    rep_pub = check_epoch(witnesses, manifest, pub_loaded, read, derived=pub_derived)
    assert rep_pub["valid"], rep_pub["findings"]
    for w in witnesses[-4:]:
        single = check({"manifest_id": manifest["id"], "root": w["conclusion"], "witnesses": [w]},
                       manifest, pub_loaded, read)
        assert single["valid"], (w["conclusion"], single["findings"])

    # 2. Under conflict_policy=block: all three invalid rational base facts trigger functional_invalid.
    blk_doc = _state_agg_rational_program(conflict_policy="block")
    blk_loaded = checker_rules.load_rules(blk_doc)
    blk_derived = checker_rules.derived_relations(blk_doc, blk_loaded)

    for iid, rat, flag_row, agg_res in (
        ("i_na_div0", "1/0", flags[1], "not_applicable"),
        ("i_na_oob", min_i64, flags[2], "not_applicable"),
        ("i_unk_oob", min_i64, flags[3], "unknown"),
    ):
        blk_rows = {
            "item": [[iid]],
            "ratio_in": [[iid, rat]],
            "flag_raw": [flag_row],
            "flag_state": [flag_row],
            "ratio_val": [[iid, "invalid", "", ""]],
        }
        blk_w = [_flag_w(*flag_row), _agg_ratio_w(iid, "invalid", "", "", rat, flag_row, agg_res)]
        m_blk, r_blk = _manifest_and_reader(blk_rows)
        rep_blk = check_epoch(blk_w, m_blk, blk_loaded, r_blk, derived=blk_derived)
        assert not rep_blk["valid"]
        assert _errors(rep_blk) == {"functional_invalid"}, rep_blk["findings"]

    # 3. Fail-closed: forging downgraded `not_applicable` or `unknown` to hide `1/0` or `-2^63` MUST fail
    #    with `outcome_state` (including blocking attempts to bypass conflict_policy=block!).
    forged_cases = [
        ("i_na_div0", "1/0", flags[1], "not_applicable", "not_applicable", "empty"),
        ("i_na_oob", min_i64, flags[2], "not_applicable", "not_applicable", "empty"),
        ("i_na_oob", min_i64, flags[2], "not_applicable", "unknown", "beyond_exact_bound"),
        ("i_unk_oob", min_i64, flags[3], "unknown", "unknown", "no_value"),
        ("i_unk_oob", min_i64, flags[3], "unknown", "unknown", "beyond_exact_bound"),
    ]
    for iid, rat, flag_row, agg_res, forged_st, forged_rsn in forged_cases:
        f_rows = {
            "item": [[iid]],
            "ratio_in": [[iid, rat]],
            "flag_raw": [flag_row],
            "flag_state": [flag_row],
            "ratio_val": [[iid, forged_st, forged_rsn, ""]],
        }
        f_w = [_flag_w(*flag_row), _agg_ratio_w(iid, forged_st, forged_rsn, "", rat, flag_row, agg_res)]
        m_f, r_f = _manifest_and_reader(f_rows)
        for loaded_prog, derived_rels in ((pub_loaded, pub_derived), (blk_loaded, blk_derived)):
            rep_f = check_epoch(f_w, m_f, loaded_prog, r_f, derived=derived_rels)
            assert not rep_f["valid"], f"accepted forged downgrade {(iid, rat, forged_st, forged_rsn)!r}"
            assert "outcome_state" in _errors(rep_f), rep_f["findings"]
