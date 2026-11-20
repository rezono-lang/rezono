"""Independent checker verification of sweep variant status_readers (decisions/central-read-access.md, section 2)."""

from __future__ import annotations

from collections.abc import Mapping, Set as AbstractSet


def _string_set(value: object, *, allow_set: bool = True) -> frozenset[str] | None:
    """Return a frozenset of non-empty strings from a concrete non-mapping collection, or None."""
    allowed = (list, tuple, AbstractSet) if allow_set else (list, tuple)
    if not isinstance(value, allowed) or isinstance(value, Mapping):
        return None
    items = list(value)
    if not all(isinstance(item, str) and bool(item) for item in items):
        return None
    return frozenset(items)


def check_variant_status_readers(
    variant: dict,
    role_full: Mapping[str, AbstractSet[str]],
    all_relations: AbstractSet[str],
    complete_roles: AbstractSet[str] = frozenset(),
) -> list[dict]:
    """Verify a sweep variant's `status_readers` against checker-derived full relation sets.

    Every role in `variant.get("status_readers", ())` must:
    - appear in `variant.get("readers", ())` (`status_reader_not_reader`), and
    - either belong to `complete_roles`, or appear in `role_full` and cover every relation
      in `all_relations` (`status_reader_incomplete`).

    Malformed inputs and an empty `all_relations` set fail closed with an error finding.
    """
    if not isinstance(variant, Mapping):
        return [{"severity": "error", "reason": "status_reader_incomplete", "detail": "malformed variant"}]

    readers = _string_set(variant.get("readers", ()), allow_set=False)
    status_readers = _string_set(variant.get("status_readers", ()), allow_set=False)
    required = _string_set(all_relations, allow_set=True)
    complete = _string_set(complete_roles, allow_set=True)

    if status_readers is None:
        return [{"severity": "error", "reason": "status_reader_incomplete", "detail": "malformed status_readers"}]
    if readers is None:
        if not status_readers:
            return [{"severity": "error", "reason": "status_reader_not_reader", "detail": "malformed readers"}]
        return [
            {"severity": "error", "reason": "status_reader_not_reader", "role": role, "detail": "malformed readers"}
            for role in sorted(status_readers)
        ]
    if required is None or not required:
        return [{"severity": "error", "reason": "status_reader_incomplete", "detail": "missing or empty all_relations"}]
    if complete is None:
        return [{"severity": "error", "reason": "status_reader_incomplete", "detail": "malformed complete_roles"}]
    if not isinstance(role_full, Mapping):
        return [{"severity": "error", "reason": "status_reader_incomplete", "detail": "malformed role_full"}]

    findings: list[dict] = []
    for role in sorted(status_readers):
        if role not in readers:
            findings.append({
                "severity": "error",
                "reason": "status_reader_not_reader",
                "role": role,
                "detail": "status reader is not listed in variant readers",
            })
        if role in complete:
            continue
        if role not in role_full:
            findings.append({
                "severity": "error",
                "reason": "status_reader_incomplete",
                "role": role,
                "detail": "status reader has no checker-derived full relation set",
            })
            continue
        covered = _string_set(role_full[role], allow_set=True)
        if covered is None:
            findings.append({
                "severity": "error",
                "reason": "status_reader_incomplete",
                "role": role,
                "detail": "status reader full relation set is malformed",
            })
            continue
        missing = sorted(required - covered)
        if missing:
            findings.append({
                "severity": "error",
                "reason": "status_reader_incomplete",
                "role": role,
                "detail": f"missing relations: {', '.join(missing)}",
            })
    return findings
