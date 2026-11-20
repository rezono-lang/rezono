"""Compose the admission translator blocks into a ValidatingAdmissionPolicy.

See decisions/k8s-admission-translator.md, "Order".
"""

from __future__ import annotations

from collections.abc import Mapping
import itertools
import re
from typing import Any

from rezono_compiler import rules
from rezono_compiler.rules import Condition, is_var

from admission_route import classify
from admission_rule_partition import partition_rule
from cel_atom import bind, exists, negative
from cel_condition import condition as cel_condition
from cel_literal import literal
from cel_parameter_tables import parameter_tables
from cel_port_range import covers
from cel_request import missing, quantify
from parameter_check import check_parameters
from policy_shell import policy_shell
from request_check import check_request

_BINDING_FORMAT = "rezono.admission-binding/1"
_REQUIRED_KEYS = ("format", "rule", "output", "match", "request", "parameters")
_CEL_IDENT = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")
_NAMESPACE_EXPR = "request.namespace"
_MAX_REQUEST_BRANCH_KEYS = 8


def _validate_binding(binding: Any, program: rules.Program) -> None:
    if not isinstance(binding, Mapping):
        raise ValueError("admission binding must be a mapping")
    absent = [key for key in _REQUIRED_KEYS if key not in binding]
    if absent:
        raise ValueError(f"admission binding is missing required key(s): {', '.join(absent)}")
    if binding["format"] != _BINDING_FORMAT:
        raise ValueError(f"unsupported admission binding format: {binding['format']!r}")
    if not binding["request"]:
        raise ValueError("admission binding must define at least one request source")

    problems = check_request(binding, program) + check_parameters(binding, program)
    if problems:
        summary = "; ".join(f"{place}: {code}" for code, place in problems)
        raise ValueError(f"invalid admission binding: {summary}")


def _request_root_expression(binding: Mapping[str, Any]) -> str:
    """Project referenced `request` paths into a CEL map compatible with both oracles.

    In the standalone cel-go oracle `request` is map(string, dyn), whereas in Kubernetes
    ValidatingAdmissionPolicy `request` is the typed kubernetes.AdmissionRequest struct
    which supports field selection and `has(request.<field>)` but not map indexing.
    """
    tree: dict[str, Any] = {}
    for source in binding["request"]:
        paths = [iterator["path"] for iterator in source["each"]]
        for col in source["columns"].values():
            paths.append(col["path"])
            if "end" in col:
                paths.append(col["end"])
        for path in paths:
            if path and path[0] == "request":
                node = tree
                for key in path[1:]:
                    if _CEL_IDENT.fullmatch(key) is None:
                        return "request"
                    node = node.setdefault(key, {})

    if not tree:
        return "{}"

    def render_tree(prefix: str, node: dict[str, Any]) -> str:
        if not node:
            return f"dyn({prefix})"
        keys = sorted(node)
        if len(keys) > _MAX_REQUEST_BRANCH_KEYS:
            raise ValueError(
                f"cannot project more than {_MAX_REQUEST_BRANCH_KEYS} guarded request fields at {prefix}"
            )

        def branch(index: int, chosen: list[str]) -> str:
            if index == len(keys):
                entries = ", ".join(
                    f"{literal(key, 'string')}: {render_tree(f'{prefix}.{key}', node[key])}"
                    for key in chosen
                )
                return f"{{{entries}}}"
            key = keys[index]
            present = branch(index + 1, [*chosen, key])
            absent = branch(index + 1, chosen)
            return f"(has({prefix}.{key}) ? {present} : {absent})"

        return branch(0, [])

    return render_tree("request", tree)


def _constants_equal(left: str, right: str, col_type: str) -> bool:
    if col_type == "integer":
        return int(left) == int(right)
    return left == right


def _rename_term(term: str, mapping: Mapping[str, str]) -> str:
    return mapping.get(term, term) if is_var(term) else term


def _apply_substitution(
    atom: rules.Atom, mapping: Mapping[str, str]
) -> rules.Atom:
    return rules.Atom(atom.relation, tuple(_rename_term(t, mapping) for t in atom.terms))


