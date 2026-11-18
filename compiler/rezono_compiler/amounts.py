"""The currency and the unit of a rule's columns: derived from the rules, never declared a second
time.

A column of a table has the unit of its attribute: money in whole minor units of an ISO 4217 currency (annotation
`currency`), or a unit the pack declares (`Pack.units`); every other whole-number column is a plain number. A
variable stands for what each column it occurs in holds, for the column a `sum`, `min` or `max` folds, and for both
sides of an addition or a subtraction; a count, a product and a quotient are plain numbers, and a constant says
nothing. A column of a derived relation holds what its head terms stand for, over all its rules.

One unit and nothing plain beside it is the unit of the column; anything else has none. Two units in one variable
or one column is an error: a sum or a comparison across them means nothing. So is a comparison of two variables
that stand for different units, and of a variable that stands for a unit with a constant other than 0, which has
no unit (P10.3, Rezono R003: `> 384` against GiB). The rules convert nothing between units.
"""

from __future__ import annotations

import re

from . import types
from .rules_dl import RuleError

PLAIN = ""   # a whole number that is no amount and has no unit
NUMBER = re.compile(r"^-?[0-9]+$")
SYMBOL = {"eq": "=", "ne": "!=", "lt": "<", "le": "<=", "gt": ">", "ge": ">="}


def unit_of(pack, slot) -> types.Unit | None:
    """The unit of an attribute's values: money in its currency (named by its code), or its declared unit."""
    if slot.currency:
        return types.money_unit(slot.currency)
    return pack.units.get(slot.unit) if getattr(slot, "unit", None) else None


def tables(pack) -> dict[str, dict[int, types.Unit]]:
    """Per table of the schema, the columns that hold an amount or a quantity: {position: unit}. The table of such
    an attribute, and the tables of its bounds and its constant, which are in the same unit."""
    out = {}
    for kind in pack.kinds.values():
        for s in kind.slots.values():
            if (u := unit_of(pack, s)) is not None:
                out[s.table] = {1: u}
                for bound in ("minimum", "maximum", "constant"):
                    out[f"{s.table}__{bound}"] = {0: u}
    return out


def clash(units: set) -> str:
    """The units of one variable or column, in words, and why they do not meet."""
    found = sorted(units - {PLAIN}, key=lambda u: u.name)
    names = " and ".join(u.name for u in found)
    if all(u.currency for u in found):
        return f"{names}: two currencies"
    dimensions = sorted({u.text for u in found})
    if len(dimensions) > 1:
        return f"{names}: dimensions differ ({', '.join(dimensions)}), two units"
    return f"{names}: two units of one dimension ({dimensions[0]}), which the rules do not convert"


