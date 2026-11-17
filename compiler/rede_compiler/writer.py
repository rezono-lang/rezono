"""The canonical writer: apply a delta to a pack's fact files, changing only the lines it must.

The writer never emits a whole file again. It finds each record's lines with the YAML composer and
replaces, inserts or removes only those lines, so untouched lines keep their bytes and comments.
A record it writes is in canonical form (docs/compiler.md#the-canonical-writer):

- the identifier first, then the slots in schema order, from the root kind down;
- one record per line in flow style; a kind with an inlined slot gets one line per slot;
- plain scalars where YAML reads them back unchanged, else single quotes, else double quotes;
- whole numbers exact, dates as ISO dates, booleans as true/false; LF and a final newline.

A file written as JSON lines (`- {"id": "a1", ...}`, as generated packs do) keeps that dialect: a
record is written the way its section, or else the file, already writes records. In JSON a date is
ISO text (decision W5).

Rows are kept in identifier order (numbers by value, text in natural order), sections in schema
order. Removing the last row of a section removes the section. Comment lines directly above a row or
a section belong to it. Every change is checked: the new text must read back as the old facts with
the change applied, or the writer stops.

A fact file with a source companion (`facts/<file>.sources.yaml`, S25) is written together with it
(`source_writer`): the real origin of a written row comes from the caller, never from the delta.

Usage: python -m rede_compiler.writer apply <pack> <delta.json> [--inverse <out.json>] [--origins <o.json>] [--undo]
(the pack in a work dir: `work_dir`, then `checkout`, which brings the packs it imports along)
"""

from __future__ import annotations

import argparse
import datetime
import functools
import json
import os
import re
import stat
import sys
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

import yaml

from . import modules, reckon_module
from . import pack as packs
from . import source_format
from .names import ISO_DATE

Loader = getattr(yaml, "CSafeLoader", yaml.SafeLoader)

FORMAT = "rede.delta/1"
OPS = ("insert", "delete", "set", "unset")
FACT_FILE = re.compile(r"^facts/[a-z0-9][a-z0-9_-]*\.yaml$")
SOURCES_FILE = re.compile(r"^facts/[a-z0-9][a-z0-9_-]*\.sources\.yaml$")  # a fact file's source companion (S25)
INTEGER = re.compile(r"^-?(0|[1-9][0-9]*)$")
PREFIX = re.compile(r"^ *- +$")
NULL = "tag:yaml.org,2002:null"
PLAIN_START = set("-?:,[]{}#&*!|>'\"%@`")
ESCAPES = {"\0": "\\0", "\t": "\\t", "\n": "\\n", "\r": "\\r", '"': '\\"', "\\": "\\\\"}
JSON_ESCAPES = {"\b": "\\b", "\t": "\\t", "\n": "\\n", "\f": "\\f", "\r": "\\r", '"': '\\"', "\\": "\\\\"}


class WriteError(Exception):
    pass


# --- The pack's order ----------------------------------------------------------------------------

@dataclass
class Layout:
    """What the writer needs from a pack: the compiler's model plus the order of the schema files."""
    pack: packs.Pack
    kinds: list[str]  # schema order
    declared: dict[str, list[str]]  # kind -> its own slots, in schema order

    def order(self, kind: str) -> list[str]:
        """Slot names of a kind in canonical order: the identifier, then root kind first."""
        p = self.pack
        ident = p.kinds[p.root(kind)].identifier
        out = [ident] if ident else []
        for k in reversed(p.ancestors(kind)):
            out += [n for n in self.declared.get(k, []) if n not in out]
        return out

    def block(self, kind: str) -> bool:
        """A record with an inlined slot is written one slot per line."""
        return any(s.inlined for s in self.pack.all_slots(kind))

    def identifier(self, kind: str) -> tuple[str, str]:
        p = self.pack
        if kind not in p.kinds:
            raise WriteError(f"unknown kind '{kind}'")
        if p.kinds[kind].abstract:
            raise WriteError(f"kind '{kind}' is abstract")
        root = p.kinds[p.root(kind)]
        if root.identifier is None:
            raise WriteError(f"kind '{kind}' has no identifier; write its elements inlined")
        return root.identifier, root.id_type


def layout(pack_dir: str | Path) -> Layout:
    """Kinds in schema order (module by module, classes as written), with their slots as declared. Every
    module counts, also those of an imported pack, under the engine name the compiler gave the class."""
    pack_dir = Path(pack_dir)
    model = packs.read(pack_dir)
    meta = yaml.safe_load((pack_dir / "pack.yaml").read_text("utf-8"))
    dirs = {name: p.dir for name, p in modules.imported_packs(pack_dir, meta, []).items()}
    name_of = {(kind.module, kind.cls): k for k, kind in model.kinds.items()}
    kinds, declared = [], {}
    for s in model.schemas:
        d = pack_dir if s["pack"] == model.meta["name"] else dirs[s["pack"]]
        if s["file"].endswith(".reckon"):  # a module written in Reckon: its classes as it lowers them
            doc = {"classes": reckon_module.schema_classes(d, s["file"])}
        else:
            doc = yaml.safe_load((d / s["file"]).read_text("utf-8")) or {}
        for cname, c in (doc.get("classes") or {}).items():
            c = c or {}
            k = name_of.get((s["module"], cname), packs.snake(cname))
            kinds.append(k)
            declared[k] = list(c.get("slots") or []) + list(c.get("attributes") or {})
    return Layout(model, kinds, declared)


