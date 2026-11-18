"""Lower a closed Rezono kind using the slot component."""

from collections.abc import Set

from . import rezono_equation, rezono_slot
from .rezono_extend import refuse_derived
from .rezono_lowering import Refuse


MEMBERS = {"kind", "world", "applies", "sealed", "slots", "derived"}


def lower(decl: dict, at: str, own: dict[str, str], owners: dict[str, list[str]],
          declared: Set[str], uses: set[str], refuse: Refuse, *, explicit_identifiers: bool = False) -> dict | None:
    ok = True
    allowed = MEMBERS | {"equations"} if explicit_identifiers else MEMBERS
    if extra := set(decl) - allowed:
        refuse(at, f"a kind with {', '.join(sorted(extra))} is not lowered", "§5.1")
        ok = False
    if decl.get("world") != "closed":
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
    equations = rezono_equation.lower(decl.get("equations", []), f"{at}/equations", refuse) if explicit_identifiers else []
    slots = decl.get("slots") or []
    if rezono_slot.validate(
        slots, decl["kind"], at, own, owners, uses, refuse, explicit_identifiers=explicit_identifiers
    ) and ok and equations is not None:
        kind = {"attributes": rezono_slot.lower(slots, declared)}
        if equations:
            kind["annotations"] = {"path_equations": equations}
        return kind
    return None
