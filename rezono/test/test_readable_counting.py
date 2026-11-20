"""A filtered count in a rule gives W107 with the call form as its hint, and a bare measured column reads
(decisions/language-readable-rules.md, section 2). The sources and spans are written from that decision."""

import json

import pytest
from reader_probe import at, read_modules

HEADER = ("rezono 0\npack sample\n\nkind Order world closed\n\nkind Line world closed\n  order: Order\n  cents: Int\n\n"
          "rule order_line(order: Order, item: Line, cents: Int) when Line.order(item, order) and Line.cents(item, cents)\n")
FILTER = "(order_line(_, _, _) where it.order = o).count()"
OLD = HEADER + f"rule line_count(o: Order, n: Int) when o in Order\n  and n = {FILTER}\n"
NEW = (HEADER + "rule line_count(o: Order, n: Int) when o in Order\n  and n = order_line(o, _, _).count()\n"
       + "rule order_total(o: Order, total: Int) when o in Order\n  and total = order_line(o, _, _).sum(cents)\n")
# Counter-case: the measure with `it.` stays valid and quiet.
WITH_IT = HEADER + "rule order_total(o: Order, total: Int) when o in Order\n  and total = order_line(o, _, _).sum(it.cents)\n"


class MissingCountingHint(AssertionError):
    """The reader did not warn at a filtered count in a rule, or warned at a form the decision adopts."""


@pytest.mark.xfail(
    strict=True,
    raises=MissingCountingHint,
    reason="extra: decisions/language-readable-rules.md: In the module reader, give W107 at an aggregate in a rule "
           "whose range is `(r(...) where it.c = x)`, from its opening parenthesis to the end of `count()`, naming "
           "the call form `r(..., x, ...).count()`; keep the form unchanged. Add W107 to rezono/messages/en.json "
           "and nl.json if test_readable_property has not. Read section 2.",
)
def test_readable_counting():
    old, new, with_it = read_modules(OLD, NEW, WITH_IT)
    for read in (new, with_it):
        assert read["module"] is not None, read
    problems = []
    want = [{"code": "W107", "span": at(OLD, FILTER)}]
    if old["module"] is None or old["diagnostics"] != want:
        problems.append({"old": old["diagnostics"], "want": want})
    for name, read in (("new", new), ("with_it", with_it)):
        if read["diagnostics"]:
            problems.append({name: read["diagnostics"]})
    if problems:
        raise MissingCountingHint(json.dumps(problems, indent=2))
