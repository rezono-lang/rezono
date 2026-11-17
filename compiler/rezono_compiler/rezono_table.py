"""Decision tables of modules written in Rezono, lowered to rules (docs/rezono/publication.md §9.1, RV-C36).

A derived value with `table unique` under `extend K` lowers to the rules a rule file could state: a named outcome
of K (decision W7) with one state for every element, the relation of its value, and an invariant that two rows
never apply to one element. The rules are written as the text of a rule file and `rules_dl.read` reads them as it
reads `rules/*.dl`, so every check, engine, proof and oracle holds for them unchanged; each rule's origin is the
module's file and the line of the part of the table it comes from. Nothing is evaluated here, and nothing is
approximated: what this slice does not lower is refused at its line.

The meaning is that of docs/rezono/tables.md §3 for `unique`, over inputs that are slots of K:

- a cell is true when the input's value passes one of its tests, false when the input has a value that passes
  none, `n/a` when an optional input has no value, and unknown when a required one has none (publication.md §4);
- a row applies when every cell is true; it is undecided when one of its cells is unknown and none is false
  (Appendix A.1: `n/a and unknown` is unknown); else it does not apply;
- the value is the output of the row that applies; two rows that apply are `invalid exception_conflict`, which
  the invariant `<k>_<d>_conflict` blocks; no row that applies and one undecided is `unknown no_value`; neither
  is `unknown no_row_applies`.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

from . import rezono_module

INTEGER = re.compile(r"^-?(0|[1-9][0-9]*)$")
NO_VALUE, NO_ROW_APPLIES = "no_value", "no_row_applies"
SECTION = "§9.1"


@dataclass
class Generated:
    """The rules of one module's tables as the text of a rule file, and the module's line of each of its lines."""
    module: str  # rezono/<path>.rezono: the file every origin and refusal names
    stem: str  # the rule module of its rules: the module's id, `/` as `_`
    lines: list[str] = field(default_factory=list)
    at: list[int] = field(default_factory=list)  # at[i] is the module's line of lines[i]

    def add(self, line: int, text: str) -> None:
        self.lines.append(text)
        self.at.append(line)

    @property
    def text(self) -> str:
        return "\n".join(self.lines) + "\n"


def lower_pack(pack, meta: dict, pack_dir: Path, errors: list[str]) -> list[Generated]:
    """The tables of every module of the pack itself, as rule text. A module of an imported pack holds no table
    yet (rezono_module refuses one there), so this reads the root pack's modules only. `meta` is its pack.yaml."""
    out = []
    for d in rezono_module.declared(meta, pack_dir, []):
        form = rezono_module.read_form(pack_dir, d, [])
        if form is None:
            continue
        gen = Generated(d.module, d.id.replace("/", "_"))
        lower(pack, pack_dir, d, form, gen, errors)
        if gen.lines:
            out.append(gen)
    return out


def lower(pack, pack_dir: Path, d, form: dict, gen: Generated, errors: list[str]) -> None:
    where, line = f"{pack_dir.name}/{d.module}", rezono_module.lines(form)

    def place(at: str) -> int:
        while at and at not in line:
            at = at.rsplit("/", 1)[0]
        return line.get(at, 1)

    def refuse(at: str, what: str) -> None:
        errors.append(f"{where}:{place(at)}: {what} ({rezono_module.PAGE} {SECTION})")

    for i, decl in enumerate(form["module"]["decls"]):
        if not isinstance(decl, dict) or "extend" not in decl:
            continue
        at = f"/decls/{i}"
        k = next((n for n, kind in pack.kinds.items() if kind.cls == decl["extend"]), None)
        if k is None:
            refuse(at, f"{decl['extend']} is not a kind of this pack")
            continue
        kind = pack.kinds[k]
        if kind.world != "closed":
            refuse(at, f"{decl['extend']} is open: a table reads closed relations only (decision W7)")
            continue
        if kind.seal is not None or kind.sealed_with is not None:
            refuse(at, f"{decl['extend']} is sealed: a table on a sealed kind is not lowered yet")
            continue
        slots = {s.name: s for a in reversed(pack.ancestors(k)) for s in pack.kinds[a].slots.values()}
        for j, dv in enumerate(decl.get("derived") or []):
            table(pack, k, slots, dv, f"{at}/derived/{j}", place, refuse, gen)


