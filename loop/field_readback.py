"""Recover observed values through their original knowledge bindings."""

from math import isfinite

from jsonpointer import JsonPointerException, resolve_pointer

_SCALAR_TYPES = {
    "boolean": (bool,),
    "integer": (int,),
    "number": (int, float),
    "null": (type(None),),
    "string": (str,),
}


def read_field(binding: dict, obj: object) -> tuple[dict, str, object] | None:
    """Resolve a bound JSON scalar without coercion and retain its row and column."""
    origin = binding.get("origin")
    if origin in ("chart_constant", "chart_default"):
        return None
    if origin != "knowledge":
        raise ValueError("invalid field origin")

    pointer = binding.get("pointer")
    column = binding.get("column")
    witness = binding.get("witness")
    declared_type = binding.get("type")
    if not isinstance(pointer, str) or not isinstance(column, str) or not column:
        raise ValueError("knowledge binding requires a JSON pointer and column")
    if not isinstance(witness, dict) or not all(
        isinstance(witness.get(field), str) and witness[field] for field in ("relation", "key")
    ):
        raise ValueError("knowledge binding requires a row witness")
    if not isinstance(declared_type, str) or declared_type not in _SCALAR_TYPES:
        raise ValueError("knowledge binding requires a supported scalar type")

    try:
        value = resolve_pointer(obj, pointer)
    except JsonPointerException as error:
        raise ValueError("knowledge pointer does not resolve") from error
    if type(value) not in _SCALAR_TYPES[declared_type] or (
        type(value) is float and not isfinite(value)
    ):
        raise ValueError("observed value does not match the binding type")

    return witness, column, value
