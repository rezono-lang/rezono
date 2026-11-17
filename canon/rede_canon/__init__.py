"""The one canonical JSON form and hash of Rede (docs/contracts.md#canonical-hash).

RFC 8785 (JCS) over a JSON value without numbers: an integer becomes decimal text, a date or a
timezone-aware datetime becomes ISO text. Anything that has no single canonical form is refused
with CanonError: floats, null, sets, non-string keys, lone surrogates, naive datetimes.
"""

import datetime as _dt
import hashlib
import json

__all__ = ["CanonError", "canonical_json", "canonical_bytes", "canonical_sha256", "sha256_hex"]


class CanonError(ValueError):
    """A value without a canonical form. `code` names the rule, as in the test vectors."""

    def __init__(self, code: str, detail: str):
        super().__init__(f"{code}: {detail}")
        self.code = code


def _string(s: str) -> str:
    try:
        s.encode("utf-8")
    except UnicodeEncodeError:
        raise CanonError("lone_surrogate", repr(s)) from None
    # json.dumps escapes exactly what RFC 8785 escapes: '"', '\\', \b \f \n \r \t, other controls as \u00xx.
    return json.dumps(s, ensure_ascii=False)


def _utf16(key: str) -> bytes:
    return key.encode("utf-16-be")  # RFC 8785 sorts keys by UTF-16 code units


def _datetime(t: _dt.datetime) -> str:
    if t.tzinfo is None or t.utcoffset() is None:
        raise CanonError("naive_datetime", t.isoformat())
    u = t.astimezone(_dt.timezone.utc).replace(tzinfo=None)
    text = u.isoformat(timespec="seconds")
    if u.microsecond:
        text += f".{u.microsecond:06d}".rstrip("0")
    return text + "Z"


def _encode(v, out: list) -> None:
    if isinstance(v, str):
        out.append(_string(v))
    elif v is True or v is False:
        out.append("true" if v else "false")
    elif isinstance(v, int):
        out.append(f'"{int(v)}"')
    elif isinstance(v, _dt.datetime):
        out.append(f'"{_datetime(v)}"')
    elif isinstance(v, _dt.date):
        out.append(f'"{v.isoformat()}"')
    elif isinstance(v, dict):
        if not all(isinstance(k, str) for k in v):
            raise CanonError("non_string_key", repr(list(v)))
        for k in v:
            _string(k)
        out.append("{")
        for i, k in enumerate(sorted(v, key=_utf16)):
            if i:
                out.append(",")
            out.append(_string(k))
            out.append(":")
            _encode(v[k], out)
        out.append("}")
    elif isinstance(v, (list, tuple)):
        out.append("[")
        for i, item in enumerate(v):
            if i:
                out.append(",")
            _encode(item, out)
        out.append("]")
    elif v is None:
        raise CanonError("null", "absent is a missing key; unknown is a state (docs/compiler.md)")
    elif isinstance(v, float):
        raise CanonError("float", repr(v))
    else:
        raise CanonError("unsupported", type(v).__name__)


def canonical_json(value) -> str:
    """The canonical JSON text of `value`."""
    out: list = []
    _encode(value, out)
    return "".join(out)


def canonical_bytes(value) -> bytes:
    """The UTF-8 bytes of the canonical JSON text."""
    return canonical_json(value).encode("utf-8")


def sha256_hex(data: bytes) -> str:
    """SHA-256 of bytes as stored (a file, a snapshot), as 64 lowercase hex digits."""
    return hashlib.sha256(data).hexdigest()


def canonical_sha256(value) -> str:
    """SHA-256 of the canonical JSON bytes of `value`: the hash of a value everywhere in Rede."""
    return sha256_hex(canonical_bytes(value))
