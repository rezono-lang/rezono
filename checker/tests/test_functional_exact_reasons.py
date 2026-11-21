"""Exact reason codes for functional derivations on empty candidate sets and multiplicity
conflicts in the independent checker (decisions/language-rezono-1.md §§2-3; the matching
Soufflé oracle check lives in compiler/tests/test_souffle_functional.py):

- 0 candidates (empty key, no explicit empty_reason override): exact reason MUST be `"no_match"`
  for both `unknown` (`T`) and `not_applicable` (`T?`) — never `"no_value"` or a forged reason.
- >1 distinct known candidate values (conflict): exact state/reason MUST be
  `("invalid", "multiple_values")` — never a forged/arbitrary reason.
"""

from __future__ import annotations

from rezono_canon import canonical_bytes, sha256_hex
from rezono_checker import rules as checker_rules
from rezono_checker.canon import encode_key
from rezono_checker.check import check_epoch


def _col(name: str, typ: str = "string") -> dict:
    return {"name": name, "type": typ}


def _lit(rel: str, *terms: str, polarity: str = "positive", stratum: str = "0") -> dict:
    return {"relation": rel, "terms": list(terms), "polarity": polarity, "stratum": stratum}


def _rule(rid: str, head_rel: str, head_terms: list[str], body: list[dict], *, stratum: str = "1") -> dict:
    return {"id": rid, "stratum": stratum, "head": {"relation": head_rel, "terms": head_terms}, "body": body}


def _ref(relation: str, *parts: str) -> dict:
    return {"relation": relation, "key": encode_key(list(parts))}


def _functional_program(*, empty_state: str | None = None, empty_reason: str | None = None) -> dict:
    func_rel: dict[str, object] = {
        "name": "pick",
        "role": "functional",
        "key": [_col("a"), _col("b")],
        "domain": "pair_dom",
        "value": _col("value", "string"),
        "conflict_policy": "publish",
    }
    if empty_state is not None:
        func_rel["empty_state"] = empty_state
    if empty_reason is not None:
        func_rel["empty_reason"] = empty_reason
    return {
        "format": "rezono.rules/2",
        "pack": "sample",
        "relations": [
            {"name": "pair_dom", "role": "base", "key": [_col("a"), _col("b")]},
            {"name": "raw_cand", "role": "base", "key": [_col("a"), _col("b"), _col("v")]},
            {"name": "cand", "role": "derived", "key": [_col("a"), _col("b"), _col("v")]},
            func_rel,
        ],
        "rules": [
            _rule(
                "cand_r",
                "cand",
                ["?a", "?b", "?v"],
                [_lit("pair_dom", "?a", "?b"), _lit("raw_cand", "?a", "?b", "?v")],
                stratum="1",
            ),
            _rule(
                "pick_r",
                "pick",
                ["?a", "?b", "?v"],
                [_lit("pair_dom", "?a", "?b"), _lit("cand", "?a", "?b", "?v", stratum="1")],
                stratum="2",
            ),
        ],
    }


def _cand_witness(a: str, b: str, v: str) -> dict:
    return {
        "conclusion": _ref("cand", a, b, v),
        "rule_id": "cand_r",
        "bindings": [{"variable": "?a", "value": a}, {"variable": "?b", "value": b}, {"variable": "?v", "value": v}],
        "premises": [
            {"row": _ref("pair_dom", a, b), "polarity": "positive", "stratum": 0},
            {"row": _ref("raw_cand", a, b, v), "polarity": "positive", "stratum": 0},
        ],
    }


def _pick_witness(a: str, b: str, state: str, reason: str, value: str, candidates: list[str]) -> dict:
    contrib_digest = sha256_hex(canonical_bytes([{"key": [a, b, v]} for v in sorted(candidates)]))
    return {
        "conclusion": _ref("pick", a, b, state, reason, value),
        "rule_id": "pick_r",
        "bindings": [{"variable": "?a", "value": a}, {"variable": "?b", "value": b}],
        "premises": [
            {"row": _ref("pair_dom", a, b), "polarity": "positive", "stratum": 0},
            *[{"row": _ref("cand", a, b, v), "polarity": "positive", "stratum": 1} for v in sorted(candidates)],
        ],
        "aggregates": [{
            "relation": "cand",
            "position": 0,
            "group_key": encode_key([a, b]),
            "count": len(candidates),
            "contributors_sha256": contrib_digest,
            "result": f"{state}:{value}" if state == "known" else f"{state}:{reason}",
        }],
    }


def _epoch(doc: dict, rows: dict[str, list[list[str]]], witnesses: list[dict]) -> dict:
    loaded = checker_rules.load_rules(doc)
    snaps = {rel: canonical_bytes([{"key": row} for row in sorted(rs)]) for rel, rs in rows.items()}
    manifest = {
        "id": "m-fn-exact-1",
        "snapshots": [
            {
                "relation": rel,
                "role": "all",
                "complete": True,
                "uri": rel,
                "format": "json",
                "sha256": sha256_hex(body),
            }
            for rel, body in sorted(snaps.items())
        ],
    }
    derived = checker_rules.derived_relations(doc, loaded)
    return check_epoch(witnesses, manifest, loaded, snaps.__getitem__, derived=derived)


def _error_reasons(report: dict) -> set[str]:
    return {f["reason"] for f in report["findings"] if f.get("severity", "error") == "error"}


