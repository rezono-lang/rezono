"""Resolve written slots and lower them to LinkML attributes in source order."""

from collections.abc import Mapping, Set

from . import rezono_cardinality, rezono_numeric_limits
from .rezono_lowering import Refuse


MEMBERS = {"slot", "type", "card"}
BUILTIN_RANGES = {"Bool": "boolean", "Date": "date", "Text": "string"}
LIST_CARDS = ("*", "+")


def builtin_range(name: str, declared: bool, *, extended_form: bool = False) -> str | None:
    # Bool became a built-in after modules could already declare it as a pack name.
    if name == "Bool" and declared:
        return None
    if name == "Int":
        return "integer" if extended_form and not declared else None
    return BUILTIN_RANGES.get(name)


def constraint_facets(slot: dict, range_name: str | None) -> dict[str, int | bool]:
    """Resolve the authored bounds for a list or a single integer value."""
    card = slot.get("card", "?")
    explicit = slot.get("identifier") is True
    constraints = slot["constraints"]
    if isinstance(constraints, list) and any(
        isinstance(constraint, dict) and "cardinality" in constraint for constraint in constraints
    ):
        facets = rezono_cardinality.bounded_list(card, constraints)
        if explicit:
            raise ValueError("a bounded list cannot be an identifier")
        return facets
    if range_name != "integer" or explicit or card != "?":
        raise ValueError("integer limits need an Int slot that is single-valued and is not an identifier")
    return rezono_numeric_limits.lower(constraints)


def lower(slots: list[dict], declared: Set[str], *, implicit_identifier: bool = True) -> dict[str, dict]:
    """Lower slots in written order, using an implicit identifier only when needed."""
    out: dict[str, dict] = {}
    if implicit_identifier and not any(slot.get("identifier") is True for slot in slots):
        out["id"] = {"identifier": True}
    for slot in slots:
        name = slot["type"]
        # Validation has already checked whether this version admits the built-in range.
        range_name = builtin_range(name, name in declared, extended_form=True) or name
        attribute: dict[str, object] = {"range": range_name}
        if "constraints" in slot:
            attribute.update(constraint_facets(slot, range_name))
        if slot.get("identifier") is True:
            attribute["identifier"] = True
        elif "card" not in slot or slot["card"] == "+":
            attribute["required"] = True
        if slot.get("card") in LIST_CARDS:
            attribute["multivalued"] = True
        out[slot["slot"]] = attribute
    return out


def validate(slots: list, kind: str, at: str, own: Mapping[str, str], owners: Mapping[str, list[str]],
             uses: set[str], refuse: Refuse, *, explicit_identifiers: bool = False) -> bool:
    """Check slot forms and resolve references against all the modules of the pack."""
    ok = True
    seen: set[str] = set()
    identifier_seen = False
    # The extended module form also carries slot constraints.
    allowed = MEMBERS | {"identifier", "constraints"} if explicit_identifiers else MEMBERS
    for index, slot in enumerate(slots):
        here = f"{at}/slots/{index}"
        extra = sorted(set(slot) - allowed) if isinstance(slot, dict) else []
        if not isinstance(slot, dict) or extra:
            refuse(here, f"a slot with {', '.join(extra)} is not lowered" if extra else "not a slot of the form",
                   "§5.1")
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
        card = slot.get("card", "?")
        has_constraints = "constraints" in slot
        if not has_constraints and explicit and card in LIST_CARDS:
            refuse(here, "an identifier cannot be multivalued", "§5.1")
            ok = False
        elif card not in ("?", *LIST_CARDS):
            refuse(here, f"a slot `{slot['type']}{slot['card']}` is not lowered (no ticket yet)")
            ok = False
        name, found = slot["type"], owners.get(slot["type"], [])
        range_name = builtin_range(name, name in own or bool(found), extended_form=explicit_identifiers)
        if has_constraints:
            try:
                constraint_facets(slot, range_name)
            except ValueError as error:
                refuse(here, str(error), "§5.1")
                ok = False
        if name in own or range_name is not None:
            continue
        if len(found) == 1:
            uses.add(found[0])
            continue
        refuse(here, f"{name} is declared by modules {' and '.join(found)} of this pack" if found else
               f"{name} is not Date, Text, or an enum or a kind of this pack. Built-in Bool is also supported", "§5.1")
        ok = False
    return ok
