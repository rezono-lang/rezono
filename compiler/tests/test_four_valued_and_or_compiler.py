"""Compiler, checker, and Feldera parity for four-valued `and`/`or` and Appendix A.4 reason choice.

Reads the shared conformance cases (`tests/conformance/value-tt-and-false-invalid.yaml` and
`tests/conformance/value-tt-or-true-invalid.yaml`) directly and tests:
1. DuckDB calculation lowering (`compiler/rezono_compiler/calc_sql.py`),
2. The exact calculation reference (`compiler/tests/calcoracle.py`),
3. Independent calculation witness verification (`checker/rezono_checker/calc.py`),
4. Rezono calculation lowering (`compiler/rezono_compiler/rezono_calc.py`), and
5. Feldera SQL (`calc_sql.feldera`, plus live Feldera execution when `FELDERA_URL` is configured)

against `decisions/four-valued-and-or-parity.md` and `docs/rezono/expressions.md` Appendix A.1 and A.4.
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest
import yaml

from calcoracle import Oracle
from calcsupport import checked, concept_types, connect, derived_rows, results, value_text
from rezono_compiler import calc, calc_sql, emit, facts, pack, rezono_calc, rezono_module

ROOT = Path(__file__).resolve().parents[2]
CORPUS = ROOT / "tests" / "conformance"
FIXTURE = Path(__file__).resolve().parent / "fixtures" / "calc"
PACK = pack.read(FIXTURE)
BINDINGS = {
    "format": "rezono.calc/1",
    "pack": "calc",
    "subject": "item",
    "parameters": "setting.value",
    "inputs": {"kind": "entry", "subject": "item", "fact": "name", "integer": "number", "boolean": "truth"},
}


class FourValuedAndOrParityError(AssertionError):
    """Compiler SQL (DuckDB / Feldera), calcoracle, or checker diverges from Appendix A.1 / A.4."""


def _load_case(case_id: str) -> dict:
    return yaml.safe_load((CORPUS / f"{case_id}.yaml").read_text(encoding="utf-8"))


def _rule(name: str, expr: dict) -> dict:
    return {
        "id": f"{name}@v1",
        "rule": name,
        "version": "v1",
        "output": f"{name}.value",
        "unit": "x",
        "valid_from": "2026-01-01",
        "valid_until": "2027-01-01",
        "known_from": "2025-12-01",
        "definitions": [{"name": "base", "when": {"boolean": True}, "value": expr}],
    }


def _op(name: str, *args: dict) -> dict:
    return {"op": name, "args": list(args)}


def _i(n: int) -> dict:
    return {"integer": str(n)}


def _fact(name: str) -> dict:
    return {"fact": name}


def _calc_doc() -> dict:
    div0_eq = _op("eq", _op("ratio", _i(1), _i(1), _i(0)), _i(0))
    bad_amount_eq = _op("eq", _fact("item.amount"), _i(0))
    bad_a_eq = _op("eq", _fact("a_bad"), _i(0))
    bad_B_eq = _op("eq", _fact("B_bad"), _i(0))
    unk_zz_eq = _op("eq", _fact("zz_missing"), _i(0))
    unk_aa_eq = _op("eq", _fact("aa_missing"), _i(0))
    unk_a_eq = _op("eq", _fact("a_missing"), _i(0))
    unk_B_eq = _op("eq", _fact("B_missing"), _i(0))
    na_extra_eq = _op("eq", _fact("item.extra"), _i(0))
    na_note = _fact("item.note")
    flag = _fact("item.flag")
    return dict(
        BINDINGS,
        templates=[],
        rules=[
            # Conformance truth-table cells (both orders + 3-ary + controls via i_f / i_t).
            _rule("and_flag_div0", _op("and", flag, div0_eq)),
            _rule("and_div0_flag", _op("and", div0_eq, flag)),
            _rule("and_3ary_false_wins", _op("and", {"boolean": True}, div0_eq, flag)),
            _rule("or_flag_div0", _op("or", flag, div0_eq)),
            _rule("or_div0_flag", _op("or", div0_eq, flag)),
            _rule("or_3ary_true_wins", _op("or", {"boolean": False}, div0_eq, flag)),
            # Appendix A.4 commutative UTF-8 byte-order least reason selection.
            _rule("and_inv_tie_late_first", _op("and", bad_amount_eq, div0_eq)),
            _rule("and_inv_tie_early_first", _op("and", div0_eq, bad_amount_eq)),
            _rule("or_inv_tie_late_first", _op("or", bad_amount_eq, div0_eq)),
            _rule("or_inv_tie_early_first", _op("or", div0_eq, bad_amount_eq)),
            _rule("and_inv_case_lower_first", _op("and", bad_a_eq, bad_B_eq)),
            _rule("and_inv_case_upper_first", _op("and", bad_B_eq, bad_a_eq)),
            _rule("and_unk_tie_late_first", _op("and", unk_zz_eq, unk_aa_eq)),
            _rule("and_unk_tie_early_first", _op("and", unk_aa_eq, unk_zz_eq)),
            _rule("or_unk_tie_late_first", _op("or", unk_zz_eq, unk_aa_eq)),
            _rule("or_unk_tie_early_first", _op("or", unk_aa_eq, unk_zz_eq)),
            _rule("and_unk_case_lower_first", _op("and", unk_a_eq, unk_B_eq)),
            _rule("and_na_tie_late_first", _op("and", na_note, na_extra_eq)),
            _rule("and_na_tie_early_first", _op("and", na_extra_eq, na_note)),
            _rule("add_unk_tie_late_first", _op("add", _fact("zz_missing"), _fact("aa_missing"))),
            _rule("add_unk_tie_early_first", _op("add", _fact("aa_missing"), _fact("zz_missing"))),
            _rule("eq_inv_tie_late_first", _op("eq", _fact("a_bad"), _fact("B_bad"))),
            _rule("and_state_beats_reason", _op("and", unk_aa_eq, bad_amount_eq)),
        ],
    )


def _calc_rows() -> dict[str, list[tuple]]:
    return {
        "item": [("i_f",), ("i_t",)],
        "item__flag": [("i_f", False), ("i_t", True)],
        "item__amount": [("i_f", 1), ("i_f", 2), ("i_t", 1), ("i_t", 2)],
        "entry": [("e1",), ("e2",), ("e3",), ("e4",)],
        "entry__item": [("e1", "i_f"), ("e2", "i_f"), ("e3", "i_f"), ("e4", "i_f")],
        "entry__name": [("e1", "a_bad"), ("e2", "a_bad"), ("e3", "B_bad"), ("e4", "B_bad")],
        "entry__number": [("e1", 1), ("e2", 2), ("e3", 1), ("e4", 2)],
        "setting": [("s0",)],
        "setting__value": [("s0", 1)],
        "calc__as_of": [("as_of", "2026-03-01", "2026-10-01")],
    }


def _lowered_rezono_doc() -> dict:
    """Lower Rezono `and`/`or` expressions via `rezono_calc.lower_module` into `rezono.calc/1`."""
    div0_eq = {"cmp": ["=", {"arith": ["/", {"lit": "1"}, {"lit": "0"}]}, {"lit": "0"}]}
    bad_amount_eq = {"cmp": ["=", {"path": ["amount"]}, {"lit": "0"}]}
    flag = {"path": ["flag"]}

    def dv(name: str, expr: dict) -> dict:
        return {
            "derived": name,
            "type": "Bool",
            "unit": "bool",
            "versions": [{
                "version": "v1",
                "valid": ["2026-01-01", "2027-01-01"],
                "known": "2025-12-01",
                "definitions": [{"name": "base", "when": {"lit": "true"}, "value": expr}],
            }],
        }

    decls = [
        {"asOf": "2026-03-01", "known": "2026-10-01"},
        {
            "extend": "Item",
            "derived": [
                dv("rezono_and_false_invalid", {"and": [flag, div0_eq]}),
                dv("rezono_and_invalid_false", {"and": [div0_eq, flag]}),
                dv("rezono_or_true_invalid", {"or": [flag, div0_eq]}),
                dv("rezono_or_invalid_true", {"or": [div0_eq, flag]}),
                dv("rezono_and_reason_tie", {"and": [bad_amount_eq, div0_eq]}),
            ],
        },
    ]
    body = {"rezono": "0", "pack": PACK.meta["name"], "use": [], "decls": decls}
    spans = [{"at": at, "line": "1", "start": "0", "end": "1"} for at in rezono_module.place_pointers(body)]
    mod = SimpleNamespace(
        pack=PACK.meta["name"],
        pack_dir=FIXTURE,
        rel="rezono/four_valued.rezono",
        form={"format": "rezono.module/2", "module": body, "spans": spans},
    )
    return rezono_calc.lower_module(PACK, mod, {"item": set()})


@pytest.mark.xfail(
    strict=True,
    raises=FourValuedAndOrParityError,
    reason="M1: decisions/four-valued-and-or-parity.md: Align compiler/rezono_compiler/calc_sql.py (DuckDB and "
           "Feldera SQL), checker/rezono_checker/calc.py, and compiler/tests/calcoracle.py with "
           "docs/rezono/expressions.md Appendix A.1 (`false and invalid = false`, `true or invalid = true`, "
           "symmetric and multi-arity) and Appendix A.4 (commutative UTF-8 byte-order least reason selection in "
           "`and`, `or`, and strict operators), matching tests/conformance/value-tt-and-false-invalid.yaml and "
           "tests/conformance/value-tt-or-true-invalid.yaml.",
)
def test_calc_sql_checker_and_feldera_follow_four_valued_and_or_conformance():
    and_case = _load_case("value-tt-and-false-invalid")
    or_case = _load_case("value-tt-or-true-invalid")
    for case in (and_case, or_case):
        unsupported = case.get("unsupported") or {}
        assert not ({"compiler", "checker", "feldera"} & set(unsupported)), (
            f"{case['id']} must be executable on compiler, checker, and Feldera: {unsupported!r}"
        )

    doc = _calc_doc()
    rows = _calc_rows()
    prog = calc.build(PACK, doc)
    db = connect(PACK, prog, rows)
    got_duckdb = results(db, prog)
    oracle = Oracle(PACK, doc, rows | derived_rows(db, PACK), concept_types(prog))
    got_oracle = oracle.results()
    checker_findings = checked(db, prog)

    div0_reason = "division by zero in ratio"
    bad_amount_reason = "fact item.amount has more than one value"

    # Counter-cases that already pass: controls and higher-state dominance over smaller reason.
    assert got_duckdb["and_flag_div0"]["i_t"][:3] == ("invalid", "", div0_reason)
    assert got_duckdb["and_div0_flag"]["i_t"][:3] == ("invalid", "", div0_reason)
    assert got_duckdb["or_flag_div0"]["i_f"][:3] == ("invalid", "", div0_reason)
    assert got_duckdb["or_div0_flag"]["i_f"][:3] == ("invalid", "", div0_reason)
    assert got_duckdb["and_state_beats_reason"]["i_f"][:3] == ("invalid", "", bad_amount_reason)

    problems: list[str] = []

    if checker_findings:
        problems.append(f"checker rejected DuckDB calculation witnesses: {checker_findings!r}")

    expected_and = (and_case["expect"]["state"], "false" if and_case["expect"]["value"] is False else "true", "")
    expected_or = (or_case["expect"]["state"], "true" if or_case["expect"]["value"] is True else "false", "")

    expected = {
        # Conformance truth table: false and invalid = false; true or invalid = true (both orders + 3-ary).
        ("and_flag_div0", "i_f"): expected_and,
        ("and_div0_flag", "i_f"): expected_and,
        ("and_3ary_false_wins", "i_f"): expected_and,
        ("or_flag_div0", "i_t"): expected_or,
        ("or_div0_flag", "i_t"): expected_or,
        ("or_3ary_true_wins", "i_t"): expected_or,
        # Appendix A.4 commutative UTF-8 byte-order least reason selection.
        ("and_inv_tie_late_first", "i_f"): ("invalid", "", div0_reason),
        ("and_inv_tie_early_first", "i_f"): ("invalid", "", div0_reason),
        ("or_inv_tie_late_first", "i_f"): ("invalid", "", div0_reason),
        ("or_inv_tie_early_first", "i_f"): ("invalid", "", div0_reason),
        ("and_inv_case_lower_first", "i_f"): ("invalid", "", "fact B_bad has more than one value"),
        ("and_inv_case_upper_first", "i_f"): ("invalid", "", "fact B_bad has more than one value"),
        ("and_unk_tie_late_first", "i_f"): ("unknown", "", "fact aa_missing is missing"),
        ("and_unk_tie_early_first", "i_f"): ("unknown", "", "fact aa_missing is missing"),
        ("or_unk_tie_late_first", "i_f"): ("unknown", "", "fact aa_missing is missing"),
        ("or_unk_tie_early_first", "i_f"): ("unknown", "", "fact aa_missing is missing"),
        ("and_unk_case_lower_first", "i_f"): ("unknown", "", "fact B_missing is missing"),
        ("and_na_tie_late_first", "i_f"): ("not_applicable", "", "fact item.extra does not apply"),
        ("and_na_tie_early_first", "i_f"): ("not_applicable", "", "fact item.extra does not apply"),
        ("add_unk_tie_late_first", "i_f"): ("unknown", "", "fact aa_missing is missing"),
        ("add_unk_tie_early_first", "i_f"): ("unknown", "", "fact aa_missing is missing"),
        ("eq_inv_tie_late_first", "i_f"): ("invalid", "", "fact B_bad has more than one value"),
    }

    for (rule_name, subj), want in expected.items():
        actual_duckdb = got_duckdb[rule_name][subj][:3]
        actual_oracle = got_oracle[rule_name][subj][:3]
        if actual_duckdb != want:
            problems.append(f"DuckDB {rule_name}[{subj}]: got {actual_duckdb!r}, expected {want!r}")
        if actual_oracle != want:
            problems.append(f"calcoracle {rule_name}[{subj}]: got {actual_oracle!r}, expected {want!r}")

    # Rezono lowering path (`rezono_calc.py` -> `calc_sql.py` -> DuckDB + checker).
    lowered_doc = _lowered_rezono_doc()
    lowered_prog = calc.build(PACK, lowered_doc)
    lowered_db = connect(PACK, lowered_prog, rows)
    lowered_res = results(lowered_db, lowered_prog)
    lowered_findings = checked(lowered_db, lowered_prog)
    if lowered_findings:
        problems.append(f"checker rejected rezono_calc lowered witnesses: {lowered_findings!r}")
    for rule_name, subj, want in (
        ("rezono_and_false_invalid", "i_f", expected_and),
        ("rezono_and_invalid_false", "i_f", expected_and),
        ("rezono_or_true_invalid", "i_t", expected_or),
        ("rezono_or_invalid_true", "i_t", expected_or),
        ("rezono_and_reason_tie", "i_f", ("invalid", "", div0_reason)),
    ):
        actual = lowered_res[rule_name][subj][:3]
        if actual != want:
            problems.append(f"rezono_calc {rule_name}[{subj}]: got {actual!r}, expected {want!r}")

    # Feldera SQL generation parity (and live Feldera execution when FELDERA_URL is configured).
    feldera_sql = calc_sql.feldera(prog)
    for rule_name in prog.rules:
        if f'CREATE MATERIALIZED VIEW "{prog.engine[rule_name]}"' not in feldera_sql:
            problems.append(f"Feldera SQL missing CREATE MATERIALIZED VIEW for {prog.engine[rule_name]}")

    import feldera

    if feldera.URL and not problems:
        pipeline = "rezono-four-valued-and-or"
        udf = ROOT / "udf"
        compiled = emit.compile_pack(PACK)
        try:
            feldera.deploy(
                pipeline,
                compiled["engine/tables.sql"] + compiled["engine/rules.sql"] + feldera_sql,
                udf_rust=(udf / "udf.rs").read_text(encoding="utf-8"),
                udf_toml=(udf / "udf.toml").read_text(encoding="utf-8"),
            )
            pack_rows = {t: rs for t, rs in rows.items() if t != "calc__as_of"}
            updates = facts.ingress(PACK, pack_rows)
            updates["calc__as_of"] = [{"insert": {"id": a, "valid_at": b, "known_at": c}} for a, b, c in rows["calc__as_of"]]
            feldera.processed(pipeline, feldera.push(pipeline, updates))
            got_feldera = {
                r: {
                    x["subject"]: (
                        x["state"],
                        value_text(prog.types[r], x["state"], x["n"], x["d"], x["b"]),
                        x["reason"],
                        x["definition"],
                        x["version"],
                    )
                    for x in feldera.read_relation(pipeline, prog.engine[r])
                }
                for r in prog.rules
            }
            if got_feldera != got_duckdb:
                problems.append(f"Live Feldera disagreed with DuckDB:\nFeldera={got_feldera!r}\nDuckDB={got_duckdb!r}")
        finally:
            try:
                feldera.stop(pipeline, delete=True)
            except Exception:
                pass

    if problems:
        raise FourValuedAndOrParityError("\n".join(problems))
