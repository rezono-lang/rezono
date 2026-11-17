"""The canonical form against the shared test vectors, and against RFC 8785 as an independent oracle."""

import datetime as dt
import hashlib
import json

import pytest
from decode import VECTORS, decode
from rede_canon import CanonError, canonical_bytes, canonical_json, canonical_sha256

DOC = json.loads(VECTORS.read_text("utf-8"))
VALID = [v for v in DOC["valid"] if v.get("only", "python") == "python"]
INVALID = [v for v in DOC["invalid"] if v.get("only", "python") == "python"]


@pytest.mark.parametrize("v", VALID, ids=lambda v: v["name"])
def test_valid(v):
    value = decode(v["input"])
    assert canonical_json(value) == v["canonical"]
    assert canonical_sha256(value) == v["sha256"]
    assert hashlib.sha256(v["canonical"].encode("utf-8")).hexdigest() == v["sha256"]


@pytest.mark.parametrize("v", INVALID, ids=lambda v: v["name"])
def test_invalid(v):
    with pytest.raises(CanonError) as e:
        canonical_json(decode(v["input"]))
    assert e.value.code == v["error"]


def _plain(v):
    """Integers to decimal text; what is left is plain JSON for RFC 8785."""
    if isinstance(v, bool) or isinstance(v, str):
        return v
    if isinstance(v, int):
        return str(v)
    if isinstance(v, dict):
        return {k: _plain(x) for k, x in v.items()}
    if isinstance(v, list):
        return [_plain(x) for x in v]
    raise TypeError(type(v))


def _has_time(v):
    if isinstance(v, (dt.date, dt.datetime)):
        return True
    if isinstance(v, dict):
        return any(_has_time(x) for x in v.values())
    return isinstance(v, list) and any(_has_time(x) for x in v)


@pytest.mark.parametrize("v", VALID, ids=lambda v: v["name"])
def test_oracle_rfc8785(v):
    rfc8785 = pytest.importorskip("rfc8785")
    value = decode(v["input"])
    if _has_time(value):
        pytest.skip("dates have their own rule; the vector fixes the text")
    assert rfc8785.dumps(_plain(value)) == canonical_bytes(value)


def test_tuple_is_array_and_set_is_refused():
    assert canonical_json(("a", "b")) == '["a","b"]'
    with pytest.raises(CanonError):
        canonical_json({"a"})
    with pytest.raises(CanonError):
        canonical_json({1: "x"})
