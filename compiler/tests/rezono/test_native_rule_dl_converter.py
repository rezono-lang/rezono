"""A Datalog source has a faithful native plan or an actionable conversion refusal."""

import importlib.util
from pathlib import Path
import subprocess

import pytest

from rezono_compiler import rules_dl


ROOT = Path(__file__).resolve().parents[3]
MODULE = "rezono_compiler.native_rule_dl"

OWNER = r'''.decl item(id: symbol)
.input item, item__label, line
// @extend
// @explain on_demand
// @explain fold
.decl tally(item: symbol, count: number, total: number, note: symbol)
  tally(x, n, total, "") :- item(x), item__label(x, "label//\"text"),
    item__label(x, _), item__label(x, _), n = count : { line(x, _, _) },
    n >= -2, total = sum cents : { line(x, _, cents) }.
.output tally
'''

EXTENSION = '''.input item
tally(x, 0, 0, "extra") :- item(x).
'''

SCHEMA = {
    "item": {"kind": "Item", "columns": {"id": "Item"}, "world": "closed"},
    "item__label": {"kind": "Item", "slot": "label", "columns": {"id": "Item", "label": "Text"}, "world": "closed"},
    "line": {"columns": {"item": "Item", "entry": "Text", "cents": "Int"}, "world": "closed"},
}

# These trees are authored from the typed-head, aggregate and ownership examples
# in §§2–7 and 10 of decisions/language-native-rules.md at 27ff4dc9.
X = {"path": ["x"]}
N = {"path": ["n"]}
TOTAL = {"path": ["total"]}
WILD = {"wildcard": True}
ITEM = {"in": [X, {"kind": "Item"}]}
LABEL = {"call": ["Item.label", [X, WILD]]}
RANGE = {"call": ["line", [X, WILD, WILD]]}
SIGNATURE = {
    "rule": "tally",
    "columns": [
        {"name": "item", "type": "Item"},
        {"name": "count", "type": "Int"},
        {"name": "total", "type": "Int"},
        {"name": "note", "type": "Text"},
    ],
    "options": [{"extend": True}, {"explain": "on_demand"}, {"explain": "fold"}],
}
TALLY = {
    "rule": "tally",
    "args": [X, N, TOTAL, {"lit": '""'}],
    "when": {"and": [
        ITEM,
        {"call": ["Item.label", [X, {"lit": r'"label//\"text"'}]]},
        LABEL,
        LABEL,
        {"cmp": ["=", N, {"agg": ["count", RANGE]}]},
        {"cmp": [">=", N, {"lit": "-2"}]},
        {"cmp": ["=", TOTAL, {"agg": ["sum", RANGE, {"path": ["it", "cents"]}]}]},
    ]},
}
EXTRA = {
    "rule": "policy.tally",
    "args": [X, {"lit": "0"}, {"lit": "0"}, {"lit": '"extra"'}],
    "when": ITEM,
}
UNRESOLVED = """.decl mystery(item: symbol)
mystery(x) :- raw_item(x).
"""
OPEN_REGISTER = """.decl ready(item: symbol)
ready(x) :- item(x), !open_item(x).
"""


def _input(pack: str, file: str, text: str) -> dict:
    return {"pack": pack, "file": file, "text": text}


def _tracked_datalog() -> list[str]:
    tracked = subprocess.check_output(["git", "ls-files", "-z", "--", "*.dl"], cwd=ROOT)
    return sorted(path for path in tracked.decode().split("\0") if path and "fixtures" not in Path(path).parts)


@pytest.mark.xfail(
    strict=True, raises=AssertionError,
    reason=(
        "Convert Datalog to native rule trees in compiler/rezono_compiler/native_rule_dl.py. "
        "Read compiler/tests/rezono/native-rule-dl-converter.md. No native reader dependency."
    ),
)
def test_native_rule_dl_converter():
    tracked = _tracked_datalog()
    assert tracked
    for path in tracked:
        rules_dl.parse_file((ROOT / path).read_text(encoding="utf-8"), path)

    clause_columns = []
    statements = rules_dl.parse_file(OWNER, "rules/summary.dl", clause_columns)
    assert [kind for kind, *_ in statements] == ["decl", "io", "decl", "rule", "io"]
    assert clause_columns == [3]
    _, head, premises, line = rules_dl.parse_file(EXTENSION, "rules/extra.dl")[1]
    assert (head[0], line) == ("tally", 2)
    assert premises == [("lit", "positive", ("item", [("var", "x")], 2))]

    assert importlib.util.find_spec(MODULE), "the Datalog-to-native conversion planner is missing"
    converter = importlib.import_module(MODULE)
    assert converter.inventory(ROOT) == tracked

    owner = _input("base", "rules/summary.dl", OWNER)
    extension = _input("client", "rules/extra.dl", EXTENSION)
    plan = converter.convert_modules([owner, extension], SCHEMA, {"client": {"policy": "base"}})
    assert plan == {
        "modules": [
            {"pack": "base", "stem": "summary", "decls": [SIGNATURE, TALLY]},
            {"pack": "client", "stem": "extra", "decls": [EXTRA]},
        ],
        "clauses": [
            {"id": "tally_1", "owner_pack": "base", "owner_module": "summary",
             "file": "rules/summary.dl", "line": 7, "column": 3},
            {"id": "tally_2", "owner_pack": "base", "owner_module": "summary",
             "file": "rules/extra.dl", "line": 2, "column": 1},
        ],
        "issues": [],
    }

    for source, code, subject, need in [
        (_input("base", "rules/nominal.dl", UNRESOLVED), "R049", "mystery.item", "nominal type"),
        (_input("base", "rules/readiness.dl", OPEN_REGISTER), "R047", "open_item", "scoped completeness"),
    ]:
        schema = {
            **SCHEMA,
            "raw_item": {"columns": {"id": "symbol"}, "world": "closed"},
            "open_item": {"kind": "OpenItem", "columns": {"id": "Item"}, "world": "open"},
        }
        refused = converter.convert_modules([source], schema, {})
        assert refused["modules"] == [] and refused["clauses"] == []
        [issue] = refused["issues"]
        assert (issue["code"], issue["file"], issue["subject"]) == (code, source["file"], subject)
        assert issue["line"] == (1 if code == "R049" else 2)
        assert need in issue["message"]
