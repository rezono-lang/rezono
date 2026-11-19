"""Lower a unit declaration to a LinkML type of whole numbers with the annotation the compiler reads for a unit
(decisions/language-units.md, section Lowering)."""

import re

from .rezono_lowering import Refuse


NAME = re.compile(r"[A-Z][A-Za-z0-9]*")
MINOR = re.compile(r"money minor ([A-Z]{3})")
MAJOR = re.compile(r"money ([A-Z]{3})")
FACTOR = re.compile(r"[0-9][0-9^]* [A-Za-z][A-Za-z0-9_]*( per [A-Za-z][A-Za-z0-9_]*)?")


def lower(decl: dict, at: str, refuse: Refuse) -> dict | None:
    name, written = decl.get("unit"), decl.get("is")
    if decl.keys() != {"unit", "is"} or not isinstance(name, str) or NAME.fullmatch(name) is None \
            or not isinstance(written, str):
        refuse(at, "a unit needs exactly a unit name and what it is", "§6")
        return None
    if minor := MINOR.fullmatch(written):
        return {"typeof": "integer", "annotations": {"currency": minor.group(1)}}
    if major := MAJOR.fullmatch(written):
        refuse(at, f"the major unit of a currency is not lowered: money is stored in minor units; write "
                   f"`unit {name} = money minor {major.group(1)}`", "§6")
        return None
    if FACTOR.fullmatch(written):
        return {"typeof": "integer", "annotations": {"unit": written}}
    refuse(at, f"`{written}` is not a unit definition this compiler lowers yet", "§6")
    return None
