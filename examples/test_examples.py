"""Recorded byte comparisons, determinism for every example pack, and for every fact
file in facts/ its hand-written expected violations (on DuckDB). A file in diagnostics/ is a known bad
import, kept to show what the checks find; it is no fact state and is never published, so it must
give violations, exactly those in expected/diagnostics/."""

import json
from functools import cache
from pathlib import Path

import pytest

from calcsupport import run_both
from golden import differences, golden
from rezono_compiler import calc, calc_sql, pack, scenarios
from rezono_compiler import facts as fact_files
from support import FIXTURE, REPO, compile_dir, expected, load, violations

ROOT = Path(__file__).parent
RECORDED_OUTPUT = ROOT / "fixtures" / "recorded-output"


def discover_examples(root: Path) -> list[Path]:
    return sorted(p.parent for p in root.rglob("pack.yaml") if (p.parent / "facts").is_dir())


EXAMPLES = discover_examples(ROOT)
FACT_FILES = [(e, f.stem) for e in EXAMPLES for f in sorted((e / "facts").glob("*.yaml"))
              if not f.name.endswith(".sources.yaml")]  # a sidecar is metadata of its fact file
DIAGNOSTICS = [(e, f.stem) for e in EXAMPLES for f in sorted((e / "diagnostics").glob("*.yaml"))]


def name(p: Path) -> str:
    return str(p.relative_to(ROOT))


def tree(d: Path) -> dict[str, bytes]:
    return {p.relative_to(d).as_posix(): p.read_bytes() for p in sorted(d.rglob("*")) if p.is_file()}


def test_examples_are_found(tmp_path):
    files = {
        "first/pack.yaml": "name: first\n",
        "first/facts/items.yaml": "item: [{id: first-item}]\n",
        "group/second/pack.yaml": "name: second\n",
        "group/second/facts/items.yaml": "item: [{id: second-item}]\n",
        "schema-only/pack.yaml": "name: schema-only\n",
        "unowned/facts/items.yaml": "item: [{id: orphan}]\n",
    }
    for name, contents in files.items():
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(contents, encoding="utf-8")
    assert discover_examples(tmp_path) == [tmp_path / "first", tmp_path / "group" / "second"]
    assert EXAMPLES


def test_golden_bytes(tmp_path):
    """Check the small recorded output and any complete example snapshots."""
    files = compile_dir(FIXTURE, tmp_path / "recorded")
    path = "engine/parameters.json"
    recorded = (RECORDED_OUTPUT / "parameters.json").read_text(encoding="utf-8").encode("utf-8")
    diff = differences(golden({path: files[path]}), {path: recorded})
    assert not diff, diff
    assert violations(files, load(FIXTURE, RECORDED_OUTPUT / "rows.yaml")) == {
        "alpha__size__value_range": {("outside", "10")},
    }

    for example in EXAMPLES:
        snapshot = example / "expected" / "compiled"
        if not snapshot.is_dir():
            continue
        output = tmp_path / "examples" / example.relative_to(ROOT)
        diff = differences(golden(compile_dir(example, output)), tree(snapshot))
        assert not diff, f"{name(example)}:\n{diff}"


@pytest.mark.parametrize("example", EXAMPLES, ids=name)
def test_two_compiles_give_identical_bytes(example, tmp_path):
    compile_dir(example, tmp_path / "a")
    compile_dir(example, tmp_path / "b")
    diff = differences(tree(tmp_path / "b"), tree(tmp_path / "a"))
    assert not diff, diff


@pytest.mark.parametrize("example, facts", FACT_FILES, ids=[f"{name(e)}:{f}" for e, f in FACT_FILES])
def test_violations(example, facts, committed_packs):
    """The pack as compiled once for this process (its compile is checked above); its own copy for each file."""
    want = example / "expected" / "violations" / f"{facts}.json"
    assert want.exists(), f"{name(example)}: facts/{facts}.yaml has no expected/violations/{facts}.json"
    files = committed_packs.compiled(example)
    rows = fact_files.load(committed_packs.model(example), example / "facts" / f"{facts}.yaml")
    assert violations(files, rows) == expected(want)


@pytest.mark.parametrize("example, fixture", DIAGNOSTICS, ids=[f"{name(e)}:{f}" for e, f in DIAGNOSTICS])
def test_diagnostics(example, fixture, committed_packs):
    want = example / "expected" / "diagnostics" / f"{fixture}.json"
    assert want.exists(), f"{name(example)}: diagnostics/{fixture}.yaml has no expected/diagnostics/{fixture}.json"
    assert expected(want), f"{name(example)}: a diagnostic fixture shows at least one violation"
    files = committed_packs.compiled(example)
    rows = fact_files.load(committed_packs.model(example), example / "diagnostics" / f"{fixture}.yaml")
    assert violations(files, rows) == expected(want)


# --- Calculation rules (M3): every pack with calc/, per fact state --------------------------------