# --- Values: from the delta's JSON into typed facts, and back -------------------------------------

def scalar(sql_type: str, v, where: str):
    """A value in its fact type. In JSON a whole number may be decimal text (decision W3), a date ISO text (W5)."""
    if sql_type == "BIGINT":
        if isinstance(v, int) and not isinstance(v, bool):
            return v
        if isinstance(v, str) and INTEGER.match(v):
            return int(v)
    elif sql_type == "BOOLEAN":
        if isinstance(v, bool):
            return v
    elif sql_type == "DATE":
        if isinstance(v, datetime.date) and not isinstance(v, datetime.datetime):
            return v
        if isinstance(v, str) and ISO_DATE.match(v):
            try:
                return datetime.date.fromisoformat(v)
            except ValueError:
                pass
    elif isinstance(v, str):
        return v
    raise WriteError(f"{where}: {v!r} is not a {sql_type}")


def typed(lay: Layout, kind: str, name: str, v, where: str):
    s = lay.pack.slot(kind, name)
    if s is None:
        raise WriteError(f"{where}: kind '{kind}' has no slot '{name}'")
    if isinstance(v, list):  # more than one value is a functionality violation, but still a fact
        return [typed_one(lay, s, x, where) for x in v]
    return typed_one(lay, s, v, where)


def typed_one(lay: Layout, s: packs.Slot, v, where: str):
    if s.arrow and s.inlined and isinstance(v, dict):
        return record(lay, s.range, v, where)
    p = lay.pack
    return scalar(p.kinds[p.root(s.range)].id_type if s.arrow else s.sql_type, v, where)


def record(lay: Layout, kind: str, values, where: str) -> dict:
    if not isinstance(values, dict):
        raise WriteError(f"{where}: a record is an object")
    return {n: typed(lay, kind, n, v, f"{where}.{n}") for n, v in values.items()}


def to_json(v):
    """A fact value as delta JSON: whole numbers as decimal text, dates as ISO text."""
    if isinstance(v, bool) or isinstance(v, str):
        return v
    if isinstance(v, int):
        return str(v)
    if isinstance(v, datetime.date) and not isinstance(v, datetime.datetime):
        return v.isoformat()
    if isinstance(v, list):
        return [to_json(x) for x in v]
    if isinstance(v, dict):
        return {k: to_json(x) for k, x in v.items()}
    raise WriteError(f"cannot write {v!r}")


def same(a, b) -> bool:
    """Equality that tells 1 from true and a date from its text."""
    if type(a) is not type(b):
        return False
    if isinstance(a, dict):
        return set(a) == set(b) and all(same(a[k], b[k]) for k in a)
    if isinstance(a, list):
        return len(a) == len(b) and all(same(x, y) for x, y in zip(a, b))
    return a == b


# --- Rendering -----------------------------------------------------------------------------------

def safe_char(c: str) -> bool:
    """A printable character that is not a line break, tab or byte order mark."""
    o = ord(c)
    return (0x20 <= o <= 0x7E or 0xA0 <= o <= 0xD7FF and o not in (0x2028, 0x2029)
            or 0xE000 <= o <= 0xFFFD and o != 0xFEFF or 0x10000 <= o <= 0x10FFFF)


@functools.lru_cache(maxsize=65536)
def plain(s: str) -> bool:
    if not s or s != s.strip() or s[0] in PLAIN_START:
        return False
    if any(c in ",[]{}#:" or not safe_char(c) for c in s):
        return False
    try:  # both YAML readers must read it back as this text, not as a number, date, boolean or null
        return all(yaml.load(doc, loader) == {"k": s} for loader in {Loader, yaml.SafeLoader}
                   for doc in ("{k: " + s + "}", "k: " + s + "\n"))
    except yaml.YAMLError:
        return False


def quote(s: str) -> str:
    if plain(s):
        return s
    if all(safe_char(c) for c in s):
        return "'" + s.replace("'", "''") + "'"
    out = []
    for c in s:
        o = ord(c)
        if c in ESCAPES:
            out.append(ESCAPES[c])
        elif safe_char(c):
            out.append(c)
        else:
            out.append(f"\\x{o:02X}" if o <= 0xFF else f"\\u{o:04X}" if o <= 0xFFFF else f"\\U{o:08X}")
    return '"' + "".join(out) + '"'


def render(v) -> str:
    """A value in flow style."""
    if v is True:
        return "true"
    if v is False:
        return "false"
    if isinstance(v, int):
        return str(v)
    if isinstance(v, datetime.date) and not isinstance(v, datetime.datetime):
        return v.isoformat()
    if isinstance(v, str):
        return quote(v)
    if isinstance(v, list):
        return "[" + ", ".join(render(x) for x in v) + "]"
    if isinstance(v, dict):
        return "{" + ", ".join(f"{quote(str(k))}: {render(x)}" for k, x in v.items()) + "}"
    raise WriteError(f"cannot write {v!r}")


