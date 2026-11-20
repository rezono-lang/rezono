"""Compile admission request sources into CEL predicates and missing-input checks.

See decisions/k8s-admission-translator.md, "The binding" and "Request sources".
"""

import itertools

from cel_literal import literal


def _is_default_valid(value, ctype):
    if ctype == "integer":
        return type(value) is int
    if ctype == "string":
        return isinstance(value, str)
    return False


def _relation_columns(program, relation):
    if relation not in program.relations:
        raise ValueError(f"unknown relation: {relation!r}")
    return program.relations[relation].key


def _path_parts(env, path):
    root, *keys = path
    if root not in env:
        raise ValueError(f"unknown path root: {root!r}")
    curr, known_map = env[root]
    checks = []
    for index, key in enumerate(keys):
        key_lit = literal(key, "string")
        if index > 0 or not known_map:
            checks.append(f"type(dyn({curr})) == map")
        checks.append(f"{key_lit} in {curr}")
        curr = f"{curr}[{key_lit}]"
    return " && ".join(checks), curr


def _scalar_parts(spec, ctype, env):
    if ctype == "integer":
        cel_type = "int"
    elif ctype == "string":
        cel_type = "string"
    else:
        raise ValueError(f"unknown column type: {ctype!r}")

    present, val = _path_parts(env, spec["path"])
    if "default" in spec and _is_default_valid(spec["default"], ctype):
        default_raw = str(spec["default"]) if ctype == "integer" else spec["default"]
        default_lit = literal(default_raw, ctype)
        ok = f"(!({present}) || type({val}) == {cel_type})"
        expr = f"(({present}) ? {cel_type}({val}) : {default_lit})"
        return ok, expr

    ok = f"({present}) && type({val}) == {cel_type}"
    expr = f"{cel_type}({val})"
    return ok, expr


def _port_range_parts(spec, ctype, env):
    if ctype != "integer":
        raise ValueError(f"port-range requires integer column, got {ctype!r}")
    start_ok, start_cel = _scalar_parts(spec, "integer", env)
    if "end" in spec:
        end_present, end_val = _path_parts(env, spec["end"])
        end_ok = f"(!({end_present}) || type({end_val}) == int)"
        end_cel = f"(({end_present}) ? int({end_val}) : {start_cel})"
        ok = f"{start_ok} && {end_ok} && 1 <= {start_cel} && {start_cel} <= {end_cel} && {end_cel} <= 65535"
    else:
        end_cel = start_cel
        ok = f"{start_ok} && 1 <= {start_cel} && {start_cel} <= 65535"
    return ok, start_cel, end_cel


def _column_missing(spec, ctype, env):
    if spec.get("reading") == "port-range":
        ok, _, _ = _port_range_parts(spec, ctype, env)
        return f"!({ok})"
    ok, _ = _scalar_parts(spec, ctype, env)
    return f"!({ok})"


def _column_value(spec, ctype, env):
    if spec.get("reading") == "port-range":
        _, start_cel, end_cel = _port_range_parts(spec, ctype, env)
        return {"start": start_cel, "end": end_cel}
    _, expr = _scalar_parts(spec, ctype, env)
    return expr


def _source_missing(source, program, env, iterators, counter):
    if not iterators:
        columns = _relation_columns(program, source["relation"])
        parts = [_column_missing(source["columns"][col.name], col.type, env) for col in columns]
        return " || ".join(f"({part})" for part in parts)

    it, rest = iterators[0], iterators[1:]
    present, val = _path_parts(env, it["path"])
    list_checks = [f"type({val}) != list"]
    if it.get("nonempty"):
        list_checks.append(f"size({val}) == 0")

    var = f"v{next(counter)}"
    elem_checks = [f"type({var}) != map"]
    if "closed" in it:
        closed_list = "[" + ", ".join(literal(key, "string") for key in it["closed"]) + "]"
        key_var = f"k{next(counter)}"
        elem_checks.append(f"!{var}.all({key_var}, {key_var} in {closed_list})")
    rest_missing = _source_missing(source, program, {**env, it["name"]: (var, True)}, rest, counter)
    elem_checks.append(f"({rest_missing})")

    list_checks.append(f"{val}.exists({var}, {' || '.join(elem_checks)})")
    body_missing = " || ".join(list_checks)
    if it.get("optional"):
        return f"({present}) && ({body_missing})"
    return f"!({present}) || ({body_missing})"


def _source_quantify(source, program, env, iterators, body, counter):
    if not iterators:
        relation = source["relation"]
        columns = {
            col.name: _column_value(source["columns"][col.name], col.type, env)
            for col in _relation_columns(program, relation)
        }
        return body(relation, columns)

    it, rest = iterators[0], iterators[1:]
    present, val = _path_parts(env, it["path"])
    var = f"v{next(counter)}"
    rest_cel = _source_quantify(source, program, {**env, it["name"]: (var, True)}, rest, body, counter)
    all_expr = f"{val}.all({var}, {rest_cel})"
    if it.get("optional"):
        return f"(!({present}) || {all_expr})"
    return all_expr


def missing(binding, program, roots):
    """Return CEL that holds when the incoming object has missing or unsupported input."""
    env = {name: (expr, False) for name, expr in roots.items()}
    counter = itertools.count()
    parts = [_source_missing(source, program, env, source["each"], counter) for source in binding["request"]]
    if not parts:
        return "false"
    return " || ".join(f"({part})" for part in parts)


def quantify(binding, program, roots, body):
    """Return CEL that holds when `body(relation, columns)` holds for every row of every source."""
    env = {name: (expr, False) for name, expr in roots.items()}
    counter = itertools.count()
    parts = [_source_quantify(source, program, env, source["each"], body, counter) for source in binding["request"]]
    if not parts:
        return "true"
    return " && ".join(f"({part})" for part in parts)
