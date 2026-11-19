"""Turn model rows into NamespacePublication lists through the binding's parameters.

See decisions/k8s-admission-translator.md, "Parameters".
"""


def _relation_columns(program, relation):
    if relation not in program.relations:
        raise ValueError(f"parameter relation {relation!r} is not in the program")
    return [column.name for column in program.relations[relation].key]


def _check_lists(relation, spec, columns):
    scope = spec["scope"]
    if scope not in columns:
        raise ValueError(f"scope {scope!r} is not a column of {relation!r}")
    for entry in spec["lists"]:
        written, fixed = list(entry["columns"]), dict(entry.get("fixed", {}))
        named = [scope, *written, *fixed]
        if len(set(named)) != len(named) or set(named) != set(columns):
            raise ValueError(f"list {entry['field']!r} of {relation!r} must cover each non-scope column once")


def _project_relation(relation, spec, columns, rows, namespaces):
    index = {name: position for position, name in enumerate(columns)}
    scope, lists = spec["scope"], spec["lists"]
    buckets = {namespace: [set() for _ in lists] for namespace in namespaces}
    for row in rows:
        row = tuple(row)
        if len(row) != len(columns):
            raise ValueError(f"row {row!r} does not have the {len(columns)} columns of {relation!r}")
        namespace = row[index[scope]]
        if namespace not in buckets:
            raise ValueError(f"row {row!r} of {relation!r} is outside the managed namespaces")
        for position, entry in enumerate(lists):
            if all(row[index[name]] == value for name, value in entry.get("fixed", {}).items()):
                buckets[namespace][position].add(tuple(row[index[name]] for name in entry["columns"]))
                break
        else:
            raise ValueError(f"row {row!r} of {relation!r} matches no parameter list")
    projected = {}
    for namespace in namespaces:
        fields = {}
        for entry, bucket in zip(lists, buckets[namespace]):
            if not bucket and entry.get("optional"):
                continue
            fields[entry["field"]] = [dict(zip(entry["columns"], values)) for values in sorted(bucket)]
        projected[namespace] = fields
    return projected


def project_parameters(binding, program, rows, namespaces):
    """Return {namespace: publication spec fields} for every managed namespace, without the digest."""
    result = {namespace: {} for namespace in namespaces}
    for relation, spec in binding["parameters"].items():
        columns = _relation_columns(program, relation)
        _check_lists(relation, spec, columns)
        projected = _project_relation(relation, spec, columns, rows.get(relation, ()), namespaces)
        for namespace, fields in projected.items():
            overlap = set(result[namespace]) & set(fields)
            if overlap:
                raise ValueError(f"publication fields {sorted(overlap)} are written twice")
            result[namespace].update(fields)
    return result
