"""Exact CEL parameter tables for admission bindings: decisions/k8s-admission-translator.md, "Parameter table"."""

from cel_literal import literal


def _fixed_literal(value, column_type):
    if column_type == "integer":
        if type(value) is not int:
            raise ValueError(f"expected integer fixed value, got {value!r}")
        return literal(str(value), "integer")
    return literal(value, column_type)


def _list_expression(entry, non_scope):
    field = entry["field"]
    base = (
        f"(has(params.spec.{field}) ? params.spec.{field} : [])"
        if entry.get("optional")
        else f"params.spec.{field}"
    )
    written = set(entry["columns"])
    fixed = entry.get("fixed", {})
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
    rel_columns = relation.key + relation.values
    types = {col.name: col.type for col in rel_columns}
    scope = spec["scope"]
    if types.get(scope) != "string":
        raise ValueError(f"{name}: scope {scope!r} must be a string column")
    lists = spec["lists"]
    if not lists:
        raise ValueError(f"{name}: parameter lists must not be empty")
    columns = {col.name: (namespace if col.name == scope else f"{{e}}.{col.name}") for col in rel_columns}
    non_scope = [col for col in rel_columns if col.name != scope]
    expr = " + ".join(_list_expression(entry, non_scope) for entry in lists)
    return {"list": expr, "columns": columns, "types": types}


def parameter_tables(binding, program, namespace):
    """Return CEL table descriptors for every relation under `binding["parameters"]`."""
    if not isinstance(namespace, str) or not namespace:
        raise ValueError("namespace expression must be a non-empty string")
    tables = {}
    for name, spec in binding["parameters"].items():
        relation = program.relations.get(name)
        if relation is None:
            raise ValueError(f"unknown parameter relation: {name}")
        tables[name] = _relation_table(name, spec, relation, namespace)
    return tables
