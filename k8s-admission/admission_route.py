"""Route checked admission rules between CEL gates and observation findings."""

from collections.abc import Callable, Mapping

from rezono_compiler import rules


def _dependencies(program: rules.Program, output: str) -> set[str]:
    pending = [output]
    reached: set[str] = set()
    while pending:
        name = pending.pop()
        if name not in reached:
            reached.add(name)
            pending.extend(program.deps(name))
    return reached


def _observe(reason: str, rule: str | None = None) -> dict[str, str | None]:
    return {"route": "observe", "reason": reason, "rule": rule}


def _reads_own_component(program: rules.Program, rule: rules.Rule) -> bool:
    head = rule.head.relation
    reads = {literal.atom.relation for literal in rule.body} | {
        aggregate.atom.relation for aggregate in rule.aggregates
    }
    return any(program.reaches(head, relation) for relation in reads)


def classify(
    program: rules.Program, output: str, request_objects: Mapping[str, str]
) -> dict[str, str | None]:
    """Classify an admission output as a CEL gate or an observation-only rule."""
    if output not in program.relations or program.relations[output].role != "derived":
        raise ValueError(f"{output}: an admission output must be a derived relation")

    relevant = _dependencies(program, output)
    request_inputs = relevant.intersection(request_objects)
    if any(program.relations[name].role != "base" for name in request_inputs):
        raise ValueError("an incoming object must bind base relations")
    if not request_inputs:
        return _observe("no_incoming_object")
    objects = {request_objects[name] for name in request_inputs}
    if not all(objects):
        raise ValueError(f"{output}: admission requires one incoming object")
    if len(objects) > 1:
        return _observe("multiple_objects")

    request = relevant.intersection(request_inputs | program.downstream(request_inputs))
    request_rules = sorted(
        (rule for rule in program.rules.values() if rule.head.relation in request),
        key=lambda rule: rule.id,
    )
    checks: tuple[tuple[str, Callable[[rules.Rule], bool]], ...] = (
        ("recursion", lambda rule: _reads_own_component(program, rule)),
        ("aggregate", lambda rule: bool(rule.aggregates)),
        ("arithmetic", lambda rule: bool(rule.assignments)),
        (
            "open_negation",
            lambda rule: any(
                literal.polarity == "negative"
                and program.relations[literal.atom.relation].world == "open"
                for literal in rule.body
            ),
        ),
    )
    for reason, predicate in checks:
        for rule in request_rules:
            if predicate(rule):
                return _observe(reason, rule.id)
    return {"route": "gate"}