def table(pack, k: str, slots: dict, dv: dict, at: str, place, refuse, gen: Generated) -> None:
    """One derived value with `table unique` (rezono_module refuses every other form), as rules."""
    from .pack import snake
    from .rules_dl import SQL

    t, name = dv["table"], f"{k}_{dv['derived']}"
    out_enum = snake(dv["type"])
    if out_enum not in pack.enums:
        refuse(at, f"{dv['derived']} is a {dv['type']}: a table's output is an enum in this slice")
        return
    inputs, ok = [], True
    for j, e in enumerate(t["inputs"]):
        here = f"{at}/table/inputs/{j}"
        path = e.get("path") if isinstance(e, dict) and set(e) == {"path"} else None
        s = slots.get(path[0]) if isinstance(path, list) and len(path) == 1 else None
        if not isinstance(path, list) or len(path) != 1:
            refuse(here, "an input is a slot of the kind in this slice; a path or an expression is not lowered yet")
        elif s is None:
            refuse(here, f"{path[0]} is not a slot of {pack.kinds[k].cls}")
        elif s.multivalued:
            refuse(here, f"{path[0]} holds more than one value: an input holds one")
        elif s.enum is None and not (SQL.get(s.sql_type) == "integer" and s.currency is None and s.unit is None):
            refuse(here, f"{path[0]} is a {s.range}: an input is an enum or a whole number in this slice")
        else:
            inputs.append(s)
            continue
        ok = False
        inputs.append(None)
    if not ok:
        return
    cells: list[list[list[tuple[str, str]]]] = []  # per row, per column: (condition, pointer) of each test
    for r, row in enumerate(t["rows"]):
        conds = []
        for j, cell in enumerate(row["tests"]):
            here = f"{at}/table/rows/{r}/tests/{j}"
            alts = []
            for n, test in enumerate([] if cell == "-" else cell):
                c = condition(pack, inputs[j], test, f"{here}/{n}", refuse)
                ok = ok and c is not None
                alts.append((c, f"{here}/{n}"))
            conds.append(alts)
        v = row["value"].get("lit") if isinstance(row["value"], dict) else None
        if v not in pack.enums[out_enum]:
            refuse(f"{at}/table/rows/{r}/value", f"{v} is not a value of {dv['type']}")
            ok = False
        cells.append(conds)
    if not ok:
        return
    # The inputs that can be unknown: a required slot that the rows test (publication.md §4, point 5).
    unknown = [j for j, s in enumerate(inputs) if s.required and any(row[j] for row in cells)]
    head = place(at)
    gen.add(head, f"// @outcome {k}")
    gen.add(head, f".decl {name}({k}: symbol, state: symbol, reason: symbol)")
    gen.add(head, f".decl {name}_value({k}: symbol, value: symbol)")
    gen.add(head, f".decl {name}_row({k}: symbol, row: number)")
    gen.add(head, f".decl {name}_cell({k}: symbol, row: number, column: number)")
    gen.add(head, f".decl {name}_applies({k}: symbol)")
    gen.add(head, "// @invariant")
    gen.add(head, f".decl {name}_conflict({k}: symbol, row: number, other: number)")
    if unknown:
        gen.add(head, f".decl {name}_has({k}: symbol, column: number)")
        gen.add(head, f".decl {name}_missing({k}: symbol, column: number)")
        gen.add(head, f".decl {name}_false({k}: symbol, row: number)")
        gen.add(head, f".decl {name}_open({k}: symbol, row: number)")
        gen.add(head, f".decl {name}_undecided({k}: symbol)")
    for r, conds in enumerate(cells, 1):
        rline = place(f"{at}/table/rows/{r - 1}")
        tested = [j for j, alts in enumerate(conds) if alts]
        for j in tested:
            for c, here in conds[j]:
                gen.add(place(here), f"{name}_cell(x, {r}, {j + 1}) :- {c}.")
        body = ", ".join([f"{k}(x)"] + [f"{name}_cell(x, {r}, {j + 1})" for j in tested])
        gen.add(rline, f"{name}_row(x, {r}) :- {body}.")
        gen.add(rline, f'{name}_value(x, "{t["rows"][r - 1]["value"]["lit"]}") :- {name}_row(x, {r}).')
        if unknown:
            for j in tested:
                gen.add(rline, f"{name}_false(x, {r}) :- {inputs[j].table}(x, _), !{name}_cell(x, {r}, {j + 1}).")
            for j in tested:
                if j in unknown:
                    gen.add(rline, f"{name}_open(x, {r}) :- {name}_missing(x, {j + 1}), !{name}_false(x, {r}).")
    for j in unknown:
        iline = place(f"{at}/table/inputs/{j}")
        gen.add(iline, f"{name}_has(x, {j + 1}) :- {inputs[j].table}(x, _).")
        gen.add(iline, f"{name}_missing(x, {j + 1}) :- {k}(x), !{name}_has(x, {j + 1}).")
    gen.add(head, f"{name}_applies(x) :- {name}_row(x, _).")
    gen.add(head, f"{name}_conflict(x, m, n) :- {name}_row(x, m), {name}_row(x, n), m < n.")
    gen.add(head, f'{name}(x, "known", "") :- {name}_applies(x).')
    if unknown:
        gen.add(head, f"{name}_undecided(x) :- {name}_open(x, _).")
        gen.add(head, f'{name}(x, "unknown", "{NO_VALUE}") :- {name}_undecided(x), !{name}_applies(x).')
        gen.add(head, f'{name}(x, "unknown", "{NO_ROW_APPLIES}") :- {k}(x), !{name}_applies(x), !{name}_undecided(x).')
    else:
        gen.add(head, f'{name}(x, "unknown", "{NO_ROW_APPLIES}") :- {k}(x), !{name}_applies(x).')


def condition(pack, s, test, at: str, refuse) -> str | None:
    """The body that holds when the input `s` passes one test: a value (equality) or a range (tables.md §2)."""
    if isinstance(test, dict) and set(test) == {"lit"}:
        v = test["lit"]
        if s.enum is not None:
            if v not in pack.enums[s.enum]:
                refuse(at, f"{v} is not a value of {s.range}")
                return None
            return f'{s.table}(x, "{v}")'
        if not isinstance(v, str) or not INTEGER.match(v):
            refuse(at, f"{v} is not a whole number")
            return None
        return f"{s.table}(x, {int(v)})"
    b = test.get("between") if isinstance(test, dict) and set(test) == {"between"} else None
    if not isinstance(b, dict) or s.enum is not None:
        refuse(at, "a range needs an ordered type, and an enum has none in this slice")
        return None
    ends = []
    for side, op in (("from", ">="), ("to", "<=" if b.get("op") == ".." else "<")):
        if side in b:
            v = b[side].get("lit") if isinstance(b[side], dict) else None
            if not isinstance(v, str) or not INTEGER.match(v):
                refuse(at, f"{v} is not a whole number")
                return None
            ends.append(f"v {op} {int(v)}")
    return ", ".join([f"{s.table}(x, v)"] + ends)