def json_text(s: str) -> str:
    """A JSON string that YAML reads back the same: like json.dumps(ensure_ascii=False), but every
    character YAML cannot hold raw (line breaks such as U+2028, control characters) as \\uXXXX."""
    return '"' + "".join(JSON_ESCAPES.get(c) or (c if safe_char(c) else f"\\u{ord(c):04x}") for c in s) + '"'


def render_json(v) -> str:
    """A value in the JSON dialect: separators as json.dumps writes them, a date as ISO text."""
    if v is True:
        return "true"
    if v is False:
        return "false"
    if isinstance(v, int):
        return str(v)
    if isinstance(v, datetime.date) and not isinstance(v, datetime.datetime):
        return json_text(v.isoformat())
    if isinstance(v, str):
        return json_text(v)
    if isinstance(v, list):
        return "[" + ", ".join(render_json(x) for x in v) + "]"
    if isinstance(v, dict):
        return "{" + ", ".join(f"{json_text(str(k))}: {render_json(x)}" for k, x in v.items()) + "}"
    raise WriteError(f"cannot write {v!r}")


def as_written(v, json_dialect: bool):
    """The value as YAML reads it back after writing: in the JSON dialect a date becomes ISO text."""
    if not json_dialect:
        return v
    if isinstance(v, datetime.date) and not isinstance(v, datetime.datetime):
        return v.isoformat()
    if isinstance(v, list):
        return [as_written(x, True) for x in v]
    if isinstance(v, dict):
        return {k: as_written(x, True) for k, x in v.items()}
    return v


def ordered(lay: Layout, kind: str, rec: dict) -> dict:
    """A record with its slots in canonical order; slots the schema does not know keep their place at the end."""
    names = lay.order(kind)
    out = {}
    for n in [n for n in names if n in rec] + [n for n in rec if n not in names]:
        v, s = rec[n], lay.pack.slot(kind, n)
        if s is not None and s.inlined:
            v = [ordered(lay, s.range, x) if isinstance(x, dict) else x for x in v] if isinstance(v, list) \
                else ordered(lay, s.range, v) if isinstance(v, dict) else v
        out[n] = v
    return out


def place(lay: Layout, kind: str, rec: dict, slot: str, value) -> dict:
    """The record with one slot set. An existing slot keeps its place; a new one goes before the first
    slot that comes later in schema order, so a record keeps the order it was written in."""
    value = ordered(lay, kind, {slot: value})[slot]
    if slot in rec:
        return {k: (value if k == slot else v) for k, v in rec.items()}
    names = lay.order(kind)
    rank = {n: i for i, n in enumerate(names)}
    keys = list(rec)
    at = next((i for i, k in enumerate(keys) if rank.get(k, len(names)) > rank.get(slot, len(names))), len(keys))
    keys.insert(at, slot)
    return {k: (value if k == slot else rec[k]) for k in keys}


def eol(tail: str, nl: str = "\n") -> str:
    return tail if tail.endswith("\n") else tail + nl


def render_row(rec: dict, prefix: str, block: bool, tails: dict, json_dialect: bool = False,
               nl: str = "\n") -> list[str]:
    """The lines of one record, slots in the order given. `tails` keeps what followed a slot (or, for a
    flow row, the row) on its line."""
    if json_dialect:
        return [f"{prefix}{render_json(rec)}{eol(tails.get(None, ''), nl)}"]
    if not block or not rec:
        return [f"{prefix}{render(rec)}{eol(tails.get(None, ''), nl)}"]
    indent = " " * len(prefix)
    return [f"{prefix if i == 0 else indent}{quote(str(k))}: {render(v)}{eol(tails.get(k, ''), nl)}"
            for i, (k, v) in enumerate(rec.items())]


# --- Where things are in a file ------------------------------------------------------------------

@dataclass
class Row:
    start: int  # first line, with the comment lines above it
    line: int  # the line with '- '
    end: int  # last line
    prefix: str  # the text before the record: indentation and '- '
    block: bool
    tails: dict  # slot name (None for a flow row) -> rest of its last line
    json: bool = False  # written as JSON: {"id": ...}
    node: yaml.MappingNode | None = None


@dataclass
class Section:
    kind: str
    start: int
    line: int
    end: int
    rows: list[Row] = field(default_factory=list)
    empty: tuple[int, int] | None = None  # 'kind: []': the columns of ' []' on the kind's line


def split_lines(text: str) -> list[str]:
    """Lines with their own line end. LF and CRLF only: YAML counts other line breaks too, which would
    shift every position after them."""
    if re.search("\r(?!\n)|[\x85  ]", text):
        raise WriteError("only LF or CRLF line ends are supported")
    parts = text.split("\n")
    return [p + "\n" for p in parts[:-1]] + ([parts[-1]] if parts[-1] else [])


def newline(lines: list[str]) -> str:
    """The file's own line end, for lines the writer adds."""
    return "\r\n" if lines and lines[0].endswith("\r\n") else "\n"


