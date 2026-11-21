"""Strict red tests for `rezono 1` derived soundness, unit validation, chaining, provenance, and sign-key immutability.

Covers decisions/language-rezono-1.md:
1. `table first` must propagate `invalid` from an earlier row even when a later row produces the same output literal.
2. `versions` with `known` date in a module without `as of` must fail closed (`unknown no_version_applies`), never match.
3. `unit` on a `rezono 1` derivation must be validated against declared pack units and value type (never silently dropped).
4. Functional kind-typed derived properties (`derived owner: Person = it.p`) must preserve their kind type for chaining
   (`it.owner.label`).
5. `@ source` on `unless` clauses (`rezono_derived.py`) must be preserved in compiled bundle rules (`contracts/bundle.yaml`).
6. Signed/decimal inline parameter values with a declared unit (`rezono_calc.py`) must retain their unit through `calc.build`,
   and invalid calendar dates such as `2026-02-30` must be rejected by `rezono_calc.validate_param` and `validate_as_of`.
7. `key_of_signs.load()` must return fresh independent copies so mutating a returned dict does not corrupt cached results.
"""

from __future__ import annotations

import json
from pathlib import Path
import shutil

import pytest
import yaml

from expression_packs import ROOT, register
from rezono_compiler import batch, calc, emit, key_of_signs, pack, rezono_calc, rezono_module, rules, scenarios
from support import FIXTURE

FACT_SOURCE = (
    'default: {kind: git, name: rezono-lang/rezono, revision: "0000000", '
    'position: compiler/tests/rezono/test_derived_soundness_and_units.py#FACTS}\n'
)


def _write_rezono1_json_pack(directory: Path, decls: list[dict], facts_yaml: str | None = None) -> Path:
    directory = Path(shutil.copytree(FIXTURE, directory))
    folder = directory / "rezono"
    folder.mkdir()
    module_path = folder / "derived.rezono"
    form_path = folder / "derived.json"
    module_path.write_text("rezono 1\npack minimal\n", encoding="utf-8", newline="\n")
    module = {"rezono": "1", "pack": "minimal", "use": [], "decls": decls}
    spans = [{"at": at, "line": "1", "start": "0", "end": "1"} for at in rezono_module.place_pointers(module)]
    form = {"format": "rezono.module/5", "module": module, "spans": spans}
    form_path.write_text(json.dumps(form, indent=2) + "\n", encoding="utf-8", newline="\n")
    if facts_yaml is not None:
        (directory / "facts").mkdir(exist_ok=True)
        (directory / "facts/case.yaml").write_text(facts_yaml, encoding="utf-8", newline="\n")
        (directory / "facts/case.sources.yaml").write_text(FACT_SOURCE, encoding="utf-8", newline="\n")
    register(directory, {"module": "rezono/derived.rezono", "form": "rezono/derived.json", "layer": "facts"})
    return directory


def _compile_and_run_duckdb(directory: Path) -> tuple[dict, dict, dict[str, set[tuple]]]:
    try:
        model = pack.read(directory)
        files = emit.compile_pack(model)
    except pack.CompileError as exc:
        raise AssertionError(f"pack failed to compile: {exc}") from exc
    assert "ir/rules.json" in files, f"missing ir/rules.json among {sorted(files)}"
    doc = json.loads(files["ir/rules.json"])
    bundle = json.loads(files["bundle/schema-bundle.json"])
    prog = rules.load(doc)
    rows = dict(scenarios.states(model, directory))["0-case"]
    con, _, _ = batch.run(model, prog, rows)
    try:
        return doc, bundle, batch.read(con, prog)
    finally:
        con.close()


