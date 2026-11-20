"""Turn model rows into NamespacePublication lists through the binding's parameters.

See decisions/k8s-admission-translator.md, "Parameters".
"""

import re

_CANONICAL_INTEGER = re.compile(r"(?:0|-?[1-9][0-9]*)")
_INT64_MIN = -(2**63)
_INT64_MAX = 2**63 - 1


def _relation_columns(program, relation):
    if relation not in program.relations:
        raise ValueError(f"parameter relation {relation!r} is not in the program")
    return {column.name: column.type for column in program.relations[relation].key}


def _check_fixed_value(value, column_type, relation, field, column_name):
    if column_type == "integer":
        if type(value) is not int or not _INT64_MIN <= value <= _INT64_MAX:
            raise ValueError(
                f"fixed value for integer column {column_name!r} of {relation!r} in list {field!r} "
                f"must be a signed 64-bit integer, got {value!r}"
            )
        return
    if column_type == "string":
        if not isinstance(value, str):
            raise ValueError(
                f"fixed value for string column {column_name!r} of {relation!r} in list {field!r} "
                f"must be a string, got {value!r}"
            )
        return
    raise ValueError(f"unknown column type {column_type!r} for {column_name!r} of {relation!r}")


def _coerce_row_value(value, column_type, relation, column_name):
    if column_type == "integer":
        if type(value) is int:
            number = value
        elif isinstance(value, str) and _CANONICAL_INTEGER.fullmatch(value) is not None:
            number = int(value)
        else:
            raise ValueError(f"column {column_name!r} of {relation!r} expects an integer, got {value!r}")
        if not _INT64_MIN <= number <= _INT64_MAX:
            raise ValueError(
                f"integer column {column_name!r} of {relation!r} is outside the signed 64-bit range: {value!r}"
            )
        return number
    if column_type == "string":
        if not isinstance(value, str):
            raise ValueError(f"column {column_name!r} of {relation!r} expects a string, got {value!r}")
        return value
    raise ValueError(f"unknown column type {column_type!r} for {column_name!r} of {relation!r}")


def _check_lists(relation, spec, column_types, seen_fields):
    scope = spec["scope"]
    if scope not in column_types:
        raise ValueError(f"scope {scope!r} is not a column of {relation!r}")
    if column_types[scope] != "string":
        raise ValueError(f"scope {scope!r} of {relation!r} must be a string column")
    for entry in spec["lists"]:
        field = entry["field"]
        if field in seen_fields:
            raise ValueError(f"publication field {field!r} is written twice")
        seen_fields.add(field)
        written, fixed = list(entry["columns"]), dict(entry.get("fixed", {}))
        named = [scope, *written, *fixed]
        if len(set(named)) != len(named) or set(named) != set(column_types):
            raise ValueError(f"list {field!r} of {relation!r} must cover each non-scope column once")
        for name, value in fixed.items():
            _check_fixed_value(value, column_types[name], relation, field, name)


def _project_relation(relation, spec, column_types, rows, namespaces):
    columns = tuple(column_types.items())
    index = {name: position for position, (name, _) in enumerate(columns)}
    scope, lists = spec["scope"], spec["lists"]
    buckets = {namespace: [set() for _ in lists] for namespace in namespaces}
    for raw_row in rows:
        raw_row = tuple(raw_row)
        if len(raw_row) != len(columns):
            raise ValueError(f"row {raw_row!r} does not have the {len(columns)} columns of {relation!r}")
        row = tuple(
            _coerce_row_value(value, column_type, relation, column_name)
            for value, (column_name, column_type) in zip(raw_row, columns)
        )
        namespace = row[index[scope]]
        if namespace not in buckets:
            raise ValueError(f"row {raw_row!r} of {relation!r} is outside the managed namespaces")
        for position, entry in enumerate(lists):
            if all(
                type(row[index[name]]) is type(value) and row[index[name]] == value
                for name, value in entry.get("fixed", {}).items()
            ):
                buckets[namespace][position].add(tuple(row[index[name]] for name in entry["columns"]))
                break
        else:
            raise ValueError(f"row {raw_row!r} of {relation!r} matches no parameter list")
    projected = {}
    for namespace in namespaces:
        fields = {}
        for entry, bucket in zip(lists, buckets[namespace]):
            if not bucket and entry.get("optional"):
                continue
            field = entry["field"]
            if field in fields:
                raise ValueError(f"publication field {field!r} is written twice")
            fields[field] = [dict(zip(entry["columns"], values)) for values in sorted(bucket)]
        projected[namespace] = fields
    return projected


def project_parameters(binding, program, rows, namespaces):
    """Return {namespace: publication spec fields} for every managed namespace, without the digest."""
    result = {namespace: {} for namespace in namespaces}
    seen_fields = set()
    for relation, spec in binding["parameters"].items():
        column_types = _relation_columns(program, relation)
        _check_lists(relation, spec, column_types, seen_fields)
        projected = _project_relation(relation, spec, column_types, rows.get(relation, ()), namespaces)
        for namespace, fields in projected.items():
            overlap = set(result[namespace]) & set(fields)
            if overlap:
                raise ValueError(f"publication fields {sorted(overlap)} are written twice")
            result[namespace].update(fields)
    return result
