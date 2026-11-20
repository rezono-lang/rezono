"""Evaluate an observation-only admission rule on observed objects: decisions/k8s-admission-translator.md."""

from collections.abc import Iterable, Mapping, Sequence

from rezono_compiler import batch, rules


def _canonical_row(row) -> tuple[str, ...]:
    return tuple(str(value) for value in row)


def _is_sequence(value: object) -> bool:
    return isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray))


def _normalize_observation(obs: object) -> tuple[dict, dict[str, list[tuple]], list]:
    if not isinstance(obs, Mapping):
        raise ValueError("each observation must be a mapping")
    missing_keys = [key for key in ("object", "rows", "missing") if key not in obs]
    if missing_keys:
        joined = ", ".join(repr(key) for key in missing_keys)
        raise ValueError(f"observation is missing required key(s): {joined}")

    raw_object = obs["object"]
    if not isinstance(raw_object, Mapping):
        raise ValueError("observation 'object' must be a mapping")
    missing_object_keys = [key for key in ("kind", "namespace", "name") if key not in raw_object]
    if missing_object_keys:
        joined = ", ".join(repr(key) for key in missing_object_keys)
        raise ValueError(f"observation 'object' is missing required key(s): {joined}")
    for key in ("kind", "namespace", "name"):
        if not isinstance(raw_object[key], str):
            raise ValueError(f"observation 'object' {key!r} must be a string")

    raw_rows = obs["rows"]
    if not isinstance(raw_rows, Mapping):
        raise ValueError("observation 'rows' must be a mapping")
    rows_by_relation: dict[str, list[tuple]] = {}
    for relation, relation_rows in raw_rows.items():
        if not isinstance(relation, str):
            raise ValueError("observation 'rows' keys must be relation names")
        if not _is_sequence(relation_rows):
            raise ValueError(f"observation rows for {relation!r} must be a sequence")
        normalized_rows: list[tuple] = []
        for row in relation_rows:
            if not _is_sequence(row):
                raise ValueError(f"observation row for {relation!r} must be a sequence")
            normalized_rows.append(tuple(row))
        rows_by_relation[relation] = normalized_rows

    raw_missing = obs["missing"]
    if not _is_sequence(raw_missing):
        raise ValueError("observation 'missing' must be a sequence")

    return dict(raw_object), rows_by_relation, list(raw_missing)


def _sort_key(finding: dict) -> tuple:
    obj = finding["object"]
    return (
        obj["kind"],
        obj["namespace"],
        obj["name"],
        finding["reason"],
        finding.get("relation", ""),
        finding.get("row", []),
    )


def observed_findings(
    program: rules.Program,
    output: str,
    model_rows: Mapping[str, Iterable],
    observations: Iterable[Mapping],
    rule: str,
    digest: str,
) -> list[dict]:
    """Evaluate `output` once over `model_rows` and all `observations`, returning sorted findings."""
    if output not in program.relations or program.relations[output].role != "derived":
        raise ValueError(f"{output}: an admission output must be a derived relation")

    normalized = [_normalize_observation(obs) for obs in observations]
    combined: dict[str, list[tuple]] = {}
    seen: dict[str, set[tuple[str, ...]]] = {}

    def add_rows(relation: str, rows: Iterable) -> None:
        bucket = combined.setdefault(relation, [])
        present = seen.setdefault(relation, set())
        for row in rows:
            key = _canonical_row(row)
            if key not in present:
                present.add(key)
                bucket.append(tuple(row))

    for relation, rows in model_rows.items():
        add_rows(relation, rows)
    for _, rows_by_relation, _ in normalized:
        for relation, rows in rows_by_relation.items():
            add_rows(relation, rows)

    with batch.connect(program, combined, threads=1) as connection:
        batch.compute(connection, program)
        admitted = batch.read(connection, program, [output])[output]

    findings: list[dict] = []
    for obj, rows_by_relation, missing in normalized:
        if missing:
            findings.append({
                "rule": rule,
                "digest": digest,
                "object": dict(obj),
                "reason": "missing_input",
                "places": list(missing),
            })
        for relation, rows in rows_by_relation.items():
            for row in rows:
                if _canonical_row(row) not in admitted:
                    findings.append({
                        "rule": rule,
                        "digest": digest,
                        "object": dict(obj),
                        "reason": "not_admitted",
                        "relation": relation,
                        "row": list(row),
                    })

    findings.sort(key=_sort_key)
    return findings
