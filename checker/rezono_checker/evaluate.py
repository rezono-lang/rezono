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


UTC_INSTANT = re.compile(r"([0-9]{4})-([0-9]{2})-([0-9]{2})T([0-9]{2}):([0-9]{2}):([0-9]{2})(?:\.([0-9]+))?Z")


def _utc_key(text):
    """The bytes that order a UTC instant written YYYY-MM-DDTHH:mm:ss[.digits]Z, else None.

    The date is a Gregorian day in the years 0001 to 9999 and the time has seconds 00 to 59. The key drops the
    terminal Z and the fraction's trailing zeros, and the separator if no digit remains: the fixed-width whole
    second decides first, then the fraction as exact decimal digits, at any precision."""
    match = UTC_INSTANT.fullmatch(text) if isinstance(text, str) else None
    if match is None:
        return None
    year, month, day, hour, minute, second, fraction = match.groups()
    try:
        datetime.date(int(year), int(month), int(day))
    except ValueError:
        return None
    if int(hour) > 23 or int(minute) > 59 or int(second) > 59:
        return None
    whole = text[:19]
    fraction = (fraction or "").rstrip("0")
    return (f"{whole}.{fraction}" if fraction else whole).encode("ascii")


def _text_key(text):
    """The UTF-8 bytes of Unicode scalar text, else None (a lone surrogate is no scalar value)."""
    try:
        return text.encode("utf-8") if isinstance(text, str) else None
    except UnicodeEncodeError:
        return None


TYPED_KEYS = {"binary_text": _text_key, "utc_instant": _utc_key}


def _holds(op, left, right, compare_as=None):
    """A comparison of two canonical values: equality as text, order only between integers. With `compare_as`
    (decisions/ordered-rule-scalars.md) both operands are read as that type and compared as bytes; an operand
    that is not of the type decides no comparison, not even `ne`."""
    if compare_as is not None:
        a, b = TYPED_KEYS[compare_as](left), TYPED_KEYS[compare_as](right)
        if a is None or b is None:
            return False
        return {"eq": a == b, "ne": a != b, "lt": a < b, "le": a <= b, "gt": a > b, "ge": a >= b}[op]
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


def _fold(function, cells, fmt=None):
    """Exact aggregate fold: strict four-state (invalid -> unknown -> not_applicable -> known) for
    rezono.rules/2 and without a format (decisions/language-rezono-1-aggregate-spelling.md, section 2);
    formal.md §6 (not_applicable skipped) for rezono.rules/1."""
    states = {v["state"] for v in cells}
    known = [v for v in cells if v["state"] == "known"]
    if "invalid" in states or len({measure(v) for v in known}) > 1:
        return "invalid"  # also amounts in two currencies, or quantities in two units: they do not add up
    if "unknown" in states:
        return "unknown"
    if fmt != "rezono.rules/1" and "not_applicable" in states:
        return "not_applicable"
    if function == "count":
        return f"known:{len(known)}"
    try:
        numbers = [number(payload(v)) for v in known]
    except ValueError:
        return "invalid"  # not an exact number: invalid input, which blocks
    if function == "sum":
        return f"known:{number_text(sum(numbers))}"
    if not numbers:
        return "not_applicable"
    return f"known:{number_text(min(numbers) if function == 'min' else max(numbers))}"
