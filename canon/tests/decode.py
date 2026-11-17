"""Decode the typed leaves of contracts/fixtures/canon/vectors.json into Python values."""

import datetime as dt
from pathlib import Path

VECTORS = Path(__file__).resolve().parents[2] / "contracts" / "fixtures" / "canon" / "vectors.json"


def decode(v):
    if isinstance(v, dict) and len(v) == 1 and next(iter(v)).startswith("$"):
        (tag, text), = v.items()
        if tag == "$int":
            return int(text)
        if tag == "$float":
            return float(text)
        if tag == "$date":
            return dt.date.fromisoformat(text)
        if tag == "$datetime":
            return dt.datetime.fromisoformat(text.replace("Z", "+00:00"))
        if tag == "$null":
            return None
        raise ValueError(f"unknown tag {tag}")
    if isinstance(v, dict):
        return {k: decode(x) for k, x in v.items()}
    if isinstance(v, list):
        return [decode(x) for x in v]
    return v