def _write_calc_json_pack(directory: Path, decls: list[dict]) -> Path:
    (directory / "rezono").mkdir(parents=True)
    (directory / "labels").mkdir()
    (directory / "messages").mkdir()
    (directory / "rezono/sample.rezono").write_text("rezono 0\npack calc-sample\n", encoding="utf-8", newline="\n")
    module = {"rezono": "0", "pack": "calc-sample", "use": [], "decls": decls}
    spans = [{"at": at, "line": "1", "start": "0", "end": "1"} for at in rezono_module.place_pointers(module)]
    form = {"format": "rezono.module/2", "module": module, "spans": spans}
    (directory / "rezono/sample.json").write_text(json.dumps(form, indent=2) + "\n", encoding="utf-8", newline="\n")
    (directory / "pack.yaml").write_text(
        yaml.safe_dump(
            {
                "name": "calc-sample",
                "version": "0.1.0",
                "default_language": "en",
                "rezono": [{"module": "rezono/sample.rezono", "form": "rezono/sample.json", "layer": "conclusions"}],
            },
            sort_keys=False,
        ),
        encoding="utf-8",
        newline="\n",
    )
    (directory / "channels.yaml").write_text("kinds:\n  - {kind: record, shape: pill}\n", encoding="utf-8", newline="\n")
    (directory / "labels/en.yaml").write_text("record: record\nrecord.metric: metric\n", encoding="utf-8", newline="\n")
    (directory / "messages/en.mf2").write_text(
        "@locale en\n---\n"
        "arrow.total = {{Every {$kind} has exactly one {$arrow}.}}\n"
        "arrow.partial = {{Every {$kind} has at most one {$arrow}.}}\n"
        "attribute.total = {{Every {$kind} has exactly one {$attribute}.}}\n"
        "attribute.partial = {{Every {$kind} has at most one {$attribute}.}}\n"
        "is_a = {{Every {$kind} is a {$parent}.}}\n"
        "unique_key = {{{$key} belongs to at most one {$kind}.}}\n"
        "path_equation = {{For every {$kind}: {$equation}.}}\n",
        encoding="utf-8",
        newline="\n",
    )
    return directory


@pytest.mark.xfail(
    strict=True,
    raises=AssertionError,
    reason=(
        "M3: decisions/language-rezono-1.md: section 2; `table first` must propagate `invalid` "
        "from an earlier undecided row even when a later matching row produces the same output value."
    ),
)
def test_table_first_propagates_invalid_even_when_later_row_has_same_output(tmp_path: Path):
    decls = [
        {"asOf": "2026-06-01", "known": "2026-06-01"},
        {"kind": "Item", "world": "closed", "slots": [{"slot": "code", "type": "Int"}], "derived": []},
        {
            "extend": "Item",
            "derived": [
                {
                    "derived": "bad_val",
                    "type": "Int",
                    "versions": [
                        {"version": "1", "valid": ["2026-01-01"], "value": {"lit": "1"}},
                        {"version": "2", "valid": ["2026-01-01"], "value": {"lit": "2"}},
                    ],
                },
                {
                    "derived": "label",
                    "type": "Text",
                    "table": {
                        "table": "first",
                        "inputs": [{"path": ["it", "bad_val"]}],
                        "rows": [
                            {"tests": [[{"lit": "1"}]], "value": {"lit": '"A"'}},
                            {"tests": ["-"], "value": {"lit": '"A"'}},
                        ],
                    },
                },
            ],
        },
    ]
    directory = _write_rezono1_json_pack(tmp_path / "table-invalid", decls, "item:\n  - {id: x1, code: 1}\n")
    _, _, derived = _compile_and_run_duckdb(directory)

    # Confirm bad_val itself is invalid (versions_overlap) on x1.
    bad_rows = {row[:3] for row in derived["item_bad_val"]}
    assert bad_rows == {("x1", "invalid", "versions_overlap")}, f"expected overlapping versions to be invalid: {bad_rows!r}"

    # Row 0 evaluates it.bad_val (invalid); row 1 has the same output "A" but MUST NOT mask invalid into known "A".
    label_rows = {row[:3] for row in derived["item_label"]}
    assert label_rows == {("x1", "invalid", "versions_overlap")}, (
        f"table first must propagate invalid even when a later row shares output 'A'; got {derived['item_label']!r}"
    )


@pytest.mark.xfail(
    strict=True,
    raises=AssertionError,
    reason=(
        "M3: decisions/language-rezono-1.md: section 2; a version carrying a `known` date in a module "
        "without `as of` must fail closed to `unknown no_version_applies`, never evaluate as `known`."
    ),
)
def test_versions_known_date_without_as_of_fails_closed(tmp_path: Path):
    decls = [
        {"kind": "Item", "world": "closed", "slots": [{"slot": "code", "type": "Int"}], "derived": []},
        {
            "extend": "Item",
            "derived": [
                {
                    "derived": "future_only",
                    "type": "Int",
                    "versions": [
                        {"version": "1", "known": "2099-01-01", "value": {"lit": "42"}},
                    ],
                },
            ],
        },
    ]
    directory = _write_rezono1_json_pack(tmp_path / "known-no-asof", decls, "item:\n  - {id: x1, code: 1}\n")
    _, _, derived = _compile_and_run_duckdb(directory)

    got_states = {row[:3] for row in derived["item_future_only"]}
    assert got_states == {("x1", "unknown", "no_version_applies")}, (
        f"version with known 2099-01-01 and no `as of` must fail closed to unknown no_version_applies; "
        f"got {derived['item_future_only']!r}"
    )