def _unfold_relation(
    request_program: rules.Program,
    relation: str,
    base_relations: set[str],
    counter: itertools.count,
) -> list[tuple[tuple[str, ...], list[rules.Literal], list[Condition]]]:
    """Return flat rules `(head_terms, body_literals, conditions)` for `relation`.

    Every positive literal in each returned rule references a base relation of `request_program`.
    """
    derived_set = {name for name, rel in request_program.relations.items() if rel.role == "derived"}
    result: list[tuple[tuple[str, ...], list[rules.Literal], list[Condition]]] = []

    def expand_rule(
        head_terms: tuple[str, ...],
        body: list[rules.Literal],
        conditions: list[Condition],
    ) -> list[tuple[tuple[str, ...], list[rules.Literal], list[Condition]]]:
        for idx, lit in enumerate(body):
            if lit.polarity == "positive" and lit.atom.relation in derived_set:
                target_rel = request_program.relations[lit.atom.relation]
                expanded: list[tuple[tuple[str, ...], list[rules.Literal], list[Condition]]] = []
                for sub_rule in sorted(request_program.rules_for(lit.atom.relation), key=lambda r: r.id):
                    prefix = f"?__u{next(counter)}_"
                    fresh = {var: prefix + var[1:] for var in sub_rule.variables}
                    sub_head = tuple(_rename_term(t, fresh) for t in sub_rule.head.terms)
                    sub_body = [
                        rules.Literal(_apply_substitution(b.atom, fresh), b.polarity, b.stratum)
                        for b in sub_rule.body
                    ]
                    sub_conds = [
                        Condition(c.op, _rename_term(c.left, fresh), _rename_term(c.right, fresh), c.compare_as)
                        for c in sub_rule.conditions
                    ]

                    unify_sub: dict[str, str] = {}
                    extra_conds: list[Condition] = []
                    possible = True
                    for call_term, head_term, col in zip(lit.atom.terms, sub_head, target_rel.key):
                        resolved_head = _rename_term(head_term, unify_sub)
                        if is_var(resolved_head) and is_var(call_term):
                            if resolved_head != call_term:
                                if resolved_head in unify_sub.values():
                                    extra_conds.append(Condition("eq", resolved_head, call_term))
                                else:
                                    unify_sub[resolved_head] = call_term
                        elif is_var(resolved_head):
                            extra_conds.append(Condition("eq", resolved_head, call_term))
                        elif is_var(call_term):
                            extra_conds.append(Condition("eq", call_term, resolved_head))
                        else:
                            if not _constants_equal(resolved_head, call_term, col.type):
                                possible = False
                                break
                    if not possible:
                        continue

                    new_sub_body = [
                        rules.Literal(_apply_substitution(b.atom, unify_sub), b.polarity, b.stratum)
                        for b in sub_body
                    ]
                    new_sub_conds = [
                        Condition(
                            c.op,
                            _rename_term(c.left, unify_sub),
                            _rename_term(c.right, unify_sub),
                            c.compare_as,
                        )
                        for c in (*sub_conds, *extra_conds)
                    ]
                    merged_body = [*body[:idx], *new_sub_body, *body[idx + 1 :]]
                    merged_conds = [*conditions, *new_sub_conds]
                    expanded.extend(expand_rule(head_terms, merged_body, merged_conds))
                return expanded
        return [(head_terms, body, conditions)]

    for rule in sorted(request_program.rules_for(relation), key=lambda r: r.id):
        result.extend(expand_rule(rule.head.terms, list(rule.body), list(rule.conditions)))
    return result


def _infer_var_types(
    request_program: rules.Program,
    head_rel: str,
    head_terms: tuple[str, ...],
    body: list[rules.Literal],
) -> dict[str, str]:
    types: dict[str, str] = {}
    for term, col in zip(head_terms, request_program.relations[head_rel].key):
        if is_var(term):
            types[term] = col.type
    for lit in body:
        if lit.polarity == "positive":
            rel = request_program.relations[lit.atom.relation]
            for term, col in zip(lit.atom.terms, rel.key):
                if is_var(term):
                    types[term] = col.type
    return types


