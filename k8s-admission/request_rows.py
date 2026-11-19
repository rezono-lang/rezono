"""Read one incoming object as request rows through its binding.

See decisions/k8s-admission-translator.md, "The binding" and "Request sources".
"""

import json
import re

_KEY = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")
_ABSENT = object()


def _place(base, keys):
    return base + "".join(f".{k}" if _KEY.fullmatch(k) else f"[{json.dumps(k)}]" for k in keys)


def _walk(value, keys):
    for key in keys:
        if not isinstance(value, dict) or key not in value:
            return _ABSENT
        value = value[key]
    return value


def _is_type(value, column_type):
    if column_type == "integer":
        return type(value) is int
    return isinstance(value, str)


def _locate(env, path):
    """Return (value, place) of a path whose first element is a root or an earlier iterator."""
    value, base = env[path[0]]
    return _walk(value, path[1:]), _place(base, path[1:])


def _read_column(spec, ctype, env, missing):
    value, place = _locate(env, spec["path"])
    if value is _ABSENT and "default" in spec:
        value = spec["default"]
    if spec.get("reading") == "port-range":
        end = _locate(env, spec["end"])[0] if "end" in spec else _ABSENT
        if end is _ABSENT:
            end = value
        if (not _is_type(value, "integer") or not _is_type(end, "integer")
                or not 1 <= value <= end <= 65535):
            missing.add(place)
            return None
        return list(range(value, end + 1))
    if value is _ABSENT or not _is_type(value, ctype):
        missing.add(place)
        return None
    return [value]


def _read_source(source, program, env, iterators, out, missing):
    if iterators:
        it, rest = iterators[0], iterators[1:]
        value, place = _locate(env, it["path"])
        if value is _ABSENT:
            if not it.get("optional"):
                missing.add(place)
            return
        if not isinstance(value, list) or (it.get("nonempty") and not value):
            missing.add(place)
            return
        closed = it.get("closed")
        for index, element in enumerate(value):
            at = f"{place}[{index}]"
            if not isinstance(element, dict) or (closed is not None and not set(element) <= set(closed)):
                missing.add(at)
                continue
            _read_source(source, program, {**env, it["name"]: (element, at)}, rest, out, missing)
        return
    columns = program.relations[source["relation"]].key
    choices = [_read_column(source["columns"][c.name], c.type, env, missing) for c in columns]
    if all(choice is not None for choice in choices):
        rows = [()]
        for choice in choices:
            rows = [row + (item,) for row in rows for item in choice]
        out.extend(rows)


def read_request_rows(binding, program, request):
    """Return {"rows": {relation: [row, ...]}, "missing": [place, ...]} for one AdmissionReview request."""
    env = {"object": (request.get("object"), "object"), "request": (request, "request")}
    rows = {source["relation"]: [] for source in binding["request"]}
    missing = set()
    for source in binding["request"]:
        _read_source(source, program, env, source["each"], rows[source["relation"]], missing)
    if missing:
        return {"rows": {relation: [] for relation in rows}, "missing": sorted(missing)}
    return {"rows": {relation: sorted(set(found)) for relation, found in rows.items()}, "missing": []}