@pytest.mark.xfail(
    strict=True,
    raises=AssertionError,
    reason=(
        "M3: decisions/language-rezono-1.md: section 2; `unit` declared on a `rezono 1` derivation "
        "must be validated against the pack's declared units and value type instead of being silently dropped."
    ),
)
def test_derived_unit_validated_against_pack_units_and_type(tmp_path: Path):
    decls = [
        {"kind": "Item", "world": "closed", "slots": [{"slot": "name", "type": "Text"}], "derived": []},
        {
            "extend": "Item",
            "derived": [
                {
                    "derived": "bogus",
                    "type": "Text",
                    "unit": "NonexistentFakeUnit",
                    "value": {"path": ["it", "name"]},
                },
            ],
        },
    ]
    directory = _write_rezono1_json_pack(tmp_path / "bad-unit", decls)
    raised: pack.CompileError | None = None
    try:
        emit.compile_pack(pack.read(directory))
    except pack.CompileError as err:
        raised = err
    assert raised is not None, (
        "derived bogus: Text with undeclared unit='NonexistentFakeUnit' must raise CompileError, "
        "never silently drop the unit"
    )


@pytest.mark.xfail(
    strict=True,
    raises=AssertionError,
    reason=(
        "M3: decisions/language-rezono-1.md: section 2; a functional kind-typed derived property "
        "(`derived owner: Person = it.p`) must preserve its kind type so slot chaining (`it.owner.label`) "
        "compiles cleanly and evaluates on DuckDB instead of failing with R003."
    ),
)
def test_functional_kind_derived_property_supports_slot_chaining(tmp_path: Path):
    decls = [
        {"kind": "Person", "world": "closed", "slots": [{"slot": "label", "type": "Text"}], "derived": []},
        {"kind": "Item", "world": "closed", "slots": [{"slot": "p", "type": "Person"}], "derived": []},
        {
            "extend": "Item",
            "derived": [
                {"derived": "owner", "type": "Person", "value": {"path": ["it", "p"]}},
                {"derived": "owner_label", "type": "Text", "value": {"path": ["it", "owner", "label"]}},
            ],
        },
    ]
    facts_yaml = "person:\n  - {id: p1, label: alice}\nitem:\n  - {id: x1, p: p1}\n"
    directory = _write_rezono1_json_pack(tmp_path / "chain-prop", decls, facts_yaml)
    _, _, derived = _compile_and_run_duckdb(directory)

    assert derived["item_owner_label"] == {("x1", "known", "", "alice")}, (
        f"expected chained property it.owner.label to evaluate to ('x1', 'known', '', 'alice'); "
        f"got {derived['item_owner_label']!r}"
    )


@pytest.mark.xfail(
    strict=True,
    raises=AssertionError,
    reason=(
        "M3: decisions/language-rezono-1.md: section 2; `@ source` on `unless` clauses in rezono_derived.py "
        "must be preserved on the compiled bundle rule entries instead of being silently dropped."
    ),
)
def test_unless_clause_source_preserved_in_bundle_rules(tmp_path: Path):
    unless_decls = [
        {"kind": "Item", "world": "closed", "slots": [{"slot": "score", "type": "Int"}], "derived": []},
        {
            "extend": "Item",
            "derived": [
                {
                    "derived": "capped",
                    "type": "Int",
                    "value": {"path": ["it", "score"]},
                    "unless": [
                        [
                            {
                                "when": {"cmp": [">", {"path": ["it", "score"]}, {"lit": "10"}]},
                                "then": {"lit": "10"},
                                "source": "law#art-7",
                            }
                        ]
                    ],
                },
            ],
        },
    ]
    unless_dir = _write_rezono1_json_pack(tmp_path / "unless-source", unless_decls, "item:\n  - {id: x1, score: 15}\n")
    _, bundle, _ = _compile_and_run_duckdb(unless_dir)
    capped_sources = {
        entry.get("source")
        for entry in bundle.get("rules", [])
        if entry.get("relation") == "item_capped"
    }
    assert "law#art-7" in capped_sources, (
        f"`@ law#art-7` on unless clause was dropped from compiled bundle rules; got sources={capped_sources!r}"
    )