def _unify_terms(
    terms: tuple[str, ...],
    columns: tuple[rules.Column, ...],
    values: tuple[Any, ...],
    env: dict[str, str],
    ranges: dict[str, tuple[str, str]],
    conditions: list[str],
) -> None:
    for term, col, value in zip(terms, columns, values):
        if isinstance(value, dict):
            start, end = value["start"], value["end"]
            if is_var(term):
                if term in ranges:
                    if ranges[term] != (start, end):
                        raise ValueError(f"cannot unify distinct port ranges for {term}")
                elif term in env:
                    conditions.append(f"({start} == {end})")
                    conditions.append(f"({start} == {env[term]})")
                else:
                    ranges[term] = (start, end)
            else:
                lit = literal(term, col.type)
                conditions.append(f"({start} == {lit})")
                conditions.append(f"({end} == {lit})")
        else:
            if is_var(term):
                if term in ranges:
                    start, end = ranges.pop(term)
                    conditions.append(f"({start} == {end})")
                    conditions.append(f"({start} == {value})")
                    env[term] = value
                elif term in env:
                    if env[term] != value:
                        conditions.append(f"({value} == {env[term]})")
                else:
                    env[term] = value
            else:
                conditions.append(f"({value} == {literal(term, col.type)})")


def _join_and(parts: list[str]) -> str:
    filtered = [part for part in parts if part and part != "true"]
    if not filtered:
        return "true"
    return " && ".join(filtered)


def _join_or(parts: list[str]) -> str:
    filtered = [part for part in parts if part and part != "false"]
    if not filtered:
        return "false"
    if len(filtered) == 1:
        return filtered[0]
    return "(" + " || ".join(f"({part})" for part in filtered) + ")"


def _atom_vars(atom: rules.Atom) -> set[str]:
    return {term for term in atom.terms if is_var(term)}


def _cond_vars(cond: Condition) -> set[str]:
    return {term for term in (cond.left, cond.right) if is_var(term)}


def _compile_range_atom(
    atom: rules.Atom,
    table: dict[str, Any],
    env: dict[str, str],
    ranges: dict[str, tuple[str, str]],
    types: dict[str, str],
    var: str,
) -> tuple[str, str]:
    """Compile a positive parameter atom covering one port-range variable with `cel_port_range.covers`."""
    columns = table["columns"]
    column_types = table["types"]
    if len(atom.terms) != len(columns):
        raise ValueError(f"atom {atom.relation} arity {len(atom.terms)} does not match table {len(columns)}")

    range_col: str | None = None
    range_var: str | None = None
    atom_conds: list[str] = []

    for (col_name, template), term in zip(columns.items(), atom.terms):
        expr = template.replace("{e}", var)
        col_type = column_types[col_name]
        if is_var(term) and term in ranges:
            if range_col is not None:
                raise ValueError(f"atom {atom.relation} cannot cover multiple port-range columns")
            if col_type != "integer":
                raise ValueError(f"port-range column {atom.relation}.{col_name} must be integer")
            range_col = col_name
            range_var = term
        elif is_var(term):
            if term not in env:
                raise ValueError(
                    f"port-range atom {atom.relation} has unbound variable {term}; "
                    "range coverage requires every non-range column to be uniquely constrained"
                )
            if term in types and types[term] != col_type:
                raise ValueError(f"variable {term} has type {types[term]}, expected {col_type}")
            atom_conds.append(f"({expr} == {env[term]})")
        else:
            atom_conds.append(f"({expr} == {literal(term, col_type)})")

    if range_col is None or range_var is None:
        raise ValueError(f"atom {atom.relation} does not bind any port-range variable")

    start, end = ranges[range_var]
    return range_var, covers(table, var, atom_conds, range_col, start, end)


def _value_key(value: Any) -> tuple[str, ...]:
    if isinstance(value, dict):
        return ("range", value["start"], value["end"])
    return ("scalar", value)


