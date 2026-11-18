"""Lower a closed Rezono enumeration to its LinkML permissible values."""

from .rezono_lowering import Refuse


MEMBERS = {"enum", "world", "values"}


def lower(decl: dict, at: str, refuse: Refuse) -> dict | None:
    if extra := set(decl) - MEMBERS:
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
    return {"permissible_values": {value: {} for value in values}}
