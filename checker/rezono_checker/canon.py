"""Canonical text forms of keys and values. JSON and hashes follow the one rule in rezono_canon."""

import json
import re
from decimal import Decimal
from fractions import Fraction
from math import gcd
from typing import Literal

from rezono_canon import canonical_json, canonical_sha256

INTEGER = re.compile(r"0|-?[1-9][0-9]*")  # integers travel as decimal strings, never JSON numbers; no "-0" (K9)
_POSITIVE = re.compile(r"[1-9][0-9]*")
CalcColumnType = Literal["integer", "rational"]


def _unique_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    obj = dict(pairs)
    if len(obj) != len(pairs):
        raise ValueError("duplicate JSON object key")
    return obj


def _reject_constant(constant: str):
    raise ValueError(f"non-standard JSON constant {constant!r}")


def strict_json_loads(data: str | bytes | bytearray):
    """Parse strict RFC 8259 JSON, rejecting duplicate object keys and NaN/Infinity constants."""
    if isinstance(data, (bytes, bytearray)):
        data = data.decode("utf-8")
    return json.loads(data, object_pairs_hook=_unique_object, parse_constant=_reject_constant)


def calc_value(text: str, column_type: CalcColumnType) -> bool:
    """Whether a selection value has the canonical spelling for its rule column."""
    if column_type == "integer":
        return INTEGER.fullmatch(text) is not None
    n, slash, d = text.partition("/")
    if not INTEGER.fullmatch(n):
        return False
    if not slash:
        return True
    # Decimal decodes the decimal digits exactly without a string-to-int digit limit.
    return bool(d != "1" and _POSITIVE.fullmatch(d) and gcd(int(Decimal(n)), int(Decimal(d))) == 1)


def encode_key(parts) -> str:
    """Canonical row key: the canonical JSON of the array of key parts."""
    return canonical_json(list(parts))


def payload(value: dict) -> str:
    """Text of a known Value, Amount, Quantity or Ratio: '42', or '1/3' in lowest terms."""
    if "numerator" in value:
        n, d = value["numerator"], value["denominator"]
        return n if d == "1" else f"{n}/{d}"
    return value["minor_units"] if "minor_units" in value else value["value"]


def measure(value: dict):
    """What a known value is counted in: its currency, its unit and scale, or nothing."""
    if "currency" in value:
        return ("currency", value["currency"])
    if "unit" in value:
        return ("unit", value["unit"], value.get("scale", 0))
    return None


def number(text: str) -> Fraction:
    """An exact number from '42' or '1/3'. Raises ValueError for anything else (no decimals)."""
    n, slash, d = text.partition("/")
    if INTEGER.fullmatch(n) and (not slash or (INTEGER.fullmatch(d) and int(d) > 0)):
        return Fraction(int(n), int(d) if slash else 1)
    raise ValueError(f"not an exact number: {text!r}")


def number_text(x: Fraction) -> str:
    return str(x.numerator) if x.denominator == 1 else f"{x.numerator}/{x.denominator}"


def value_text(value: dict) -> str:
    """Canonical text of a value with its state: 'known:<payload>', or the bare state name."""
    state = value["state"]
    return f"known:{payload(value)}" if state == "known" else state


sha256_json = canonical_sha256
