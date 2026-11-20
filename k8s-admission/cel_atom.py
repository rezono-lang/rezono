"""Exact CEL quantifiers for parameter atoms: decisions/k8s-admission-translator.md, "Atom"."""

from cel_literal import literal
from rezono_compiler.rules import is_var


def bind(atom, table, env, types, var):
    """Return `(conditions, env2)` binding a parameter atom against `table` with element `var`."""
    columns = table["columns"]
    if len(atom.terms) != len(columns):
        raise ValueError(f"atom {atom.relation} arity {len(atom.terms)} does not match table {len(columns)}")
    column_types = table["types"]
    env2 = dict(env)
    conditions = []
    for (column, template), term in zip(columns.items(), atom.terms):
        expr = template.replace("{e}", var)
        col_type = column_types[column]
        if is_var(term):
            if term in types and types[term] != col_type:
                raise ValueError(f"variable {term} has type {types[term]}, expected {col_type}")
            if term in env2:
                conditions.append(f"({expr} == {env2[term]})")
            else:
                env2[term] = expr
        else:
            conditions.append(f"({expr} == {literal(term, col_type)})")
    return conditions, env2


def exists(table, var, conditions, rest=None):
    """Return `<list>.exists(<var>, <parts>)` for `table` and element variable `var`."""
    parts = list(conditions)
    if rest:
        parts.append(rest)
    body = " && ".join(parts) if parts else "true"
    return f"{table['list']}.exists({var}, {body})"


def negative(atom, table, env, types, var):
    """Return `!<list>.exists(<var>, <parts>)` for a negated atom whose variables are all bound."""
    unbound = [term for term in atom.terms if is_var(term) and term not in env]
    if unbound:
        raise ValueError(f"negated atom {atom.relation} has unbound variable(s): {', '.join(unbound)}")
    conditions, _ = bind(atom, table, env, types, var)
    return "!" + exists(table, var, conditions)