def last_line(node) -> int:
    if isinstance(node, yaml.MappingNode) and not node.flow_style and node.value:
        return last_line(node.value[-1][1])
    if isinstance(node, yaml.SequenceNode) and not node.flow_style and node.value:
        return last_line(node.value[-1])
    m = node.end_mark
    if block_scalar(node):  # `|` or `>`: it ends with its line break, so the mark is on a later line
        return max(node.start_mark.line, m.line - 1)
    return m.line - 1 if m.column == 0 and m.line > node.start_mark.line else m.line


def comments_above(lines: list[str], line: int, floor: int) -> int:
    i = line
    while i - 1 > floor and lines[i - 1].lstrip().startswith("#"):
        i -= 1
    return i


def block_scalar(node) -> bool:
    return isinstance(node, yaml.ScalarNode) and node.style in ("|", ">")


def block_value(node) -> bool:
    """A value over its own lines (a block mapping or list, or text with `|` or `>`): it is replaced up to
    the end of its last line, never up to its end mark, which lies on the next slot's line."""
    return block_scalar(node) or isinstance(node, (yaml.MappingNode, yaml.SequenceNode)) and not node.flow_style


def tail(lines: list[str], node) -> str:
    if block_value(node):
        return "\n"  # a block value: comments inside it are not kept
    return lines[last_line(node)][node.end_mark.column:]


def parse(text: str) -> tuple[list[str], list[Section], dict]:
    lines = split_lines(text)
    loader = Loader(text)
    try:  # one read: the nodes give the positions, the same nodes give the values
        root = loader.get_single_node()
        data = (loader.construct_document(root) if root is not None else None) or {}
    except yaml.YAMLError as e:
        raise WriteError(f"not valid YAML: {e}") from e
    finally:
        loader.dispose()
    if root is None:
        return lines, [], {}
    if not isinstance(root, yaml.MappingNode) or root.flow_style:
        raise WriteError("a fact file is a block mapping from kind to records")
    sections: list[Section] = []
    prev = -1
    for knode, vnode in root.value:
        kind, kline = knode.value, knode.start_mark.line
        if any(s.kind == kind for s in sections):
            raise WriteError(f"kind '{kind}' appears twice")
        start = comments_above(lines, kline, prev)
        sec = Section(kind, kline if start == 0 else start, kline, kline)
        if isinstance(vnode, yaml.SequenceNode) and not vnode.flow_style:
            floor = kline
            for item in vnode.value:
                if not isinstance(item, yaml.MappingNode):
                    raise WriteError(f"line {item.start_mark.line + 1}: a record is a mapping")
                line, col = item.start_mark.line, item.start_mark.column
                prefix = lines[line][:col]
                if not PREFIX.match(prefix):
                    raise WriteError(f"line {line + 1}: write '- ' and the record on one line")
                block = not item.flow_style
                tails = {k.value: tail(lines, v) for k, v in item.value} if block else {None: tail(lines, item)}
                row = Row(comments_above(lines, line, floor), line, last_line(item), prefix, block, tails,
                          not block and lines[line][col:].startswith('{"'), item)
                sec.rows.append(row)
                floor = row.end
            sec.end = floor
        elif (isinstance(vnode, yaml.SequenceNode) and not vnode.value
              and vnode.start_mark.line == kline == vnode.end_mark.line):
            # An empty list says "no records" in so many words (kind: []); the first insert makes it a block list.
            col = vnode.start_mark.column
            while col and lines[kline][col - 1] in " \t":
                col -= 1
            sec.empty = (col, vnode.end_mark.column)
        elif not (isinstance(vnode, yaml.ScalarNode) and vnode.tag == NULL):
            raise WriteError(f"{kind}: write the records as a block list ('- ' per record)")
        sections.append(sec)
        prev = sec.end
    return lines, sections, data


# --- Applying changes ----------------------------------------------------------------------------

def sort_key(v) -> tuple:
    """Numbers by value, text in natural order (t2 before t10)."""
    if isinstance(v, int) and not isinstance(v, bool):
        return (0, v)
    parts = re.findall(r"[0-9]+|[^0-9]+", str(v))
    return (1, tuple((0, int(p), p) if p[0] in "0123456789" else (1, 0, p) for p in parts), str(v))


class Text:
    """A file as lines, with positions as (line, column) the way the YAML composer reports them."""

    def __init__(self, lines: list[str]):
        self.lines = lines
        self.offsets = [0]
        for line in lines:
            self.offsets.append(self.offsets[-1] + len(line))

    def at(self, line: int, col: int = 0) -> int:
        return self.offsets[line] + col

    def content_end(self, line: int) -> int:
        """The end of a line without its line end."""
        return self.offsets[line] + len(self.lines[line].rstrip("\r\n"))


