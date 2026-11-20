"""A count with its fixed column in the call, and a sum with a bare measured column, lower to the same rule IR as
the filter form and the `it.` form (decisions/language-readable-rules.md, section 2). The existing spellings are the
oracle; the expected aggregate terms, and the counts and sums over the rows below, are written out by hand from the
section Whole rows and empty groups of that decision."""

import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest
from expression_packs import ROOT, compile_rules, register
from rezono_compiler import batch, pack, rules
from support import FIXTURE

HEADER = """rezono 0
pack minimal

kind Order world closed

kind Line world closed
  order: Order
  cents: Int

rule order_line(order: Order, item: Line, cents: Int) when Line.order(item, order) and Line.cents(item, cents)
"""
OLD = HEADER + """rule line_count(o: Order, n: Int) when o in Order
  and n = (order_line(_, _, _) where it.order = o).count()
rule order_total(o: Order, total: Int) when o in Order
  and total = order_line(o, _, _).sum(it.cents)
"""
NEW = HEADER + """rule line_count(o: Order, n: Int) when o in Order
  and n = order_line(o, _, _).count()
rule order_total(o: Order, total: Int) when o in Order
  and total = order_line(o, _, _).sum(cents)
"""
# A bare name that is both a column of the aggregated relation and a name bound outside.
CLASH = HEADER + """rule order_total(o: Order, cents: Int) when o in Order
  and cents = order_line(o, _, _).sum(cents)
"""


def compiled(tmp_path: Path, source: str) -> dict:
    directory = Path(shutil.copytree(FIXTURE, tmp_path / "minimal"))
    folder = directory / "rezono"
    folder.mkdir()
    module, form = folder / "order.rezono", folder / "order.json"
    module.write_text(source, encoding="utf-8", newline="\n")
    result = subprocess.run(
        [os.environ.get("REZONO_NODE", "node"), str(ROOT / "rezono/src/write-form.ts"), str(module), str(form)],
        capture_output=True, text=True, encoding="utf-8", check=False,
    )
    assert result.returncode == 0, result.stderr
    register(directory, {"module": "rezono/order.rezono", "form": "rezono/order.json", "layer": "facts"})
    return compile_rules(directory)


def without_places(program: dict) -> dict:
    """The program without source places; the two spellings sit on the same lines but in other columns."""
    rules = [{key: value for key, value in rule.items() if key not in ("origin", "span")}
             for rule in program["rules"]]
    return {"relations": program["relations"], "rules": rules}


def aggregates(program: dict) -> dict:
    return {rule["head"]["relation"]: [(item["relation"], item["terms"], item["function"])
                                       for item in rule.get("aggregates", [])]
            for rule in program["rules"] if rule["head"]["relation"] in ("line_count", "order_total")}


# Order a has two lines of the same amount, order b has none.
BASE = {"order": [("a",), ("b",)], "line": [("l1",), ("l2",)],
        "line__order": [("l1", "a"), ("l2", "a")], "line__cents": [("l1", "250"), ("l2", "250")]}
# Both lines count and both amounts add up, although `_` hides the line; an order without lines gives zero.
EXPECTED_ROWS = {"line_count": {("a", "2"), ("b", "0")}, "order_total": {("a", "500"), ("b", "0")}}


def evaluated(program: dict) -> dict:
    loaded = rules.load(program)
    base = {name: [] for name, relation in loaded.relations.items() if relation.role == "base"} | BASE
    with batch.connect(loaded, base) as con:
        batch.compute(con, loaded)
        derived = batch.read(con, loaded)
    return {name: derived.get(name) for name in EXPECTED_ROWS}


class MissingReadableCounting(AssertionError):
    """The adopted spellings lowered otherwise than the existing ones, or the name clash was not refused."""


@pytest.mark.xfail(
    strict=True,
    raises=MissingReadableCounting,
    reason="extra: decisions/language-readable-rules.md: In compiler/rezono_compiler/native_rule_groups.py, resolve "
           "a bare name inside a rule aggregate on the aggregated relation's columns first, so sum(cents) lowers "
           "as sum(it.cents), and refuse a name that is also bound outside with R011. Read section 2. Waits for "
           "test_order_check_ordinary_filtered_count, which lowers rule aggregates at all. The counts and sums "
           "are over whole rows: two lines of 250 give 500, and an order without lines gives 0 for both.",
)
def test_lower_readable_counting(tmp_path):
    try:
        old = compiled(tmp_path / "old", OLD)
        new = compiled(tmp_path / "new", NEW)
    except pack.CompileError as error:
        raise MissingReadableCounting(str(error)) from error
    expected = {"line_count": [("order_line", ["?o", "_", "_"], "count")],
                "order_total": [("order_line", ["?o", "_", "_"], "sum")]}
    problems = []
    if aggregates(old) != expected:
        problems.append({"old": aggregates(old)})
    if without_places(new) != without_places(old):
        problems.append({"new": without_places(new), "old": without_places(old)})
    if (rows := evaluated(new)) != EXPECTED_ROWS:
        problems.append({"rows": rows, "expected": EXPECTED_ROWS})
    try:
        compiled(tmp_path / "clash", CLASH)
        codes = []
    except pack.CompileError as error:
        codes = [item.code for item in error.diagnostics]
    if "R011" not in codes:
        problems.append({"clash": codes})
    if problems:
        raise MissingReadableCounting(json.dumps(problems, indent=2, default=str))
