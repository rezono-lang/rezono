"""Turn recorded billing evidence into inputs for the invoice drift pack."""

from collections import defaultdict
from collections.abc import Iterable, Mapping
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


def _round_minor(amount: Fraction, mode: str) -> int:
    if mode == "half_even":
        return round(amount)
    whole, remainder = divmod(abs(amount.numerator), amount.denominator)
    rounded = whole + (2 * remainder >= amount.denominator)
    return -rounded if amount < 0 else rounded


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
        add("expected_line", ref, {"plan_hash": plan, "item": item, "currency": currency,
                                  "minor": _round_minor(amount * units, mode), "rounding_sha256": digest})

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
