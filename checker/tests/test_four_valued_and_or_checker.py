"""Independent checker parity for the four-valued `and`/`or` truth tables and Appendix A.4 reason choice.

Reads the shared conformance cases (`tests/conformance/value-tt-and-false-invalid.yaml` and
`tests/conformance/value-tt-or-true-invalid.yaml`) directly without importing `rezono_compiler`, and checks
`rezono_checker.calc.logic`, `worst_of`, `apply`, and end-to-end `calc.check` against
`decisions/four-valued-and-or-parity.md` and `docs/rezono/expressions.md` Appendix A.1 and A.4.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from rezono_checker import calc
from rezono_checker.canon import encode_key

ROOT = Path(__file__).resolve().parents[2]
CORPUS = ROOT / "tests" / "conformance"


class CheckerFourValuedParityError(AssertionError):
    """`checker/rezono_checker/calc.py` diverges from Appendix A.1 or Appendix A.4."""


def _load_case(case_id: str) -> dict:
    return yaml.safe_load((CORPUS / f"{case_id}.yaml").read_text(encoding="utf-8"))


def _binding_val(raw) -> calc.Val:
    if isinstance(raw, bool):
        return calc.known(raw)
    assert isinstance(raw, dict) and "state" in raw
    return calc.Val(raw["state"], None, raw.get("reason") or "")


def _expect_val(expect: dict) -> calc.Val:
    if expect["state"] == "known":
        return calc.known(expect["value"])
    return calc.Val(expect["state"], None, expect.get("reason") or "")


def _ir_and_snapshots():
    """Minimal self-contained rezono.calc-ir/1 program and snapshots for end-to-end `calc.check`."""
    div0_eq = {"op": "eq", "args": [{"op": "ratio", "args": [{"integer": "1"}, {"integer": "1"}, {"integer": "0"}]}, {"integer": "0"}]}
    bad_amount_eq = {"op": "eq", "args": [{"fact": "item.amount"}, {"integer": "0"}]}
    ir_doc = {
        "format": "rezono.calc-ir/1",
        "pack": "calc",
        "subject": "item",
        "subject_table": "item",
        "as_of": "calc__as_of",
        "facts": [
            {"id": "item.amount", "index": 1, "reads": "attribute", "table": "item__amount", "type": "number"},
            {"id": "item.flag", "index": 1, "reads": "attribute", "table": "item__flag", "type": "boolean"},
        ],
        "rules": [
            {"rule": "and_false_invalid", "type": "boolean", "versions": ["and_false_invalid@v1"], "view": "calc__and_false_invalid"},
            {"rule": "or_true_invalid", "type": "boolean", "versions": ["or_true_invalid@v1"], "view": "calc__or_true_invalid"},
            {"rule": "and_reason_tie", "type": "boolean", "versions": ["and_reason_tie@v1"], "view": "calc__and_reason_tie"},
        ],
        "versions": [
            {
                "id": "and_false_invalid@v1", "rule": "and_false_invalid", "version": "v1",
                "view": "calc__and_false_invalid__v1", "valid_from": "2026-01-01", "valid_until": "2027-01-01",
                "known_from": "2025-12-01",
                "definitions": [{"name": "base", "before": [], "when": {"boolean": True},
                                 "value": {"op": "and", "args": [{"fact": "item.flag"}, div0_eq]}}],
            },
            {
                "id": "or_true_invalid@v1", "rule": "or_true_invalid", "version": "v1",
                "view": "calc__or_true_invalid__v1", "valid_from": "2026-01-01", "valid_until": "2027-01-01",
                "known_from": "2025-12-01",
                "definitions": [{"name": "base", "before": [], "when": {"boolean": True},
                                 "value": {"op": "or", "args": [{"fact": "item.flag"}, div0_eq]}}],
            },
            {
                "id": "and_reason_tie@v1", "rule": "and_reason_tie", "version": "v1",
                "view": "calc__and_reason_tie__v1", "valid_from": "2026-01-01", "valid_until": "2027-01-01",
                "known_from": "2025-12-01",
                "definitions": [{"name": "base", "before": [], "when": {"boolean": True},
                                 "value": {"op": "and", "args": [bad_amount_eq, div0_eq]}}],
            },
        ],
    }
    base_tables = {
        "calc__as_of": [("as_of", "2026-03-01", "2026-10-01")],
        "item": [("i_f",), ("i_t",)],
        "item__flag": [("i_f", "false"), ("i_t", "true")],
        "item__amount": [("i_f", "1"), ("i_f", "2"), ("i_t", "1"), ("i_t", "2")],
    }
    return ir_doc, base_tables


def _witness(rule: str, view: str, subject: str, value: str, state: str, reason: str,
             reads: list[str], steps: list[dict]) -> dict:
    return {
        "conclusion": {"relation": view, "key": encode_key([subject, value, state, reason])},
        "rule": rule,
        "version": "v1",
        "valid_at": "2026-03-01",
        "known_at": "2026-10-01",
        "definition": "base",
        "value": value,
        "state": state,
        "reason": reason,
        "premises": [],
        "reads": reads,
        "steps": steps,
    }


def _run_check(ir_doc: dict, tables: dict[str, list[tuple[str, ...]]], witnesses: list[dict]) -> list[dict]:
    encoded = {
        name: {encode_key(list(row)): (tuple(row), {}) for row in rows}
        for name, rows in tables.items()
    }
    return calc.check(witnesses, ir_doc, lambda rel: encoded.get(rel, {}))


def test_checker_calc_follows_four_valued_and_or_conformance():
    and_case = _load_case("value-tt-and-false-invalid")
    or_case = _load_case("value-tt-or-true-invalid")
    for case in (and_case, or_case):
        unsupported = case.get("unsupported") or {}
        assert not ({"compiler", "checker", "feldera"} & set(unsupported)), (
            f"{case['id']} must be executable on compiler, checker, and Feldera: {unsupported!r}"
        )

    # Counter-cases that already hold: controls and state precedence over smaller reason.
    invalid_v = calc.Val("invalid", None, "versions_overlap")
    assert calc.logic("and", [calc.known(True), invalid_v]) == invalid_v
    assert calc.logic("and", [invalid_v, calc.known(True)]) == invalid_v
    assert calc.logic("or", [calc.known(False), invalid_v]) == invalid_v
    assert calc.logic("or", [invalid_v, calc.known(False)]) == invalid_v
    assert calc.logic("and", [calc.known(False), calc.Val("unknown", None, "u")]) == calc.known(False)
    assert calc.logic("or", [calc.known(True), calc.Val("unknown", None, "u")]) == calc.known(True)
    assert calc.logic("and", [calc.Val("unknown", None, "aa_early"), calc.Val("invalid", None, "zz_late")]) == (
        calc.Val("invalid", None, "zz_late")
    )

    problems: list[str] = []

    # 1. Shared conformance cases in both operand orders plus 3-ary forms.
    for op_name, case, extra_neutral in (
        ("and", and_case, calc.known(True)),
        ("or", or_case, calc.known(False)),
    ):
        left = _binding_val(case["input"]["bindings"]["left"])
        right = _binding_val(case["input"]["bindings"]["right"])
        expected = _expect_val(case["expect"])
        for label, args in (
            ("forward", [left, right]),
            ("swapped", [right, left]),
            ("3-ary", [extra_neutral, right, left]),
        ):
            got = calc.apply(op_name, args)
            if got != expected:
                problems.append(f"{case['id']} ({label}): got {got!r}, expected {expected!r}")

    # 2. Full 25-cell Appendix A.1 truth tables for `and` and `or`.
    vals = {
        "T": calc.known(True),
        "F": calc.known(False),
        "N": calc.Val("not_applicable", None, "na_reason"),
        "U": calc.Val("unknown", None, "unk_reason"),
        "I": calc.Val("invalid", None, "inv_reason"),
    }
    order = ("T", "F", "N", "U", "I")
    and_table = {
        "T": ("T", "F", "N", "U", "I"),
        "F": ("F", "F", "F", "F", "F"),
        "N": ("N", "F", "N", "U", "I"),
        "U": ("U", "F", "U", "U", "I"),
        "I": ("I", "F", "I", "I", "I"),
    }
    or_table = {
        "T": ("T", "T", "T", "T", "T"),
        "F": ("T", "F", "N", "U", "I"),
        "N": ("T", "N", "N", "U", "I"),
        "U": ("T", "U", "U", "U", "I"),
        "I": ("T", "I", "I", "I", "I"),
    }
    for op_name, table in (("and", and_table), ("or", or_table)):
        for row_k in order:
            for col_k, exp_k in zip(order, table[row_k], strict=True):
                got = calc.logic(op_name, [vals[row_k], vals[col_k]])
                if got != vals[exp_k]:
                    problems.append(f"A.1 {row_k} {op_name} {col_k}: got {got!r}, expected {vals[exp_k]!r}")

    # 3. Appendix A.4 commutative UTF-8 byte-order least reason selection.
    for state in ("invalid", "unknown", "not_applicable"):
        for late, early in (("zz_late", "aa_early"), ("a_lower", "B_upper")):
            v_late, v_early = calc.Val(state, None, late), calc.Val(state, None, early)
            for op_name in ("and", "or"):
                fwd = calc.logic(op_name, [v_late, v_early])
                rev = calc.logic(op_name, [v_early, v_late])
                if fwd != v_early or rev != v_early:
                    problems.append(
                        f"A.4 {op_name}({state}:{late}, {state}:{early}): fwd={fwd!r}, rev={rev!r}, expected {v_early!r}"
                    )
            for strict_op in ("add", "eq", "min"):
                fwd = calc.apply(strict_op, [v_late, v_early])
                rev = calc.apply(strict_op, [v_early, v_late])
                if fwd != v_early or rev != v_early:
                    problems.append(
                        f"A.4 {strict_op}({state}:{late}, {state}:{early}): fwd={fwd!r}, rev={rev!r}, expected {v_early!r}"
                    )

    # 4. End-to-end `calc.check` witness verification (valid accepted, forged rejected).
    ir_doc, base_tables = _ir_and_snapshots()
    div0_reason = "division by zero in ratio"
    bad_amount_reason = "fact item.amount has more than one value"
    div0_steps_1 = [
        {"path": "base/value/1", "op": "eq", "value": "", "state": "invalid", "reason": div0_reason},
        {"path": "base/value/1/0", "op": "ratio", "value": "", "state": "invalid", "reason": div0_reason},
    ]

    valid_and = _witness(
        "and_false_invalid", "calc__and_false_invalid", "i_f", "false", "known", "",
        ["calc__as_of", "item__flag"],
        [
            {"path": "base/value", "op": "and", "value": "false", "state": "known", "reason": ""},
            {"path": "base/value/0", "op": "fact", "ref": "item.flag", "relation": "item__flag",
             "value": "false", "state": "known", "reason": ""},
            *div0_steps_1,
        ],
    )
    findings = _run_check(ir_doc, base_tables | {"calc__and_false_invalid": [("i_f", "false", "known", "")]}, [valid_and])
    if findings:
        problems.append(f"calc.check rejected valid false-and-invalid witness: {findings!r}")

    forged_and = _witness(
        "and_false_invalid", "calc__and_false_invalid", "i_f", "", "invalid", div0_reason,
        ["calc__as_of", "item__flag"],
        [
            {"path": "base/value", "op": "and", "value": "", "state": "invalid", "reason": div0_reason},
            {"path": "base/value/0", "op": "fact", "ref": "item.flag", "relation": "item__flag",
             "value": "false", "state": "known", "reason": ""},
            *div0_steps_1,
        ],
    )
    if not _run_check(ir_doc, base_tables | {"calc__and_false_invalid": [("i_f", "", "invalid", div0_reason)]}, [forged_and]):
        problems.append("calc.check accepted forged invalid witness for false and invalid")

    valid_or = _witness(
        "or_true_invalid", "calc__or_true_invalid", "i_t", "true", "known", "",
        ["calc__as_of", "item__flag"],
        [
            {"path": "base/value", "op": "or", "value": "true", "state": "known", "reason": ""},
            {"path": "base/value/0", "op": "fact", "ref": "item.flag", "relation": "item__flag",
             "value": "true", "state": "known", "reason": ""},
            *div0_steps_1,
        ],
    )
    findings = _run_check(ir_doc, base_tables | {"calc__or_true_invalid": [("i_t", "true", "known", "")]}, [valid_or])
    if findings:
        problems.append(f"calc.check rejected valid true-or-invalid witness: {findings!r}")

    tie_steps_base = [
        {"path": "base/value/0", "op": "eq", "value": "", "state": "invalid", "reason": bad_amount_reason},
        {"path": "base/value/0/0", "op": "fact", "ref": "item.amount", "relation": "item__amount",
         "value": "", "state": "invalid", "reason": bad_amount_reason},
        *div0_steps_1,
    ]
    valid_tie = _witness(
        "and_reason_tie", "calc__and_reason_tie", "i_f", "", "invalid", div0_reason,
        ["calc__as_of", "item__amount"],
        [{"path": "base/value", "op": "and", "value": "", "state": "invalid", "reason": div0_reason}, *tie_steps_base],
    )
    findings = _run_check(ir_doc, base_tables | {"calc__and_reason_tie": [("i_f", "", "invalid", div0_reason)]}, [valid_tie])
    if findings:
        problems.append(f"calc.check rejected UTF-8 least reason on invalid tie: {findings!r}")

    positional_tie = _witness(
        "and_reason_tie", "calc__and_reason_tie", "i_f", "", "invalid", bad_amount_reason,
        ["calc__as_of", "item__amount"],
        [{"path": "base/value", "op": "and", "value": "", "state": "invalid", "reason": bad_amount_reason}, *tie_steps_base],
    )
    if not _run_check(ir_doc, base_tables | {"calc__and_reason_tie": [("i_f", "", "invalid", bad_amount_reason)]}, [positional_tie]):
        problems.append("calc.check accepted positional-first non-least reason on invalid tie")

    if problems:
        raise CheckerFourValuedParityError("\n".join(problems))
