"""Exact evaluation of what a rule computes: conditions, assignments and aggregate results.

One place, read by the check of one witness (check.py) and by the closure pass (closure.py), so both hold a rule
instance to the same arithmetic. Values are canonical text: an integer is decimal text, a result carries its state.
"""

import datetime
import re

from .canon import INTEGER, measure, number, number_text, payload


def _value(term, theta):
    return theta[term] if term.startswith("?") else term


def _int(text):
    return int(text) if INTEGER.fullmatch(text) else None


BIGINT = (-2**63, 2**63 - 1)  # the engines' integer: a value outside it is an error there, never a value


def _fits(text):
    """True unless the text is an integer outside BIGINT (an operand, a result or an aggregate's result)."""
    n = _int(text)
    return n is None or BIGINT[0] <= n <= BIGINT[1]


ISO_DATE = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}")


def _days(left, right):
    """The whole number of days from the ISO date `right` to the ISO date `left` in the proleptic Gregorian
    calendar, as canonical text; None if either is no calendar day written YYYY-MM-DD. Computed here from
    the text of the fact, apart from the engine that derived the row."""
    try:
        if not (ISO_DATE.fullmatch(left) and ISO_DATE.fullmatch(right)):
            return None
        return str(datetime.date.fromisoformat(left).toordinal() - datetime.date.fromisoformat(right).toordinal())
    except ValueError:
        return None


def _arith(op, left, right):
    if op == "days":
        return _days(left, right)
    a, b = _int(left), _int(right)
    if a is None or b is None or (op == "div" and b == 0):
        return None
    if op == "div":  # truncation toward zero
        return str(abs(a) // abs(b) * (1 if (a < 0) == (b < 0) else -1))
    return str({"add": a + b, "sub": a - b, "mul": a * b}[op])


def _holds(op, left, right):
    """A comparison of two canonical values: equality as text, order only between integers."""
    if op in ("eq", "ne"):
        return (left == right) == (op == "eq")
    a, b = _int(left), _int(right)
    if a is None or b is None:
        return False
    return {"lt": a < b, "le": a <= b, "gt": a > b, "ge": a >= b}[op]


def cells(spec, members) -> list:
    """What each row of a group gives a `sum`, `min` or `max`: its value in the column the aggregate reads, or,
    for a key column the aggregate ranges over, that part of the key as a known value. `members` are
    (key parts, values); a missing column counts as unknown."""
    if spec.over_key is not None:
        return [{"state": "known", "value": parts[spec.over_key]} for parts, _ in members]
    return [values.get(spec.over, {"state": "unknown"}) for _, values in members]


def _fold(function, cells):
    """formal.md §6, exact: invalid blocks, unknown is strict, not_applicable does not count."""
    states = {v["state"] for v in cells}
    known = [v for v in cells if v["state"] == "known"]
    if "invalid" in states or len({measure(v) for v in known}) > 1:
        return "invalid"  # also amounts in two currencies, or quantities in two units: they do not add up
    if "unknown" in states:
        return "unknown"
    try:
        numbers = [number(payload(v)) for v in known]
    except ValueError:
        return "invalid"  # not an exact number: invalid input, which blocks
    if function == "sum":
        return f"known:{number_text(sum(numbers))}"
    if not numbers:
        return "not_applicable"
    return f"known:{number_text(min(numbers) if function == 'min' else max(numbers))}"
