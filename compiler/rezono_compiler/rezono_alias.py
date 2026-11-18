"""Lower a named scalar alias while preserving its LinkML type identity."""

import re


NAME = re.compile(r"[A-Z][A-Za-z0-9]*")
BASES = {"Bool": "boolean", "Date": "date", "Int": "integer", "Text": "string"}


def lower(decl: dict, at: str, refuse) -> dict[str, str] | None:
    name, base = decl.get("type"), decl.get("base")
    if (decl.keys() != {"type", "base"} or not isinstance(name, str) or NAME.fullmatch(name) is None
            or not isinstance(base, str)):
        refuse(at, "a scalar alias needs exactly a type name and scalar base", "§5.1")
        return None
    if name in BASES:
        refuse(at, f"{name} is a built-in scalar type and cannot be redeclared", "§5.1")
        return None
    if base not in BASES:
        refuse(at, f"{base} is not a supported built-in scalar base", "§5.1")
        return None
    return {"typeof": BASES[base]}
