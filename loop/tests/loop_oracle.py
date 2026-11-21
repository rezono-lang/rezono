"""Evaluate one production rule fragment from live packs/std-loop with a closed set of typed fixture inputs."""

from copy import deepcopy
from functools import cache
from pathlib import Path

STD_LOOP = Path(__file__).resolve().parents[2] / "packs" / "std-loop"
RULES = STD_LOOP / "rules"


@cache
def _loop_rules_doc() -> dict:
    from rezono_compiler import pack

    return pack.read(STD_LOOP).rules


def has_relation(name: str) -> bool:
    return any(rel["name"] == name for rel in _loop_rules_doc().get("relations", ()))


def _column_specs(fields) -> list[dict[str, str]]:
    if isinstance(fields, str):
        return [{"name": column, "type": "string"} for column in fields.split()]
    return [{"name": column, "type": typ} for column, typ in fields]


def evaluate(name, columns, facts):
    from rezono_compiler import batch, rules

    doc = _loop_rules_doc()
    inputs = set(columns)
    rules_by_head: dict[str, list[dict]] = {}
    for rule in doc.get("rules", ()):
        rules_by_head.setdefault(rule["head"]["relation"], []).append(rule)

    needed_rels = {name}
    kept_rules: list[dict] = []
    seen_rels: set[str] = set()
    seen_rule_ids: set[str] = set()
    queue = [name]
    while queue:
        rel_name = queue.pop()
        if rel_name in seen_rels or rel_name in inputs:
            continue
        seen_rels.add(rel_name)
        for rule in rules_by_head.get(rel_name, ()):
            rule_id = rule["id"]
            if rule_id not in seen_rule_ids:
                seen_rule_ids.add(rule_id)
                kept_rules.append(deepcopy(rule))
            for item in rule.get("body", ()):
                dep = item["relation"]
                needed_rels.add(dep)
                if dep not in seen_rels and dep not in inputs:
                    queue.append(dep)
            for agg in rule.get("aggregates", ()):
                dep = agg["relation"]
                needed_rels.add(dep)
                if dep not in seen_rels and dep not in inputs:
                    queue.append(dep)

    by_name = {rel["name"]: rel for rel in doc.get("relations", ())}
    assert name in by_name, f"packs/std-loop does not declare relation {name!r}"

    sliced_relations: list[dict] = []
    for rel_name in sorted(inputs):
        sliced_relations.append({"name": rel_name, "role": "base", "key": _column_specs(columns[rel_name])})
    for rel_name in sorted(needed_rels - inputs):
        assert rel_name in by_name, f"packs/std-loop rule for {name!r} references unknown relation {rel_name!r}"
        sliced_relations.append(deepcopy(by_name[rel_name]))

    # Recompute exact least strata for the sliced fragment after cutting upstream inputs to base (stratum 0).
    rel_map = {rel["name"]: rel for rel in sliced_relations}
    strata = {rel_name: 0 for rel_name in rel_map}
    changed = True
    while changed:
        changed = False
        for rel_name, rel in rel_map.items():
            if rel.get("role") == "functional":
                need = max(strata[rel["domain"]] + 1, 1)
                if strata[rel_name] < need:
                    strata[rel_name] = need
                    changed = True
        for rule in kept_rules:
            head_rel = rule["head"]["relation"]
            is_func = rel_map[head_rel].get("role") == "functional"
            need = max(
                [
                    strata[item["relation"]] + (1 if is_func or item.get("polarity") == "negative" else 0)
                    for item in rule.get("body", ())
                ]
                + [strata[agg["relation"]] + 1 for agg in rule.get("aggregates", ())]
                + ([strata[rel_map[head_rel]["domain"]] + 1] if is_func else [])
                + [1]
            )
            if strata[head_rel] < need:
                strata[head_rel] = need
                changed = True
    for rule in kept_rules:
        rule["stratum"] = str(strata[rule["head"]["relation"]])
        for item in rule.get("body", ()):
            item["stratum"] = str(strata[item["relation"]])
        for agg in rule.get("aggregates", ()):
            agg["stratum"] = str(strata[agg["relation"]])

    sliced = {
        "format": doc["format"],
        "pack": doc["pack"],
        "relations": sliced_relations,
        "rules": kept_rules,
        "invariants": [],
    }
    program = rules.load(sliced)
    connection = batch.connect(program, facts)
    try:
        batch.compute(connection, program)
        return batch.read(connection, program, [name])[name]
    finally:
        connection.close()