def _base_rows_and_witnesses(
    *,
    empty_state: str = "unknown",
    empty_reason: str = "no_match",
    conflict_reason: str = "multiple_values",
) -> tuple[dict[str, list[list[str]]], list[dict]]:
    rows = {
        "pair_dom": [["g1", "k1"], ["g1", "k2"], ["g1", "k3"]],
        "raw_cand": [["g1", "k1", "v1"], ["g1", "k3", "v1"], ["g1", "k3", "v2"]],
        "cand": [["g1", "k1", "v1"], ["g1", "k3", "v1"], ["g1", "k3", "v2"]],
        "pick": [
            ["g1", "k1", "known", "", "v1"],
            ["g1", "k2", empty_state, empty_reason, ""],
            ["g1", "k3", "invalid", conflict_reason, ""],
        ],
    }
    witnesses = [
        _cand_witness("g1", "k1", "v1"),
        _cand_witness("g1", "k3", "v1"),
        _cand_witness("g1", "k3", "v2"),
        _pick_witness("g1", "k1", "known", "", "v1", ["v1"]),
        _pick_witness("g1", "k2", empty_state, empty_reason, "", []),
        _pick_witness("g1", "k3", "invalid", conflict_reason, "", ["v1", "v2"]),
    ]
    return rows, witnesses


def test_checker_enforces_exact_functional_empty_and_conflict_reasons():
    # 1. Default empty_state ('unknown') with no explicit empty_reason: 'no_match' and 'multiple_values' pass.
    doc = _functional_program()
    valid_rows, valid_witnesses = _base_rows_and_witnesses(
        empty_state="unknown", empty_reason="no_match", conflict_reason="multiple_values"
    )
    rep_ok = _epoch(doc, valid_rows, valid_witnesses)
    assert rep_ok["valid"], f"valid functional epoch with no_match / multiple_values rejected: {rep_ok['findings']}"

    # 2. Forged/arbitrary reason on empty key (0 candidates) MUST be rejected.
    for bad_empty_reason in ("made_up_reason", "no_value"):
        rows, witnesses = _base_rows_and_witnesses(
            empty_state="unknown", empty_reason=bad_empty_reason, conflict_reason="multiple_values"
        )
        rep = _epoch(doc, rows, witnesses)
        assert not rep["valid"], f"checker accepted forged empty-key reason {bad_empty_reason!r}"
        assert "outcome_state" in _error_reasons(rep), (
            f"forged empty-key reason {bad_empty_reason!r} did not trigger outcome_state: {rep['findings']}"
        )

    # 3. Optional T? functional derivation (empty_state='not_applicable', no explicit empty_reason):
    #    exact 'no_match' passes; forged reason fails.
    opt_doc = _functional_program(empty_state="not_applicable")
    opt_ok_rows, opt_ok_witnesses = _base_rows_and_witnesses(
        empty_state="not_applicable", empty_reason="no_match", conflict_reason="multiple_values"
    )
    rep_opt_ok = _epoch(opt_doc, opt_ok_rows, opt_ok_witnesses)
    assert rep_opt_ok["valid"], f"valid T? functional epoch with no_match rejected: {rep_opt_ok['findings']}"

    for bad_opt_reason in ("made_up_reason", "empty"):
        opt_bad_rows, opt_bad_witnesses = _base_rows_and_witnesses(
            empty_state="not_applicable", empty_reason=bad_opt_reason, conflict_reason="multiple_values"
        )
        rep_opt_bad = _epoch(opt_doc, opt_bad_rows, opt_bad_witnesses)
        assert not rep_opt_bad["valid"], f"checker accepted forged T? empty-key reason {bad_opt_reason!r}"
        assert "outcome_state" in _error_reasons(rep_opt_bad), (
            f"forged T? empty-key reason {bad_opt_reason!r} did not trigger outcome_state: {rep_opt_bad['findings']}"
        )

    # 4. Forged/arbitrary reason on >1 distinct known candidate values (conflict) MUST be rejected.
    bad_conflict_rows, bad_conflict_witnesses = _base_rows_and_witnesses(
        empty_state="unknown", empty_reason="no_match", conflict_reason="made_up_reason"
    )
    rep_conflict = _epoch(doc, bad_conflict_rows, bad_conflict_witnesses)
    assert not rep_conflict["valid"], "checker accepted forged conflict reason 'made_up_reason' on >1 candidates"
    assert "outcome_state" in _error_reasons(rep_conflict), (
        f"forged conflict reason did not trigger outcome_state: {rep_conflict['findings']}"
    )

    # 5. Explicit empty_reason override in IR (e.g. 'empty' for min/max) remains honored and still rejects forgeries.
    explicit_doc = _functional_program(empty_state="not_applicable", empty_reason="empty")
    exp_ok_rows, exp_ok_witnesses = _base_rows_and_witnesses(
        empty_state="not_applicable", empty_reason="empty", conflict_reason="multiple_values"
    )
    assert _epoch(explicit_doc, exp_ok_rows, exp_ok_witnesses)["valid"]
    exp_bad_rows, exp_bad_witnesses = _base_rows_and_witnesses(
        empty_state="not_applicable", empty_reason="made_up_reason", conflict_reason="multiple_values"
    )
    assert not _epoch(explicit_doc, exp_bad_rows, exp_bad_witnesses)["valid"]
