"""The calculation check (rezono_checker/calc.py) on planted faults, without the compiler.

The example is one compiled calculation program, frozen as data in tests/fixtures/calc: `calc.json` (ir/calc.json),
`snapshots.json` (every table as its rows; a calculation view as subject, value, state, reason) and
`witnesses.json` (the witness of every evaluation). The compiler's own tests compile it again and hold it against
these files (compiler/tests/test_calc.py), so the checker is tested here on what the compiler really gives, and
this file imports nothing of it. Each case changes the witnesses as a wrong engine would, and names the reason.

The rows themselves are held too (calc.total). A wrong engine that leaves out a row and its witness leaves
nothing wrong behind; only the count of rows per subject refuses it.
"""

import copy
import hashlib
import json
import re
from pathlib import Path

import pytest

from rezono_checker import calc
from rezono_checker.canon import encode_key
from rezono_checker.check import check_epoch
from rezono_checker.rules import load_rules

HERE = Path(__file__).parent / "fixtures" / "calc"


def frozen(name):
    return json.loads((HERE / name).read_text(encoding="utf-8"))


IR = frozen("calc.json")


def planted(change=None, forge=None) -> list[str]:
    """The checker's reasons after one change to the witnesses; `forge(witnesses, snapshots)` may also add
    or drop witnesses and rows, as a wrong engine would. The reasons are those of every witness (calc.check)
    and of the rows of the complete snapshots (calc.total)."""
    witnesses, snapshots = frozen("witnesses.json"), frozen("snapshots.json")
    by = {(w["conclusion"]["relation"], json.loads(w["conclusion"]["key"])[0]): w for w in witnesses}
    if change:
        change(by)
    if forge:
        forge(witnesses, snapshots)
    rows = {name: {encode_key(parts): (tuple(parts), {}) for parts in table} for name, table in snapshots.items()}
    kept = [w for w in witnesses if w.pop("keep", True)]

    def read(relation):
        return rows.get(relation, {})

    return sorted({f["reason"] for f in calc.check(kept, IR, read) + calc.total(IR, read)})


def step(w, path) -> dict:
    return next(s for s in w["steps"] if s["path"] == path)


def version(by):  # v3 is valid on the evaluation date but known only later
    by["calc__rate", "i0"]["version"] = "v3"


def branch(by):  # lazy, flag false: the engine took the first branch
    w = by["calc__lazy", "i1"]
    w["steps"] = [s for s in w["steps"] if s["path"] != "base/value/2"]
    step(w, "base/value").update(value="1", state="known", reason="")
    w.update(value="1", state="known", reason="")


def rounding(by):  # round(7/2) half down instead of away from zero
    w = by["calc__half", "i0"]
    step(w, "base/value")["value"] = "3"
    w["value"] = "3"


def zero(by):  # x0 is missing for i1, and was taken as 0: 0 + 1
    w = by["calc__concept", "i1"]
    step(w, "base/value").update(value="1", state="known", reason="")
    w.update(value="1", state="known", reason="")


def wrapped(by):  # 2^63 - 1 + 1 beyond the numeric bound, given as the value a 64-bit sum wraps to
    w = by["calc__overflow", "i0"]
    step(w, "base/value").update(value="-9223372036854775808", state="known", reason="")
    w.update(value="-9223372036854775808", state="known", reason="")


def guessed(by):  # pow(2, 64) beyond the bound, given as its exact value: the result must still be unknown
    w = by["calc__too_big", "i0"]
    step(w, "base/value").update(value=str(2**64), state="known", reason="")
    w.update(value=str(2**64), state="known", reason="")


def leaf(by):  # the step says x0 = 0, the facts have no x0 for i1
    step(by["calc__concept", "i1"], "base/value/0").update(value="0", state="known", reason="")


def row(by):  # the parameter step names an element the leaf did not read
    step(by["calc__parameters", "i1"], "base/value/0")["element"] = "s9"


def node(by):  # the step names another rule than the program's leaf: its link would be wrong
    step(by["calc__uses", "i0"], "base/value/0").update(ref="rate@v1", relation="calc__rate__v1")


def operator(by):  # an operator step that claims to be a leaf
    step(by["calc__uses", "i0"], "base/value")["op"] = "fact"


def definition(by):  # the flag makes `special` go before `base`
    by["calc__prefer", "i0"]["definition"] = "base"


