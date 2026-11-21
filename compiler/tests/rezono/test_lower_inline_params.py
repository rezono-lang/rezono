"""Inline parameter declarations (`param x: T = <expr>` and versioned `param x: T` with `valid`/`known`)
and dimensionless built-in types (`Ratio`, `Int`) lower into calculation rules in `rezono_calc.py`
(decisions/language-healthcare-allowance-slice.md)."""

from __future__ import annotations

import datetime
import json
import os
from pathlib import Path
import subprocess

import yaml

from calcsupport import run_both
from rezono_compiler import calc, calc_sql, facts, pack, rezono_calc


ROOT = Path(__file__).resolve().parents[3]
NODE = os.environ.get("REZONO_NODE", "node")

SAMPLE_MODULE = """\
rezono 0
pack inline-params-sample

unit Points = money minor EUR

kind Record  world closed
  flag: Bool
  active: Bool
  metric: Points

param base_val: Points
  version 1, valid 2025-01-01..<2026-01-01, known 2024-09-17  = 1000  @ ref#art-1
  version 2, valid 2026-01-01.., known 2025-09-16             = 2000  @ ref#art-1
  version 3, valid 2026-01-01.., known 2026-03-02             = 2200  @ ref#art-2

param extra_rate: Ratio = 10 %

extend Record
  derived factor: Ratio =
      when flag then 20 % else 10 %

  derived adjusted: Points =
      base_val + floor(factor * metric) + floor(extra_rate * metric)
    unless
      when not active then 0  @ ref#art-3

as of 2026-01-01 known 2026-02-01
"""

SAMPLE_FACTS = """\
rezono 0
pack inline-params-sample

fact Record
  | id | flag  |
  | r1 | false |
  | r2 | true  |
  | r3 | false |

fact record r1, valid 2025-01-01.., known 2025-01-05
  active = true
fact record r2, valid 2025-01-01.., known 2025-01-05
  active = true
fact record r3, valid 2025-01-01.., known 2025-01-05
  active = false

fact record r1, valid 2025-01-01..<2026-01-01, known 2025-01-10
  metric = 500
fact record r1, valid 2026-01-01..<2027-01-01, known 2025-12-01
  metric = 1000
fact record r2, valid 2026-01-01..<2027-01-01, known 2026-01-05
  metric = 1000
fact record r2, valid 2026-01-01..<2027-01-01, known 2026-04-15
  metric = 2000
"""


def _write_form(source: Path, dest: Path) -> dict:
    result = subprocess.run(
        [NODE, str(ROOT / "rezono/src/write-form.ts"), str(source), str(dest)],
        capture_output=True, text=True, encoding="utf-8",
    )
    assert result.returncode == 0, result.stderr
    return json.loads(dest.read_bytes())


def _as_dataset_form(form: dict, name: str = "facts") -> dict:
    body = form["module"]
    return {
        "format": "rezono.module/2",
        "module": {
            "rezono": body.get("rezono", "0"),
            "pack": body["pack"],
            "use": body.get("use", []),
            "decls": [{"dataset": name, "decls": body["decls"]}],
        },
        "spans": [],
    }


def _stage_sample_pack(tmp_path: Path) -> tuple[Path, dict]:
    """Stage a domain-free pack with versioned and constant inline parameters plus dated facts."""
    pack_dir = tmp_path / "inline-params-sample"
    (pack_dir / "rezono").mkdir(parents=True)
    (pack_dir / "labels").mkdir()
    (pack_dir / "messages").mkdir()

    mod_path = pack_dir / "rezono/sample.rezono"
    mod_path.write_text(SAMPLE_MODULE, encoding="utf-8")
    _write_form(mod_path, pack_dir / "rezono/sample.json")

    (pack_dir / "pack.yaml").write_text(
        yaml.safe_dump({
            "name": "inline-params-sample",
            "version": "0.1.0",
            "default_language": "en",
            "rezono": [{
                "module": "rezono/sample.rezono",
                "form": "rezono/sample.json",
                "layer": "conclusions",
            }],
        }, sort_keys=False),
        encoding="utf-8",
    )
    (pack_dir / "channels.yaml").write_text(
        "kinds:\n  - {kind: record, shape: pill}\n",
        encoding="utf-8",
    )
    (pack_dir / "labels/en.yaml").write_text(
        "record: record\n"
        "record.flag: flag\n"
        "record.active: active\n"
        "record.metric: metric\n",
        encoding="utf-8",
    )
    (pack_dir / "messages/en.mf2").write_text(
        "@locale en\n---\n"
        "arrow.total = {{Every {$kind} has exactly one {$arrow}.}}\n"
        "arrow.partial = {{Every {$kind} has at most one {$arrow}.}}\n"
        "attribute.total = {{Every {$kind} has exactly one {$attribute}.}}\n"
        "attribute.partial = {{Every {$kind} has at most one {$attribute}.}}\n"
        "is_a = {{Every {$kind} is a {$parent}.}}\n"
        "unique_key = {{{$key} belongs to at most one {$kind}.}}\n"
        "path_equation = {{For every {$kind}: {$equation}.}}\n",
        encoding="utf-8",
    )

    facts_src = tmp_path / "facts.rezono"
    facts_src.write_text(SAMPLE_FACTS, encoding="utf-8")
    facts_form = _as_dataset_form(_write_form(facts_src, tmp_path / "facts.json"))
    return pack_dir, facts_form


