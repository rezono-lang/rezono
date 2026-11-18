"""Turn recorded billing evidence into inputs for the invoice drift pack."""

from collections import defaultdict
from collections.abc import Callable, Iterable, Mapping
from fractions import Fraction
from hashlib import sha256
import json
import re
from urllib.parse import urlsplit


Row = tuple[str | int, ...]
Record = Mapping[str, object]


def _text(record: Record, field: str, pattern: str | None = None) -> str:
    value = record.get(field)
    if not isinstance(value, str) or not value.strip() or (pattern and not re.fullmatch(pattern, value)):
        raise ValueError(f"invalid {field}")
    return value


def _digits(value: int) -> list[int]:
    """Least significant digit first, with zero represented by one digit."""
    digits = []
    while value >= 10:
        value, digit = divmod(value, 10)
        digits.append(digit)
    digits.append(value)
    return digits


def _rounding_certificate(
    ref: str, amount: Fraction, units: int, add: Callable[[str, str, dict[str, str | int]], None],
) -> tuple[str, int]:
    """Supply a candidate quotient and carry evidence for independently checked equations."""
    numerator = abs(amount.numerator)
    denominator = amount.denominator
    quotient, remainder = divmod(numerator * units, denominator)
    sign = "negative" if amount < 0 else "nonnegative"
    floor = -quotient if sign == "negative" else quotient
    gap = denominator - remainder
    digits = {part: _digits(value) for part, value in (
        ("numerator", numerator), ("denominator", denominator),
        ("remainder", remainder), ("gap", gap),
    )}
    for part, values in digits.items():
        for index, digit in enumerate(values):
            add("rounding_digit", f"{ref}/{part}/{index}",
                {"line": ref, "part": part, "position": index, "digit": digit,
                 "last": "last" if index == len(values) - 1 else "more"})

    for part, value in (("units", units), ("floor", floor)):
        remaining = value
        for index, _ in enumerate(_digits(abs(value))):
            add("rounding_word", f"{ref}/{part}/{index}",
                {"line": ref, "part": part, "position": index, "remaining": remaining})
            magnitude = abs(remaining) // 10
            remaining = -magnitude if remaining < 0 else magnitude

    division: dict[int, int] = defaultdict(int)
    for signum, name, factor in ((1, "numerator", units), (-1, "denominator", quotient)):
        factor_digits = _digits(factor)
        for index, digit in enumerate(digits[name]):
            for offset, other in enumerate(factor_digits):
                division[index + offset] += signum * digit * other
    for index, digit in enumerate(digits["remainder"]):
        division[index] -= digit

    complement: dict[int, int] = defaultdict(int)
    for signum, name in ((1, "denominator"), (-1, "remainder"), (-1, "gap")):
        for index, digit in enumerate(digits[name]):
            complement[index] += signum * digit

    # Each carry is just a candidate. The pack checks the complete sequence.
    for equation, coefficients in (("division", division), ("complement", complement)):
        carry = 0
        for index in range(max(coefficients) + 2):
            add("rounding_carry", f"{ref}/{equation}/{index}", {
                "line": ref, "equation": equation, "position": index, "carry": carry,
            })
            carry = (carry + coefficients.get(index, 0)) // 10
    return sign, floor


def invoice_facts(
    expected: Iterable[Record], observed: Iterable[Record], rounding: Record,
) -> dict[str, list[Row]]:
    """Verify one billing term and retain the source records behind each line."""
    body = rounding.get("body")
    digest = _text(rounding, "sha256", r"[0-9a-f]{64}")
    if not isinstance(body, bytes) or sha256(body).hexdigest() != digest:
        raise ValueError("rounding term bytes do not match their SHA-256 digest")
    url = _text(rounding, "url")
    source = urlsplit(url)
    if source.scheme not in {"http", "https"} or not source.hostname:
        raise ValueError("rounding terms require a source URL")
    terms = json.loads(body)
    if not isinstance(terms, dict):
        raise ValueError("rounding terms must be an object")
    currency = _text(terms, "currency", r"[A-Z]{3}")
    mode = terms.get("mode")
    units = terms.get("minor_per_unit")
    if (terms.get("boundary") != "line" or mode not in ("half_up", "half_even")
            or type(units) is not int or units <= 0):
        raise ValueError("rounding terms require a supported line mode and a positive minor-unit factor")

    facts: dict[str, list[Row]] = defaultdict(list)

    def add(kind: str, ref: str, fields: dict[str, str | int]) -> None:
        facts[kind].append((ref,))
        for field, value in fields.items():
            facts[f"{kind}__{field}"].append((ref, value))

    add("rounding", digest, {"source_url": url, "currency": currency, "boundary": "line",
                             "mode": mode, "minor_per_unit": units})

    prices: dict[tuple[str, str], tuple[str, Fraction]] = {}
    cost_refs: dict[str, tuple[str, str]] = {}
    for line in expected:
        ref = _text(line, "ref")
        plan = _text(line, "plan_hash", r"[0-9a-f]{64}")
        item = _text(line, "item")
        if line.get("currency") != currency:
            raise ValueError("the expected price must use the rounding term currency")
        pair = line.get("expected")
        if (not isinstance(pair, (list, tuple)) or len(pair) != 2
                or any(type(part) is not int for part in pair) or pair[1] <= 0):
            raise ValueError("an expected price requires an exact numerator and positive denominator")
        amount = Fraction(*pair)
        key = (plan, item)
        if prices.setdefault(key, (ref, amount)) != (ref, amount) or cost_refs.setdefault(ref, key) != key:
            raise ValueError("conflicting priced item evidence")
        sign, floor = _rounding_certificate(ref, amount, units, add)
        add("expected_line", ref, {"plan_hash": plan, "item": item, "currency": currency,
                                  "sign": sign, "floor_minor": floor, "rounding_sha256": digest})

    invoices: dict[str, tuple[str | None, str, str, int]] = {}
    for line in observed:
        ref = _text(line, "ref")
        plan = None if line.get("plan_hash") is None else _text(line, "plan_hash", r"[0-9a-f]{64}")
        item = _text(line, "item")
        observed_currency = _text(line, "currency", r"[A-Z]{3}")
        minor = line.get("observed_minor")
        if type(minor) is not int:
            raise ValueError("an invoice line requires a whole signed amount in minor units")
        evidence = (plan, item, observed_currency, minor)
        if invoices.setdefault(ref, evidence) != evidence:
            raise ValueError("conflicting invoice line evidence")
        fields = {"item": item, "currency": observed_currency, "minor": minor}
        if plan is not None:
            fields["plan_hash"] = plan
        add("invoice_line", ref, fields)

    return {relation: sorted(set(rows)) for relation, rows in sorted(facts.items())}