def _same_req_matches_current_row(
    head_terms: tuple[str, ...],
    head_columns: tuple[rules.Column, ...],
    target_values: tuple[Any, ...],
    req_terms: tuple[str, ...],
    req_columns: tuple[rules.Column, ...],
    current_values: tuple[Any, ...],
    conds: list[Condition],
    types: Mapping[str, str],
) -> bool:
    """Return True only when head unification and rule equalities force `req_terms` to equal `current_values`.

    Single-row CEL translation only knows that `current_values` belongs to `current_rel`; it cannot
    quantify over other rows of `current_rel`. Unifying a `same_req` literal with `current_values`
    is sound only when every valuation satisfying the head and rule conditions must already assign
    each column of `req_terms` to the corresponding column of `current_values`.
    """
    parent: dict[tuple[Any, ...], tuple[Any, ...]] = {}

    def find(node: tuple[Any, ...]) -> tuple[Any, ...]:
        root = parent.setdefault(node, node)
        while parent[root] != root:
            root = parent[root]
        while node != root:
            nxt = parent[node]
            parent[node] = root
            node = nxt
        return root

    def union(left: tuple[Any, ...], right: tuple[Any, ...]) -> None:
        lroot, rroot = find(left), find(right)
        if lroot != rroot:
            parent[lroot] = rroot

    for term, col, value in zip(head_terms, head_columns, target_values):
        term_node: tuple[Any, ...] = ("var", term) if is_var(term) else ("lit", literal(term, col.type))
        union(term_node, ("val", _value_key(value)))

    for cond in conds:
        if cond.op != "eq" or getattr(cond, "compare_as", None) is not None:
            continue
        if is_var(cond.left) and is_var(cond.right):
            union(("var", cond.left), ("var", cond.right))
        elif is_var(cond.left) and cond.left in types:
            union(("var", cond.left), ("lit", literal(cond.right, types[cond.left])))
        elif is_var(cond.right) and cond.right in types:
            union(("var", cond.right), ("lit", literal(cond.left, types[cond.right])))

    for term, col, value in zip(req_terms, req_columns, current_values):
        term_node = ("var", term) if is_var(term) else ("lit", literal(term, col.type))
        val_node = ("val", _value_key(value))
        if find(term_node) != find(val_node):
            return False
    return True