def test_inline_parameter_versions_and_ratio_lower_cleanly(tmp_path):
    """Versioned and constant inline parameters, dimensionless Ratio, bare VARCHAR record ids, and
    unit-annotated integer leaves evaluate identically across DuckDB calc_sql and Python calcoracle."""
    pack_dir, facts_form = _stage_sample_pack(tmp_path)
    model = pack.read(pack_dir)
    assert model.calc is not None
    rule_ids = {r["id"] for r in model.calc["rules"]}
    assert {
        "base_val@1",
        "base_val@2",
        "base_val@3",
        "extra_rate@1",
        "factor@1",
        "adjusted@1",
    } <= rule_ids

    program = calc.build(model, model.calc)
    fact_schema = facts.schema(model)

    cases = [
        # (as_of, known, record_id, expected_state, expected_value)
        (datetime.date(2025, 12, 1), datetime.date(2026, 2, 1), "r1", "known", "1100"),  # 1000 + 50 + 50
        (datetime.date(2026, 1, 1), datetime.date(2026, 2, 1), "r1", "known", "2200"),   # 2000 + 100 + 100
        (datetime.date(2026, 3, 1), datetime.date(2026, 3, 10), "r1", "known", "2400"),  # v3: 2200 + 100 + 100
        (datetime.date(2026, 1, 1), datetime.date(2026, 2, 1), "r2", "known", "2300"),   # 2000 + 200 + 100
        (datetime.date(2026, 4, 1), datetime.date(2026, 5, 1), "r2", "known", "2800"),   # v3 + corrected metric 2000: 2200 + 400 + 200
        (datetime.date(2026, 2, 1), datetime.date(2026, 2, 10), "r3", "known", "0"),     # unless not active -> 0
        (datetime.date(2025, 12, 1), datetime.date(2026, 2, 1), "r2", "unknown", ""),    # omitted 2025 metric -> unknown
    ]

    for as_of, known, rec_id, want_state, want_value in cases:
        rows = facts.rows_of(
            model,
            facts.scalar_dataset(fact_schema, facts_form, as_of=as_of, known=known),
        )
        day = {calc_sql.AS_OF: [("as_of", str(as_of), str(known))]}
        got, reference = run_both(model, program, model.calc, rows | day)
        assert got == reference, (as_of, known, rec_id)
        state, value, *_ = got["adjusted"][rec_id]
        assert (state, value) == (want_state, want_value), (as_of, known, rec_id)


def test_inline_parameter_validation_fails_closed():
    """Malformed or unsupported inline parameter shapes fail closed with R050."""
    cases = [
        (
            {
                "param": "both",
                "type": "Ratio",
                "source": {"kind": "K", "slot": "v", "nameSlot": "n"},
                "value": {"lit": "10 %"},
            },
            "both source and inline",
        ),
        (
            {
                "param": "dup",
                "type": "Ratio",
                "versions": [
                    {"version": "1", "value": {"lit": "10 %"}},
                    {"version": "1", "value": {"lit": "12 %"}},
                ],
            },
            "duplicate parameter version",
        ),
        (
            {
                "param": "rep",
                "type": "Ratio",
                "versions": [
                    {"version": "1", "value": {"lit": "10 %"}},
                    {"version": "2", "replaces": "1", "value": {"lit": "12 %"}},
                ],
            },
            "replaces is not lowered",
        ),
        (
            {"param": "scoped", "type": "Ratio", "per": "Record", "value": {"lit": "10 %"}},
            "with `per` is not lowered",
        ),
        (
            {"param": "bare", "type": "Ratio"},
            "needs `from Kind.slot by nameSlot`, `= value`, or `versions`",
        ),
    ]
    for decl, match in cases:
        errors: list[str] = []
        ok = rezono_calc.validate_param(decl, "/decls/0", lambda _at, msg, _sec="": errors.append(msg))
        assert not ok, decl["param"]
        assert any(match in err for err in errors), (decl["param"], errors)
