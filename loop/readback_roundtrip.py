"""Recover typed rows from the checked field bindings for one observed object."""

from loop.field_readback import read_field
from loop.readback_identity import verify_identity


def read_rows(reference: dict, manifest: str, obj: dict) -> list[dict]:
    """Group the knowledge fields by their original row after checking object identity."""
    verify_identity(reference, manifest, obj)
    fields = reference.get("fields")
    if not isinstance(fields, list):
        raise ValueError("read-back requires an indexed field list")

    rows: dict[tuple[str, str], tuple[dict, dict[str, object]]] = {}
    pointers: set[str] = set()
    for binding in fields:
        if not isinstance(binding, dict):
            raise ValueError("expected an indexed field binding")
        field = read_field(binding, obj)
        if field is None:
            continue
        witness, column, value = field
        key = (witness["relation"], witness["key"])
        original, row = rows.setdefault(key, (witness, {}))
        if original != witness or column in row or binding["pointer"] in pointers:
            raise ValueError("ambiguous read-back field binding")
        row[column] = value
        pointers.add(binding["pointer"])

    return [
        {"witness": witness, "row": dict(sorted(row.items()))}
        for _, (witness, row) in sorted(rows.items())
    ]
