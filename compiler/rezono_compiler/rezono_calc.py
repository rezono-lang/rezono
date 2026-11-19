"""Lower calculations written in Rezono to rezono.calc/1 (decisions/language-calculations.md).

A module's `as of` declaration and non-table derived values under `extend` or `kind` lower to a
`rezono.calc/1` program document that joins the pack closure alongside `calc/*.yaml` files. Every
check, binding, SQL translation and proof after lowering is unchanged.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping, Sequence, Set
from typing import TYPE_CHECKING

from . import rezono_module
from .diagnostics import Diagnostic
from .names import ISO_DATE
from .rezono_lowering import Refuse

if TYPE_CHECKING:
    from .modules import Module
    from .pack import Pack

FORMAT = "rezono.calc/1"
SECTION = "§5.4"
DEFAULT_VERSION = "1"
DEFAULT_VALID_FROM = "0001-01-01"
DEFAULT_VALID_UNTIL = "9999-12-31"
DEFAULT_KNOWN_FROM = "0001-01-01"

INTEGER = re.compile(r"^-?(?:0|[1-9][0-9]*)$")
DECIMAL = re.compile(r"^(-?[0-9]+)\.([0-9]+)$")
PERCENT = re.compile(r"^(-?[0-9]+)(?:\.([0-9]+))?\s*%$")
QUANTITY = re.compile(r"^(-?(?:0|[1-9][0-9]*))\s+(\S+)$")

CALC_CALLS = frozenset({"round", "floor", "ceil", "pow", "min", "max"})
DIRECT_CMP = {"=": "eq", "<": "lt", "<=": "lte", ">=": "gte"}
DERIVED_MEMBERS = frozenset({
    "derived", "type", "card", "value", "unless", "versions", "output", "unit", "definitions", "totality",
})
VERSION_MEMBERS = frozenset({"version", "replaces", "valid", "known", "value", "source", "definitions"})
DEFINITION_MEMBERS = frozenset({"name", "when", "value", "overrides"})
OVERRIDE_MEMBERS = frozenset({"definition", "reason"})


def _is_calc_derived(item: object) -> bool:
    return isinstance(item, dict) and not isinstance(item.get("table"), dict)


def _subject_of_decl(decl: object) -> tuple[str, list[tuple[int, dict]]] | None:
    if not isinstance(decl, dict):
        return None
    kind_name = decl.get("extend") if "extend" in decl else decl.get("kind") if "kind" in decl else None
    if not isinstance(kind_name, str):
        return None
    derived = [(idx, dv) for idx, dv in enumerate(decl.get("derived") or []) if _is_calc_derived(dv)]
    return (kind_name, derived) if derived else None


def has_calculation(form: dict) -> bool:
    """Whether a module form carries an `as of` line or any non-table derived value."""
    if form.get("format") not in (rezono_module.IDENTIFIER_FORMAT, rezono_module.NATIVE_FORMAT):
        return False
    for decl in form["module"]["decls"]:
        if isinstance(decl, dict) and "asOf" in decl:
            return True
        if _subject_of_decl(decl) is not None:
            return True
    return False


def calc_modules(mods: Iterable[Module], pack_name: str) -> list[Module]:
    """The Rezono modules of `pack_name` that carry calculations, in deterministic path order."""
    return sorted(
        (m for m in mods if m.pack == pack_name and m.form is not None and has_calculation(m.form)),
        key=lambda m: m.rel,
    )


def module_rules(form: dict) -> tuple[str | None, set[str]]:
    """The subject class name (if any) and rule names declared by a module form."""
    subject: str | None = None
    rules: set[str] = set()
    for decl in form["module"]["decls"]:
        found = _subject_of_decl(decl)
        if found is None:
            continue
        kind_name, derived = found
        if subject is None:
            subject = kind_name
        for _, dv in derived:
            if isinstance(dv.get("derived"), str):
                rules.add(dv["derived"])
    return subject, rules


def validate_as_of(decl: dict, at: str, refuse: Refuse) -> bool:
    """Check an `as of DAY known DAY` declaration."""
    if set(decl) != {"asOf", "known"}:
        refuse(at, "an `as of` line needs only `asOf` and `known` (R050)", SECTION)
        return False
    ok = True
    for key in ("asOf", "known"):
        value = decl.get(key)
        if not isinstance(value, str) or not ISO_DATE.match(value):
            refuse(at, f"`as of` {key} must be a date YYYY-MM-DD (R050)", SECTION)
            ok = False
    return ok


def _validate_definition(defn: object, at: str, refuse: Refuse) -> bool:
    if not isinstance(defn, dict):
        refuse(at, "a definition must be an object (R050)", SECTION)
        return False
    if extra := set(defn) - DEFINITION_MEMBERS:
        refuse(at, f"a definition with {', '.join(sorted(extra))} is not lowered (R050)", SECTION)
        return False
    ok = True
    if not isinstance(defn.get("name"), str) or not defn["name"]:
        refuse(at, "a definition needs a name (R050)", SECTION)
        ok = False
    if not isinstance(defn.get("when"), dict):
        refuse(f"{at}/when", "a definition needs a `when` expression (R050)", SECTION)
        ok = False
    if not isinstance(defn.get("value"), dict):
        refuse(f"{at}/value", "a definition needs a `value` expression (R050)", SECTION)
        ok = False
    if "overrides" in defn:
        overrides = defn["overrides"]
        if not isinstance(overrides, list):
            refuse(f"{at}/overrides", "overrides must be a list (R050)", SECTION)
            ok = False
        else:
            for oi, ov in enumerate(overrides):
                here = f"{at}/overrides/{oi}"
                if (not isinstance(ov, dict) or set(ov) != OVERRIDE_MEMBERS
                        or not isinstance(ov.get("definition"), str) or not ov["definition"]
                        or not isinstance(ov.get("reason"), str) or not ov["reason"]):
                    refuse(here, "an override needs a target definition and a reason (R050)", SECTION)
                    ok = False
    return ok


def validate_derived(dv: object, at: str, refuse: Refuse) -> bool:
    """Check the structure of a calculated derived value during module loading."""
    if not isinstance(dv, dict):
        refuse(at, "a derived value must be an object (R050)", SECTION)
        return False
    if extra := set(dv) - DERIVED_MEMBERS:
        refuse(at, f"a derived value with {', '.join(sorted(extra))} is not lowered (R050)", SECTION)
        return False
    ok = True
    if not isinstance(dv.get("derived"), str) or not dv["derived"]:
        refuse(at, "a derived value needs a name (R050)", SECTION)
        ok = False
    if not isinstance(dv.get("type"), str) or not dv["type"]:
        refuse(at, "a derived value needs a type (R050)", SECTION)
        ok = False
    if "totality" in dv:
        refuse(at, "`total` is not lowered on a calculated value (R050)", SECTION)
        ok = False
    if "card" in dv:
        refuse(at, f"a derived value `{dv.get('type', '')}{dv['card']}` is not lowered in a calculation (R050)", SECTION)
        ok = False
    if "unless" in dv:
        refuse(f"{at}/unless", "`unless` under a calculated value is not lowered (R050)", SECTION)
        ok = False
    if "definitions" in dv and "versions" in dv:
        refuse(at, "definitions beside versions (R050)", SECTION)
        ok = False
    if "value" in dv and "versions" in dv:
        refuse(at, "value beside versions (R050)", SECTION)
        ok = False
    if "value" in dv and "definitions" in dv:
        refuse(at, "value beside definitions (R050)", SECTION)
        ok = False
    if "output" in dv:
        out = dv["output"]
        if (not isinstance(out, dict) or set(out) != {"relation", "slot"}
                or not isinstance(out.get("relation"), str) or not out["relation"]
                or not isinstance(out.get("slot"), str) or not out["slot"]):
            refuse(f"{at}/output", "output needs relation and slot (R050)", SECTION)
            ok = False
    if "unit" in dv and (not isinstance(dv["unit"], str) or not dv["unit"]):
        refuse(f"{at}/unit", "unit must be non-empty text (R050)", SECTION)
        ok = False
    if "versions" in dv:
        versions = dv["versions"]
        if not isinstance(versions, list) or not versions:
            refuse(f"{at}/versions", "versions must be a non-empty list (R050)", SECTION)
            ok = False
        else:
            for vi, ver in enumerate(versions):
                vat = f"{at}/versions/{vi}"
                if not isinstance(ver, dict):
                    refuse(vat, "a version must be an object (R050)", SECTION)
                    ok = False
                    continue
                if extra := set(ver) - VERSION_MEMBERS:
                    refuse(vat, f"a version with {', '.join(sorted(extra))} is not lowered (R050)", SECTION)
                    ok = False
                if not isinstance(ver.get("version"), str) or not ver["version"]:
                    refuse(vat, "a version needs a version number (R050)", SECTION)
                    ok = False
                has_defs, has_val = "definitions" in ver, "value" in ver
                if has_defs == has_val:
                    refuse(vat, "a version needs either definitions or a value (R050)", SECTION)
                    ok = False
                elif has_defs:
                    defs = ver["definitions"]
                    if not isinstance(defs, list) or not defs:
                        refuse(f"{vat}/definitions", "version definitions must be a non-empty list (R050)", SECTION)
                        ok = False
                    else:
                        for di, defn in enumerate(defs):
                            if not _validate_definition(defn, f"{vat}/definitions/{di}", refuse):
                                ok = False
                elif not isinstance(ver.get("value"), dict):
                    refuse(f"{vat}/value", "a version value must be an expression (R050)", SECTION)
                    ok = False
    elif "definitions" in dv:
        defs = dv["definitions"]
        if not isinstance(defs, list) or not defs:
            refuse(f"{at}/definitions", "definitions must be a non-empty list (R050)", SECTION)
            ok = False
        else:
            for di, defn in enumerate(defs):
                if not _validate_definition(defn, f"{at}/definitions/{di}", refuse):
                    ok = False
    elif "value" in dv:
        if not isinstance(dv["value"], dict):
            refuse(f"{at}/value", "a derived value needs an expression (R050)", SECTION)
            ok = False
    else:
        refuse(at, "a derived value needs a value, definitions or versions (R050)", SECTION)
        ok = False
    return ok


def validate_module(decls: list, refuse: Refuse) -> None:
    """Check module-level calculation constraints: one subject per module and at most one `as of`."""
    first_subject: str | None = None
    seen_as_of = False
    for index, decl in enumerate(decls):
        at = f"/decls/{index}"
        if not isinstance(decl, dict):
            continue
        if "asOf" in decl:
            if seen_as_of:
                refuse(at, "two evaluation dates in one module (R050)", SECTION)
            seen_as_of = True
        found = _subject_of_decl(decl)
        if found is None:
            continue
        kind_name, _ = found
        if first_subject is None:
            first_subject = kind_name
        elif kind_name != first_subject:
            refuse(at, f"two subjects: {first_subject} and {kind_name} (R050)", SECTION)


def resolve_subject(pack: Pack, pack_name: str, cls_name: str,
                    renames: Mapping[str, Mapping[str, str]] | None = None) -> tuple[str, str]:
    """Return `(own_id, root_id)` for a subject class name in `pack_name`."""
    from .pack import snake

    if pack_name == pack.meta["name"]:
        found = next((k for k, kind in pack.kinds.items() if kind.cls == cls_name), None)
        own = found if found is not None else snake(cls_name)
        return own, own
    mapping = (renames or {}).get(pack_name, {})
    for own_id, root_id in mapping.items():
        if root_id in pack.kinds and pack.kinds[root_id].cls == cls_name:
            return own_id, root_id
    own = snake(cls_name)
    return own, mapping.get(own, own)


def _place(line_map: Mapping[str, int], at: str) -> int:
    while at and at not in line_map:
        at = at.rsplit("/", 1)[0]
    return line_map.get(at, 1)


def _lower_literal(text: str, at: str, refuse) -> dict | None:
    if text == "true":
        return {"boolean": True}
    if text == "false":
        return {"boolean": False}
    if INTEGER.fullmatch(text):
        return {"integer": str(int(text))}
    if match := PERCENT.fullmatch(text):
        whole, frac = match.group(1), match.group(2) or ""
        sign = -1 if whole.startswith("-") else 1
        num = sign * int(whole.lstrip("-") + frac)
        den = 10 ** (len(frac) + 2)
        return {"op": "ratio", "args": [{"integer": str(num)}, {"integer": "1"}, {"integer": str(den)}]}
    if match := DECIMAL.fullmatch(text):
        whole, frac = match.group(1), match.group(2)
        sign = -1 if whole.startswith("-") else 1
        num = sign * int(whole.lstrip("-") + frac)
        den = 10 ** len(frac)
        return {"op": "ratio", "args": [{"integer": str(num)}, {"integer": "1"}, {"integer": str(den)}]}
    if match := QUANTITY.fullmatch(text):
        num, unit = match.group(1), match.group(2)
        return {"integer": str(int(num)), "unit": unit}
    refuse(at, f"literal {text!r} is not lowered in a calculation")
    return None


def lower_expression(
    expr: object,
    at: str,
    pack: Pack,
    subject_cls: str,
    own_subject: str,
    root_subject: str,
    current_rule: str,
    rules: Set[str],
    parameters: Set[str],
    refuse,
    *,
    where_prefix: str = "",
    line_map: Mapping[str, int] | None = None,
    bare_leaves: list[tuple[str, str, str, str]] | None = None,
) -> dict | None:
    """Lower one Rezono expression tree to a `rezono.calc/1` Expression."""
    if not isinstance(expr, dict) or len(expr) != 1:
        refuse(at, "expression must be a single-key object")
        return None
    key, value = next(iter(expr.items()))

    def sub(child: object, child_at: str) -> dict | None:
        return lower_expression(
            child, child_at, pack, subject_cls, own_subject, root_subject, current_rule,
            rules, parameters, refuse, where_prefix=where_prefix, line_map=line_map, bare_leaves=bare_leaves,
        )

    if key == "lit":
        if not isinstance(value, str):
            refuse(at, "literal must be text")
            return None
        return _lower_literal(value, at, refuse)

    if key == "path":
        if not isinstance(value, list) or not value or not all(isinstance(s, str) for s in value):
            refuse(at, "invalid path")
            return None
        if any("@" in s for s in value):
            refuse(at, "rule@version leaf is not lowered")
            return None
        if len(value) == 1:
            name = value[0]
            matches: list[tuple[str, dict]] = []
            if name in parameters:
                matches.append(("parameter", {"parameter": name}))
            if name in rules and name != current_rule:
                matches.append(("rule", {"rule": name}))
            if root_subject in pack.kinds and pack.slot(root_subject, name) is not None:
                matches.append(("slot", {"fact": f"{own_subject}.{name}"}))
            if len(matches) > 1:
                refuse(at, f"ambiguous leaf {name!r}")
                return None
            if len(matches) == 1:
                kind_tag, leaf = matches[0]
                if bare_leaves is not None and line_map is not None:
                    bare_leaves.append((f"{where_prefix}:{_place(line_map, at)}", root_subject, name, kind_tag))
                return leaf
            return {"fact": name}
        if len(value) == 2:
            head, tail = value
            if head == subject_cls:
                if tail in rules and tail != current_rule:
                    return {"rule": tail}
                if root_subject in pack.kinds and pack.slot(root_subject, tail) is not None:
                    return {"fact": f"{own_subject}.{tail}"}
                refuse(at, f"{head}.{tail} is not another derived value or slot of {subject_cls}")
                return None
            return {"fact": f"{head}.{tail}"}
        refuse(at, f"path {'.'.join(value)!r} is not lowered")
        return None

    if key == "dot":
        if (isinstance(value, list) and len(value) == 2
                and isinstance(value[0], dict) and value[0].keys() == {"kind"}
                and value[0]["kind"] == subject_cls and isinstance(value[1], str)):
            tail = value[1]
            if "@" in tail:
                refuse(at, "rule@version leaf is not lowered")
                return None
            if tail in rules and tail != current_rule:
                return {"rule": tail}
            if root_subject in pack.kinds and pack.slot(root_subject, tail) is not None:
                return {"fact": f"{own_subject}.{tail}"}
            refuse(at, f"{subject_cls}.{tail} is not another derived value or slot of {subject_cls}")
            return None
        refuse(at, "dot expression is not lowered")
        return None

    if key == "arith":
        if not isinstance(value, list) or len(value) != 3 or not isinstance(value[0], str):
            refuse(at, "invalid arithmetic expression")
            return None
        op, left, right = value
        if op == "+":
            la, lb = sub(left, f"{at}/arith/1"), sub(right, f"{at}/arith/2")
            return None if la is None or lb is None else {"op": "add", "args": [la, lb]}
        if op == "-":
            la, lb = sub(left, f"{at}/arith/1"), sub(right, f"{at}/arith/2")
            return None if la is None or lb is None else {"op": "sub", "args": [la, lb]}
        if op == "*":
            la, lb = sub(left, f"{at}/arith/1"), sub(right, f"{at}/arith/2")
            return None if la is None or lb is None else {"op": "ratio", "args": [la, lb, {"integer": "1"}]}
        if op == "/":
            if (isinstance(left, dict) and left.keys() == {"arith"}
                    and isinstance(left["arith"], list) and len(left["arith"]) == 3
                    and left["arith"][0] == "*"):
                lx = sub(left["arith"][1], f"{at}/arith/1/arith/1")
                ln = sub(left["arith"][2], f"{at}/arith/1/arith/2")
                ld = sub(right, f"{at}/arith/2")
                return None if lx is None or ln is None or ld is None else {"op": "ratio", "args": [lx, ln, ld]}
            lx, ld = sub(left, f"{at}/arith/1"), sub(right, f"{at}/arith/2")
            return None if lx is None or ld is None else {"op": "ratio", "args": [lx, {"integer": "1"}, ld]}
        refuse(at, f"arithmetic operator {op!r} is not lowered")
        return None

    if key == "neg":
        if (isinstance(value, dict) and value.keys() == {"lit"}
                and isinstance(value["lit"], str) and INTEGER.fullmatch(value["lit"])):
            return {"integer": str(-int(value["lit"]))}
        inner = sub(value, f"{at}/neg")
        return None if inner is None else {"op": "sub", "args": [{"integer": "0"}, inner]}

    if key == "call":
        if (isinstance(value, list) and len(value) == 2
                and isinstance(value[0], str) and isinstance(value[1], list)
                and value[0] in CALC_CALLS):
            fn, raw_args = value
            args = [sub(arg, f"{at}/call/1/{idx}") for idx, arg in enumerate(raw_args)]
            return None if any(a is None for a in args) else {"op": fn, "args": args}
        fn = value[0] if isinstance(value, list) and value else value
        refuse(at, f"call {fn!r} is not lowered")
        return None

    if key == "when":
        if not isinstance(value, list) or len(value) != 3:
            refuse(at, "invalid when expression")
            return None
        cond = sub(value[0], f"{at}/when/0")
        then_expr = sub(value[1], f"{at}/when/1")
        else_expr = sub(value[2], f"{at}/when/2")
        if cond is None or then_expr is None or else_expr is None:
            return None
        return {"op": "if", "args": [cond, then_expr, else_expr]}

    if key in ("and", "or"):
        if not isinstance(value, list) or len(value) < 2:
            refuse(at, f"invalid {key} expression")
            return None
        args = [sub(item, f"{at}/{key}/{idx}") for idx, item in enumerate(value)]
        return None if any(a is None for a in args) else {"op": key, "args": args}

    if key == "not":
        inner = sub(value, f"{at}/not")
        return None if inner is None else {"op": "if", "args": [inner, {"boolean": False}, {"boolean": True}]}

    if key == "cmp":
        if not isinstance(value, list) or len(value) != 3 or not isinstance(value[0], str):
            refuse(at, "invalid comparison")
            return None
        op, left, right = value
        la, lb = sub(left, f"{at}/cmp/1"), sub(right, f"{at}/cmp/2")
        if la is None or lb is None:
            return None
        if op in DIRECT_CMP:
            return {"op": DIRECT_CMP[op], "args": [la, lb]}
        if op == ">":
            return {"op": "lt", "args": [lb, la]}
        if op == "!=":
            return {"op": "if", "args": [{"op": "eq", "args": [la, lb]}, {"boolean": False}, {"boolean": True}]}
        refuse(at, f"comparison {op!r} is not lowered")
        return None

    if key == "is":
        refuse(at, "state test `is` is not lowered")
    elif key == "agg":
        refuse(at, "aggregate expression is not lowered")
    elif key in ("filter", "in", "range", "kind"):
        refuse(at, f"set expression `{key}` is not lowered")
    else:
        refuse(at, f"expression `{key}` is not lowered")
    return None


def lower_module(
    pack: Pack,
    module: Module,
    rules_by_subject: Mapping[str, Set[str]],
    parameters: Set[str] = frozenset(),
    *,
    renames: Mapping[str, Mapping[str, str]] | None = None,
    bare_leaves: list[tuple[str, str, str, str]] | None = None,
) -> dict:
    """Lower one Rezono module form to a `rezono.calc/1` program document."""
    from .pack import CompileError

    form = module.form
    assert form is not None
    where = f"{module.pack_dir.name}/{module.rel}"
    line_map = rezono_module.lines(form)
    errors: list[str] = []

    def refuse(at: str, what: str) -> None:
        errors.append(f"{where}:{_place(line_map, at)}: {what} (R050)")

    doc: dict = {"format": FORMAT, "pack": module.pack, "rules": [], "templates": []}
    subject_cls: str | None = None
    own_subject: str | None = None
    root_subject: str | None = None

    for decl_idx, decl in enumerate(form["module"]["decls"]):
        decl_at = f"/decls/{decl_idx}"
        if not isinstance(decl, dict):
            continue
        if "asOf" in decl:
            if "as_of" in doc:
                refuse(decl_at, "two evaluation dates in one module")
            else:
                doc["as_of"] = {"valid_at": decl["asOf"], "known_at": decl["known"]}
            continue
        found = _subject_of_decl(decl)
        if found is None:
            continue
        kind_name, derived_list = found
        if subject_cls is None:
            subject_cls = kind_name
            own_subject, root_subject = resolve_subject(pack, module.pack, kind_name, renames)
            doc["subject"] = own_subject
        elif kind_name != subject_cls:
            refuse(decl_at, f"two subjects: {subject_cls} and {kind_name}")
            continue

        assert own_subject is not None and root_subject is not None
        subject_rules = rules_by_subject.get(own_subject, frozenset())

        for dv_idx, dv in derived_list:
            dv_at = f"{decl_at}/derived/{dv_idx}"
            rule_name = dv["derived"]
            if "output" in dv:
                output = f"{dv['output']['relation']}.{dv['output']['slot']}"
            else:
                output = f"{own_subject}.{rule_name}"
            if "unit" in dv:
                unit = dv["unit"]
            elif dv.get("type") in pack.units:
                unit = dv["type"]
            else:
                refuse(dv_at, f"{rule_name}: unit is required unless the declared type names a unit the pack declares")
                continue

            if "versions" in dv:
                version_specs = [
                    (
                        f"{dv_at}/versions/{vi}",
                        str(ver["version"]),
                        ver["valid"][0] if ver.get("valid") else DEFAULT_VALID_FROM,
                        ver["valid"][1] if ver.get("valid") and len(ver["valid"]) > 1 else DEFAULT_VALID_UNTIL,
                        ver.get("known") or DEFAULT_KNOWN_FROM,
                        ver.get("definitions"),
                        ver.get("value"),
                    )
                    for vi, ver in enumerate(dv["versions"])
                ]
            else:
                version_specs = [
                    (
                        dv_at,
                        DEFAULT_VERSION,
                        DEFAULT_VALID_FROM,
                        DEFAULT_VALID_UNTIL,
                        DEFAULT_KNOWN_FROM,
                        dv.get("definitions"),
                        dv.get("value"),
                    )
                ]

            for ver_at, v_str, valid_from, valid_until, known_from, raw_defs, raw_val in version_specs:
                lowered_defs: list[dict] = []
                if raw_defs is not None:
                    for di, defn in enumerate(raw_defs):
                        def_at = f"{ver_at}/definitions/{di}"
                        when = lower_expression(
                            defn["when"], f"{def_at}/when", pack, subject_cls, own_subject, root_subject,
                            rule_name, subject_rules, parameters, refuse,
                            where_prefix=where, line_map=line_map, bare_leaves=bare_leaves,
                        )
                        val = lower_expression(
                            defn["value"], f"{def_at}/value", pack, subject_cls, own_subject, root_subject,
                            rule_name, subject_rules, parameters, refuse,
                            where_prefix=where, line_map=line_map, bare_leaves=bare_leaves,
                        )
                        if when is None or val is None:
                            continue
                        entry: dict = {"name": defn["name"], "when": when, "value": val}
                        if defn.get("overrides"):
                            entry["overrides"] = [
                                {"definition": f"{rule_name}@{v_str}#{ov['definition']}", "reason": ov["reason"]}
                                for ov in defn["overrides"]
                            ]
                        lowered_defs.append(entry)
                elif raw_val is not None:
                    val = lower_expression(
                        raw_val, f"{ver_at}/value", pack, subject_cls, own_subject, root_subject,
                        rule_name, subject_rules, parameters, refuse,
                        where_prefix=where, line_map=line_map, bare_leaves=bare_leaves,
                    )
                    if val is not None:
                        lowered_defs.append({"name": rule_name, "when": {"boolean": True}, "value": val})
                doc["rules"].append({
                    "id": f"{rule_name}@{v_str}",
                    "rule": rule_name,
                    "version": v_str,
                    "output": output,
                    "unit": unit,
                    "valid_from": valid_from,
                    "valid_until": valid_until,
                    "known_from": known_from,
                    "definitions": lowered_defs,
                })

    if errors:
        raise CompileError("\n".join(errors), [Diagnostic("R050", msg) for msg in errors])
    return doc


def check_relation_ambiguity(
    pack: Pack,
    bare_leaves: Sequence[tuple[str, str, str, str]],
    errors: list[str],
) -> None:
    """Report R050 if a bare leaf resolved to a parameter, rule or slot also names a subject presence relation."""
    from . import calc, types

    derived = calc.derived_relations(pack)
    if not derived:
        return
    for where, subject, name, kind_tag in bare_leaves:
        if name not in derived or subject not in pack.kinds:
            continue
        key = derived[name]["key"]
        id_type = types.rule_type(pack.kinds[pack.root(subject)].id_type)
        if len(key) == 1 and key[0]["type"] == id_type:
            errors.append(f"{where}: ambiguous leaf {name!r} (both {kind_tag} and relation {name}) (R050)")
