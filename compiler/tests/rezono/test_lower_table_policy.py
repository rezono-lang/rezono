"""A `table first` must lower to the outcome and value relations of tables.md section 3, run on DuckDB.

The expected rows are worked out by hand from that section, element by element, below each table."""

import pytest

from test_rezono_table import ETA, LEVEL, STANDING, TONE, lit, rows, run, table, written
from rezono_compiler import pack


# Rows in the order written; `first` reads them in that order.
FIRST = table(["level", "tone"],
              ([lit("valid")], "-", "good"),
              ([lit("revoked")], [lit("up")], "withdrawn"),
              ("-", [lit("down")], "withdrawn"),
              ("-", "-", "good"),
              policy="first")


@pytest.mark.xfail(
    strict=True,
    raises=pack.CompileError,
    reason="Lower a table first to the named outcome and value relations of a unique table, without the conflict "
           "invariant, in compiler/rezono_compiler/rezono_table.py and rezono_extend.py. Read docs/rezono/tables.md "
           "section 3 and decisions/language-tables.md, section Lowering a first table. Ready for a worker: the refusal "
           "of a first table is gone from compiler/tests/test_rezono_table.py, so only this mark goes. No reader "
           "dependency.",
)
def test_lower_table_first(tmp_path):
    d = written(tmp_path, LEVEL, TONE, STANDING, ETA, {"extend": "Eta", "derived": [FIRST]})
    db = run(d, {"eta": [(e,) for e in ("e1", "e2", "e3", "e4", "e5", "e6", "e7")],
                 "eta__level": [("e1", "valid"), ("e2", "revoked"), ("e3", "suspended"), ("e5", "suspended"),
                                ("e7", "revoked")],
                 "eta__tone": [("e1", "up"), ("e2", "up"), ("e3", "down"), ("e4", "down"), ("e7", "down")]})
    assert rows(db, "eta_standing") == {
        ("e1", "known", ""),  # row 1 applies
        ("e2", "known", ""),  # row 2 applies; rows 3 and 4 below it do not matter
        ("e3", "known", ""),  # row 3 is the first that applies
        ("e4", "unknown", "no_value"),  # level unknown: row 1 is undecided above row 3 and gives another output
        ("e5", "known", ""),  # tone n/a: a test on it does not apply, so row 4 applies
        # level unknown, tone n/a: row 2 is `unknown and n/a`, which is unknown (expressions.md A.1), so it is
        # undecided above row 4 and gives another output; row 1, undecided with row 4's output, changes nothing
        ("e6", "unknown", "no_value"),
        ("e7", "known", ""),  # rows 3 and 4 both apply: the first wins, which is no conflict
    }
    assert rows(db, "eta_standing_value") == {
        ("e1", "good"), ("e2", "withdrawn"), ("e3", "withdrawn"), ("e5", "good"), ("e7", "withdrawn"),
    }
