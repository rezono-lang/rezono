"""Check an extension form before its decision tables are lowered against the pack."""

from .rezono_lowering import Refuse


MEMBERS = {"extend", "derived"}


def refuse_derived(at: str, refuse: Refuse) -> None:
    refuse(at, "a derived value is not lowered yet", "§5.4")


def validate(decl: dict, at: str, imported: bool, refuse: Refuse) -> None:
    """Check the form. `rezono_table` checks the kind, inputs and values against the pack."""
    if extra := set(decl) - MEMBERS:
        refuse(at, f"an extend with {', '.join(sorted(extra))} is not lowered", "§9.1")
        return
    if imported:
        refuse(at, "a decision table in a module of an imported pack is not lowered yet", "§9.1")
        return
    for index, derived in enumerate(decl.get("derived") or []):
        here = f"{at}/derived/{index}"
        table = derived.get("table") if isinstance(derived, dict) else None
        if not isinstance(table, dict):
            refuse_derived(here, refuse)
        elif table.get("table") not in ("unique", "first", "collect"):
            refuse(here, f"a table `{table.get('table')}` is not lowered yet", "§9.1")
        elif "totality" in derived:
            refuse(here, "`total` on a table is not lowered: its proof is the check of `rezono/` (tables.md §7, "
                         "point 3)", "§9.1")
        elif table["table"] == "collect" and derived.get("card") != "*":
            refuse(here, f"a table `collect` gives a set: its derived value is a `{derived['type']}*` (tables.md §2)",
                   "§9.1")
        elif table["table"] != "collect" and "card" in derived:
            refuse(here, f"a derived value `{derived['type']}{derived['card']}` is not lowered yet", "§9.1")