def slot_edit(lay: Layout, kind: str, row: Row, t: Text, slot: str, value, nl: str) -> tuple[int, int, str]:
    """The one text edit that sets (value given) or removes (value is None) one slot of a record. Only the
    value changes, or one slot is added or taken out; the rest of the record keeps its text."""
    pairs = row.node.value
    names = [k.value for k, _ in pairs]
    key_text = json_text(slot) if row.json else quote(slot)
    value_text = None if value is None else (render_json(value) if row.json else render(value))
    pos = lambda m: t.at(m.line, m.column)  # noqa: E731
    if value is not None and slot in names:  # replace only the value
        k, v = pairs[names.index(slot)]
        if block_value(v):
            return pos(k.end_mark), t.content_end(last_line(v)), f": {value_text}"
        return pos(v.start_mark), pos(v.end_mark), value_text
    if value is not None:  # a new slot, before the first slot that comes later in schema order
        rank = {n: i for i, n in enumerate(lay.order(kind))}
        later = [i for i, n in enumerate(names) if rank.get(n, len(rank)) > rank.get(slot, len(rank))]
        if not row.block:
            if later:
                at = pos(pairs[later[0]][0].start_mark)
                return at, at, f"{key_text}: {value_text}, "
            at = pos(pairs[-1][1].end_mark)
            return at, at, f", {key_text}: {value_text}"
        indent = " " * pairs[0][0].start_mark.column
        if later and later[0] == 0:  # becomes the first slot, on the line with '- '
            at = pos(pairs[0][0].start_mark)
            return at, at, f"{key_text}: {value_text}{nl}{indent}"
        if later:
            k = pairs[later[0]][0]
            line = comments_above(t.lines, k.start_mark.line, last_line(pairs[later[0] - 1][1]))
        else:
            line = last_line(pairs[-1][1]) + 1
        lead = nl if line == len(t.lines) and t.lines and not t.lines[-1].endswith("\n") else ""
        return t.at(line), t.at(line), f"{lead}{indent}{key_text}: {value_text}{nl}"
    i = names.index(slot)  # remove one slot
    k, v = pairs[i]
    if not row.block:
        if i + 1 < len(pairs):
            return pos(k.start_mark), pos(pairs[i + 1][0].start_mark), ""
        return pos(pairs[i - 1][1].end_mark), pos(v.end_mark), ""
    if i == 0:  # the next slot moves up onto the line with '- '
        return pos(k.start_mark), pos(pairs[1][0].start_mark), ""
    first = comments_above(t.lines, k.start_mark.line, last_line(pairs[i - 1][1]))
    return t.at(first), t.at(last_line(v) + 1), ""


def fingerprint(v):
    """A value with its type, for comparing records regardless of the order of slots."""
    if isinstance(v, dict):
        return ("map", tuple(sorted((k, fingerprint(x)) for k, x in v.items())))
    if isinstance(v, list):
        return ("list", tuple(fingerprint(x) for x in v))
    return (type(v).__name__, v.isoformat() if isinstance(v, datetime.date) else v)


def same_facts(got: dict, expected: dict, ordered_rows: bool) -> bool:
    """A kind without records (`kind:` or `kind: []`) states the same facts as a kind that is not in the file."""
    for k in {k for d in (got, expected) for k, v in d.items() if v}:
        a = [fingerprint(r) for r in got.get(k) or []]
        b = [fingerprint(r) for r in expected.get(k) or []]
        if (a if ordered_rows else sorted(a, key=repr)) != (b if ordered_rows else sorted(b, key=repr)):
            return False
    return True


def line_patch(old: list[str], new: list[str]) -> dict:
    """The smallest run of lines that turns `new` back into `old`: the exact text for an undo."""
    p = 0
    while p < min(len(old), len(new)) and old[p] == new[p]:
        p += 1
    s = 0
    while s < min(len(old), len(new)) - p and old[-1 - s] == new[-1 - s]:
        s += 1
    return {"at": p, "old": "".join(new[p:len(new) - s]), "new": "".join(old[p:len(old) - s])}


def restored(lines: list[str], restore) -> str | None:
    """The text with an undo's exact lines put back, if they still fit where they were; else None."""
    if not isinstance(restore, dict) or not isinstance(restore.get("at"), int) or restore["at"] < 0:
        return None
    at, old, new = restore["at"], restore.get("old"), restore.get("new")
    if not isinstance(old, str) or not isinstance(new, str) or at > len(lines):
        return None
    n = len(split_lines(old))
    if "".join(lines[at:at + n]) != old:
        return None
    return "".join(lines[:at]) + new + "".join(lines[at + n:])


