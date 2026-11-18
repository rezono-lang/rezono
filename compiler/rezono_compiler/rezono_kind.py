"""Lower a closed Rezono kind using the slot component."""

from collections.abc import Set

from . import rezono_equation, rezono_slot
from .rezono_extend import refuse_derived
from .rezono_lowering import Refuse


MEMBERS = {"kind", "world", "applies", "sealed", "slots", "derived"}


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
    allowed = MEMBERS | {"embedded", "equations", "parent"} if extended_format else MEMBERS
    if extra := set(decl) - allowed:
        refuse(at, f"a kind with {', '.join(sorted(extra))} is not lowered", "§5.1")
        ok = False
    embedded = decl.get("embedded") is True
    if extended_format and "embedded" in decl and not embedded:
        refuse(at, "an embedded kind must be marked true", "§5.1")
        ok = False
    has_parent = extended_format and "parent" in decl
    if embedded and has_parent:
        refuse(at, "an embedded kind cannot inherit an identifier from a parent", "§5.1")
        ok = False
    parent = parent_of(decl["parent"], decl["kind"], f"{at}/parent", own, owners, uses, refuse) if has_parent else None
    if has_parent and parent is None:
        ok = False
    if decl.get("world") != "closed" and not (has_parent and "world" not in decl):
        refuse(at, "an open kind is refused: a kind says `world closed`", "§5.1")
        ok = False
    if "applies" in decl:
        refuse(f"{at}/applies", "`applies` is not lowered yet")
        ok = False
    if "sealed" in decl:
        refuse(f"{at}/sealed", "`sealed at` is not lowered yet")
        ok = False
    for index, _ in enumerate(decl.get("derived") or []):
        refuse_derived(f"{at}/derived/{index}", refuse)
        ok = False
    equations = rezono_equation.lower(decl.get("equations", []), f"{at}/equations", refuse) if extended_format else []
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
        slots, decl["kind"], at, own, owners, uses, refuse, explicit_identifiers=extended_format
    ) and ok and equations is not None:
        attributes = rezono_slot.lower(slots, declared, implicit_identifier=not embedded and parent is None)
        kind = {"is_a": parent, "attributes": attributes} if parent is not None else {"attributes": attributes}
        if equations:
            kind.setdefault("annotations", {})["path_equations"] = equations
        return kind
    return None
