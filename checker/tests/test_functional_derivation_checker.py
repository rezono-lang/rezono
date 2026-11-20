"""Independent checker verification for rezono.rules/2 functional derivations: multi-key `outcome_total` /
`outcome_state`, `conflict_policy` (`publish` vs `block`), closure coverage over `domain` + candidate/guard inputs,
strict four-state `_fold`, `may_read` / `may_read_full` refusal + filtered-role `access.py` full-read requirement
(preserving the checker/publisher boundary), proof-tree reconstruction (`proof.py`), and `transition.py` support
(decisions/language-rezono-1.md, sections 2, 3.5, 4, 5.4 and 8)."""

from __future__ import annotations

import ast
from copy import deepcopy
import hashlib
import json
from pathlib import Path

import pytest

from rezono_canon import canonical_bytes, canonical_json, canonical_sha256, sha256_hex
from rezono_checker import access, closure, evaluate, proof, rules as checker_rules, transition
from rezono_checker.canon import encode_key
from rezono_checker.check import check_epoch

ROOT = Path(__file__).resolve().parents[2]
CHECKER_SRC = ROOT / "checker" / "rezono_checker"


class MissingFunctionalDerivationChecker(AssertionError):
    """Independent checker support for rezono.rules/2 functional derivations is missing or incomplete."""


def _col(name: str, typ: str = "string") -> dict:
    return {"name": name, "type": typ}


def _lit(rel: str, *terms: str, polarity: str = "positive", stratum: str = "0") -> dict:
    return {"relation": rel, "terms": list(terms), "polarity": polarity, "stratum": stratum}


def _rule(rid: str, head_rel: str, head_terms: list[str], body: list[dict], *, stratum: str = "1") -> dict:
    return {"id": rid, "stratum": stratum, "head": {"relation": head_rel, "terms": head_terms}, "body": body}


def _ref(relation: str, *parts: str) -> dict:
    return {"relation": relation, "key": encode_key(list(parts))}


def _functional_program(*, conflict_policy: str = "publish") -> dict:
    """Two-key closed domain `pair_dom(a, b)`, derived candidate relation `cand(a, b, v)`, and functional derivation
    `pick(a, b) -> value` over `pair_dom`."""
    return {
        "format": "rezono.rules/2",
        "pack": "sample",
        "relations": [
            {"name": "pair_dom", "role": "base", "key": [_col("a"), _col("b")]},
            {"name": "raw_cand", "role": "base", "key": [_col("a"), _col("b"), _col("v")]},
            {"name": "cand", "role": "derived", "key": [_col("a"), _col("b"), _col("v")]},
            {
                "name": "pick", "role": "functional",
                "key": [_col("a"), _col("b")], "domain": "pair_dom",
                "value": _col("value", "string"), "conflict_policy": conflict_policy,
            },
        ],
        "rules": [
            _rule("cand_r", "cand", ["?a", "?b", "?v"],
                  [_lit("pair_dom", "?a", "?b"), _lit("raw_cand", "?a", "?b", "?v")], stratum="1"),
            _rule("pick_r", "pick", ["?a", "?b", "?v"],
                  [_lit("pair_dom", "?a", "?b"), _lit("cand", "?a", "?b", "?v", stratum="1")], stratum="2"),
        ],
    }


def _epoch(doc: dict, rows: dict[str, list[list[str]]], witnesses: list[dict]) -> dict:
    loaded = checker_rules.load_rules(doc)
    snaps = {rel: canonical_bytes([{"key": row} for row in sorted(rs)]) for rel, rs in rows.items()}
    manifest = {
        "id": "m-fn-1",
        "snapshots": [
            {"relation": rel, "role": "all", "complete": True, "uri": rel, "format": "json",
             "sha256": sha256_hex(body)}
            for rel, body in sorted(snaps.items())
        ],
    }
    derived = checker_rules.derived_relations(doc, loaded)
    return check_epoch(witnesses, manifest, loaded, snaps.__getitem__, derived=derived)


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


def _error_reasons(report: dict) -> set[str]:
    return {f["reason"] for f in report["findings"] if f.get("severity", "error") == "error"}