def apply_change(lay: Layout, text: str, ch: dict) -> tuple[str, dict]:
    """Apply one change to the text of a fact file. Returns the new text and the change that undoes it.

    The undo carries `restore`: the exact lines this change replaced and where. Applied right after, it
    gives the same bytes back, comments, quoting and position included. If the lines no longer fit,
    the undo is applied from its values instead.
    """
    op, kind = ch.get("op"), ch.get("kind")
    if op not in OPS:
        raise WriteError(f"op must be one of {OPS}, not {op!r}")
    ident, id_type = lay.identifier(kind)
    key = scalar(id_type, ch.get("key"), f"{kind}.{ident}")
    where = f"{kind} {key}"
    lines, sections, data = parse(text)
    t, nl = Text(lines), newline(lines)
    sec = next((s for s in sections if s.kind == kind), None)
    records = (data.get(kind) or []) if sec else []
    hits = [i for i, r in enumerate(records) if isinstance(r, dict) and same(r.get(ident), key)]
    expected = {k: list(v) if isinstance(v, list) else v for k, v in data.items()}
    base = {"op": None, "file": ch.get("file"), "kind": kind, "key": to_json(key)}

    if op == "insert":
        if hits:
            raise WriteError(f"{where}: exists already")
        values = ch.get("values") or {}
        if ident in values:
            raise WriteError(f"{where}: give the identifier as 'key', not among the values")
        rec = ordered(lay, kind, {ident: key, **record(lay, kind, values, where)})
        dialect = sec.rows[0].json if sec and sec.rows else any(r.json for s in sections for r in s.rows[:1])
        rec = as_written(rec, dialect)
        if sec is None:
            later = [s for s in sections if lay.kinds.index(s.kind) > lay.kinds.index(kind)] \
                if all(s.kind in lay.kinds for s in sections) else []
            at = later[0].start if later else len(lines)
            new = [f"{kind}:{nl}"] + render_row(rec, "  - ", lay.block(kind), {}, dialect, nl)
            expected[kind] = [rec]
        else:
            i = next((i for i, r in enumerate(records)
                      if isinstance(r, dict) and r.get(ident) is not None and sort_key(r[ident]) > sort_key(key)),
                     len(records))
            at = sec.rows[i].start if i < len(sec.rows) else sec.end + 1
            prefix = sec.rows[0].prefix if sec.rows else "  - "
            block = sec.rows[0].block if sec.rows else lay.block(kind)
            new = render_row(rec, prefix, block, {}, dialect, nl)
            expected[kind] = records[:i] + [rec] + records[i:]
        lead = nl if at == len(lines) and lines and not lines[-1].endswith("\n") else ""
        edit = (t.at(at), t.at(at), lead + "".join(new))
        if sec is not None and sec.empty:  # 'kind: []' becomes 'kind:' with the record below; a comment after it stays
            edit = (t.at(sec.line, sec.empty[0]), t.at(at), lines[sec.line][sec.empty[1]:] + edit[2])
        inverse = {**base, "op": "delete"}
    else:
        if len(hits) != 1:
            raise WriteError(f"{where}: {'not found' if not hits else 'appears more than once'}")
        i = hits[0]
        row, old = sec.rows[i], records[i]
        if op == "delete":
            if len(sec.rows) == 1:
                edit = (t.at(sec.start), t.at(sec.end + 1), "")
                del expected[kind]
            else:
                edit = (t.at(row.start), t.at(row.end + 1), "")
                expected[kind] = records[:i] + records[i + 1:]
            inverse = {**base, "op": "insert", "values": to_json({k: v for k, v in old.items() if k != ident})}
        else:
            slot = ch.get("slot")
            if slot == ident:
                raise WriteError(f"{where}: the identifier does not change; delete the record and insert a new one")
            if op == "set":
                value = as_written(typed(lay, kind, slot, ch.get("value"), f"{where}.{slot}"), row.json)
                rec = place(lay, kind, old, slot, value)
                edit = slot_edit(lay, kind, row, t, slot, value, nl)
            elif slot not in old:
                raise WriteError(f"{where}: '{slot}' has no value to unset")
            else:
                rec = {k: v for k, v in old.items() if k != slot}
                edit = slot_edit(lay, kind, row, t, slot, None, nl)
            inverse = {**base, "op": "set", "slot": slot, "value": to_json(old[slot])} if slot in old \
                else {**base, "op": "unset", "slot": slot}
            expected[kind] = records[:i] + [rec] + records[i + 1:]

    out = text[:edit[0]] + edit[2] + text[edit[1]:]
    exact = restored(lines, ch.get("restore"))
    if exact is not None:
        out = exact
    got = yaml.load(out, Loader) or {}  # quoting is checked against both readers, so the fast one suffices
    if exact is not None:  # restored lines keep the dialect they were written in: a date may stand there as ISO text
        got, expected = as_written(got, True), as_written(expected, True)
    if not same_facts(got, expected, ordered_rows=exact is None):
        if exact is not None:
            raise WriteError(f"{where}: the lines to restore do not give the facts this change describes")
        raise WriteError(f"{where}: the written file does not read back as the intended facts")  # a writer bug
    inverse = {k: v for k, v in inverse.items() if v is not None}
    inverse["restore"] = line_patch(lines, split_lines(out))
    return out, inverse


def apply(lay: Layout, text: str, changes: list[dict]) -> tuple[str, list[dict]]:
    """Apply changes in order. Returns the new text and the changes that undo them, in undo order."""
    undo = []
    for ch in changes:
        text, inverse = apply_change(lay, text, ch)
        undo.insert(0, inverse)
    return text, undo


def canonical(lay: Layout, text: str) -> str:
    """The file with every record written again in canonical form; comments, gaps and row order stay."""
    lines, sections, data = parse(text)
    nl = newline(lines)
    for sec in reversed(sections):
        for row, rec in reversed(list(zip(sec.rows, data.get(sec.kind) or []))):
            lines[row.line:row.end + 1] = render_row(rec, row.prefix, row.block, row.tails, row.json, nl)
    return "".join(lines)


# --- A delta on a pack ---------------------------------------------------------------------------

