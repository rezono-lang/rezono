"""Exact CEL literals for rule constants: decisions/k8s-admission-translator.md, "Literal"."""

import re

_CANONICAL_INTEGER = re.compile(r"(?:0|-?[1-9][0-9]*)")
_INT64_MIN = -(2**63)
_INT64_MAX = 2**63 - 1


def _integer(value):
    if not isinstance(value, str) or _CANONICAL_INTEGER.fullmatch(value) is None:
        raise ValueError(f"not a canonical integer: {value!r}")
    if not _INT64_MIN <= int(value) <= _INT64_MAX:
        raise ValueError(f"integer outside the signed 64-bit range: {value}")
    return value


def _escape(char):
    point = ord(char)
    if char == '"':
        return '\\"'
    if char == "\\":
        return "\\\\"
    if 0x20 <= point <= 0x7E:
        return char
    if 0xD800 <= point <= 0xDFFF:
        raise ValueError(f"surrogate code point U+{point:04X} has no CEL literal")
    if point > 0xFFFF:
        return f"\\U{point:08x}"
    return f"\\u{point:04x}"


def _string(value):
    if not isinstance(value, str):
        raise ValueError(f"not a string: {value!r}")
    return '"' + "".join(_escape(char) for char in value) + '"'


_WRITERS = {"integer": _integer, "string": _string}


def literal(value, type):
    """Return the exact CEL literal for a rule constant `value` of the rule type `type`."""
    writer = _WRITERS.get(type)
    if writer is None:
        raise ValueError(f"unknown literal type: {type!r}")
    return writer(value)
