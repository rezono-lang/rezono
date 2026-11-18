"""Adapter for snapshot files. The only module that knows their layout.

A JSON snapshot is a list of rows: {"key": [<string>, ...], "values": {<column>: Value}},
with Value as in contracts/value.yaml. Parquet is not read yet.
"""

import json
import re
from math import gcd
from pathlib import Path

from .canon import INTEGER, encode_key

STATES = ("known", "unknown", "not_applicable", "invalid")  # ValueState in contracts/value.yaml
REASON = re.compile(r"[a-z][a-z0-9_]*")  # a reason code; an empty reason is written by leaving it out


def resolve(uri: str, root: Path) -> Path:
    """Map a snapshot URI to a local file. S3 goes through the storage port, not here."""
    if uri.startswith("file://"):
        return Path(uri[len("file://"):])
    if "://" in uri:
        raise ValueError(f"unsupported snapshot URI {uri}")
    return root / uri


# The classes of contracts/value.yaml, told apart by their fields: (marker, fields, integer fields).
# A Ratio that is not known has no numerator, so it reads as a Value: both have the same fields then.
SHAPES = (
    ("numerator", {"state", "reason", "numerator", "denominator"}, ("numerator", "denominator")),  # Ratio
    ("currency", {"state", "reason", "minor_units", "currency"}, ("minor_units",)),  # Amount
    ("unit", {"state", "reason", "minor_units", "scale", "unit"}, ("minor_units",)),  # Quantity
    ("state", {"state", "reason", "value"}, ()),  # Value
)


def _check_value(v) -> None:
    """A value as in contracts/value.yaml, with integers as decimal strings. Raises ValueError."""
    if not isinstance(v, dict) or v.get("state") not in STATES:
        raise ValueError(f"not a value: {v!r}")
    marker, fields, integers = next(shape for shape in SHAPES if shape[0] in v or shape[0] == "state")
    if set(v) - fields:
        raise ValueError(f"unexpected fields {sorted(set(v) - fields)} in {v!r}")
    for field in integers:
        if field in v and not isinstance(v[field], str):
            raise ValueError(f"{field} must be a decimal string, not a JSON {type(v[field]).__name__}: {v!r}")
        if field in v and not INTEGER.fullmatch(v[field]):
            raise ValueError(f"{field} is not a decimal integer: {v!r}")
    if "currency" in v and not (isinstance(v["currency"], str) and re.fullmatch(r"[A-Z]{3}", v["currency"])):
        raise ValueError(f"currency is not ISO 4217: {v!r}")
    if "unit" in v and not (isinstance(v["unit"], str) and v["unit"]):
        raise ValueError(f"unit is not a UCUM string: {v!r}")
    if "scale" in v and (type(v["scale"]) is not int or v["scale"] < 0):
        raise ValueError(f"scale is not a non-negative integer: {v!r}")
    if "reason" in v:
        if not (isinstance(v["reason"], str) and REASON.fullmatch(v["reason"])):
            raise ValueError(f"reason is not a reason code: {v!r}")
        if v["state"] == "known" and v["reason"] != "added_later":
            raise ValueError(f"a known value has no reason except added_later: {v!r}")
    payload = [f for f in (*integers, "value") if f in v]
    if v["state"] != "known":
        if payload:  # also an empty one: one meaning, one spelling (K11)
            raise ValueError(f"{v['state']} value with a payload: {v!r}")
        return
    if marker == "numerator":
        n, d = (int(v.get(f, "0")) for f in ("numerator", "denominator"))
        if len(payload) != 2 or d < 1 or gcd(n, d) != 1:
            raise ValueError(f"ratio not in canonical form: {v!r}")
    elif marker == "state" and not isinstance(v.get("value"), str):
        raise ValueError(f"known value without text: {v!r}")
    elif marker != "state" and not payload:
        raise ValueError(f"known value without minor units: {v!r}")


def read_rows(data: bytes, fmt: str) -> dict:
    """Return {canonical key: (key parts, values)}. Raises ValueError on a malformed snapshot."""
    if fmt != "json":
        raise ValueError(f"unsupported snapshot format {fmt}")
    return rows_of(json.loads(data))  # bad JSON or bad UTF-8 raises a ValueError too


def rows_of(table) -> dict:
    """read_rows of a snapshot already parsed: for a caller that needs the parsed list as well."""
    if not isinstance(table, list):
        raise ValueError(f"a snapshot is a list of rows, not a JSON {type(table).__name__}")
    rows = {}
    for row in table:
        if not isinstance(row, dict) or "key" not in row or set(row) - {"key", "values"}:
            raise ValueError(f"not a row: {row!r}")
        parts, values = row["key"], row.get("values", {})
        if not isinstance(parts, list) or not all(isinstance(p, str) for p in parts):
            raise ValueError(f"not a key: {parts!r}")
        if not isinstance(values, dict):
            raise ValueError(f"not a value map: {values!r}")
        for v in values.values():
            _check_value(v)
        key = encode_key(parts)
        if key in rows:
            raise ValueError(f"duplicate key {key}")
        rows[key] = (tuple(parts), values)
    return rows