def premise(by):  # uses reads rate, whose witness is gone
    by["calc__rate", "i0"]["keep"] = False


# Witnesses a wrong engine could write consistently, row and all (review of #139).

def unreadable(by):  # a condition that is no canonical value decides nothing; never a silent pass
    step(by["calc__prefer", "i0"], "special/when")["value"] = "yes"


def number_condition(by):  # the number 1 for a condition: no boolean
    step(by["calc__prefer", "i0"], "special/when")["value"] = "1"


def number_flag(by):  # the flag of lazy as 1 instead of true: True == Fraction(1) must not pass
    step(by["calc__lazy", "i0"], "base/value/0")["value"] = "1"


def fabricated(by):  # a premise none of its evaluated leaves reads
    by["calc__uses", "i0"]["premises"].append({"relation": "item", "key": '["i0"]'})


def self_cycle(by):  # it rests on itself
    w = by["calc__uses", "i0"]
    w["premises"].append(dict(w["conclusion"]))


def narrower(by):  # a smaller read set would let a role see what rests on rows it reads in part
    by["calc__half", "i0"]["reads"] = ["calc__as_of"]


def stranger(witnesses, snapshots):  # a row and a witness for a subject that is no item
    w = copy.deepcopy(next(w for w in witnesses if w["conclusion"]["relation"] == "calc__negative_half"))
    w["conclusion"]["key"] = '["i9","-1","known",""]'
    witnesses.append(w)
    snapshots["calc__negative_half"].append(["i9", *snapshots["calc__negative_half"][0][1:]])


# Rows a wrong engine could leave out or add, every witness it kept still right.

def absent(witnesses, snapshots):  # i1 has no amount: its half is unknown, which is a row, never no row
    snapshots["calc__half"] = [r for r in snapshots["calc__half"] if r[0] != "i1"]
    witnesses[:] = [w for w in witnesses if (w["conclusion"]["relation"], calc.subject_of(w["conclusion"]["key"]))
                    != ("calc__half", "i1")]


def twice(witnesses, snapshots):  # a second value for i0 in one view
    snapshots["calc__half"].append(["i0", "5", "known", ""])


def stateless(witnesses, snapshots):  # a row for i1 without a state is no row with a state
    absent(witnesses, snapshots)
    snapshots["calc__half"].append(["i1", "", "", ""])


# (the change, the forgery, the reasons it must give, and whether those are all it gives)
CASES = [
    (version, None, {"calc_version"}, False),
    (branch, None, {"calc_path"}, False),
    (rounding, None, {"calc_step"}, False),
    (zero, None, {"calc_step"}, False),
    (wrapped, None, {"calc_step"}, False),
    (guessed, None, {"calc_step"}, False),
    (leaf, None, {"calc_leaf"}, False),
    (row, None, {"calc_leaf"}, True),
    (node, None, {"calc_node"}, True),
    (operator, None, {"calc_node"}, True),
    (definition, None, {"calc_result"}, True),
    (premise, None, {"unproven_premise"}, False),
    (unreadable, None, {"calc_step", "calc_result"}, False),
    (number_condition, None, {"calc_leaf"}, False),
    (number_flag, None, {"calc_leaf"}, False),
    (None, stranger, {"calc_result"}, True),
    (fabricated, None, {"calc_premise"}, False),
    (self_cycle, None, {"calc_premise", "cycle"}, False),
    (narrower, None, {"calc_reads"}, False),
    (None, absent, {"calc_row_missing"}, True),
    (None, twice, {"calc_row_duplicate"}, True),
    (None, stateless, {"calc_row_missing"}, True),
]


def test_the_frozen_example_is_valid():
    assert planted() == []


@pytest.mark.parametrize("change, forge, reasons, exactly", CASES, ids=lambda v: getattr(v, "__name__", ""))
def test_the_checker_finds_a_planted_error(change, forge, reasons, exactly):
    found = set(planted(change, forge))
    assert found == reasons if exactly else reasons <= found