def check_delta(delta) -> list[dict]:
    if not isinstance(delta, dict) or delta.get("format") != FORMAT:
        raise WriteError(f"a delta is an object with format '{FORMAT}'")
    changes = delta.get("changes")
    if not isinstance(changes, list):
        raise WriteError("a delta needs a list 'changes'")
    for n, ch in enumerate(changes):
        if not isinstance(ch, dict):
            raise WriteError(f"change {n}: not an object")
        if ("file" in ch or ch.get("op") == "insert") and not FACT_FILE.match(str(ch.get("file", ""))):
            raise WriteError(f"change {n}: file must be facts/<name>.yaml, not {ch.get('file')!r}")
        needed = {"insert": (), "delete": (), "set": ("slot", "value"), "unset": ("slot",)}.get(ch.get("op"), ())
        missing = [f for f in ("kind", "key", *needed) if f not in ch]
        if missing:
            raise WriteError(f"change {n}: needs {', '.join(missing)}")
    return changes


def fact_path(pack_dir: str | Path, rel: str) -> Path:
    """A fact file of the pack or its source companion, refused when it is a symbolic link or resolves outside
    the pack (say, because `facts` links elsewhere): the writer must never write outside the pack."""
    if not (FACT_FILE.match(rel) or SOURCES_FILE.match(rel)):
        raise WriteError(f"file must be facts/<name>.yaml, not {rel!r}")
    root = Path(pack_dir).resolve()
    p = Path(pack_dir) / rel
    if p.is_symlink() or p.parent.is_symlink() or not p.resolve().is_relative_to(root):
        raise WriteError(f"{rel}: refused, it is or passes a symbolic link out of the pack")
    return p


def read_fact_file(pack_dir: str | Path, rel: str) -> str:
    """The file as it is, line ends included; an absent file is empty."""
    p = fact_path(pack_dir, rel)
    return p.read_bytes().decode("utf-8") if p.exists() else ""


def locate(pack_dir: str | Path, lay: Layout, kind: str, key, texts: dict[str, str]) -> str:
    """The one fact file that holds this record, for a change that names none (the viewer knows records,
    not files). Read as the delta has changed them so far. None or more than one is refused."""
    ident, id_type = lay.identifier(kind)
    want = scalar(id_type, key, f"{kind}.{ident}")
    fmt = source_format.YAML_DATALOG
    names = {rel for rel, _ in fmt.fact_files(pack_dir)} | set(texts)
    found = []
    for rel in sorted(n for n in names if fmt.fact_file(n)):
        data = fmt.fact_records(texts[rel] if rel in texts else read_fact_file(pack_dir, rel))
        if any(isinstance(r, dict) and same(r.get(ident), want) for r in (data.get(kind) or [])):
            found.append(rel)
    if len(found) != 1:
        raise WriteError(f"{kind} {to_json(want)}: {'in no fact file' if not found else 'in ' + ', '.join(found)}; name the file")
    return found[0]


def apply_delta(pack_dir: str | Path, delta: dict, lay: Layout | None = None, *, origins: dict | None = None,
                stated: dict | None = None, undo: bool = False) -> tuple[dict[str, str], dict]:
    """New text per changed fact file (path relative to the pack), and the delta that undoes it. A change
    without a file goes to the one file that holds its record; the undo delta names it.

    A fact file with a source companion (`facts/<file>.sources.yaml`, S25) changes together with it: the
    companion's new text is among the texts, and the undo carries what puts it back byte for byte (`sources`).
    A change that writes rows there needs their real origin from the caller, never from the delta: `origins`
    maps its step to `{sources, reason?}`, and `stated` is the one origin of every written row that `origins`
    does not name: who states the delta's values (`source_writer.stated`, RV-M17). `undo` says the delta is an undo this writer made, so its `sources`
    may put the companions back. Without companions nothing changes (docs/compiler.md#provenance-per-fact-s25).
    """
    changes = check_delta(delta)
    lay = lay or layout(pack_dir)
    if delta.get("pack", lay.pack.meta["name"]) != lay.pack.meta["name"]:
        raise WriteError(f"the delta is for pack {delta['pack']!r}, not {lay.pack.meta['name']!r}")
    companions = None
    if (origins is not None or stated is not None or undo or "sources" in delta
            or any((Path(pack_dir) / "facts").glob("*.sources.yaml"))):
        from . import source_writer  # it imports this module

        companions = source_writer.Companions(pack_dir, lay, len(changes), delta.get("sources"), origins, undo, stated)
    texts: dict[str, str] = {}
    inverses: list[dict] = []
    for n, ch in enumerate(changes):
        if "file" not in ch:
            try:
                ch = {**ch, "file": locate(pack_dir, lay, ch["kind"], ch["key"], texts)}
            except WriteError as e:
                raise WriteError(f"change {n}: {e}") from e
        f = ch["file"]
        if f not in texts:
            texts[f] = read_fact_file(pack_dir, f)
        try:
            texts[f], inverse = (companions.step(n, f, texts[f], ch) if companions
                                 else source_format.of(f).edit_fact(lay, texts[f], ch))
        except WriteError as e:
            raise WriteError(f"change {n} ({f}): {e}") from e
        inverses.insert(0, inverse)
    head = {k: delta[k] for k in ("pack", "base_manifest") if k in delta}
    back = {"format": FORMAT, **head, "changes": inverses}
    if companions:
        companions.finish(texts, back)
    return texts, back


