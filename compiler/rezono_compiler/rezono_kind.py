"""Lower a closed Rezono kind using the slot component."""

from collections.abc import Set

from . import rezono_slot
from .rezono_extend import refuse_derived
from .rezono_lowering import Refuse


MEMBERS = {"kind", "world", "applies", "sealed", "slots", "derived"}


def lower(decl: dict, at: str, own: dict[str, str], owners: dict[str, list[str]],
          declared: Set[str], uses: set[str], refuse: Refuse, *, extended_format: bool = False) -> dict | None:
    ok = True
    members = MEMBERS | {"embedded"} if extended_format else MEMBERS
    if extra := set(decl) - members:
        refuse(at, f"a kind with {', '.join(sorted(extra))} is not lowered", "§5.1")
        ok = False
    embedded = decl.get("embedded") is True
    if extended_format and "embedded" in decl and not embedded:
        refuse(at, "an embedded kind must be marked true", "§5.1")
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
    slots = decl.get("slots") or []
    if embedded:
        for index, slot in enumerate(slots):
            if isinstance(slot, dict) and slot.get("identifier") is True:
                refuse(f"{at}/slots/{index}", "an embedded kind cannot declare an identifier", "§5.1")
                ok = False
    if rezono_slot.validate(
        slots, decl["kind"], at, own, owners, uses, refuse, explicit_identifiers=extended_format
    ) and ok:
        return {"attributes": rezono_slot.lower(slots, declared, implicit_identifier=not embedded)}
    return None
