"""Turning points by hand (decisions/viewer-slip.md, "Turning points"): pairs of neighbouring stops of a sweep,
each with the role's rows and witnesses at both stops, and the rows that turn between them with their causes.

There is one case for each cause the decision lists, one where a premise turns and the row on it turns with it,
and two where only an amount or a number moves along the same proof, which is no turning point. Every value is
made up for the case; nothing comes from an engine. `between(columns, program, before, after)` in the publisher
must give `turns`, and the checker must accept exactly that list for the same stops.

- `columns`: per relation, what each column holds: reference, enum, boolean, text, number or date.
- `program`: the calculation program (ir/calc.json, rezono.calc/1) where a case needs one, for the constants.
- `before`, `after`: {"rows": {relation: [key]}, "witnesses": [...], "calc_witnesses": [...]}, as a role's
  snapshots and witness set hold them; keys are canonical key text.
- `turns`: [{"relation", "key", "causes"}] in (relation, key) order, the key at the later stop where the row is
  there, else at the earlier one; causes sorted. Only conclusions turn: a row with a witness or a calculation
  witness at one of the two stops. A fact that moves is the cause of a turn, never a turning point itself.
"""

import json


def k(*parts: str) -> str:
    return json.dumps(list(parts), separators=(",", ":"), ensure_ascii=False)


def ref(relation: str, *key: str) -> dict:
    return {"relation": relation, "key": k(*key)}


def premise(relation: str, *key: str, negative: bool = False, stratum: int = 0) -> dict:
    return {"row": ref(relation, *key), "polarity": "negative" if negative else "positive", "stratum": stratum}


def witness(relation: str, key: tuple, rule: str, premises=(), aggregates=(), bindings=()) -> dict:
    out = {"conclusion": ref(relation, *key), "rule_id": rule, "premises": list(premises)}
    if aggregates:
        out["aggregates"] = list(aggregates)
    if bindings:
        out["bindings"] = [{"variable": v, "value": x} for v, x in bindings]
    return out


def aggregate(relation: str, group: tuple, count: int, contributors: str, result: str) -> dict:
    return {"relation": relation, "position": 0, "group_key": k(*group), "count": count,
            "contributors_sha256": contributors * 64, "result": result}


def step(path: str, op: str, value: str, state: str = "known", reason: str = "", **leaf) -> dict:
    return {"path": path, "op": op, "value": value if state == "known" else "", "state": state, "reason": reason,
            **leaf}


def calc(subject: str, value: str, rule: str, steps, version="v1", definition="d", state="known", reason="",
         premises=()) -> dict:
    return {"conclusion": ref(f"calc__{rule}", subject, value if state == "known" else "", state, reason),
            "rule": rule, "version": version, "valid_at": "2026-01-01", "known_at": "2026-01-01",
            "definition": definition, "value": value if state == "known" else "", "state": state, "reason": reason,
            "premises": list(premises), "reads": ["calc__as_of", "measure"], "steps": list(steps)}


def stop(rows: dict, witnesses=(), calc_witnesses=()) -> dict:
    return {"rows": {rel: [k(*key) for key in keys] for rel, keys in rows.items()},
            "witnesses": list(witnesses), "calc_witnesses": list(calc_witnesses)}


def fact(value: str, subject: str = "x1") -> dict:
    return {"measure": [(subject, value)]}


COLUMNS = {
    "measure": ["reference", "number"],
    "rated": ["reference", "enum"],
    "open": ["reference", "boolean"],
    "flagged": ["reference", "number"],
    "exempt": ["reference", "number"],
    "member": ["reference", "reference"],
    "size": ["reference", "number"],
    "busy": ["reference"],
    "step_a": ["reference"],
    "step_b": ["reference"],
    "cycle_b": ["reference"],
    "cycle_c": ["reference"],
    "cycle_z": ["reference"],
    "calc__share": ["reference", "number", "enum", "text"],
    "calc__capped": ["reference", "number", "enum", "text"],
    "calc__bounded": ["reference", "number", "enum", "text"],
}

