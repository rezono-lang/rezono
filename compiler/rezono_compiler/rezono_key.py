"""Lower written unique keys to LinkML, retaining names and slot order."""

import re

from .rezono_lowering import Refuse


NAME = re.compile(r"[a-z][a-z0-9_]*")


def lower(keys: object, at: str, refuse: Refuse) -> dict[str, dict[str, list[str]]] | None:
    if not isinstance(keys, list) or not keys:
        refuse(at, "expected a nonempty list of unique keys", "§5.1")
        return None

    result = {}
    for index, key in enumerate(keys):
        here = f"{at}/{index}"
        if not isinstance(key, dict) or key.keys() != {"unique", "slots"}:
            refuse(here, "a unique key needs a name and an ordered list of slots", "§5.1")
            return None
        name, slots = key["unique"], key["slots"]
        if (not isinstance(name, str) or not NAME.fullmatch(name) or not isinstance(slots, list) or not slots
                or any(not isinstance(slot, str) or not NAME.fullmatch(slot) for slot in slots)):
            refuse(here, "a unique key needs a name and an ordered list of slots", "§5.1")
            return None
        if name in result:
            refuse(here, f"the unique key {name} is written twice", "§5.1")
            return None
        if len(slots) != len(set(slots)):
            refuse(here, f"unique key {name} repeats a slot", "§5.1")
            return None
        result[name] = {"unique_key_slots": list(slots)}
    return result