def _compile_derived(
    request_program: rules.Program,
    rel_name: str,
    target_values: tuple[Any, ...],
    current_rel: str,
    current_values: tuple[Any, ...],
    request_set: set[str],
    tables: dict[str, dict[str, Any]],
    unfolded_cache: dict[str, list[tuple[tuple[str, ...], list[rules.Literal], list[Condition]]]],
    var_counter: itertools.count,
) -> str:
    derived_set = {name for name, rel in request_program.relations.items() if rel.role == "derived"}
    rel_obj = request_program.relations[rel_name]
    flat_rules = unfolded_cache[rel_name]

    def compile_tail(
        pos_params: list[rules.Atom],
        neg_lits: list[rules.Literal],
        pending_conds: list[Condition],
        env: dict[str, str],
        ranges: dict[str, tuple[str, str]],
        types: dict[str, str],
    ) -> str:
        ready: list[str] = []
        remaining_conds: list[Condition] = []
        for cond in pending_conds:
            cvars = _cond_vars(cond)
            if cvars & ranges.keys():
                raise ValueError(f"condition over port-range variable is not supported: {cond}")
            if cvars <= env.keys():
                ready.append(cel_condition(cond, env, types))
            else:
                remaining_conds.append(cond)

        remaining_negs: list[rules.Literal] = []
        for lit in neg_lits:
            nvars = _atom_vars(lit.atom)
            if nvars & ranges.keys():
                raise ValueError(f"negated atom over port-range variable is not supported: {lit.atom.relation}")
            if nvars <= env.keys():
                if lit.atom.relation in tables:
                    var = f"e{next(var_counter)}"
                    ready.append(negative(lit.atom, tables[lit.atom.relation], env, types, var))
                elif lit.atom.relation in derived_set:
                    neg_rel = request_program.relations[lit.atom.relation]
                    neg_target = tuple(
                        env[t] if is_var(t) else literal(t, col.type)
                        for t, col in zip(lit.atom.terms, neg_rel.key)
                    )
                    sub = _compile_derived(
                        request_program,
                        lit.atom.relation,
                        neg_target,
                        current_rel,
                        current_values,
                        request_set,
                        tables,
                        unfolded_cache,
                        var_counter,
                    )
                    ready.append(f"!({sub})")
                else:
                    raise ValueError(f"unsupported negated relation in request fragment: {lit.atom.relation}")
            else:
                remaining_negs.append(lit)

        if pos_params:
            # Prefer non-range atoms first so they bind any scalar variables before range coverage runs.
            non_range_idx = next(
                (i for i, atom in enumerate(pos_params) if not (_atom_vars(atom) & ranges.keys())),
                None,
            )
            if non_range_idx is not None:
                atom = pos_params[non_range_idx]
                rest_atoms = [*pos_params[:non_range_idx], *pos_params[non_range_idx + 1 :]]
                table = tables[atom.relation]
                var = f"e{next(var_counter)}"
                atom_conds, env2 = bind(atom, table, env, types, var)
                rest_expr = compile_tail(rest_atoms, remaining_negs, remaining_conds, env2, ranges, types)
                ready.append(exists(table, var, atom_conds, None if rest_expr == "true" else rest_expr))
                return _join_and(ready)

            # Remaining positive atoms all touch at least one port-range variable.
            atom = pos_params[0]
            rest_atoms = pos_params[1:]
            var = f"e{next(var_counter)}"
            covered_var, cover_expr = _compile_range_atom(atom, tables[atom.relation], env, ranges, types, var)
            if any(covered_var in _atom_vars(other) for other in rest_atoms):
                raise ValueError(
                    f"port-range variable {covered_var} cannot appear in multiple parameter atoms"
                )
            next_ranges = {k: v for k, v in ranges.items() if k != covered_var}
            ready.append(cover_expr)
            rest_expr = compile_tail(rest_atoms, remaining_negs, remaining_conds, env, next_ranges, types)
            if rest_expr != "true":
                ready.append(rest_expr)
            return _join_and(ready)

        if remaining_conds:
            raise ValueError(f"unbound condition variable(s): {remaining_conds}")
        if remaining_negs:
            raise ValueError(f"unbound negated literal(s): {[lit.atom.relation for lit in remaining_negs]}")
        if ranges:
            raise ValueError(f"unconstrained port-range variable(s): {sorted(ranges)}")
        return _join_and(ready)

    branches: list[str] = []
    for head_terms, body, conds in flat_rules:
        types = _infer_var_types(request_program, rel_name, head_terms, body)
        env: dict[str, str] = {}
        ranges: dict[str, tuple[str, str]] = {}
        pre_conds: list[str] = []

        _unify_terms(head_terms, rel_obj.key, target_values, env, ranges, pre_conds)

        pos_req = [lit for lit in body if lit.polarity == "positive" and lit.atom.relation in request_set]
        pos_params = [lit.atom for lit in body if lit.polarity == "positive" and lit.atom.relation in tables]
        neg_lits = [lit for lit in body if lit.polarity == "negative"]

        unknown_pos = [
            lit.atom.relation
            for lit in body
            if lit.polarity == "positive" and lit.atom.relation not in request_set and lit.atom.relation not in tables
        ]
        if unknown_pos:
            raise ValueError(f"unbound relation(s) in request fragment: {', '.join(sorted(set(unknown_pos)))}")

        other_req = [lit for lit in pos_req if lit.atom.relation != current_rel]
        same_req = [lit for lit in pos_req if lit.atom.relation == current_rel]
        if other_req:
            if same_req:
                raise ValueError(
                    f"cannot join distinct request relations in one rule: "
                    f"{current_rel} and {other_req[0].atom.relation}"
                )
            raise ValueError(
                f"cannot compile rule for {rel_name} referencing request relation "
                f"{other_req[0].atom.relation} while checking {current_rel}"
            )
        if len(same_req) > 1:
            raise ValueError(
                f"cannot self-join request relation {current_rel} in rule for {rel_name}"
            )

        if same_req:
            req_lit = same_req[0]
            req_rel = request_program.relations[current_rel]
            if not _same_req_matches_current_row(
                head_terms,
                rel_obj.key,
                target_values,
                req_lit.atom.terms,
                req_rel.key,
                current_values,
                conds,
                types,
            ):
                raise ValueError(
                    f"cannot quantify over other rows of request relation {current_rel} "
                    f"in rule for {rel_name}"
                )
            _unify_terms(
                req_lit.atom.terms,
                req_rel.key,
                current_values,
                env,
                ranges,
                pre_conds,
            )

        tail = compile_tail(pos_params, neg_lits, list(conds), env, ranges, types)
        branches.append(_join_and([*pre_conds, tail]))

    return _join_or(branches)


def _fixed_dyn_literal(value: Any, column_type: str) -> str:
    if column_type == "integer":
        if type(value) is not int:
            raise ValueError(f"expected integer fixed value, got {value!r}")
        return f"dyn({literal(str(value), 'integer')})"
    return f"dyn({literal(value, column_type)})"


