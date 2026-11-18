"""Subsidy awards and decisions in the two final cumulative states."""
import importlib.util
from datetime import date
from pathlib import Path

import pytest

pytest.importorskip("duckdb")
pytest.importorskip("rezono_compiler")

from calcsupport import checked, connect, results, run_both
from rezono_compiler import calc, calc_sql, pack, scenarios

HERE = Path(__file__).parent


def reference():
    """The pack's reference.py under a name of its own: other packs have a reference.py too."""
    spec = importlib.util.spec_from_file_location("subsidy_reference", HERE / "reference.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_the_evaluation_date_decides_the_partial_rate():
    """The partial rate has two rows (facts/scheme.yaml): 20% until 1 July 2026, 24% from then on. The
    evaluation date is a fact row, so asking for another date needs no compilation."""
    ref = reference()
    model = pack.read(HERE)
    prog = calc.build(model, model.calc)
    _, facts = scenarios.states(model, HERE)[0]
    t = next(ref.states())[1]

    def awards(valid_at: str):
        as_of = {table: [tuple({**r, "valid_at": valid_at if isinstance(r["valid_at"], str) else date.fromisoformat(valid_at)}.values())
                         for r in rs] for table, rs in calc_sql.rows(prog).items()}
        got, exact = run_both(model, prog, model.calc, facts | as_of)
        assert got == exact
        mine = ref.calc(t, on=valid_at)["award"]
        assert {a: (v[1] if v[0] == "known" else v[0]) for a, v in got["award"].items()} == mine
        return mine

    spring, autumn = awards("2026-03-01"), awards("2026-11-10")
    assert (spring["A001"], autumn["A001"]) == ("227000", "269400")  # 20% and 24% of 10,600 euros, plus the allowance
    assert spring["A002"] == autumn["A002"] == "166000"                # the full rate did not change
    assert spring["A003"] == autumn["A003"] == "unknown"               # and unknown stays unknown, on any date


@pytest.fixture(scope="module")
def final_states():
    model = pack.read(HERE)
    program = calc.build(model, model.calc)
    as_of = {table: [tuple(row.values()) for row in rows] for table, rows in calc_sql.rows(program).items()}
    facts = dict(scenarios.states(model, HERE))
    ref = reference()
    states = {}
    for name, inputs in ref.states():
        if name not in ("3-late-payment", "4-family-threshold"):
            continue
        with connect(model, program, facts[name] | as_of) as db:
            assert checked(db, program) == [], name
            awards = {key: value if state == "known" else state
                      for key, (state, value, *_) in results(db, program)["award"].items()}
            assert awards == ref.calc(inputs)["award"], name
            decisions = {}
            expected = ref.rules(inputs)
            for relation in ("decided_parameter", "undecided_parameter"):
                rows = db.execute(f"SELECT * FROM {relation}").fetchall()
                decisions[relation] = sorted([str(cell) for cell in row] for row in rows)
                assert decisions[relation] == expected[relation], (name, relation)
            states[name] = {"award": awards, **decisions}
    return states["3-late-payment"], states["4-family-threshold"]


def test_the_supposed_threshold_has_gainers_and_losers(final_states):
    """Compare the population under the original and proposed household thresholds."""
    before, after = (state["award"] for state in final_states)
    known = [a for a in before if before[a] != "unknown"]
    assert [a for a in before if (before[a] == "unknown") != (after[a] == "unknown")] == []
    change = {a: int(after[a]) - int(before[a]) for a in known}
    gain, lose = [d for d in change.values() if d > 0], [d for d in change.values() if d < 0]
    assert (len(gain), sum(gain)) == (23, 2780081)
    assert (len(lose), sum(lose)) == (14, -1760996)
    assert (len(known) - len(gain) - len(lose), len(before) - len(known)) == (187, 16)


def test_a_supposed_amount_is_reported_as_not_decided(final_states):
    """The two proposed parameters are the only ones without a decision in force."""
    before, after = final_states
    assert before["undecided_parameter"] == [] and len(before["decided_parameter"]) == 8
    assert ["par-06", "2026-047", "2026-11-10"] in before["decided_parameter"]
    assert after["undecided_parameter"] == [["par-01", "2026-11-10"], ["par-02", "2026-11-10"]]
    assert len(after["decided_parameter"]) == 6