WORK_PREFIX = "rede-work-"


def work_dir() -> Path:
    """A new private, throwaway work dir for one proposal: a checkout goes in it, the writer writes there,
    and on any error the whole dir is thrown away. It sits directly under the process's temp dir."""
    return Path(tempfile.mkdtemp(prefix=WORK_PREFIX))


def checkout(pack_dir: str | Path, work: str | Path) -> Path:
    """Copy a pack into a work dir together with every pack it imports, and return where the pack is in the
    copy. An import is a path relative to the pack, so the imported packs keep their places relative to it
    (modules.copy_closure), each checked against its pinned hash, and the copy compiles like the original."""
    from . import modules

    # The destination is checked before anything is written: only inside a work dir, never through a link.
    return modules.copy_closure(pack_dir, Path(work) / "pack", check=check_work_dir)


def check_work_dir(pack_dir: str | Path) -> None:
    """The writer writes only inside a work dir (rede-work-* directly under the temp dir), with no symbolic
    link from the work dir down to the pack. Nobody else writes there, so no link can appear while it
    writes, and an error never needs a repair: the work dir is discarded."""
    pack = Path(pack_dir).absolute()
    tmp = Path(tempfile.gettempdir()).resolve()
    for top in [pack, *pack.parents]:
        if top.name.startswith(WORK_PREFIX) and top.parent.resolve() == tmp:
            cur = top
            for part in ("", *pack.relative_to(top).parts, "facts"):
                cur = cur / part if part else cur
                if cur.is_symlink():
                    raise WriteError(f"{cur}: refused, a symbolic link in the work dir")
            return
    raise WriteError(f"{pack_dir}: the writer writes only in a private work dir ({WORK_PREFIX}* directly under "
                     f"{tmp}); check the pack out there first")


def write_files(pack_dir: str | Path, texts: dict[str, str]) -> None:
    """Write the fact files in a work dir, each with its source companion when it has one (S25: `apply_delta`
    gives both). Each file is replaced at once (temporary file, then os.replace), so no file is ever half
    written; after an error between files the work dir is not consistent and must be discarded, which is why
    the writer refuses to write anywhere else."""
    check_work_dir(pack_dir)
    for rel in sorted(texts):
        companion = rel.removesuffix(".yaml") + ".sources.yaml"
        if (FACT_FILE.match(rel) and companion not in texts and fact_path(pack_dir, companion).exists()
                and texts[rel] != read_fact_file(pack_dir, rel)):
            raise WriteError(f"{rel}: its source companion must be written with it; no facts changed")
    temps: list[str] = []
    try:
        for rel in sorted(texts):
            p = fact_path(pack_dir, rel)
            p.parent.mkdir(parents=True, exist_ok=True)
            fd, tmp = tempfile.mkstemp(prefix=f".{p.name}.", suffix=".tmp", dir=p.parent)
            temps.append(tmp)
            with os.fdopen(fd, "wb") as f:
                f.write(texts[rel].encode("utf-8"))
            os.chmod(tmp, stat.S_IMODE(p.stat().st_mode) if p.exists() else 0o644)
            os.replace(tmp, p)
            temps.remove(tmp)
    except OSError as e:
        raise WriteError(f"could not write the fact files; discard the work dir: {e}") from e
    finally:
        for tmp in temps:
            Path(tmp).unlink(missing_ok=True)


def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog="python -m rede_compiler.writer")
    sub = p.add_subparsers(dest="cmd", required=True)
    a = sub.add_parser("apply", help="apply a delta (JSON) to the fact files of a pack")
    a.add_argument("pack")
    a.add_argument("delta")
    a.add_argument("--inverse", help="write the delta that undoes this one to this file")
    a.add_argument("--origins", help="JSON file: per step that writes rows in a fact file with a source companion, "
                                     "the real origin of those rows, as {step: {sources, reason?}}")
    a.add_argument("--undo", action="store_true", help="the delta is an undo this writer made: its 'sources' put "
                                                       "the source companions back")
    args = p.parse_args(argv)
    try:
        delta = json.loads(Path(args.delta).read_text("utf-8"))
        origins = json.loads(Path(args.origins).read_text("utf-8")) if args.origins else None
        if origins is not None and (not isinstance(origins, dict) or not all(INTEGER.match(k) for k in origins)):
            raise WriteError("origins is an object from step number to {sources, reason?}")
        texts, undo = apply_delta(args.pack, delta, origins=origins and {int(k): v for k, v in origins.items()},
                                  undo=args.undo)
        write_files(args.pack, texts)
    except (WriteError, packs.CompileError, json.JSONDecodeError) as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    for f in sorted(texts):
        print(f"wrote {f}", file=sys.stderr)
    if args.inverse:
        Path(args.inverse).write_text(json.dumps(undo, ensure_ascii=False, indent=2) + "\n", "utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
