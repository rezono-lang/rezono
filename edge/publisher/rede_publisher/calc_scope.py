"""The calculation program as the publisher reads it (ir/calc.json; decisions W12 and O8).

The filter decides which calculated rows and witnesses a role gets (access.calc_visible). The checker checks
that decision with its own reading of the same program (rede_checker.calc, rede_checker.access). The two
readings share no code: a mistake in one is then a difference the check reports, not an agreement. So nothing
here imports the checker, and tests/test_checker_boundary.py holds both that and that the two readings agree
on every calculation program in the repository.
"""

from __future__ import annotations

import json


def _nodes(version: dict):
    """Every node of the expressions of a version: the condition and the value of each definition."""
    todo = [e for d in version["definitions"] for e in (d["when"], d["value"])]
    while todo:
        node = todo.pop()
        yield node
        todo.extend(node.get("args") or ())


def published_views(ir: dict) -> set[str]:
    """The calculation views a publication holds: the view of every rule, and the view of every version that
    some definition names as `rule@version`."""
    versions = ir.get("versions", ())
    view = {v["id"]: v["view"] for v in versions}
    named = {n["rule"] for v in versions for n in _nodes(v) if "@" in (n.get("rule") or "")}
    return {r["view"] for r in ir.get("rules", ())} | {view[name] for name in named}


def subject_of(key) -> str | None:
    """The subject of a calculated row, from its key text (subject, value, state, reason); None for any other key."""
    try:
        parts = json.loads(key)
    except (TypeError, ValueError):
        return None
    if isinstance(parts, list) and len(parts) == 4 and all(isinstance(p, str) for p in parts):
        return parts[0]
    return None


def version_of(ir: dict, witness: dict) -> str | None:
    """The version a calculation witness evaluated: the version whose own view it concludes, or else the one the
    witness names as chosen for its rule (none: no version was chosen)."""
    own = {v["view"]: v["id"] for v in ir.get("versions", ())}
    relation = witness["conclusion"]["relation"]
    if relation in own:
        return own[relation]
    return f"{witness['rule']}@{witness['version']}" if witness.get("version") else None


def reads(ir: dict, version: str | None) -> set[str]:
    """Every relation the evaluation of a version reads, also where it reads an absence: a role sees the result
    only if it reads each of them in full (O8). Without a version, only the evaluation date."""
    tables = {ir["as_of"]}
    if version is None:
        return tables
    evaluated = {v["id"]: v for v in ir.get("versions", ())}[version]
    facts = {f["id"]: f for f in ir.get("facts", ())}
    for node in _nodes(evaluated):
        if "fact" in node:
            fact = facts[node["fact"]]
            if fact["reads"] == "input":  # an input is a row of the input kind: its subject, its name and its value
                inputs = ir["inputs"]
                value = inputs["integer" if fact["type"] == "number" else "boolean"]
                tables |= {inputs["subject"], inputs["fact"], value}
            else:
                tables.add(fact["table"])
        elif "parameter" in node:
            tables |= {ir["parameters"], *ir.get("parameter_choice", {}).values()}
    return tables


def view_sources(ir: dict) -> dict[str, frozenset[str] | None]:
    """What every published view rests on, besides its subject kind (O8, RV-S26): each relation that any
    version of its rule reads, absences included, and each calculation view such a version takes as a premise.
    The view of a version rests on that version alone. None where the program does not account for the view
    (a rule without its versions, a version or a premise the program does not hold): nothing is known of it."""
    versions = {v["id"]: v for v in ir.get("versions", ())}
    rules = {r["rule"]: r["view"] for r in ir.get("rules", ()) if "rule" in r}

    def of(ids) -> frozenset[str] | None:
        if ids is None or any(i not in versions for i in ids):
            return None
        found = reads(ir, None)
        for vid in sorted(ids):
            found |= reads(ir, vid)
            for name in sorted({n["rule"] for n in _nodes(versions[vid]) if n.get("rule")}):
                view = versions[name]["view"] if name in versions else rules.get(name)
                if view is None:
                    return None
                found.add(view)
        return frozenset(found)

    out = {r["view"]: of(r.get("versions")) for r in ir.get("rules", ())}
    own = {v["view"]: v["id"] for v in versions.values()}
    for view in sorted(published_views(ir) - set(out)):
        out[view] = of([own[view]])
    return out
