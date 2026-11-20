"""Period shorthand literals (`valid 2026`, `valid 2026-03`) and digit grouping (`38_520`, `2_400_000`)
in rezono 1 (decisions/language-rezono-1.md, section 1)."""

import json

import pytest
from reader_probe import read_modules

SHORTHAND_AND_GROUPING = """\
rezono 1
pack sample
param cap: Int
  version 0 = 0
  version 1, valid 2026 = 2_400_000
  version 2, valid 2026-03 = 38_520
  version 3, valid 2024-02 = 1_000
  version 4, valid 2026-12 = 50_000
kind Item world closed
  amount: Money<EUR>
  derived high: Bool = amount > € 38_520.50
"""

UNGROUPED_EQUIVALENT = """\
rezono 1
pack sample
param cap: Int
  version 0 = 0
  version 1, valid 2026-01-01..<2027-01-01 = 2400000
  version 2, valid 2026-03-01..<2026-04-01 = 38520
  version 3, valid 2024-02-01..<2024-03-01 = 1000
  version 4, valid 2026-12-01..<2027-01-01 = 50000
kind Item world closed
  amount: Money<EUR>
  derived high: Bool = amount > € 38520.50
"""

BAD_LEADING_UNDERSCORE = "rezono 1\npack sample\nparam cap: Int = _100\n"
BAD_TRAILING_UNDERSCORE = "rezono 1\npack sample\nparam cap: Int = 100_\n"
BAD_DOUBLE_UNDERSCORE = "rezono 1\npack sample\nparam cap: Int = 1__000\n"


class MissingRezono1Literals(AssertionError):
    """The reader did not desugar period shorthands, strip digit-grouping underscores, or refuse malformed underscores."""


def test_rezono_1_period_shorthand_and_digit_grouping():
    short, plain, *bad = read_modules(
        SHORTHAND_AND_GROUPING,
        UNGROUPED_EQUIVALENT,
        BAD_LEADING_UNDERSCORE,
        BAD_TRAILING_UNDERSCORE,
        BAD_DOUBLE_UNDERSCORE,
    )
    problems = []
    if short["diagnostics"] or short["module"] is None:
        problems.append({"shorthand_and_grouping": short})
    if plain["diagnostics"] or plain["module"] is None:
        problems.append({"ungrouped_equivalent": plain})
    if not problems:
        if short["module"] != plain["module"]:
            problems.append({"ast_mismatch": {"short": short["module"], "plain": plain["module"]}})
        if short["printed"] != UNGROUPED_EQUIVALENT:
            problems.append({"printed": short["printed"], "want": UNGROUPED_EQUIVALENT})
    for label, read in zip(("leading", "trailing", "double"), bad):
        if read["module"] is not None or "R000" not in [d["code"] for d in read["diagnostics"]]:
            problems.append({f"bad_{label}": read})
    if problems:
        raise MissingRezono1Literals(json.dumps(problems, indent=2))