def columns(doc: dict, tables: dict) -> dict[str, list]:
    """Per derived relation of a rule IR document, the currency of each key column, or None. Raises RuleError
    with one line per variable or column that joins two units, and per comparison across units."""
    keys = {r["name"]: [c["name"] for c in r["key"]] for r in doc["relations"]}
    holds = {}   # (relation, position) of every whole-number column -> the units it holds, and PLAIN
    for r in doc["relations"]:
        for i, c in enumerate(r["key"]):
            if c["type"] == "integer":
                amount = tables.get(r["name"], {}).get(i)
                holds[r["name"], i] = set() if r["role"] == "derived" else {amount or PLAIN}

    def variables(rule) -> dict[str, set]:
        found = {}

        def stands_for(term, what):
            if term.startswith("?"):
                found.setdefault(term, set()).update(what)

        for atom in (*rule.get("body", ()), *rule.get("aggregates", ())):
            for i, term in enumerate(atom["terms"]):
                stands_for(term, holds.get((atom["relation"], i), ()))
        for a in rule.get("aggregates", ()):
            over = a.get("over")
            folded = holds[a["relation"], keys[a["relation"]].index(over)] if over in keys[a["relation"]] else {PLAIN}
            stands_for(a["as"], {PLAIN} if a["function"] == "count" else folded)
        for s in rule.get("assignments", ()):   # in the order written: an assignment may read an earlier one
            sides = [found.get(t, set()) for t in (s["left"], s["right"]) if t.startswith("?")]
            stands_for(s["var"], set().union(*sides) if s["op"] in ("add", "sub") else {PLAIN})
        return found

    changed = True
    while changed:   # a column only gains: the least fixpoint, whatever the order of the rules
        changed = False
        for rule in doc["rules"]:
            found = variables(rule)
            for i, term in enumerate(rule["head"]["terms"]):
                column = holds.get((rule["head"]["relation"], i))
                if column is not None and not found.get(term, set()) <= column:
                    column |= found[term]
                    changed = True

    problems = []
    for (name, i), what in sorted(holds.items()):
        if len(what - {PLAIN}) > 1:
            problems.append(f"rules: column {keys[name][i]} of {name} holds {clash(what)} in one column")
    for rule in sorted(doc["rules"], key=lambda r: r["id"]):
        at = f"{rule['origin']['file']}:{rule['origin']['line']}"
        found = variables(rule)
        for var, what in sorted(found.items()):
            if len(what - {PLAIN}) > 1:
                problems.append(f"{at}: {var[1:]} in {rule['id']} joins {clash(what)} in one variable")
        problems += compared(rule, found, at)
        problems += added(rule, found, at)
    if problems:
        raise RuleError("\n".join(problems))
    return {r["name"]: [next(iter(holds[r["name"], i])).currency if len(holds.get((r["name"], i), ())) == 1
                        and PLAIN not in holds[r["name"], i] else None for i in range(len(r["key"]))]
            for r in doc["relations"] if r["role"] == "derived"}


def single(found: dict, term: str) -> types.Unit | None:
    """The one unit a variable stands for, or None (no unit, or two, which is an error of its own)."""
    units = found.get(term, set()) - {PLAIN}
    return next(iter(units)) if len(units) == 1 else None


def bare(term: str) -> bool:
    """A constant number other than 0: it has no unit (0 is zero in every unit)."""
    return bool(NUMBER.match(term)) and int(term) != 0


def without(left: str, ul: types.Unit | None, right: str, ur: types.Unit | None) -> str:
    """Why a quantity cannot meet the constant on the other side, or nothing when it can."""
    for term, u in ((right, ul), (left, ur)):
        if u is not None and bare(term):
            return f"{term} has no unit and {u.name} is {u.text}; compare with a fact or a parameter in {u.name}"
    return ""


def compared(rule, found: dict, at: str) -> list[str]:
    """A comparison across units, and of a quantity with a constant that has no unit (R003)."""
    out = []
    for c in rule.get("conditions", ()):
        left, right = c["left"], c["right"]
        what = f"{left.lstrip('?')} {SYMBOL[c['op']]} {right.lstrip('?')} in {rule['id']}"
        ul, ur = single(found, left), single(found, right)
        if ul is not None and ur is not None and ul != ur:
            out.append(f"{at}: {what}: {clash({ul, ur})}")
        elif reason := without(left, ul, right, ur):
            out.append(f"{at}: {what}: {reason}")
    return out


def added(rule, found: dict, at: str) -> list[str]:
    """A sum or a difference of a quantity and a constant that has no unit (R003). Two units in one sum are the
    error of the variable that holds it (`columns`)."""
    out = []
    for s in rule.get("assignments", ()):
        if s["op"] not in ("add", "sub"):
            continue
        if reason := without(s["left"], single(found, s["left"]), s["right"], single(found, s["right"])):
            what = f"{s['var'].lstrip('?')} = {s['left'].lstrip('?')} {'+' if s['op'] == 'add' else '-'} " \
                   f"{s['right'].lstrip('?')} in {rule['id']}"
            out.append(f"{at}: {what}: {reason}")
    return out
