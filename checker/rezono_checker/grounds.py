"""Compare the observations behind checked publications."""

from collections import defaultdict
from dataclasses import replace
from functools import cache
import json

from . import access, calc, closure
from .canon import encode_key
from .check import _calc_premise_problem, _check_calc, _check_witness, _load, _rows, _well_formed, aggregate_members
from .evaluate import _holds, _value


Ground = tuple[str, str, str]
Row = tuple[str, str]


def reference(row: dict) -> Row:
    return row["relation"], row["key"]


def encoded(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def terms(atom, theta: dict[str, str]) -> tuple[str, ...]:
    return tuple(theta.get(term, term) for term in atom.terms)


def aggregate_grounds(spec, theta, rows, groups) -> set[Ground]:
    relation = spec.atom.relation
    fixed = [(i, value) for i, value in enumerate(terms(spec.atom, theta)) if spec.atom.terms[i] != "_"]
    members = aggregate_members(spec, fixed, rows(relation, None), groups)
    if not members:
        return {("empty-group", relation, encoded(fixed))}
    return {("read", relation, key) for key, _ in members}


def comparison(condition, theta):
    op = condition.op
    left, right = _value(condition.left, theta), _value(condition.right, theta)
    result = _holds(op, left, right)
    if op in ("gt", "ge"):
        op, left, right = {"gt": "lt", "ge": "le"}[op], right, left
    if op in ("eq", "ne"):
        left, right = sorted((left, right), key=str)
    return op, left, right, result


def selections(rules, rows, groups):
    """Reads and rejection grounds for the comparisons behind an absent derived key."""
    by_head = defaultdict(list)
    for rule in rules.values():
        if rule.conditions or any(body.polarity != "positive" for body in rule.body):
            by_head[rule.head.relation].append(rule)

    @cache
    def table(relation):
        return sorted(rows(relation, None).values(), key=lambda row: row[0])

    @cache
    def candidates(relation):
        by_key = defaultdict(set)
        for rule in by_head[relation]:
            positive = tuple(body for body in rule.body if body.polarity == "positive")
            negative = tuple(body for body in rule.body if body.polarity != "positive")
            # Use the checker's ordinary joins, keeping candidates on both sides of the guards.
            variables, instances = closure.instances(replace(rule, body=positive, conditions=()), table)
            for values in instances:
                theta = dict(zip(variables, values))
                key = encode_key(terms(rule.head, theta))
                reads = {("read", body.atom.relation, encode_key(terms(body.atom, theta))) for body in positive}
                for aggregate in rule.aggregates:
                    reads.update(aggregate_grounds(aggregate, theta, rows, groups))
                exclusions = set()
                for body in negative:
                    absent = encode_key(terms(body.atom, theta))
                    scope = body.atom.relation
                    reason = "read" if absent in rows(scope, None) else "absent"
                    exclusions.add((reason, scope, absent))
                guards = {comparison(condition, theta) for condition in rule.conditions}
                by_key[key].update(reads | exclusions)
                by_key[key].add(("comparison", relation, encoded(
                    [key, sorted(reads), sorted(exclusions), sorted(guards, key=str)]
                )))
        return by_key

    @cache
    def observations(relation, key):
        # A candidate can itself be excluded by an absent result of a lower-stratum choice.
        # Keep every such exclusion's grounds, as well as the directly inspected candidates.
        observed = set()
        pending = [(relation, key)]
        visited = set()
        while pending:
            current = pending.pop()
            if current in visited:
                continue
            visited.add(current)
            direct = candidates(current[0]).get(current[1], ())
            observed.update(direct)
            pending.extend((scope, absent) for kind, scope, absent in direct if kind == "absent")
        return frozenset(observed)

    return observations


def admissible(instances, derived, calculations):
    """Keep each instance which can appear in a well-founded checked proof."""
    by_head = defaultdict(list)
    for witness in instances:
        by_head[reference(witness["conclusion"])].append(witness)
    calc_edges = [
        {"conclusion": witness["conclusion"], "rule_id": witness["rule"],
         "premises": [{"polarity": "positive", "row": premise} for premise in witness.get("premises", ())]}
        for witness in calculations
    ]
    derived = derived | {witness["conclusion"]["relation"] for witness in calculations}
    all_instances = [*instances, *calc_edges]
    chosen = access.select(all_instances, derived)
    dependencies = {row: access._derived_premises(witness, derived) for row, witness in chosen.items()}

    @cache
    def reaches(start, target):
        todo, seen = [start], set()
        while todo:
            row = todo.pop()
            if row == target:
                return True
            if row not in seen:
                seen.add(row)
                todo.extend(dependencies.get(row, ()))
        return False

    for head, alternatives in by_head.items():
        without_head = None
        for witness in alternatives:
            needs = access._derived_premises(witness, derived)
            if head in needs or not needs <= dependencies.keys():
                continue
            if not any(reaches(row, head) for row in needs):
                yield witness
                continue
            if without_head is None:
                without_head = access.select(all_instances, derived,
                                             usable=lambda row: reference(row["conclusion"]) != head)
            if needs <= without_head.keys():
                yield witness


def checked_grounds(witnesses, manifest, rules, read_bytes, *, calc_ir=None, calc_witnesses=()):
    """Union the actual ground reads of every valid instance, by conclusion.

    Publications still choose and check one acyclic proof per conclusion. Alternative
    instances are independently checked against those same complete snapshots.
    """
    findings = []
    snapshots, _ = _load(manifest, read_bytes, None, findings)
    if snapshots is None or findings:
        raise ValueError(f"cannot read the verified complete snapshots: {findings[:1]}")
    rows, groups = _rows(snapshots, findings), {}
    instances = [witness for witness in _well_formed(witnesses, findings) if witness is not None]
    for i, witness in enumerate(instances):
        _check_witness(i, witness, rules, rows, findings, groups)
    if findings:
        raise ValueError(f"checker refused a witness: {findings[0]}")
    derived = {rule.head.relation for rule in rules.values()}
    calculated = []
    if calc_ir is not None or calc_witnesses:
        concluded = {reference(witness["conclusion"]) for witness in instances}
        calculated = _check_calc(list(calc_witnesses), calc_ir, rows, concluded, derived, None, findings)
    if findings:
        raise ValueError(f"checker refused a witness: {findings[0]}")
    calc_views = calc.published_views(calc_ir) if calc_ir is not None else set()
    calc_views.update(relation for rule in rules.values() for relation in rule.calc_inputs)
    calculated_by_row = {reference(witness["conclusion"]): witness for witness in calculated}
    choices = selections(rules, rows, groups)
    result = defaultdict(set)
    for witness in admissible(instances, derived, calculated):
        grounds = result[reference(witness["conclusion"])]
        rule = rules[witness["rule_id"]]
        for premise in witness.get("premises", ()):
            relation, key = reference(premise["row"])
            if premise["polarity"] == "positive":
                problem = _calc_premise_problem((relation, key), rule, calculated_by_row, calc_views)
                if problem:
                    raise ValueError(f"checker refused a witness: {problem} {relation} {key}")
                grounds.add(("read", relation, key))
            else:
                grounds.add(("absent", relation, key))
                grounds.update(choices(relation, key))
        theta = {binding["variable"]: binding["value"] for binding in witness.get("bindings", ())}
        for spec in rule.aggregates:
            grounds.update(aggregate_grounds(spec, theta, rows, groups))
    if calculated:
        result.update(calculation_grounds(calc_ir, calculated, rows))
    if findings:
        raise ValueError(f"checker refused a witness: {findings[0]}")
    return dict(result)


def read_subject(program, table: str, subject: str) -> set[Ground]:
    rows = {("read", table, key) for key, _ in program.of(table, subject)}
    return rows or {("absent-subject", table, encode_key([subject]))}


def read_column(program, table: str, value: str, elements: set[str]) -> set[Ground]:
    return {("read", table, key) for element in elements for key, parts in program.of(table, element)
            if tuple(parts[1:]) == (value,)}


def parameter_grounds(program, name) -> set[Ground]:
    table = program.ir["parameters"]
    choice = program.ir.get("parameter_choice")
    if not choice:
        return read_subject(program, table, name)
    elements = program.column_ids(choice["name"], name)
    found = read_column(program, choice["name"], name, elements)
    found.update(read_subject(program, program.ir["as_of"], "as_of"))
    found.update(ground for element in elements for column in (table, *choice.values())
                 if column != choice["name"] for ground in read_subject(program, column, element))
    if not elements:
        found.add(("absent-name", choice["name"], encode_key([name])))
    found.add(("parameter-choice", table, encode_key([name, program.parameter(name)[1]])))
    return found


def calculation_grounds(ir, witnesses, rows):
    """Reads by checked calculation leaves and the candidates inspected by selection."""
    program = calc.Program(ir, lambda relation: rows(relation, None))
    selected = {}
    for witness in witnesses:
        conclusion = reference(witness["conclusion"])
        subject = calc.subject_of(conclusion[1])
        grounds = {("read", *reference(row)) for row in witness.get("premises", ())}
        grounds.update(read_subject(program, ir["subject_table"], subject))
        kind, name = program.views[conclusion[0]]
        if kind == "rule":
            grounds.update(read_subject(program, ir["as_of"], "as_of"))
            if name not in selected:
                winner, _, _ = program.select(name)
                selected[name] = {("version-candidate", conclusion[0], encoded([
                    version["valid_from"], version["valid_until"], version["known_from"],
                    version["version"], version["id"] == winner,
                ])) for version in (program.versions[v] for v in program.rules[name]["versions"])}
            grounds.update(selected[name])
        for step in witness.get("steps", ()):
            if step["op"] == "fact":
                fid = step["ref"]
                fact = program.facts[fid]
                if fact["reads"] == "input":
                    tables = ir["inputs"]
                    subjects = program.column_ids(tables["subject"], subject)
                    facts = program.column_ids(tables["fact"], fid)
                    elements = subjects & facts
                    grounds.update(read_column(program, tables["subject"], subject, elements))
                    grounds.update(read_column(program, tables["fact"], fid, elements))
                    table = tables["integer" if fact["type"] == "number" else "boolean"]
                    for element in elements:
                        grounds.update(read_subject(program, table, element))
                    if not elements:
                        grounds.add(("absent-input", table, encode_key([subject, fid])))
                else:
                    grounds.update(read_subject(program, fact["table"], subject))
            elif step["op"] == "parameter":
                grounds.update(parameter_grounds(program, step["ref"]))
        yield conclusion, grounds