# A calculation program for the cap: capped = min(measure, 20); share = measure, for the other calculation cases.
PROGRAM = {
    "format": "rezono.calc/1", "pack": "turns", "subject": "thing",
    "rules": [{"rule": "capped", "type": "number", "versions": ["capped@v1"], "view": "calc__capped"},
              {"rule": "share", "type": "number", "versions": ["share@v1", "share@v2"], "view": "calc__share"},
              {"rule": "bounded", "type": "number", "versions": ["bounded@v1", "bounded@v2"],
               "view": "calc__bounded"}],
    "versions": [
        {"id": "capped@v1", "rule": "capped", "version": "v1", "view": "calc__capped__v1",
         "valid_from": "2026-01-01", "valid_until": "2027-01-01", "known_from": "2026-01-01",
         "definitions": [{"name": "d", "before": [], "when": {"boolean": True},
                          "value": {"op": "min", "args": [{"fact": "measure.value"}, {"integer": "20"}]}}]},
        {"id": "share@v1", "rule": "share", "version": "v1", "view": "calc__share__v1",
         "valid_from": "2026-01-01", "valid_until": "2027-01-01", "known_from": "2026-01-01",
         "definitions": [
             {"name": "d", "before": [], "when": {"boolean": True},
              "value": {"op": "if", "args": [{"fact": "open.value"}, {"fact": "measure.value"}, {"integer": "0"}]}},
             {"name": "e", "before": [], "when": {"boolean": True}, "value": {"fact": "measure.value"}}]},
        {"id": "share@v2", "rule": "share", "version": "v2", "view": "calc__share__v2",
         "valid_from": "2026-01-01", "valid_until": "2027-01-01", "known_from": "2026-01-01",
         "definitions": [{"name": "d", "before": [], "when": {"boolean": True}, "value": {"fact": "measure.value"}}]},
        {"id": "bounded@v1", "rule": "bounded", "version": "v1", "view": "calc__bounded",
         "valid_from": "2025-01-01", "valid_until": "2026-01-01", "known_from": "2025-01-01",
         "definitions": [{"name": "d", "before": [], "when": {"boolean": True},
                          "value": {"op": "min", "args": [{"fact": "measure.value"}, {"integer": "10"}]}}]},
        {"id": "bounded@v2", "rule": "bounded", "version": "v2", "view": "calc__bounded__v2",
         "valid_from": "2026-01-01", "valid_until": "2027-01-01", "known_from": "2026-01-01",
         "definitions": [{"name": "d", "before": [], "when": {"boolean": True},
                          "value": {"op": "min", "args": [{"fact": "measure.value"}, {"integer": "20"}]}}]},
    ],
}


def flagged_by(rule: str, value: str) -> dict:
    return stop({**fact(value), "flagged": [("x1", value)]},
                [witness("flagged", ("x1", value), rule, [premise("measure", "x1", value)])])


def share(value: str, steps, **kw) -> dict:
    return stop(fact(value), calc_witnesses=[calc("x1", value, "share", steps, **kw)])


def capped(measure: str, value: str) -> dict:
    return stop(fact(measure), calc_witnesses=[calc("x1", value, "capped", [
        step("d/value", "min", value),
        step("d/value/0", "fact", measure, ref="measure.value", relation="measure")])])


def counted(members: list[str], contributors: str) -> dict:
    n = str(len(members))
    return stop({"member": [(m, "g1") for m in members], "size": [("g1", n)], "busy": [("g1",)]},
                [witness("size", ("g1", n), "size", aggregates=[aggregate("member", ("g1",), len(members),
                                                                           contributors, f"known:{n}")]),
                 witness("busy", ("g1",), "busy", [premise("size", "g1", n, stratum=1)])])


