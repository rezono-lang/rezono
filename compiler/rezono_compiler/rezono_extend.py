"""Check an extension form before its decision tables are lowered against the pack."""

from .rezono_lowering import Refuse


MEMBERS = {"extend", "derived"}


def refuse_derived(at: str, refuse: Refuse) -> None:
    refuse(at, "a derived value is not lowered yet", "§5.4")


def validate(decl: dict, at: str, imported: bool, refuse: Refuse, *,
             extended_format: bool = False, rezono_1: bool = False, form: dict | None = None) -> None:
    """Check the form. `rezono_table` lowers tables and `rezono_calc` lowers calculated values against the pack; in
    rezono 1, `rezono_derived` lowers the other derived values, which may name their subject (`extend s: K`)."""
    from . import rezono_calc, rezono_derived

    derivations = [rezono_derived.is_derivation(form, derived) for derived in decl.get("derived") or []]
    binder = rezono_1 and "binder" in decl and all(derivations)
    if extra := set(decl) - MEMBERS - ({"binder"} if binder else set()):
        refuse(at, f"an extend with {', '.join(sorted(extra))} is not lowered", "§9.1")
        return
    if imported and not extended_format:
        refuse(at, "a decision table in a module of an imported pack is not lowered yet", "§9.1")
        return
    for index, derived in enumerate(decl.get("derived") or []):
        here = f"{at}/derived/{index}"
        table = derived.get("table") if isinstance(derived, dict) else None
        if rezono_1 and isinstance(table, dict) and table.get("table") == "priority":
            refuse(here, "`table priority` is removed in `rezono 1` (R028); use `table first` instead", "§9.1")
            continue
        if derivations[index]:
            continue
        if not isinstance(table, dict):
            if extended_format:
                rezono_calc.validate_derived(derived, here, refuse)
            else:
                refuse_derived(here, refuse)
        elif imported:
            refuse(at, "a decision table in a module of an imported pack is not lowered yet", "§9.1")
        elif table.get("table") not in ("unique", "first", "priority", "collect"):
            refuse(here, f"a table `{table.get('table')}` is not lowered yet", "§9.1")
        elif "totality" in derived:
            refuse(here, "`total` on a table is not lowered: its proof is the check of `rezono/` (tables.md §7, "
                         "point 3)", "§9.1")
        elif table["table"] == "collect" and derived.get("card") != "*":
            refuse(here, f"a table `collect` gives a set: its derived value is a `{derived['type']}*` (tables.md §2)",
                   "§9.1")
        elif table["table"] != "collect" and "card" in derived:
            refuse(here, f"a derived value `{derived['type']}{derived['card']}` is not lowered yet", "§9.1")
