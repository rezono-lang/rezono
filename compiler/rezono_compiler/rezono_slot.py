"""Resolve written slots and lower them to LinkML attributes in source order."""

from collections.abc import Mapping, Set

from . import rezono_metadata
from .rezono_lowering import Refuse


MEMBERS = {"slot", "type", "card"}
BUILTIN_RANGES = {"Bool": "boolean", "Date": "date", "Text": "string"}


def builtin_range(name: str, declared: bool) -> str | None:
    # Bool became a built-in after modules could already declare it as a pack name.
    if name == "Bool" and declared:
        return None
    return BUILTIN_RANGES.get(name)


def lower(slots: list[dict], declared: Set[str]) -> dict[str, dict]:
    """Lower slots in written order, using an implicit identifier only when needed."""
    out: dict[str, dict] = {} if any(slot.get("identifier") is True for slot in slots) else {"id": {"identifier": True}}
    for slot in slots:
        name = slot["type"]
        attribute = {"range": builtin_range(name, name in declared) or name} | rezono_metadata.lower(slot)
        if "slotUri" in slot:
            attribute["slot_uri"] = slot["slotUri"]
        if slot.get("identifier") is True:
            attribute["identifier"] = True
        elif "card" not in slot:
            attribute["required"] = True
        out[slot["slot"]] = attribute
    return out


def validate(slots: list, kind: str, at: str, own: Mapping[str, str], owners: Mapping[str, list[str]],
             uses: set[str], refuse: Refuse, *, extended: bool = False) -> bool:
    """Check slot forms and resolve references against all the modules of the pack."""
    ok = True
    seen: set[str] = set()
    identifier_seen = False
    allowed = MEMBERS | {"identifier", "slotUri"} | rezono_metadata.FIELDS if extended else MEMBERS
    for index, slot in enumerate(slots):
        here = f"{at}/slots/{index}"
        extra = sorted(set(slot) - allowed) if isinstance(slot, dict) else []
        if not isinstance(slot, dict) or extra:
            refuse(here, f"a slot with {', '.join(extra)} is not lowered" if extra else "not a slot of the form",
                   "§5.1")
            ok = False
            continue
        if not rezono_metadata.valid(slot) or ("slotUri" in slot and not isinstance(slot["slotUri"], str)):
            refuse(here, "invalid slot metadata", "§5.1")
            ok = False
            continue
        if slot["slot"] in seen:
            refuse(here, f"the slot {slot['slot']} is written twice in kind {kind}", "§5.1")
            ok = False
        seen.add(slot["slot"])
        explicit = slot.get("identifier") is True
        if "identifier" in slot and not explicit:
            refuse(here, "an explicit identifier must be marked true", "§5.1")
            ok = False
        if explicit:
            if identifier_seen:
                refuse(here, f"kind {kind} has more than one identifier", "§5.1")
                ok = False
            identifier_seen = True
        if slot["slot"] == "id" and not explicit:
            refuse(here, "a slot named `id` is refused: `id` identifies the elements of a kind", "§5.1")
            ok = False
        if slot.get("card", "?") != "?":
            refuse(here, f"a slot `{slot['type']}{slot['card']}` is not lowered (no ticket yet)")
            ok = False
        name, found = slot["type"], owners.get(slot["type"], [])
        if name in own or builtin_range(name, bool(found)) is not None:
            continue
        if len(found) == 1:
            uses.add(found[0])
            continue
        refuse(here, f"{name} is declared by modules {' and '.join(found)} of this pack" if found else
               f"{name} is not Date, Text, or an enum or a kind of this pack. Built-in Bool is also supported", "§5.1")
        ok = False
    return ok
