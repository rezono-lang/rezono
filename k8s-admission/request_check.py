"""Check the output and request side of an admission binding against its rule program.

See decisions/k8s-admission-binding-checks.md, "Request check".
"""

_RESERVED_ROOTS = frozenset({"object", "request"})


def _matches_type(value, column_type):
    if column_type == "integer":
        return type(value) is int
    return isinstance(value, str)


def _check_source(index, source, relations, problems):
    prefix = f"request/{index}"
    seen_iterators = set()

    for j, iterator in enumerate(source["each"]):
        name = iterator["name"]
        if name in _RESERVED_ROOTS or name in seen_iterators:
            problems.append(("iterator_name", f"{prefix}/each/{j}/name"))
        path = iterator["path"]
        if not path or (path[0] not in _RESERVED_ROOTS and path[0] not in seen_iterators):
            problems.append(("path_root", f"{prefix}/each/{j}/path"))
        seen_iterators.add(name)

    valid_roots = _RESERVED_ROOTS | seen_iterators
    columns = source["columns"]
    for col_name, col_spec in columns.items():
        path = col_spec["path"]
        if not path or path[0] not in valid_roots:
            problems.append(("path_root", f"{prefix}/columns/{col_name}/path"))
        if "end" in col_spec:
            end_path = col_spec["end"]
            if not end_path or end_path[0] not in valid_roots:
                problems.append(("path_root", f"{prefix}/columns/{col_name}/end"))

    rel_name = source["relation"]
    relation = relations.get(rel_name)
    if relation is None:
        problems.append(("unknown_relation", f"{prefix}/relation"))
        return

    if relation.role != "base":
        problems.append(("request_role", f"{prefix}/relation"))

    rel_columns = {col.name: col.type for col in relation.key}
    for col_name in rel_columns:
        if col_name not in columns:
            problems.append(("column_missing", f"{prefix}/columns/{col_name}"))

    for col_name, col_spec in columns.items():
        col_type = rel_columns.get(col_name)
        if col_type is None:
            problems.append(("column_unknown", f"{prefix}/columns/{col_name}"))
            continue
        if col_spec.get("reading") == "port-range" and col_type != "integer":
            problems.append(("reading_type", f"{prefix}/columns/{col_name}/reading"))
        if "default" in col_spec and not _matches_type(col_spec["default"], col_type):
            problems.append(("default_type", f"{prefix}/columns/{col_name}/default"))


def check_request(binding, program):
    """Return sorted unique (code, place) pairs for problems in `output` and `request`."""
    problems = []
    relations = program.relations

    output_name = binding["output"]
    output_rel = relations.get(output_name)
    if output_rel is None:
        problems.append(("unknown_relation", "output"))
    elif output_rel.role != "derived":
        problems.append(("output_role", "output"))

    for index, source in enumerate(binding["request"]):
        _check_source(index, source, relations, problems)

    return sorted(set(problems))
