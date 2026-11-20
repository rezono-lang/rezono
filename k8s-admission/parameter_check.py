"""Check the parameter side of an admission binding against its rule program.

See decisions/k8s-admission-binding-checks.md, "Parameter check".
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from rezono_compiler import rules


def _matches_type(value: Any, column_type: str) -> bool:
    if column_type == "integer":
        return type(value) is int
    return isinstance(value, str)


def _same_fixed_value(left: Any, right: Any) -> bool:
    return type(left) is type(right) and left == right


def _shadows(earlier_fixed: Mapping[str, Any], fixed: Mapping[str, Any]) -> bool:
    return all(col in fixed and _same_fixed_value(fixed[col], val) for col, val in earlier_fixed.items())


def _check_list(
    place: str,
    entry: Mapping[str, Any],
    columns: Mapping[str, str],
    scope: str,
    earlier_fixed: list[Mapping[str, Any]],
    seen_fields: set[str],
    problems: set[tuple[str, str]],
) -> None:
    field = entry["field"]
    if field in seen_fields:
        problems.add(("field_repeated", f"{place}/field"))
    else:
        seen_fields.add(field)

    written = entry["columns"]
    for idx, col in enumerate(written):
        if col not in columns or col == scope:
            problems.add(("list_column", f"{place}/columns/{idx}"))

    written_set = set(written)
    fixed = entry.get("fixed", {})
    for col, value in fixed.items():
        if col not in columns or col == scope or col in written_set:
            problems.add(("fixed_column", f"{place}/fixed/{col}"))
        if col in columns and not _matches_type(value, columns[col]):
            problems.add(("fixed_type", f"{place}/fixed/{col}"))

    non_scope = columns.keys() - {scope}
    if not non_scope <= (written_set | fixed.keys()):
        problems.add(("list_cover", place))

    if any(_shadows(prev, fixed) for prev in earlier_fixed):
        problems.add(("list_shadowed", place))
    earlier_fixed.append(fixed)


def check_parameters(binding: Mapping[str, Any], program: rules.Program) -> list[tuple[str, str]]:
    """Return sorted, unique (code, place) problems for binding['parameters'] against program."""
    request_relations = {source["relation"] for source in binding.get("request", ())}
    seen_fields: set[str] = set()
    problems: set[tuple[str, str]] = set()

    for rel_name, param in binding.get("parameters", {}).items():
        rel_place = f"parameters/{rel_name}"
        relation = program.relations.get(rel_name)
        if relation is None:
            problems.add(("unknown_relation", rel_place))
            continue
        if rel_name in request_relations:
            problems.add(("request_relation", rel_place))

        columns = {col.name: col.type for col in relation.key}
        scope = param["scope"]
        if columns.get(scope) != "string":
            problems.add(("scope_column", f"{rel_place}/scope"))

        earlier_fixed: list[Mapping[str, Any]] = []
        for idx, entry in enumerate(param["lists"]):
            _check_list(
                f"{rel_place}/lists/{idx}",
                entry,
                columns,
                scope,
                earlier_fixed,
                seen_fields,
                problems,
            )

    return sorted(problems)