CASES = {
    "rule": {
        "before": flagged_by("flagged_high", "12"), "after": flagged_by("flagged_low", "12"),
        "turns": [{"relation": "flagged", "key": k("x1", "12"), "causes": ["rule"]}]},
    "version": {
        "before": share("5", [step("d/value", "fact", "5", ref="measure.value", relation="measure")]),
        "after": share("5", [step("d/value", "fact", "5", ref="measure.value", relation="measure")], version="v2"),
        "turns": [{"relation": "calc__share", "key": k("x1", "5", "known", ""), "causes": ["version"]}]},
    "definition": {
        "before": share("5", [step("d/value", "fact", "5", ref="measure.value", relation="measure")]),
        "after": share("5", [step("e/value", "fact", "5", ref="measure.value", relation="measure")],
                       definition="e"),
        "turns": [{"relation": "calc__share", "key": k("x1", "5", "known", ""), "causes": ["definition", "path"]}]},
    "path": {
        "before": share("5", [step("d/value", "if", "5"), step("d/value/0", "fact", "true", ref="open.value",
                                                                 relation="open"),
                              step("d/value/1", "fact", "5", ref="measure.value", relation="measure")]),
        "after": share("0", [step("d/value", "if", "0"), step("d/value/0", "fact", "false", ref="open.value",
                                                                relation="open")]),
        "turns": [{"relation": "calc__share", "key": k("x1", "0", "known", ""), "causes": ["path", "value"]}]},
    "count": {
        "before": counted(["m1", "m2"], "a"), "after": counted(["m1", "m2", "m3"], "b"),
        "turns": [{"relation": "busy", "key": k("g1"), "causes": ["contributors", "count"]},
                  {"relation": "size", "key": k("g1", "3"), "causes": ["contributors", "count"]}]},
    "contributors": {
        "before": counted(["m1", "m2"], "a"), "after": counted(["m1", "m3"], "c"),
        "turns": [{"relation": "busy", "key": k("g1"), "causes": ["contributors"]},
                  {"relation": "size", "key": k("g1", "2"), "causes": ["contributors"]}]},
    "state": {
        "before": share("5", [step("d/value", "fact", "5", ref="measure.value", relation="measure")]),
        "after": stop({}, calc_witnesses=[calc("x1", "", "share", [
            step("d/value", "fact", "", "unknown", "fact measure.value is missing", ref="measure.value",
                 relation="measure")], state="unknown", reason="fact measure.value is missing")]),
        "turns": [{"relation": "calc__share", "key": k("x1", "", "unknown", "fact measure.value is missing"),
                   "causes": ["state"]}]},
    "presence": {
        "before": stop(fact("5")), "after": flagged_by("flagged_high", "12"),
        "turns": [{"relation": "flagged", "key": k("x1", "12"), "causes": ["presence"]}]},
    "value": {
        "before": stop({"rated": [("x1", "low")]}, [witness("rated", ("x1", "low"), "rated")]),
        "after": stop({"rated": [("x1", "high")]}, [witness("rated", ("x1", "high"), "rated")]),
        "turns": [{"relation": "rated", "key": k("x1", "high"), "causes": ["value"]}]},
    "cap": {
        "before": capped("15", "15"), "after": capped("25", "20"),
        "turns": [{"relation": "calc__capped", "key": k("x1", "20", "known", ""), "causes": ["cap"]}]},
    # A tie takes the lowest index: min(20, 20) took the measure, as min(15, 20) did, so 15 to 20 is no turn.
    "cap tie": {"before": capped("15", "15"), "after": capped("20", "20"), "turns": []},
    # Only an amount moves along the same proof: no turning point.
    "amount": {"before": flagged_by("flagged_high", "12"), "after": flagged_by("flagged_high", "15"), "turns": []},
    "number": {
        "before": share("5", [step("d/value", "fact", "5", ref="measure.value", relation="measure")]),
        "after": share("7", [step("d/value", "fact", "7", ref="measure.value", relation="measure")]),
        "turns": []},
    # Multiple witnesses in reversed order: deterministic selection chooses the same proof on both stops.
    "witness order": {
        "before": stop(
            {**fact("12"), "flagged": [("x1", "12")]},
            [witness("flagged", ("x1", "12"), "flagged_high", [premise("measure", "x1", "12")]),
             witness("flagged", ("x1", "12"), "flagged_low", [premise("measure", "x1", "12")])],
        ),
        "after": stop(
            {**fact("12"), "flagged": [("x1", "12")]},
            [witness("flagged", ("x1", "12"), "flagged_low", [premise("measure", "x1", "12")]),
             witness("flagged", ("x1", "12"), "flagged_high", [premise("measure", "x1", "12")])],
        ),
        "turns": []},
    # Minimum proof depth beats a lexicographically smaller rule_id even when listed last.
    "witness minimum depth": {
        "before": stop(
            {**fact("12"), "step_a": [("x1",)], "step_b": [("x1",)]},
            [witness("step_a", ("x1",), "rule_mid", [premise("measure", "x1", "12")]),
             witness("step_b", ("x1",), "rule_a", [premise("step_a", "x1", stratum=1)])],
        ),
        "after": stop(
            {**fact("12"), "step_a": [("x1",)], "step_b": [("x1",)]},
            [witness("step_a", ("x1",), "rule_mid", [premise("measure", "x1", "12")]),
             witness("step_b", ("x1",), "rule_z", [premise("measure", "x1", "12")]),
             witness("step_b", ("x1",), "rule_a", [premise("step_a", "x1", stratum=1)])],
        ),
        "turns": [{"relation": "step_b", "key": k("x1"), "causes": ["presence", "rule"]}]},
    # Encoded value state transition on a non-calc number column.
    "encoded number state": {
        "before": flagged_by("flagged_high", "known:10"),
        "after": flagged_by("flagged_high", "unknown"),
        "turns": [{"relation": "flagged", "key": k("x1", "unknown"), "causes": ["state"]}]},
    # Negative premise with same prefix and changed number column: no turning point.
    "negative premise number change": {
        "before": stop(
            {**fact("10"), "flagged": [("x1", "10")]},
            [witness("flagged", ("x1", "10"), "flagged_high",
                     [premise("measure", "x1", "10"), premise("exempt", "x1", "10", negative=True)])],
        ),
        "after": stop(
            {**fact("20"), "flagged": [("x1", "20")]},
            [witness("flagged", ("x1", "20"), "flagged_high",
                     [premise("measure", "x1", "20"), premise("exempt", "x1", "20", negative=True)])],
        ),
        "turns": []},
    # Negative premise with same prefix and changed enum column: value turn.
    "negative premise value change": {
        "before": stop(
            {**fact("12"), "flagged": [("x1", "12")]},
            [witness("flagged", ("x1", "12"), "flagged_high",
                     [premise("measure", "x1", "12"), premise("rated", "x1", "low", negative=True)])],
        ),
        "after": stop(
            {**fact("12"), "flagged": [("x1", "12")]},
            [witness("flagged", ("x1", "12"), "flagged_high",
                     [premise("measure", "x1", "12"), premise("rated", "x1", "high", negative=True)])],
        ),
        "turns": [{"relation": "flagged", "key": k("x1", "12"), "causes": ["value"]}]},
    # Aggregate with changed group_key on the same (relation, position) slot: contributors turn.
    "aggregate group key change": {
        "before": stop(
            {"busy": [("x1",)]},
            [witness("busy", ("x1",), "busy", aggregates=[aggregate("member", ("g1",), 2, "a", "known:2")])],
        ),
        "after": stop(
            {"busy": [("x1",)]},
            [witness("busy", ("x1",), "busy", aggregates=[aggregate("member", ("g2",), 2, "b", "known:2")])],
        ),
        "turns": [{"relation": "busy", "key": k("x1"), "causes": ["contributors"]}]},
    # Paired row switching from fact (no witness) to conclusion (with witness): rule turn.
    "fact to conclusion": {
        "before": stop({**fact("12"), "flagged": [("x1", "12")]}),
        "after": flagged_by("flagged_high", "12"),
        "turns": [{"relation": "flagged", "key": k("x1", "12"), "causes": ["rule"]}]},
    # Aggregate result without "known:" prefix: plain known numbers do not cause a state turn.
    "aggregate plain result": {
        "before": stop(
            {"member": [("m1", "g1"), ("m2", "g1")], "size": [("g1", "2")], "busy": [("g1",)]},
            [witness("size", ("g1", "2"), "size", aggregates=[aggregate("member", ("g1",), 2, "a", "2")]),
             witness("busy", ("g1",), "busy", [premise("size", "g1", "2", stratum=1)])],
        ),
        "after": stop(
            {"member": [("m1", "g1"), ("m2", "g1"), ("m3", "g1")], "size": [("g1", "3")], "busy": [("g1",)]},
            [witness("size", ("g1", "3"), "size", aggregates=[aggregate("member", ("g1",), 3, "b", "3")]),
             witness("busy", ("g1",), "busy", [premise("size", "g1", "3", stratum=1)])],
        ),
        "turns": [{"relation": "busy", "key": k("g1"), "causes": ["contributors", "count"]},
                  {"relation": "size", "key": k("g1", "3"), "causes": ["contributors", "count"]}]},
    # Mutually recursive witness cycle: cycle_b <-> cycle_z with turning cycle_c must not drop cycle_z.
    "mutually recursive cycle": {
        "before": stop(
            {"cycle_b": [("x1",)], "cycle_c": [("x1",)], "cycle_z": [("x1",)]},
            [witness("cycle_c", ("x1",), "rule_c1"),
             witness("cycle_b", ("x1",), "rule_b", [premise("cycle_z", "x1"), premise("cycle_c", "x1")]),
             witness("cycle_z", ("x1",), "rule_z", [premise("cycle_b", "x1")])],
        ),
        "after": stop(
            {"cycle_b": [("x1",)], "cycle_c": [("x1",)], "cycle_z": [("x1",)]},
            [witness("cycle_c", ("x1",), "rule_c2"),
             witness("cycle_b", ("x1",), "rule_b", [premise("cycle_z", "x1"), premise("cycle_c", "x1")]),
             witness("cycle_z", ("x1",), "rule_z", [premise("cycle_b", "x1")])],
        ),
        "turns": [{"relation": "cycle_b", "key": k("x1"), "causes": ["rule"]},
                  {"relation": "cycle_c", "key": k("x1"), "causes": ["rule"]},
                  {"relation": "cycle_z", "key": k("x1"), "causes": ["rule"]}]},
    # Calculation version lookup matches (rule, version) before falling back to version view name.
    "version lookup before view": {
        "before": stop(
            fact("15"),
            calc_witnesses=[calc("x1", "15", "bounded", [
                step("d/value", "min", "15"),
                step("d/value/0", "fact", "15", ref="measure.value", relation="measure")], version="v2")],
        ),
        "after": stop(
            fact("25"),
            calc_witnesses=[calc("x1", "20", "bounded", [
                step("d/value", "min", "20"),
                step("d/value/0", "fact", "25", ref="measure.value", relation="measure")], version="v2")],
        ),
        "turns": [{"relation": "calc__bounded", "key": k("x1", "20", "known", ""), "causes": ["cap"]}]},
}
