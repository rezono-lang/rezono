"""Evaluate an observation-only admission rule on observed objects: decisions/k8s-admission-translator.md."""

from collections.abc import Iterable, Mapping

from rezono_compiler import batch, rules


def _canonical_row(row) -> tuple[str, ...]:
    return tuple(str(value) for value in row)


def _sort_key(finding: dict) -> tuple:
    obj = finding["object"]
    return (
        obj["kind"],
        obj.get("namespace") or "",
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

    observation_list = list(observations)
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
    for obs in observation_list:
        for relation, rows in obs.get("rows", {}).items():
            add_rows(relation, rows)

    with batch.connect(program, combined, threads=1) as connection:
        batch.compute(connection, program)
        admitted = batch.read(connection, program, [output])[output]

    findings: list[dict] = []
    for obs in observation_list:
        obj = dict(obs["object"])
        missing = list(obs.get("missing", ()))
        if missing:
            findings.append({
                "rule": rule,
                "digest": digest,
                "object": dict(obj),
                "reason": "missing_input",
                "places": missing,
            })
        for relation, rows in obs.get("rows", {}).items():
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
