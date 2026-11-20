"""Exact CEL port range check: decisions/k8s-admission-translator.md, "Port range"."""


def covers(table, var, conditions, column, start, end):
    """Return CEL checking that `table` contains every integer port from `start` to `end`."""
    columns = table["columns"]
    if column not in columns:
        raise ValueError(f"unknown column: {column!r}")
    types = table.get("types")
    if types is not None and types.get(column) != "integer":
        raise ValueError(f"port range column {column!r} must have type 'integer'")
    item = columns[column].replace("{e}", var)
    parts = [*conditions, f"({item} >= {start})", f"({item} <= {end})"]
    joined = " && ".join(parts)
    return f"({start} <= {end} && size({table['list']}.filter({var}, {joined})) == {end} - {start} + 1)"