CALC = [e for e in EXAMPLES if (e / "calc").is_dir()]
SUBSIDY = ROOT / "subsidy"
# Packs whose expected/calc no calc/ program covers yet: one explicit list, each with its reason.
# A pack that gets calc/ must leave the list (the test below fails until it does).
CALC_GAPS: dict[str, str] = {}
WITH_EXPECTED_CALC = [e for e in EXAMPLES if (e / "expected" / "calc").is_dir()]


def test_every_known_gap_is_a_pack():
    assert set(CALC_GAPS) <= {name(e) for e in WITH_EXPECTED_CALC}, "CALC_GAPS names a pack without expected/calc"


def test_calculation_examples_are_found():
    assert SUBSIDY in CALC, "the subsidy example evaluates the award and payment difference"


@pytest.mark.parametrize("example", WITH_EXPECTED_CALC, ids=name)
def test_every_expected_calc_has_a_program(example):
    """A pack that states expected outcomes for calculation has the calculation rules to reach them."""
    gap = CALC_GAPS.get(name(example))
    if gap:
        assert not (example / "calc").is_dir(), f"{name(example)} has calc/ now: take it off CALC_GAPS"
        pytest.skip(f"known gap: {gap}")
    assert (example / "calc").is_dir(), f"{name(example)} has expected/calc but no calc/ program"


@cache
def checked_calculations(example):
    """Run both evaluators once per fact state. Keep their agreed results for the byte comparison."""
    model = pack.read(example)
    prog = calc.build(model, model.calc)
    evaluation_rows = {t: [tuple(r.values()) for r in rs] for t, rs in calc_sql.rows(prog).items()}
    outputs = {}
    for label, rows in scenarios.states(model, example):
        assert label not in outputs, label
        got, reference = run_both(model, prog, model.calc, rows | evaluation_rows)
        assert got == reference, label
        assert got and got.keys() == prog.rules.keys(), label
        outputs[label] = got
    return outputs


@pytest.mark.parametrize("example", CALC, ids=name)
def test_calculation_rules(example):
    """Check the full DuckDB and exact Python results for the initial facts and each authored scenario."""
    facts = [stem for directory, stem in FACT_FILES if directory == example]
    labels = ([f"0-{facts[0]}"] if facts else []) + [p.stem for p in sorted((example / "scenarios").glob("*.yaml"))]
    assert labels and list(checked_calculations(example)) == labels


def test_receiving_the_income_statement_establishes_the_award_and_payment_difference():
    """The worked A003 scenario in the subsidy README, in cents."""
    outputs = checked_calculations(SUBSIDY)
    before, after = outputs["0-applications"], outputs["1-income-received"]
    assert before["award"]["A003"][:2] == before["payment_difference"]["A003"][:2] == ("unknown", "")
    # The documented partial rate gives 327550 × 24% = 78612. The ledger already paid 131020.
    assert after["award"]["A003"][:2] == ("known", "78612")
    assert after["payment_difference"]["A003"][:2] == ("known", "52408")


class MissingCalculationFiles(FileNotFoundError):
    """The reviewed calculation files for one or more fact states are absent."""


@pytest.mark.parametrize("example", [
    *(pytest.param(e, id=name(e)) for e in CALC if e != SUBSIDY),
    pytest.param(SUBSIDY, id="subsidy"),
])
def test_calculation_reference_files(example):
    """Compare the complete serialized output and write candidates for missing or changed files under compiled/."""
    outputs = checked_calculations(example)
    files = sorted((example / "expected" / "calc").glob("*.json"))
    missing, changed = [], []
    for label, result in outputs.items():
        want = example / "expected" / "calc" / f"{label}.json"
        data = golden_text(result).encode("utf-8")
        if not want.exists():
            missing.append(label)
        elif want.read_bytes() != data:
            changed.append(label)
        else:
            continue
        out = REPO / "compiled" / example.relative_to(REPO) / "expected" / "calc" / want.name
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_bytes(data)
    assert not changed, f"expected/calc differs for {changed}; candidates are under compiled/"
    unexpected = {f.stem for f in files} - outputs.keys()
    assert not unexpected, f"unexpected expected/calc files: {sorted(unexpected)}"
    if missing:
        raise MissingCalculationFiles(f"{name(example)}: missing expected/calc for {missing}")
    assert [f.stem for f in files] == list(outputs), "one expected/calc file per fact state"


def golden_text(results: dict[str, dict]) -> str:
    """Per rule and subject the value, or the state when it is not known. No reasons: a pack's own
    reference writes this file too, and the reasons are checked against the exact reference above."""
    out = {rule: {str(s): (v[1] if v[0] == "known" else v[0]) for s, v in sorted(subjects.items())}
           for rule, subjects in sorted(results.items())}
    return json.dumps(out, ensure_ascii=False, indent=1, sort_keys=True) + "\n"