def _checker_imports_publisher() -> list[str]:
    hits = []
    for path in sorted(CHECKER_SRC.glob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and (node.module or "").split(".")[0] == "rezono_publisher":
                hits.append(f"{path.name}: from {node.module}")
            elif isinstance(node, ast.Import):
                for alias in node.names:
                    if alias.name.split(".")[0] == "rezono_publisher":
                        hits.append(f"{path.name}: import {alias.name}")
    return hits


@pytest.mark.xfail(
    strict=True,
    raises=MissingFunctionalDerivationChecker,
    reason="M3: decisions/language-rezono-1.md: Extend checker/rezono_checker/ for rezono.rules/2 `role: functional`: "
           "generalize outcome_total/outcome_state to multi-key closed domains in check.py, allow `invalid` with "
           "complete conflict witness under conflict_policy=publish while failing rezono:proofs under block, cover "
           "domain + candidate/guard inputs in closure.py, align evaluate._fold to strict four-state propagation "
           "(Appendix A.3), refuse may_read AND may_read_full on functional/calc in rules.py, enforce full-read "
           "visibility for functional derivations in access.py (without importing rezono_publisher), rebuild "
           "functional/conflict proof trees in proof.py, and admit rezono.rules/2 functional relations in "
           "transition.py. Read sections 2, 3.5, 4, 5.4 and 8. "
           "Waits for compiler/tests/test_functional_derivation_ir.py--test_functional_derivation_ir_and_stratification.",
)
def test_checker_verifies_functional_derivation_and_access():
    # Counter-case: checker never imports rezono_publisher (independent trust boundary).
    assert _checker_imports_publisher() == []

    # Counter-case: existing rezono.rules/1 check_epoch still accepts plain derived relations.
    v1_doc = {
        "format": "rezono.rules/1",
        "relations": [
            {"name": "item", "role": "base", "key": [_col("id")]},
            {"name": "seen", "role": "derived", "key": [_col("id")]},
        ],
        "rules": [_rule("seen_r", "seen", ["?x"], [_lit("item", "?x")], stratum="0")],
    }
    v1_w = [{
        "conclusion": _ref("seen", "i1"), "rule_id": "seen_r",
        "bindings": [{"variable": "?x", "value": "i1"}],
        "premises": [{"row": _ref("item", "i1"), "polarity": "positive", "stratum": 0}],
    }]
    assert _epoch(v1_doc, {"item": [["i1"]], "seen": [["i1"]]}, v1_w)["valid"]

    problems: list[str] = []

    # 1. Strict four-state `_fold` semantics (Appendix A.3 / section 5.4): not_applicable propagates!
    strict_na = evaluate._fold("sum", [{"state": "known", "value": "10"}, {"state": "not_applicable"}])
    if strict_na != "not_applicable":
        problems.append(f"evaluate._fold('sum', [known:10, not_applicable]) returned {strict_na!r}, expected 'not_applicable'")
    assert evaluate._fold("sum", [{"state": "known", "value": "10"}, {"state": "unknown"}]) == "unknown"
    assert evaluate._fold("sum", [{"state": "known", "value": "10"}, {"state": "invalid"}]) == "invalid"

    # 2. Load rezono.rules/2 functional program; verify outcome_total, outcome_state, publish vs block, and closure.
    publish_doc = _functional_program(conflict_policy="publish")
    block_doc = _functional_program(conflict_policy="block")
    base_rows = {
        "pair_dom": [["g1", "k1"], ["g1", "k2"], ["g1", "k3"]],
        "raw_cand": [["g1", "k1", "v1"], ["g1", "k3", "v1"], ["g1", "k3", "v2"]],
        "cand": [["g1", "k1", "v1"], ["g1", "k3", "v1"], ["g1", "k3", "v2"]],
        "pick": [
            ["g1", "k1", "known", "", "v1"],
            ["g1", "k2", "unknown", "no_value", ""],
            ["g1", "k3", "invalid", "multiple_values", ""],
        ],
    }
    base_witnesses = [
        _cand_witness("g1", "k1", "v1"),
        _cand_witness("g1", "k3", "v1"),
        _cand_witness("g1", "k3", "v2"),
        _pick_witness("g1", "k1", "known", "", "v1", ["v1"]),
        _pick_witness("g1", "k2", "unknown", "no_value", "", []),
        _pick_witness("g1", "k3", "invalid", "multiple_values", "", ["v1", "v2"]),
    ]

    try:
        loaded_publish = checker_rules.load_rules(publish_doc)
    except Exception as exc:
        raise MissingFunctionalDerivationChecker(f"checker_rules.load_rules rejected rezono.rules/2 functional IR: {exc}") from None

    # 2a. Valid publish epoch (with invalid multiple_values + complete conflict witness) passes.
    rep_pub = _epoch(publish_doc, base_rows, base_witnesses)
    if not rep_pub["valid"]:
        problems.append(f"conflict_policy=publish rejected valid conflict epoch: {rep_pub['findings']}")

    # 2b. Same epoch under conflict_policy=block MUST fail rezono:proofs.
    rep_blk = _epoch(block_doc, base_rows, base_witnesses)
    if rep_blk["valid"]:
        problems.append("conflict_policy=block accepted an epoch containing an invalid functional row")

    # 2c. Multi-key outcome_total: dropping one domain key row from `pick` must fail with outcome_total.
    missing_row = deepcopy(base_rows)
    missing_row["pick"] = [row for row in missing_row["pick"] if row[:2] != ["g1", "k2"]]
    missing_w = [w for w in base_witnesses if w["conclusion"] != _ref("pick", "g1", "k2", "unknown", "no_value", "")]
    rep_missing = _epoch(publish_doc, missing_row, missing_w)
    if "outcome_total" not in _error_reasons(rep_missing):
        problems.append(f"missing multi-key domain row did not trigger outcome_total: {rep_missing['findings']}")

    # 2d. Multi-key outcome_state: forging `known` when two distinct candidates exist must fail.
    forged_known = deepcopy(base_rows)
    forged_known["pick"] = [
        ["g1", "k1", "known", "", "v1"],
        ["g1", "k2", "unknown", "no_value", ""],
        ["g1", "k3", "known", "", "v1"],
    ]
    forged_known_w = [
        *base_witnesses[:-1],
        _pick_witness("g1", "k3", "known", "", "v1", ["v1"]),
    ]
    rep_forged = _epoch(publish_doc, forged_known, forged_known_w)
    if rep_forged["valid"]:
        problems.append("checker accepted forged known state when two distinct candidates exist")

    # 2e. closure.py (`covered`): covers `cand` (and `pair_dom`), so dropping a candidate row to forge `known` fails!
    covered_rels = closure.covered(loaded_publish)
    if "cand" not in covered_rels:
        problems.append(f"closure.covered omitted candidate input relation 'cand': {covered_rels!r}")
    dropped_cand = deepcopy(forged_known)
    dropped_cand["cand"] = [["g1", "k1", "v1"], ["g1", "k3", "v1"]]  # dropped ("g1", "k3", "v2")!
    dropped_cand_w = [w for w in forged_known_w if w["conclusion"] != _ref("cand", "g1", "k3", "v2")]
    rep_drop = _epoch(publish_doc, dropped_cand, dropped_cand_w)
    if "underived_row" not in _error_reasons(rep_drop):
        problems.append(f"dropping candidate row from cand was not caught by closure (underived_row): {rep_drop['findings']}")

    # 3. rules.py: refuse may_read and may_read_full depending on functional or calc.
    for access_rel, cols, head_terms in (
        ("may_read", [_col("role"), _col("kind"), _col("id")], ["?r", "item", "?a"]),
        ("may_read_full", [_col("role"), _col("kind")], ["?r", "item"]),
    ):
        acc_doc = deepcopy(publish_doc)
        acc_doc["relations"].extend([
            {"name": "role", "role": "base", "key": [_col("id")]},
            {"name": access_rel, "role": "derived", "key": cols},
        ])
        acc_doc["rules"].append(
            _rule("acc_bad", access_rel, head_terms,
                  [_lit("role", "?r"), _lit("pick", "?a", "?b", "known", "", "v1", stratum="2")], stratum="3")
        )
        try:
            checker_rules.load_rules(acc_doc)
        except ValueError:
            pass
        else:
            problems.append(f"checker_rules.load_rules accepted {access_rel} depending on functional derivation")

    # check_calc_bindings refuses may_read_full depending on a calc selection.
    calc_access_doc = {
        "format": "rezono.rules/1",
        "relations": [
            {"name": "role", "role": "base", "key": [_col("id")]},
            {"name": "calc__score", "role": "calc", "world": "open",
             "key": [_col("subject"), _col("value", "integer"), _col("state"), _col("reason")]},
            {"name": "may_read_full", "role": "derived", "key": [_col("role"), _col("kind")]},
        ],
        "rules": [
            _rule("acc_calc", "may_read_full", ["?r", "item"],
                  [_lit("role", "?r"), _lit("calc__score", "?s", "1", "known", "", stratum="0")], stratum="1"),
        ],
    }
    calc_ir = {"format": "rezono.calc-ir/1", "subject": "item", "rules": [{"view": "calc__score", "type": "number"}],
               "facts": [], "versions": []}
    try:
        checker_rules.check_calc_bindings(calc_access_doc, checker_rules.load_rules(calc_access_doc), calc_ir)
    except ValueError:
        pass
    else:
        problems.append("checker_rules.check_calc_bindings accepted may_read_full depending on calc selection")

    # 4. access.py: a filtered role sees a functional relation in `full` only when every candidate/domain input is full.
    cols_map = {
        "pair_dom": ("group", "group"),
        "raw_cand": ("group", "group", "secret"),
        "role": (None,),
    }
    full_without_secret = access.full_relations(publish_doc, cols_map, {"group"}, set(cols_map))
    if "pick" in full_without_secret:
        problems.append(f"access.full_relations marked functional 'pick' full despite hidden candidate kind: {full_without_secret!r}")
    full_with_secret = access.full_relations(publish_doc, cols_map, {"group", "secret"}, set(cols_map))
    if "pick" not in full_with_secret:
        problems.append(f"access.full_relations omitted functional 'pick' when all inputs are full: {full_with_secret!r}")

    # 5. proof.py: rebuild proof steps for functional derivation including all competing candidates in conflict witness.
    try:
        rows_decoded = {
            rel: {encode_key(row): (tuple(row), {}) for row in rs}
            for rel, rs in base_rows.items()
        }
        step_rows = proof.steps(publish_doc, base_witnesses, rows_decoded)
        conflict_key = encode_key(["g1", "k3", "invalid", "multiple_values", ""])
        conflict_targets = {
            (s[2], s[3]) for s in step_rows if s[0] == "pick" and s[1] == conflict_key
        }
        for cand_val in ("v1", "v2"):
            if ("cand", encode_key(["g1", "k3", cand_val])) not in conflict_targets:
                problems.append(f"proof.steps omitted conflict candidate {cand_val!r} from rebuilt proof tree: {conflict_targets!r}")
    except Exception as exc:
        problems.append(f"proof.steps failed on rezono.rules/2 functional witnesses: {exc}")

    # 6. transition.py: admit rezono.rules/2 program with `role: functional` for safe steps and invariants.
    trans_prog = {
        "format": "rezono.rules/2",
        "relations": [
            {"name": "item", "role": "base", "key": [_col("id")]},
            {"name": "item__tag", "role": "base", "key": [_col("id"), _col("tag")]},
            {
                "name": "tag_fn", "role": "functional",
                "key": [_col("id")], "domain": "item",
                "value": _col("value", "string"), "conflict_policy": "publish",
            },
            {"name": "bad_tag", "role": "derived", "key": [_col("id")], "invariant": True},
        ],
        "rules": [
            _rule("tag_fn_r", "tag_fn", ["?x", "?t"], [_lit("item", "?x"), _lit("item__tag", "?x", "?t")], stratum="1"),
            _rule("bad_tag_r", "bad_tag", ["?x"], [_lit("tag_fn", "?x", "known", "", "blocked", stratum="1")], stratum="2"),
        ],
    }

    def _state(sid: str, tag: str) -> dict:
        digest = sha256_hex(canonical_bytes([{"key": ["i1", tag]}]))
        w = {
            "conclusion": _ref("tag_fn", "i1", "known", "", tag),
            "rule_id": "tag_fn_r",
            "bindings": [{"variable": "?x", "value": "i1"}],
            "premises": [
                {"row": _ref("item", "i1"), "polarity": "positive", "stratum": 0},
                {"row": _ref("item__tag", "i1", tag), "polarity": "positive", "stratum": 0},
            ],
            "aggregates": [{
                "relation": "item__tag", "position": 0, "group_key": encode_key(["i1"]),
                "count": 1, "contributors_sha256": digest, "result": f"known:{tag}",
            }],
        }
        return {
            "id": sid,
            "rows": {
                "item": [("i1",)],
                "item__tag": [("i1", tag)],
                "tag_fn": [("i1", "known", "", tag)],
                "bad_tag": [],
            },
            "witnesses": [w],
        }

    obs = {"obs-1": b'{"id":"obs-1","scope":"items","run":"run-1"}'}
    cut = {"run": "run-1", "scope": "items", "id": "cut-1", "observation_sha256": sha256_hex(obs["obs-1"])}
    before, after = _state("base", "open"), _state("variant", "closed")
    ctx = {
        "manifest": "m-t1", "cut": cut, "definition_sha256": canonical_sha256(trans_prog),
        "observations": obs, "program": trans_prog, "invariants": ("bad_tag",),
    }
    cert = {
        "manifest": "m-t1", "run": "run-1", "cut": "cut-1",
        "definition_sha256": ctx["definition_sha256"],
        "base": canonical_sha256(before), "variant": canonical_sha256(after),
        "rule": "set_tag", "bindings": {"item": "i1"}, "effect": "set-tag-i1",
        "expected_old": [{"relation": "item__tag", "key": canonical_json(["i1", "open"])}],
        "delta": [("item__tag", ("i1", "open"), -1), ("item__tag", ("i1", "closed"), 1)],
        "invariants": {"bad_tag": {"rows": [], "count": "0"}},
    }
    tr = transition.check_transition_certificate(cert, ctx, before, after)
    if not tr["valid"]:
        problems.append(f"transition.check_transition_certificate rejected valid rezono.rules/2 functional transition: {tr['findings']}")

    # Re-verify boundary after all checks.
    assert _checker_imports_publisher() == []

    if problems:
        raise MissingFunctionalDerivationChecker("\n".join(problems))
