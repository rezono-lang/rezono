"""Exact CEL parameter tables for admission bindings: decisions/k8s-admission-translator.md, "Parameter table"."""

from collections.abc import Mapping, Sequence
import re

from cel_literal import literal

_IDENT_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_ENTRY_REQUIRED_KEYS = ("field", "columns")
_ENTRY_ALLOWED_KEYS = frozenset({"field", "columns", "fixed", "optional"})
_SPEC_REQUIRED_KEYS = ("scope", "lists")
_SPEC_ALLOWED_KEYS = frozenset({"scope", "lists"})


def _is_sequence(value: object) -> bool:
    return isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray))


def _require_identifier(value: object, label: str) -> str:
    if not isinstance(value, str) or _IDENT_RE.fullmatch(value) is None:
        raise ValueError(f"{label} must be a valid CEL identifier, got {value!r}")
    return value


def _fixed_literal(value, column_type):
    if column_type == "integer":
        if type(value) is not int:
            raise ValueError(f"expected integer fixed value, got {value!r}")
        return literal(str(value), "integer")
    return literal(value, column_type)


def _list_expression(entry, non_scope):
    if not isinstance(entry, Mapping):
        raise ValueError("parameter list entry must be a mapping")
    unknown_keys = sorted(key for key in entry if key not in _ENTRY_ALLOWED_KEYS)
    if unknown_keys:
        joined = ", ".join(repr(key) for key in unknown_keys)
        raise ValueError(f"parameter list entry has unknown key(s): {joined}")
    missing_keys = [key for key in _ENTRY_REQUIRED_KEYS if key not in entry]
    if missing_keys:
        joined = ", ".join(repr(key) for key in missing_keys)
        raise ValueError(f"parameter list entry is missing required key(s): {joined}")

    field = _require_identifier(entry["field"], "parameter list 'field'")
    if "optional" in entry:
        optional = entry["optional"]
        if type(optional) is not bool:
            raise ValueError(f"list {field!r} 'optional' must be a boolean, got {optional!r}")
    else:
        optional = False

    raw_columns = entry["columns"]
    if not _is_sequence(raw_columns) or not raw_columns:
        raise ValueError(f"list {field!r} 'columns' must be a non-empty sequence")
    written_list = [_require_identifier(col, f"list {field!r} column") for col in raw_columns]
    if len(set(written_list)) != len(written_list):
        raise ValueError(f"list {field!r} 'columns' must not contain duplicates")
    written = set(written_list)

    if "fixed" in entry:
        fixed = entry["fixed"]
        if not isinstance(fixed, Mapping):
            raise ValueError(f"list {field!r} 'fixed' must be a mapping")
        for key in fixed:
            _require_identifier(key, f"list {field!r} fixed column")
    else:
        fixed = {}

    base = (
        f"(has(params.spec.{field}) ? params.spec.{field} : [])"
        if optional
        else f"params.spec.{field}"
    )
    overlap = written & fixed.keys()
    if overlap:
        raise ValueError(f"list {field!r} both writes and fixes {sorted(overlap)}")
    expected = {col.name for col in non_scope}
    if written | fixed.keys() != expected:
        raise ValueError(f"list {field!r} must cover non-scope columns {sorted(expected)}")
    parts = []
    for col in non_scope:
        if col.name in written:
            parts.append(f'"{col.name}": x.{col.name}')
        else:
            parts.append(f'"{col.name}": {_fixed_literal(fixed[col.name], col.type)}')
    return f"{base}.map(x, {{{', '.join(parts)}}})"


def _relation_table(name, spec, relation, namespace):
    if not isinstance(spec, Mapping):
        raise ValueError(f"{name}: parameter spec must be a mapping")
    unknown_keys = sorted(key for key in spec if key not in _SPEC_ALLOWED_KEYS)
    if unknown_keys:
        joined = ", ".join(repr(key) for key in unknown_keys)
        raise ValueError(f"{name}: parameter spec has unknown key(s): {joined}")
    missing_keys = [key for key in _SPEC_REQUIRED_KEYS if key not in spec]
    if missing_keys:
        joined = ", ".join(repr(key) for key in missing_keys)
        raise ValueError(f"{name}: parameter spec is missing required key(s): {joined}")

    rel_columns = relation.key + relation.values
    for col in rel_columns:
        _require_identifier(col.name, f"{name} column")
    types = {col.name: col.type for col in rel_columns}
    scope = spec["scope"]
    if not isinstance(scope, str) or types.get(scope) != "string":
        raise ValueError(f"{name}: scope {scope!r} must be a string column")
    lists = spec["lists"]
    if not _is_sequence(lists) or not lists:
        raise ValueError(f"{name}: parameter lists must be a non-empty sequence")
    columns = {col.name: (namespace if col.name == scope else f"{{e}}.{col.name}") for col in rel_columns}
    non_scope = [col for col in rel_columns if col.name != scope]
    expr = " + ".join(_list_expression(entry, non_scope) for entry in lists)
    if len(lists) > 1:
        expr = f"({expr})"
    return {"list": expr, "columns": columns, "types": types}


def parameter_tables(binding, program, namespace):
    """Return CEL table descriptors for every relation under `binding["parameters"]`."""
    if not isinstance(namespace, str) or not namespace:
        raise ValueError("namespace expression must be a non-empty string")
    if not isinstance(binding, Mapping) or "parameters" not in binding or not isinstance(binding["parameters"], Mapping):
        raise ValueError("binding must be a mapping with a 'parameters' mapping")
    tables = {}
    for name, spec in binding["parameters"].items():
        relation = program.relations.get(name)
        if relation is None:
            raise ValueError(f"unknown parameter relation: {name}")
        tables[name] = _relation_table(name, spec, relation, namespace)
    return tables
