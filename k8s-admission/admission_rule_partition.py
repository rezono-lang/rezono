"""Separate a checked admission rule's model reads from its incoming object."""

from collections.abc import Mapping

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


def _fragment(program: rules.Program, relations: set[str], parameters: set[str]) -> rules.Program:
    catalogue = {}
    for name in sorted(relations | parameters):
        relation = program.relations[name]
        if name in parameters:
            relation = rules.Relation(name, "base", relation.key, relation.values, world=relation.world)
        catalogue[name] = relation
    definitions = {name: rule for name, rule in program.rules.items() if rule.head.relation in relations}
    fragment = rules.Program(program.pack, catalogue, definitions)
    # A projected parameter is a base relation in this fragment. Recompute its consumers' strata
    # and check the resulting program with the ordinary compiler, preserving the original rules and origins.
    return rules.load(rules.with_strata(rules.to_doc(fragment)))


def partition_rule(
    program: rules.Program, output: str, *, request_objects: Mapping[str, str]
) -> tuple[rules.Program, rules.Program]:
    """Return the model program and its one-object consumer for a derived output.

    A request relation maps to the identity of its bound incoming object. Relations for different
    fields of the same object share that identity. The request program reads each model parameter
    using its complete original key and values. The model retains the corresponding rules and witnesses.
    """
    if output not in program.relations or program.relations[output].role != "derived":
        raise ValueError(f"{output}: an admission output must be a derived relation")

    relevant = _dependencies(program, output)
    request_inputs = relevant.intersection(request_objects)
    if any(program.relations[name].role != "base" for name in request_inputs):
        raise ValueError("an incoming object must bind base relations")
    objects = {request_objects[name] for name in request_inputs}
    if len(objects) != 1 or not all(objects):
        reads = ", ".join(f"{name} ({request_objects[name]})" for name in sorted(request_inputs)) or "none"
        raise ValueError(f"{output}: admission requires one incoming object; it reads {reads}")

    request = relevant.intersection(request_inputs | program.downstream(request_inputs))
    parameters = set().union(*(program.deps(name) for name in request)) - request
    return _fragment(program, relevant - request, set()), _fragment(program, request, parameters)
