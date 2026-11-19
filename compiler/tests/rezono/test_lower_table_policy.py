"""A `table first`, `priority` or `collect` must lower to the outcome and value relations of tables.md section 3,
run on DuckDB.

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


# Standing lists `good` before `withdrawn`; `priority` reads that order, not the order of the rows.
PRIORITY = table(["level", "tone"],
                 ([lit("revoked")], "-", "withdrawn"),
                 ("-", [lit("up")], "good"),
                 ([lit("suspended")], "-", "good"),
                 ("-", [lit("down")], "withdrawn"),
                 policy="priority")


class MissingPriorityTableLowering(AssertionError):
    """The compiler refused a `table priority`, which decisions/language-tables.md lowers."""


@pytest.mark.xfail(
    strict=True,
    raises=MissingPriorityTableLowering,
    reason="extra: decisions/language-tables.md: Lower a table priority to the named outcome and value relations "
           "of a unique table, without the conflict invariant, in compiler/rezono_compiler/rezono_table.py and "
           "rezono_extend.py. Read docs/rezono/tables.md section 3 and the section Lowering a priority table. "
           "Waits for test_lower_table_collect while it owns rezono_table.py and rezono_extend.py.",
)
def test_lower_table_priority(tmp_path):
    d = written(tmp_path, LEVEL, TONE, STANDING, ETA, {"extend": "Eta", "derived": [PRIORITY]})
    try:
        db = run(d, {"eta": [(e,) for e in ("e1", "e2", "e3", "e4", "e5", "e6", "e7")],
                     "eta__level": [("e1", "revoked"), ("e2", "revoked"), ("e5", "valid"), ("e7", "suspended")],
                     "eta__tone": [("e1", "up"), ("e2", "down"), ("e3", "down"), ("e4", "up"), ("e7", "down")]})
    except pack.CompileError as refused:
        raise MissingPriorityTableLowering(str(refused)) from refused
    assert rows(db, "eta_standing") == {
        ("e1", "known", ""),  # rows 1 and 2 apply: good comes first in Standing, though row 1 comes first
        ("e2", "known", ""),  # rows 1 and 4 apply, both withdrawn
        # level unknown: rows 1 and 3 are undecided and row 4 applies; row 3 gives good, which comes before
        # withdrawn, so it would change the value if it applied
        ("e3", "unknown", "no_value"),
        ("e4", "known", ""),  # level unknown: row 2 applies with good; undecided rows 1 and 3 change nothing
        ("e5", "unknown", "no_row_applies"),  # tone n/a: rows 2 and 4 do not apply, rows 1 and 3 are false
        ("e6", "unknown", "no_value"),  # level unknown, tone n/a: only the undecided rows 1 and 3 remain
        ("e7", "known", ""),  # rows 3 and 4 apply: good wins over withdrawn, which is no conflict
    }
    assert rows(db, "eta_standing_value") == {("e1", "good"), ("e2", "withdrawn"), ("e4", "good"), ("e7", "good")}


# A set of Standing: the output of every row that applies is a member, each output once.
COLLECT = table(["level", "tone"],
                ([lit("valid")], "-", "good"),
                ("-", [lit("down")], "withdrawn"),
                ([lit("revoked")], "-", "withdrawn"),
                ([lit("suspended")], [lit("up")], "good"),
                policy="collect") | {"card": "*"}


class MissingCollectTableLowering(AssertionError):
    """The compiler refused a `table collect`, which decisions/language-tables.md lowers."""


@pytest.mark.xfail(
    strict=True,
    raises=MissingCollectTableLowering,
    reason="extra: decisions/language-tables.md: Lower a table collect on a derived value T* to the named outcome, "
           "the relation of its known members and the relation of its undecided members, without the conflict "
           "invariant, in compiler/rezono_compiler/rezono_table.py and rezono_extend.py. Read docs/rezono/tables.md "
           "section 3 and the section Lowering a collect table.",
)
def test_lower_table_collect(tmp_path):
    d = written(tmp_path, LEVEL, TONE, STANDING, ETA, {"extend": "Eta", "derived": [COLLECT]})
    try:
        db = run(d, {"eta": [(e,) for e in ("e1", "e2", "e3", "e4", "e5", "e6", "e7")],
                     "eta__level": [("e1", "valid"), ("e2", "valid"), ("e3", "revoked"), ("e5", "suspended"),
                                    ("e7", "suspended")],
                     "eta__tone": [("e1", "up"), ("e2", "down"), ("e3", "down"), ("e4", "down"), ("e7", "up")]})
    except pack.CompileError as refused:
        raise MissingCollectTableLowering(str(refused)) from refused
    # A set is a value for every element, also when it is empty or a membership is undecided.
    assert rows(db, "eta_standing") == {(e, "known", "") for e in ("e1", "e2", "e3", "e4", "e5", "e6", "e7")}
    assert rows(db, "eta_standing_value") == {
        ("e1", "good"),  # row 1 applies
        ("e2", "good"), ("e2", "withdrawn"),  # rows 1 and 2 apply, which is no conflict
        ("e3", "withdrawn"),  # rows 2 and 3 apply with one output: one member
        ("e4", "withdrawn"),  # row 2 applies; row 3 is undecided with an output that is already a member
        # e5: suspended with tone n/a: row 4 is `true and n/a`, which does not apply; the set is empty
        # e6: no row applies
        ("e7", "good"),  # row 4 applies
    }
    assert rows(db, "eta_standing_undecided_member") == {
        ("e4", "good", "unknown", "no_value"),  # level unknown: row 1 is undecided; row 4 is false on its tone
        # level unknown, tone n/a: rows 1 and 3 are undecided, and so is row 4 (`unknown and n/a` is unknown,
        # expressions.md A.1); good comes from rows 1 and 4, withdrawn from row 3
        ("e6", "good", "unknown", "no_value"),
        ("e6", "withdrawn", "unknown", "no_value"),
    }