@pytest.mark.xfail(
    strict=True,
    raises=AssertionError,
    reason=(
        "M3: decisions/language-rezono-1.md: section 2; signed/decimal inline parameter values with a declared "
        "unit in rezono_calc.py must retain their declared unit through calc.build, and rezono_calc date "
        "validators must reject invalid calendar dates such as 2026-02-30."
    ),
)
def test_signed_decimal_inline_param_units_and_calendar_date_validation(tmp_path: Path):
    # 1. Positive and negative decimal inline parameters with declared unit `Cents` must retain unit and pass calc.build.
    calc_decls = [
        {"unit": "Cents", "is": "money minor EUR"},
        {"kind": "Record", "world": "closed", "slots": [{"slot": "metric", "type": "Cents"}], "derived": []},
        {"param": "pos_dec", "type": "Cents", "value": {"lit": "12.50"}},
        {"param": "neg_dec", "type": "Cents", "value": {"neg": {"lit": "12.50"}}},
        {
            "extend": "Record",
            "derived": [
                {
                    "derived": "total",
                    "type": "Cents",
                    "value": {
                        "arith": [
                            "+",
                            {"arith": ["+", {"path": ["pos_dec"]}, {"path": ["neg_dec"]}]},
                            {"path": ["metric"]},
                        ]
                    },
                },
            ],
        },
        {"asOf": "2025-06-01", "known": "2025-06-01"},
    ]
    calc_dir = _write_calc_json_pack(tmp_path / "calc-units", calc_decls)
    try:
        model = pack.read(calc_dir)
        assert model.calc is not None
        program = calc.build(model, model.calc)
    except pack.CompileError as err:
        raise AssertionError(
            f"signed/decimal inline parameters with declared unit Cents must retain unit and pass calc.build: {err}"
        ) from err
    assert program.versions["pos_dec@1"].unit == "Cents"
    assert program.versions["neg_dec@1"].unit == "Cents"

    # 2. Invalid calendar dates such as 2026-02-30 must be rejected by rezono_calc.validate_param and validate_as_of.
    param_errors: list[tuple[str, str]] = []
    rezono_calc.validate_param(
        {
            "param": "bad_param",
            "type": "Cents",
            "versions": [{"version": "1", "valid": ["2026-02-30"], "known": "2026-02-30", "value": {"lit": "10"}}],
        },
        "/decls/2",
        lambda at, message, *_extra: param_errors.append((at, message)),
    )
    assert param_errors, "invalid calendar date 2026-02-30 in inline parameter version must be rejected"

    as_of_errors: list[tuple[str, str]] = []
    rezono_calc.validate_as_of(
        {"asOf": "2026-02-30", "known": "2026-02-30"},
        "/decls/3",
        lambda at, message, *_extra: as_of_errors.append((at, message)),
    )
    assert as_of_errors, "invalid calendar date 2026-02-30 in `as of` declaration must be rejected"


@pytest.mark.xfail(
    strict=True,
    raises=AssertionError,
    reason=(
        "M3: decisions/language-rezono-1.md: section 2; key_of_signs.load() must return fresh independent copies "
        "so mutating a returned dict or list never corrupts subsequent calls."
    ),
)
def test_key_of_signs_load_returns_fresh_independent_copies(tmp_path: Path):
    std_view_copy = tmp_path / "std-view"
    shutil.copytree(ROOT / "packs" / "std-view", std_view_copy)
    first_key, _ = key_of_signs.load(std_view_copy)
    original_glyph = first_key["statuses"][0]["glyph"]
    original_count = len(first_key["statuses"])
    first_key["statuses"][0]["glyph"] = "CORRUPTED"
    first_key["statuses"].append({"status": "bogus"})

    second_key, _ = key_of_signs.load(std_view_copy)
    assert second_key["statuses"][0]["glyph"] == original_glyph, (
        "mutating key_of_signs.load() result corrupted cached status glyph"
    )
    assert len(second_key["statuses"]) == original_count, (
        "mutating key_of_signs.load() result corrupted cached status list"
    )
