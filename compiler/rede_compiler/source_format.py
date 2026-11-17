"""The source-format edit boundary (B13, #394 A9): every edit of a fact, rule or calc file goes through one
interface, so the switch of the source text from YAML and Datalog to Reckon (D12) is a migration, not a rewrite.

A `SourceFormat` is what an edit needs to know of the text a pack is written in, per kind of file:

- facts: which files hold them, the records a file states, and one change of `rede.delta/1` (`insert`,
  `delete`, `set`, `unset`) applied to a file's text with the change that undoes it;
- rules: which files hold them, and the tokens a schema operation rewrites;
- calc: which calculation inputs a pack has. No format edits them yet, so a caller that would have to change
  them refuses (the schema operations do, `operate.execution`).

`YAML_DATALOG` is the format of every pack today: it is the canonical writer (`writer.apply_change`) and the
Datalog tokenizer (`rules_dl.tokens`) behind the interface, unchanged. `of` gives the format of a fact file,
and refuses a path no registered format owns. The canonical writer (`writer.apply_delta`), the source writer
(`source_writer`) and the schema operations (`operate`) find their files and edit them through it.

`ReckonStub` shows that a second format fits the interface: it edits the value of one cell of a Reckon fact
table (docs/reckon/publication.md §5.3) and refuses everything else, explicitly. It is not registered, so no
pack is written through it; the Reckon writer of D12 replaces it. It does not parse Reckon: that is `reckon/`.

What the boundary does not cover yet: the schema operations still rewrite the YAML of fact files at the nodes
the YAML composer finds, and the labels, channels and schema files are YAML in every format.
"""
from __future__ import annotations

import re
from abc import ABC, abstractmethod
from pathlib import Path

from . import rules_dl, writer
from .pack import snake

Files = list[tuple[str, Path]]  # (path relative to the pack, the file)


class SourceFormat(ABC):
    """The text a pack's facts, rules and calculations are written in, as an edit sees it."""

    name: str

    @abstractmethod
    def fact_file(self, rel: str) -> bool:
        """Whether `rel` (relative to the pack) is a fact file this format writes."""

    @abstractmethod
    def fact_files(self, pack_dir: str | Path, dirs: tuple[str, ...] = ("facts",)) -> Files:
        """The fact files under the state directories `dirs` of the pack, in a fixed order."""

    @abstractmethod
    def fact_records(self, text: str) -> dict:
        """The records per kind that the text of a fact file states, as written."""

    @abstractmethod
    def edit_fact(self, lay: writer.Layout, text: str, change: dict) -> tuple[str, dict]:
        """One change of `rede.delta/1` applied to the text of a fact file: the new text and the change that
        undoes it. Only what the change concerns may differ; a change it cannot make raises `writer.WriteError`."""

    @abstractmethod
    def rule_files(self, pack_dir: str | Path) -> Files:
        """The rule files of the pack, in a fixed order."""

    @abstractmethod
    def rule_tokens(self, text: str, where: str) -> list:
        """The tokens of a rule file, with their positions, that a schema operation rewrites."""

    @abstractmethod
    def calc_files(self, pack_dir: str | Path) -> list[str]:
        """The calculation inputs of the pack (relative to it). No format edits them yet."""


class YamlDatalog(SourceFormat):
    """Facts in YAML (`facts/*.yaml`, `scenarios/`, `diagnostics/`), rules in Datalog (`rules/*.dl`), calculations
    in YAML (`calc/`, `sweeps.yaml`): the canonical writer and the Datalog tokenizer, as they are."""

    name = "yaml-datalog"

    def fact_file(self, rel: str) -> bool:
        return bool(writer.FACT_FILE.match(rel))

    def fact_files(self, pack_dir: str | Path, dirs: tuple[str, ...] = ("facts",)) -> Files:
        return [(f"{d}/{f.name}", f) for d in dirs for f in sorted((Path(pack_dir) / d).glob("*.yaml"))]

    def fact_records(self, text: str) -> dict:
        return writer.parse(text)[2]

    def edit_fact(self, lay: writer.Layout, text: str, change: dict) -> tuple[str, dict]:
        return writer.apply_change(lay, text, change)

    def rule_files(self, pack_dir: str | Path) -> Files:
        return [(f"rules/{f.name}", f) for f in sorted((Path(pack_dir) / "rules").glob("*.dl"))]

    def rule_tokens(self, text: str, where: str) -> list:
        return rules_dl.tokens(text, where)

    def calc_files(self, pack_dir: str | Path) -> list[str]:
        return [n for n in ("calc", "sweeps.yaml") if (Path(pack_dir) / n).exists()]


YAML_DATALOG = YamlDatalog()
FORMATS: tuple[SourceFormat, ...] = (YAML_DATALOG,)  # the formats packs are written in; D12 adds Reckon


def of(rel: str) -> SourceFormat:
    """The format that writes the fact file `rel`; a path no format owns is refused."""
    for fmt in FORMATS:
        if fmt.fact_file(rel):
            return fmt
    raise writer.WriteError(f"{rel!r}: no source format writes this file as a fact file")


# --- A stub of Reckon facts ----------------------------------------------------------------------------------

