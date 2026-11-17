"""Every example pack under examples/, at any depth: golden bytes, determinism, and for every fact
file in facts/ its hand-written expected violations (on DuckDB). A file in diagnostics/ is a known bad
import, kept to show what the checks find; it is no fact state and is never published, so it must
give violations, exactly those in expected/diagnostics/."""

import json
from pathlib import Path

import pytest

from calcsupport import run_both
from golden import differences, golden
from rede_compiler import calc, calc_sql, pack, scenarios
from support import REPO, compile_dir, expected, load, violations

ROOT = Path(__file__).parent
EXAMPLES = sorted(p.parent for p in ROOT.rglob("pack.yaml") if (p.parent / "facts").is_dir())
FACT_FILES = [(e, f.stem) for e in EXAMPLES for f in sorted((e / "facts").glob("*.yaml"))
              if not f.name.endswith(".sources.yaml")]  # a sidecar is metadata of its fact file (S25)
DIAGNOSTICS = [(e, f.stem) for e in EXAMPLES for f in sorted((e / "diagnostics").glob("*.yaml"))]


def name(p: Path) -> str:
    return str(p.relative_to(ROOT))


def tree(d: Path) -> dict[str, bytes]:
    return {p.relative_to(d).as_posix(): p.read_bytes() for p in sorted(d.rglob("*")) if p.is_file()}


@pytest.mark.xfail(strict=True, reason="generated expected/compiled goldens are not stored in git")
def test_examples_are_found():
    assert EXAMPLES and all((e / "expected" / "compiled").is_dir() for e in EXAMPLES), \
        [name(e) for e in EXAMPLES if not (e / "expected" / "compiled").is_dir()]


@pytest.mark.xfail(strict=True, reason="generated expected/compiled goldens are not stored in git")
@pytest.mark.parametrize("example", EXAMPLES, ids=name)
def test_golden_bytes(example, tmp_path):
    """The golden form: every file, but a large one by its hash (compiler/tests/golden.py)."""
    diff = differences(golden(compile_dir(example, tmp_path)), tree(example / "expected" / "compiled"))
    assert not diff, diff


@pytest.mark.parametrize("example", EXAMPLES, ids=name)
def test_two_compiles_give_identical_bytes(example, tmp_path):
    compile_dir(example, tmp_path / "a")
    compile_dir(example, tmp_path / "b")
    diff = differences(tree(tmp_path / "b"), tree(tmp_path / "a"))
    assert not diff, diff


@pytest.mark.parametrize("example, facts", FACT_FILES, ids=[f"{name(e)}:{f}" for e, f in FACT_FILES])
def test_violations(example, facts, tmp_path):
    want = example / "expected" / "violations" / f"{facts}.json"
    assert want.exists(), f"{name(example)}: facts/{facts}.yaml has no expected/violations/{facts}.json"
    files = compile_dir(example, tmp_path)
    assert violations(files, load(example, example / "facts" / f"{facts}.yaml")) == expected(want)


@pytest.mark.parametrize("example, fixture", DIAGNOSTICS, ids=[f"{name(e)}:{f}" for e, f in DIAGNOSTICS])
def test_diagnostics(example, fixture, tmp_path):
    want = example / "expected" / "diagnostics" / f"{fixture}.json"
    assert want.exists(), f"{name(example)}: diagnostics/{fixture}.yaml has no expected/diagnostics/{fixture}.json"
    assert expected(want), f"{name(example)}: a diagnostic fixture shows at least one violation"
    files = compile_dir(example, tmp_path)
    assert violations(files, load(example, example / "diagnostics" / f"{fixture}.yaml")) == expected(want)


# --- Calculation rules (M3): every pack with calc/, per fact state --------------------------------

CALC = [e for e in EXAMPLES if (e / "calc").is_dir()]
# Packs whose expected/calc no calc/ program covers yet: one explicit list, each with its reason.
# A pack that gets calc/ must leave the list (the test below fails until it does).
CALC_GAPS: dict[str, str] = {}
WITH_EXPECTED_CALC = [e for e in EXAMPLES if (e / "expected" / "calc").is_dir()]


def test_every_known_gap_is_a_pack():
    assert set(CALC_GAPS) <= {name(e) for e in WITH_EXPECTED_CALC}, "CALC_GAPS names a pack without expected/calc"


@pytest.mark.parametrize("example", WITH_EXPECTED_CALC, ids=name)
def test_every_expected_calc_has_a_program(example):
    """A pack that states expected outcomes for calculation has the calculation rules to reach them."""
    gap = CALC_GAPS.get(name(example))
    if gap:
        assert not (example / "calc").is_dir(), f"{name(example)} has calc/ now: take it off CALC_GAPS"
        pytest.skip(f"known gap: {gap}")
    assert (example / "calc").is_dir(), f"{name(example)} has expected/calc but no calc/ program"



@pytest.mark.xfail(strict=True, reason="generated expected/calc goldens are not stored in git")
@pytest.mark.parametrize("example", CALC, ids=name)
def test_calculation_rules(example):
    """Per fact state (facts/ together, then each scenarios/*.yaml cumulatively): DuckDB gives exactly
    what the exact reference gives, and that is expected/calc/<state>.json. A new or changed golden
    comes from CI (artifact compiled-examples), never from a local machine."""
    model = pack.read(example)
    prog = calc.build(model, model.calc)
    states = scenarios.states(model, example)
    files = sorted((example / "expected" / "calc").glob("*.json"))
    wrong = []
    for label, rows in states:
        rows = rows | {t: [tuple(r.values()) for r in rs] for t, rs in calc_sql.rows(prog).items()}
        got, reference = run_both(model, prog, model.calc, rows)
        assert got == reference, label
        want = example / "expected" / "calc" / f"{label}.json"
        text = golden_text(got)
        if not want.exists() or want.read_text(encoding="utf-8") != text:
            out = REPO / "compiled" / example.relative_to(REPO) / "expected" / "calc" / want.name
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_text(text, encoding="utf-8")
            wrong.append(label)
    assert [f.stem for f in files] == [s for s, _ in states], "one expected/calc file per fact state"
    assert not wrong, f"expected/calc differs for {wrong}; the new files are in the CI artifact"


def golden_text(results: dict[str, dict]) -> str:
    """Per rule and subject the value, or the state when it is not known. No reasons: a pack's own
    reference writes this file too, and the reasons are checked against the exact reference above."""
    out = {rule: {str(s): (v[1] if v[0] == "known" else v[0]) for s, v in sorted(subjects.items())}
           for rule, subjects in sorted(results.items())}
    return json.dumps(out, ensure_ascii=False, indent=1, sort_keys=True) + "\n"
