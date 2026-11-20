"""Resolve written slots and lower them to LinkML attributes in source order."""

from collections.abc import Mapping, Set

from . import rezono_cardinality, rezono_metadata, rezono_numeric_limits
from .rezono_lowering import Refuse


MEMBERS = {"slot", "type", "card", "inverse"}
BUILTIN_RANGES = {"Bool": "boolean", "Date": "date", "Text": "string"}
LIST_CARDS = ("*", "+")


def builtin_range(name: str, declared: bool) -> str | None:
    # Bool became a built-in after modules could already declare it as a pack name.
    if name == "Bool" and declared:
        return None
    if name == "Int":
        return None if declared else "integer"
    return BUILTIN_RANGES.get(name)


def constraint_facets(slot: dict, is_integer: bool) -> dict[str, str | int | bool]:
    """Keep the written pattern and let the pack loader validate it as a LinkML facet."""
    facets: dict[str, str | int | bool] = {}
    constraints = slot["constraints"]
    if isinstance(constraints, list):
        bounds = []
        for constraint in constraints:
            if not isinstance(constraint, dict) or "pattern" not in constraint:
                bounds.append(constraint)
                continue
            if constraint.keys() != {"pattern"} or not isinstance(constraint["pattern"], str):
                raise ValueError("a pattern constraint needs one text value")
            if "pattern" in facets:
                raise ValueError("the pattern constraint is written twice")
            facets["pattern"] = constraint["pattern"]
        if "pattern" in facets and not bounds:
            if slot.get("identifier") is True and slot.get("card") in LIST_CARDS:
                raise ValueError("an identifier cannot be multivalued")
            return facets
        constraints = bounds
    facets.update(bound_facets(slot, is_integer, constraints))
    return facets


def bound_facets(slot: dict, is_integer: bool, constraints: object) -> dict[str, int | bool]:
    """Resolve the authored bounds for a list or a single integer value."""
    card = slot.get("card", "?")
    explicit = slot.get("identifier") is True
    if isinstance(constraints, list) and any(
        isinstance(constraint, dict) and "cardinality" in constraint for constraint in constraints
    ):
        facets = rezono_cardinality.bounded_list(card, constraints)
        if explicit:
            raise ValueError("a bounded list cannot be an identifier")
        return facets
    if not is_integer or explicit or card != "?":
        raise ValueError("integer limits need an Int slot that is single-valued and is not an identifier")
    return rezono_numeric_limits.lower(constraints)


def resolve_prefixed(
    name: str,
    aliases: Mapping[str, Mapping[str, list[str]]] | None,
    at: str,
    refuse: Refuse,
    *,
    role: str = "",
) -> str | None:
    """Resolve `prefix.Name` against the module's aliased `use` packs, returning `Name` or refusing at `at`."""
    prefix, _, local = name.partition(".")
    if aliases is None or prefix not in aliases:
        refuse(at, f"prefix {prefix} is not declared by a `use` line", "§5.1")
        return None
    found = aliases[prefix].get(local, [])
    if len(found) == 1:
        return local
    subject = f"{role} {name}" if role else name
    reason = (
        f"{subject} is declared by modules {' and '.join(found)}"
        if found
        else f"{subject} is not declared by the pack imported as {prefix}"
    )
    refuse(at, reason, "§5.1")
    return None


def lower(slots: list[dict], declared: Set[str], *, implicit_identifier: bool = True) -> dict[str, dict]:
    """Lower slots in written order, using an implicit identifier only when needed."""
    out: dict[str, dict] = {}
    if implicit_identifier and not any(slot.get("identifier") is True for slot in slots):
        out["id"] = {"identifier": True}
    for slot in slots:
        name = slot["type"]
        if "." in name:
            range_name = name.partition(".")[2]
        else:
            # Validation has already checked whether this version admits the built-in range.
            range_name = builtin_range(name, name in declared) or name
        attribute: dict[str, object] = {"range": range_name}
        attribute.update(rezono_metadata.lower(slot))
        if "slotUri" in slot:
            attribute["slot_uri"] = slot["slotUri"]
        if "constraints" in slot:
            attribute.update(constraint_facets(slot, range_name))
        if slot.get("identifier") is True:
            attribute["identifier"] = True
        elif "card" not in slot or slot["card"] == "+":
            attribute["required"] = True
        if slot.get("card") in LIST_CARDS:
            attribute["multivalued"] = True
        if slot.get("embedded") is True:
            attribute["inlined"] = True
        if slot.get("world") == "open":
            attribute.setdefault("annotations", {})["world"] = "open"
        if "inverse" in slot:
            attribute["inverse"] = slot["inverse"]
        out[slot["slot"]] = attribute
    return out