def _homogeneous_parameter_tables(
    binding: Mapping[str, Any], program: rules.Program, namespace: str
) -> dict[str, dict[str, Any]]:
    """Build CEL parameter tables whose map literals satisfy HomogeneousAggregateLiterals.

    Kubernetes ValidatingAdmissionPolicy enables cel.HomogeneousAggregateLiterals(), which
    rejects map literals mixing `dyn` field selections (`x.<col>`) with concrete fixed
    literals (`"TCP"`). Wrapping fixed literals in `dyn(...)` keeps every map value `dyn`
    in both plain cel-go and Kubernetes apiserver environments.
    """
    tables = parameter_tables(binding, program, namespace)
    for name, spec in binding["parameters"].items():
        lists = spec["lists"]
        if not any(entry.get("fixed") for entry in lists):
            continue
        relation = program.relations[name]
        scope = spec["scope"]
        non_scope = [col for col in (relation.key + relation.values) if col.name != scope]
        items = []
        for entry in lists:
            field = entry["field"]
            base = (
                f"(has(params.spec.{field}) ? params.spec.{field} : [])"
                if entry.get("optional")
                else f"params.spec.{field}"
            )
            written = set(entry["columns"])
            fixed = entry.get("fixed", {})
            parts = []
            for col in non_scope:
                if col.name in written:
                    parts.append(f'"{col.name}": x.{col.name}')
                else:
                    parts.append(f'"{col.name}": {_fixed_dyn_literal(fixed[col.name], col.type)}')
            items.append(f"{base}.map(x, {{{', '.join(parts)}}})")
        expr = " + ".join(items)
        if len(lists) > 1:
            expr = f"({expr})"
        tables[name] = {**tables[name], "list": expr}
    return tables


def translate(program: rules.Program, binding: Mapping[str, Any], digest: str) -> dict[str, Any]:
    """Compile a checked rule program and admission binding into a ValidatingAdmissionPolicy."""
    _validate_binding(binding, program)

    output = binding["output"]
    request_relations = sorted({source["relation"] for source in binding["request"]})
    request_set = set(request_relations)
    request_objects = {name: "incoming" for name in request_relations}

    verdict = classify(program, output, request_objects)
    if verdict["route"] != "gate":
        reason = verdict["reason"]
        offending = verdict.get("rule")
        if offending:
            raise ValueError(f"{output}: rule {offending} cannot become a CEL gate ({reason})")
        raise ValueError(f"{output}: cannot become a CEL gate ({reason})")

    _, request_program = partition_rule(program, output, request_objects=request_objects)

    required_params = {
        name
        for name, rel in request_program.relations.items()
        if rel.role == "base" and name not in request_set
    }
    unbound_params = sorted(required_params - set(binding["parameters"]))
    if unbound_params:
        raise ValueError(f"{output}: missing parameter binding(s): {', '.join(unbound_params)}")

    output_types = [col.type for col in program.relations[output].key]
    for rel_name in request_relations:
        req_types = [col.type for col in program.relations[rel_name].key]
        if req_types != output_types:
            raise ValueError(
                f"{output}: request relation {rel_name} columns {req_types} do not match output {output_types}"
            )

    tables = _homogeneous_parameter_tables(binding, program, _NAMESPACE_EXPR)
    roots = {
        "object": "object",
        "request": _request_root_expression(binding),
    }

    base_relations = {name for name, rel in request_program.relations.items() if rel.role == "base"}
    unfold_counter = itertools.count()
    unfolded_cache = {
        name: _unfold_relation(request_program, name, base_relations, unfold_counter)
        for name, rel in sorted(request_program.relations.items())
        if rel.role == "derived"
    }

    var_counter = itertools.count()

    def body(relation: str, columns: Mapping[str, Any]) -> str:
        rel_obj = program.relations[relation]
        row_values = tuple(columns[col.name] for col in rel_obj.key)
        return _compile_derived(
            request_program,
            output,
            row_values,
            relation,
            row_values,
            request_set,
            tables,
            unfolded_cache,
            var_counter,
        )

    missing_cel = missing(binding, program, roots)
    violation_cel = quantify(binding, program, roots, body)
    return policy_shell(binding, digest, missing=missing_cel, violation=violation_cel)
