"""Exact CEL comparisons for rule conditions: decisions/k8s-admission-translator.md, "Condition"."""

from rezono_compiler.rules import const_type, is_var

from cel_literal import literal

_OPS = {
    "eq": "==",
    "ne": "!=",
    "lt": "<",
    "le": "<=",
    "gt": ">",
    "ge": ">=",
}


def _term(term, other, env, types):
    if is_var(term):
        if term not in env:
            raise ValueError(f"variable outside environment: {term!r}")
        return env[term]
    if is_var(other):
        other_type = types.get(other)
        if other_type is None:
            raise ValueError(f"unknown variable type: {other!r}")
        return literal(term, other_type)
    return literal(term, const_type(term))


def condition(condition, env, types):
    """Return the exact CEL comparison for rule `condition`."""
    if getattr(condition, "compare_as", None) is not None:
        raise ValueError(f"unsupported compare_as: {condition.compare_as!r}")
    op = _OPS.get(condition.op)
    if op is None:
        raise ValueError(f"unknown condition operator: {condition.op!r}")
    left = _term(condition.left, condition.right, env, types)
    right = _term(condition.right, condition.left, env, types)
    return f"({left} {op} {right})"