def epoch(forge=None, full=None) -> set[str]:
    """The reasons check_epoch gives the frozen example: as the complete epoch, or as one role's (`full`)."""
    witnesses, snapshots = frozen("witnesses.json"), frozen("snapshots.json")
    if forge:
        forge(witnesses, snapshots)
    files = {name: json.dumps([{"key": parts} for parts in table]).encode() for name, table in snapshots.items()}
    manifest = {"id": "m-1", "snapshots": [
        {"relation": name, "role": "all", "complete": True, "uri": name, "format": "json",
         "sha256": hashlib.sha256(data).hexdigest()} for name, data in files.items()]}
    rules = load_rules({"format": "rezono.rules/1", "relations": [], "rules": []})
    report = check_epoch([], manifest, rules, files.__getitem__, derived=set(), full=full,
                         calc_witnesses=witnesses, calc_ir=IR)
    return {f["reason"] for f in report["findings"]}


def test_a_missing_calculated_row_refuses_the_complete_epoch_and_no_role():
    """The complete epoch owes every subject its row. A role may read a subject and not see its calculated row,
    so its filtered snapshots get no such check. The example's own `invalid` results never
    publish (`calc_invalid`); that is all an epoch of it is refused for."""
    everything = set(frozen("snapshots.json"))
    assert epoch() == epoch(full=everything) == {"calc_invalid"}
    assert epoch(absent) == {"calc_invalid", "calc_row_missing"}
    assert epoch(absent, full=everything) == {"calc_invalid"}


def test_every_reason_of_the_calculation_check_is_reached():
    """A reason the calculation check can give and no case here plants would be an untested check."""
    source = (Path(calc.__file__)).read_text(encoding="utf-8")
    assert set(re.findall(r'"(calc_[a-z_]+)"', source)) <= set().union(*(reasons for _, _, reasons, _ in CASES))


def test_no_test_of_the_checker_imports_the_compiler():
    """The checker's suite runs with the checker alone: no test file here has an import of the compiler."""
    tests = sorted(Path(__file__).parent.glob("*.py"))
    assert tests
    assert [t.name for t in tests if re.search(r"^\s*(from|import)\s+rezono_compiler", t.read_text(encoding="utf-8"), re.M)] == []


# --- The cost follows the witnesses, not the snapshots ------------------------------------------------

SUBJECT = re.compile(r"(?<![\w-])([ie][0-9])(?![\w-])")  # the example's items i0..i2 and entries e0, e1


class Counted(dict):
    """A table that counts every row a pass over it visits."""
    visits = 0

    def values(self):
        for v in super().values():
            Counted.visits += 1
            yield v

    def items(self):
        for kv in super().items():
            Counted.visits += 1
            yield kv


def scaled(copies: int, witnessed: int):
    """The example with its items and entries copied `copies` times (copy c renames i0 to i0-c), and the witnesses
    and calculated rows of only the first `witnessed` copies: a large snapshot, few witnesses."""
    witnesses, snapshots = frozen("witnesses.json"), frozen("snapshots.json")
    rename = lambda text, c: SUBJECT.sub(lambda m: f"{m.group(1)}-{c}", text)
    rows = {}
    for name, table in snapshots.items():
        per_subject = any(SUBJECT.fullmatch(x) for parts in table for x in parts)
        calculated = name.startswith("calc__") and name != IR["as_of"] and not name.startswith("calc__input")
        upto = witnessed if calculated else copies
        copied = [json.loads(rename(json.dumps(parts), c)) for c in range(upto) for parts in table] if per_subject else table
        rows[name] = Counted({encode_key(parts): (tuple(parts), {}) for parts in copied})
    ws = [json.loads(rename(json.dumps(w), c)) for c in range(witnessed) for w in witnesses]
    return ws, (lambda relation: rows.get(relation, Counted()))


def test_the_calculation_check_visits_rows_in_proportion_to_its_witnesses():
    """20,000 items, and the witnesses of one copy, then of two: the second 75 witnesses cost fewer row visits than
    one pass over the items, where reading a table per witness cost 75 passes over each table a leaf reads."""
    copies = 6667  # 3 items each: 20,001
    visits, findings = [], []
    for witnessed in (1, 2):
        ws, read = scaled(copies, witnessed)
        assert len(read(IR["subject_table"])) == 3 * copies
        Counted.visits = 0
        findings.append(calc.check(ws, IR, read))
        visits.append(Counted.visits)
    assert findings == [[], []]  # every copy is as valid as the example
    assert visits[1] - visits[0] < 3 * copies, visits
    assert visits[0] < 3 * sum(len(read(t)) for t in frozen("snapshots.json")), visits
