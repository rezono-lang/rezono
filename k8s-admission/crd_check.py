"""Check a NamespacePublication CRD against the admission bindings that write it.

See decisions/k8s-admission-binding-checks.md, "CRD check".
"""

DIGEST_PATTERN = "^[0-9a-f]{64}$"


def _storage_spec(crd: dict) -> dict:
    for version in crd.get("spec", {}).get("versions", ()):
        if version.get("storage") is True:
            return version["schema"]["openAPIV3Schema"]["properties"]["spec"]
    raise ValueError("CRD has no storage version")


def _collect_writers(pairs) -> dict[str, list[tuple[list[str], bool, dict[str, str]]]]:
    writers: dict[str, list[tuple[list[str], bool, dict[str, str]]]] = {}
    for binding, program in pairs:
        for relation_name, param_spec in (binding.get("parameters") or {}).items():
            relation = program.relations.get(relation_name)
            col_types = (
                {col.name: col.type for col in (*relation.key, *relation.values)}
                if relation is not None
                else {}
            )
            for list_spec in param_spec.get("lists") or ():
                field = list_spec["field"]
                columns = list(list_spec["columns"])
                optional = bool(list_spec.get("optional", False))
                writers.setdefault(field, []).append((columns, optional, col_types))
    return writers


def _check_digest(properties: dict, required: set[str], problems: set[tuple[str, str]]) -> None:
    digest_schema = properties.get("digest")
    if (
        "digest" not in required
        or not isinstance(digest_schema, dict)
        or digest_schema.get("type") != "string"
        or digest_schema.get("pattern") != DIGEST_PATTERN
    ):
        problems.add(("digest", "digest"))


def _check_written_field(
    field_name: str,
    prop_schema: object,
    required: set[str],
    writer: tuple[list[str], bool, dict[str, str]],
    problems: set[tuple[str, str]],
) -> None:
    columns, optional, col_types = writer
    schema = prop_schema if isinstance(prop_schema, dict) else {}

    max_items = schema.get("maxItems")
    if (
        schema.get("type") != "array"
        or not (isinstance(max_items, int) and not isinstance(max_items, bool) and max_items > 0)
        or schema.get("x-kubernetes-list-type") != "map"
    ):
        problems.add(("list_shape", field_name))

    if schema.get("x-kubernetes-list-map-keys") != columns:
        problems.add(("list_keys", field_name))

    items_schema = schema.get("items")
    item_props = items_schema.get("properties") if isinstance(items_schema, dict) else None
    item_req = items_schema.get("required") if isinstance(items_schema, dict) else None
    col_set = set(columns)
    if (
        not isinstance(item_props, dict)
        or set(item_props) != col_set
        or not isinstance(item_req, list)
        or set(item_req) != col_set
    ):
        problems.add(("item_columns", field_name))

    if isinstance(item_props, dict):
        for col in columns:
            if col in item_props:
                col_prop = item_props[col]
                if not isinstance(col_prop, dict) or col_prop.get("type") != col_types.get(col):
                    problems.add(("item_type", f"{field_name}/{col}"))

    if (field_name in required) == optional:
        problems.add(("required", field_name))


def check_crd(crd: dict, pairs) -> list[tuple[str, str]]:
    """Return sorted unique (code, place) problems comparing `crd` against `pairs`."""
    spec_schema = _storage_spec(crd)
    properties = spec_schema.get("properties") or {}
    required = set(spec_schema.get("required") or ())

    problems: set[tuple[str, str]] = set()
    _check_digest(properties, required, problems)

    writers = _collect_writers(pairs)
    for field_name in properties:
        if field_name != "digest" and field_name not in writers:
            problems.add(("field_unwritten", field_name))

    for field_name, field_writers in writers.items():
        if field_name not in properties:
            problems.add(("field_missing", field_name))
            continue
        if len(field_writers) > 1:
            problems.add(("field_shared", field_name))
            continue
        _check_written_field(field_name, properties[field_name], required, field_writers[0], problems)

    return sorted(problems)
