"""Lower a closed Rezono enumeration to its LinkML permissible values."""

from . import rezono_metadata
from .rezono_lowering import Refuse


MEMBERS = {"enum", "world", "values"}


def lower(decl: dict, at: str, refuse: Refuse, *, extended: bool = False) -> dict | None:
    allowed = MEMBERS | {"memberMetadata"} | rezono_metadata.FIELDS if extended else MEMBERS
    if extra := set(decl) - allowed:
        refuse(at, f"an enum with {', '.join(sorted(extra))} is not lowered", "§5.2")
        return None
    if decl.get("world") == "open":
        refuse(at, "an open enum (`world open`) is refused", "§5.2")
        return None
    values = decl["values"]
    duplicates = [i for i, value in enumerate(values) if value in values[:i]]
    if duplicates:
        for i in duplicates:
            refuse(f"{at}/values/{i}", f"the value {values[i]} is written twice in enum {decl['enum']}", "§5.2")
        return None
    members = decl.get("memberMetadata", {})
    if not rezono_metadata.valid(decl) or not isinstance(members, dict):
        refuse(at, "invalid enum metadata", "§5.2")
        return None
    for name, metadata in members.items():
        if (name not in values or not isinstance(metadata, dict) or metadata.keys() - rezono_metadata.FIELDS
                or not rezono_metadata.valid(metadata)):
            refuse(f"{at}/memberMetadata/{name}", f"invalid metadata for enum member {name}", "§5.2")
            return None
    permissible = {value: rezono_metadata.lower(members.get(value, {})) for value in values}
    return {"permissible_values": permissible} | rezono_metadata.lower(decl)
