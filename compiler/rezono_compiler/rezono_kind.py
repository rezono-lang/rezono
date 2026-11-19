"""Lower a closed or open Rezono kind using the slot component."""

from collections.abc import Set

from . import rezono_equation, rezono_metadata, rezono_slot
from .names import NAME
from .rezono_extend import refuse_derived
from .rezono_lowering import Refuse


MEMBERS = {"kind", "world", "applies", "sealed", "slots", "derived"}


def bare_name(expr: object) -> str | None:
    match expr:
        case {"path": [str(name)], **other} if not other and NAME.fullmatch(name):
            return name
    return None


def lower_checks(checks: object, at: str, refuse: Refuse) -> list[dict] | None:
    """Lower the supported class requirements in order, using the existing rule facets."""
    if not isinstance(checks, list):
        refuse(at, "expected a list of class requirements", "§5.1")
        return None
    rules = []
    names: set[str] = set()
    for index, check in enumerate(checks):
        here = f"{at}/{index}"
        if (not isinstance(check, dict) or check.keys() - {"name", "check", "when", "then", "description"}
                or check.get("check") != "require" or not rezono_metadata.name(check.get("name"))
                or not rezono_metadata.valid(check)):
            refuse(here, "expected a named conditional class requirement", "§5.1")
            continue
        name = check["name"]
        if name in names:
            refuse(here, f"class requirement {name} is written twice", "§5.1")
            continue
        names.add(name)

        when_slot = value = None
        match check.get("when"):
            case {"cmp": ["=", left, right], **other} if not other:
                when_slot, value = bare_name(left), bare_name(right)
        if when_slot is None or value is None:
            refuse(f"{here}/when", "expected one slot equated to a bare value", "§5.1")
            continue
        then_slot = None
        match check.get("then"):
            case {"is": [target, "known"], **other} if not other:
                then_slot = bare_name(target)
        if then_slot is None:
            refuse(f"{here}/then", "expected one slot required to be known", "§5.1")
            continue
        rules.append(rezono_metadata.lower(check) | {
            "preconditions": {"slot_conditions": {when_slot: {"equals_string": value}}},
            "postconditions": {"slot_conditions": {then_slot: {"required": True}}},
        })
    return rules if len(rules) == len(checks) else None


def parent_of(value: object, kind: str, at: str, own: dict[str, str],
              owners: dict[str, list[str]], uses: set[str], refuse: Refuse) -> str | None:
    """Resolve a parent using the same module imports as a slot reference."""
    if not isinstance(value, str) or not value:
        refuse(at, "a parent needs a kind name", "§5.1")
        return None
    if value == kind:
        refuse(at, "a kind cannot be its own parent", "§5.1")
        return None
    if value in own:
        return value
    modules = owners.get(value, [])
    if len(modules) == 1:
        uses.add(modules[0])
        return value
    reason = (f"parent {value} is declared by modules {' and '.join(modules)} of this pack" if modules else
              f"parent {value} is not declared in this pack")
    refuse(at, reason, "§5.1")
    return None


def lower(decl: dict, at: str, own: dict[str, str], owners: dict[str, list[str]],
          declared: Set[str], uses: set[str], refuse: Refuse, *, extended_format: bool = False) -> dict | None:
    ok = True
    allowed = (MEMBERS | {"checks", "embedded", "equations", "parent", "relationship"} | rezono_metadata.FIELDS
               if extended_format else MEMBERS)
    if extra := set(decl) - allowed:
        refuse(at, f"a kind with {', '.join(sorted(extra))} is not lowered", "§5.1")
        ok = False
    if not rezono_metadata.valid(decl):
        refuse(at, "invalid kind metadata", "§5.1")
        ok = False
    embedded = decl.get("embedded") is True
    if extended_format and "embedded" in decl and not embedded:
        refuse(at, "an embedded kind must be marked true", "§5.1")
        ok = False
    relationship = decl.get("relationship") is True
    if extended_format and "relationship" in decl and not relationship:
        refuse(at, "a relationship kind must be marked true", "§5.1")
        ok = False
    if embedded and relationship:
        refuse(at, "an embedded kind cannot be a relationship: it has no identity of its own", "§5.1")
        ok = False
    has_parent = extended_format and "parent" in decl
    if embedded and has_parent:
        refuse(at, "an embedded kind cannot inherit an identifier from a parent", "§5.1")
        ok = False
    parent = parent_of(decl["parent"], decl["kind"], f"{at}/parent", own, owners, uses, refuse) if has_parent else None
    if has_parent and parent is None:
        ok = False
    world = decl.get("world")
    if has_parent and world == "open":
        refuse(at, "a kind with a parent has the world of its root kind", "§5.1")
        ok = False
    elif not (world == "closed" or (extended_format and world == "open") or (has_parent and "world" not in decl)):
        refuse(at, "an open kind is refused: a kind says `world closed`", "§5.1")
        ok = False
    if "applies" in decl:
        refuse(f"{at}/applies", "`applies` is not lowered yet")
        ok = False
    sealed = decl.get("sealed")
    if "sealed" in decl and not extended_format:
        refuse(f"{at}/sealed", "`sealed at` is not lowered yet")
        ok = False
    elif "sealed" in decl and not (isinstance(sealed, str) and NAME.fullmatch(sealed)):
        refuse(f"{at}/sealed", "`sealed at` names the period slot of the kind", "§5a")
        ok = False
    for index, _ in enumerate(decl.get("derived") or []):
        refuse_derived(f"{at}/derived/{index}", refuse)
        ok = False
    equations = rezono_equation.lower(decl.get("equations", []), f"{at}/equations", refuse) if extended_format else []
    rules = lower_checks(decl.get("checks", []), f"{at}/checks", refuse) if extended_format else []
    slots = decl.get("slots") or []
    if embedded:
        for index, slot in enumerate(slots):
            if isinstance(slot, dict) and slot.get("identifier") is True:
                refuse(f"{at}/slots/{index}", "an embedded kind cannot declare an identifier", "§5.1")
                ok = False
    if has_parent and any(isinstance(slot, dict) and slot.get("identifier") is True for slot in slots):
        refuse(at, "a kind with a parent inherits its identifier and cannot declare its own", "§5.1")
        ok = False
    if rezono_slot.validate(
        slots, decl["kind"], at, own, owners, uses, refuse, extended=extended_format, open_kind=world == "open"
    ) and ok and equations is not None and rules is not None:
        attributes = rezono_slot.lower(slots, declared, implicit_identifier=not embedded and parent is None)
        result = {"attributes": attributes} | rezono_metadata.lower(decl)
        if world == "open":
            result.setdefault("annotations", {})["world"] = "open"
        if parent is not None:
            result["is_a"] = parent
        if relationship:
            result["represents_relationship"] = True
        if "sealed" in decl:
            result.setdefault("annotations", {})["seal"] = sealed
        if equations:
            result.setdefault("annotations", {})["path_equations"] = equations
        if rules:
            result["rules"] = rules
        return result
    return None


def lower_abstract(decl: dict, at: str, refuse: Refuse) -> tuple[dict, dict[str, bool]] | None:
    """Lower the abstract modifier separately from the kind's slots and other properties."""
    if decl["abstract"] is not True:
        refuse(f"{at}/abstract", "an abstract kind must be marked true", "§5.1")
        return None
    kind = {member: value for member, value in decl.items() if member != "abstract"}
    return kind, {"abstract": True}