RECKON_FILE = re.compile(r"^reckon/[a-z][a-z0-9_]*(/[a-z][a-z0-9_]*)*\.reckon$")
FACT_HEAD = re.compile(r"^fact +([A-Za-z][A-Za-z0-9_]*) *$")
TABLE_ROW = re.compile(r"^ +\|.*\| *$")
NOT_BUILT = "the Reckon source format is a stub (B13): {what} waits for the Reckon writer (D12)"


class ReckonStub(SourceFormat):
    """Fact tables of Reckon modules (`reckon/**/*.reckon`): only `set` of a cell that has a value is built.

    A table is `fact <Kind>`, then a header row of column names, the first `id`, then one row per record, each
    `| cell | cell |`. A `set` replaces the text of one cell within the cell's width, so every other byte stays;
    its inverse sets the old text back, which gives the same bytes. A cell is written as it reads, so a value is
    plain text without `|` or a line break. A wider value, every other change, rules and calculations are
    refused."""

    name = "reckon-stub"

    def fact_file(self, rel: str) -> bool:
        return bool(RECKON_FILE.match(rel))

    def fact_files(self, pack_dir: str | Path, dirs: tuple[str, ...] = ("facts",)) -> Files:
        if "facts" not in dirs:  # the fact tables of a module are main state
            return []
        root = Path(pack_dir)
        found = ((f.relative_to(root).as_posix(), f) for f in sorted((root / "reckon").rglob("*.reckon")))
        return [(rel, f) for rel, f in found if self.fact_file(rel)]

    def tables(self, text: str) -> dict[str, tuple[list[str], list[tuple[int, list[str]]]]]:
        """Per table as written: its columns, and per row its line (0-based) and cells."""
        lines, out, i = text.split("\n"), {}, 0
        while i < len(lines):
            head = FACT_HEAD.match(lines[i])
            i += 1
            if not head:
                continue
            rows = []
            while i < len(lines) and TABLE_ROW.match(lines[i]):
                rows.append((i, [c.strip() for c in lines[i].strip()[1:-1].split("|")]))
                i += 1
            if not rows or rows[0][1][:1] != ["id"] or any(len(c) != len(rows[0][1]) for _, c in rows):
                raise writer.WriteError(f"line {i}: fact {head[1]}: a header row with id first, then rows of its width")
            if head[1] in out:
                raise writer.WriteError(f"fact {head[1]} appears twice")
            out[head[1]] = (rows[0][1], rows[1:])
        return out

    def fact_records(self, text: str) -> dict:
        return {kind: [dict(zip(cols, cells)) for _, cells in rows] for kind, (cols, rows) in self.tables(text).items()}

    def edit_fact(self, lay: writer.Layout, text: str, change: dict) -> tuple[str, dict]:
        if change.get("op") != "set":
            raise writer.WriteError(NOT_BUILT.format(what=f"the change {change.get('op')!r}"))
        kind, key, slot, value = (change.get(k) for k in ("kind", "key", "slot", "value"))
        tables = {snake(k): t for k, t in self.tables(text).items()}
        if kind not in tables:
            raise writer.WriteError(f"{kind}: no fact table of this kind in the module")
        cols, rows = tables[kind]
        if slot not in cols[1:]:
            raise writer.WriteError(f"{kind}: no column '{slot}' (the id does not change)")
        if not isinstance(value, str) or not value or value != value.strip() or re.search(r"[|\r\n]", value):
            raise writer.WriteError(f"{kind} {key}.{slot}: a cell is plain text without '|' or a line break")
        hits = [(n, cells) for n, cells in rows if cells[0] == key]
        if len(hits) != 1:
            raise writer.WriteError(f"{kind} {key}: {'not found' if not hits else 'appears more than once'}")
        n, cells = hits[0]
        col = cols.index(slot)
        if cells[col] == "n/a":
            raise writer.WriteError(NOT_BUILT.format(what="a value for a cell that is n/a"))
        lines = text.split("\n")
        bars = [i for i, c in enumerate(lines[n]) if c == "|"]
        start, end = bars[col] + 1, bars[col + 1]
        cell = lines[n][start:end]
        lead, tail = len(cell) - len(cell.lstrip(" ")), " " if cell.endswith(" ") else ""
        room = len(cell) - lead - len(tail)
        if len(value) > room:  # a wider column moves every row of the table: that is the printer's (D12)
            raise writer.WriteError(NOT_BUILT.format(what=f"{kind} {key}.{slot}: a value wider than its column"))
        lines[n] = lines[n][:start] + cell[:lead] + value.ljust(room) + tail + lines[n][end:]
        inverse = {"op": "set", **({"file": change["file"]} if "file" in change else {}), "kind": kind, "key": key,
                   "slot": slot, "value": cells[col]}
        return "\n".join(lines), inverse

    def rule_files(self, pack_dir: str | Path) -> Files:
        return []

    def rule_tokens(self, text: str, where: str) -> list:
        raise writer.WriteError(NOT_BUILT.format(what=f"{where}: a rule written in Reckon"))

    def calc_files(self, pack_dir: str | Path) -> list[str]:
        return []


RECKON_STUB = ReckonStub()