def inverse_points_back(slot: dict, kind: str, here: str, kinds: Mapping[str, list], own: Mapping[str, str],
                        owners: Mapping[str, list[str]], refuse: Refuse) -> bool:
    """An inverse names a forward slot of the kind its type names, and that slot's type is the kind that declares the
    inverse (decisions/language-inverse-references.md). `kinds` holds the slots of each kind of this module."""
    forward, target = slot["inverse"], slot["type"]
    if not isinstance(forward, str):
        refuse(here, "an inverse names the forward slot", "§5.1")
        return False
    if target not in own and owners.get(target):
        refuse(here, f"an inverse of a slot of {target}, which another module declares, is not lowered yet", "§5.1")
        return False
    found = [s for s in kinds.get(target, []) if isinstance(s, dict) and s.get("slot") == forward]
    if not found:
        refuse(here, f"the inverse {forward} is not a slot of {target}", "§5.1")
        return False
    if found[0].get("type") != kind:
        refuse(here, f"the inverse {forward} of {target} is a {found[0].get('type')}, not a {kind}", "§5.1")
        return False
    if found[0] is slot or (target == kind and forward == slot.get("slot")):
        refuse(here, f"the inverse {forward} of {target} cannot be the slot itself", "§5.1")
        return False
    if "inverse" in found[0]:
        refuse(here, f"the inverse {forward} of {target} is itself an inverse, not a forward slot", "§5.1")
        return False
    return True


def validate(slots: list, kind: str, at: str, own: Mapping[str, str], owners: Mapping[str, list[str]],
             uses: set[str], refuse: Refuse, *, extended: bool = False, open_kind: bool = False,
             aliases: Mapping[str, Mapping[str, list[str]]] | None = None,
             kinds: Mapping[str, list] | None = None,
             integer_types: Mapping[str, Set[str]] | None = None,
             own_module: str = "") -> bool:
    """Check slot forms and resolve references against all the modules of the pack."""
    ok = True
    seen: set[str] = set()
    identifier_seen = False
    allowed = (MEMBERS | {"identifier", "slotUri", "constraints", "embedded", "world"} | rezono_metadata.FIELDS
               if extended else MEMBERS)
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
        embedded = slot.get("embedded") is True
        if "embedded" in slot and not embedded:
            refuse(here, "an embedded reference must be marked true", "§5.1")
            ok = False
        if "identifier" in slot and not explicit:
            refuse(here, "an explicit identifier must be marked true", "§5.1")
            ok = False
        if "world" in slot:
            # The pack loader keeps the world of an identifier on its kind and an open kind's slots open.
            if slot["world"] not in ("open", "closed"):
                refuse(here, "a slot world is `open` or `closed`", "§5.1")
                ok = False
            elif explicit:
                refuse(here, "an identifier has the world of its kind", "§5.1")
                ok = False
            elif open_kind and slot["world"] != "open":
                refuse(here, "a slot of an open kind is open", "§5.1")
                ok = False
        if explicit:
            if embedded:
                refuse(here, "an embedded reference cannot be an identifier", "§5.1")
                ok = False
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
        if "inverse" in slot and not inverse_points_back(slot, kind, here, kinds or {}, own, owners, refuse):
            ok = False
        name = slot["type"]
        ints = integer_types or {}
        if "." in name:
            resolved = resolve_prefixed(name, aliases, here, refuse)
            if resolved is None:
                ok = False
            if has_constraints:
                prefix, _, local = name.partition(".")
                targets = (aliases or {}).get(prefix, {}).get(local, [])
                is_integer = len(targets) == 1 and local in ints.get(targets[0], ())
                try:
                    constraint_facets(slot, is_integer)
                except ValueError as error:
                    refuse(here, str(error), "§5.1")
                    ok = False
            continue
        found = owners.get(name, [])
        range_name = builtin_range(name, name in own or bool(found))
        is_integer = (
            range_name == "integer"
            or (name in own and name in ints.get(own_module, ()))
            or (len(found) == 1 and name in ints.get(found[0], ()))
        )
        if has_constraints:
            try:
                constraint_facets(slot, is_integer)
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
