"""S25 source writing: a delta on a fact file with a source companion changes both, or nothing.

`plan` is the pure planner (step 5b2): no IO, pinned base bytes, explicit origins per RowRef. `Companions`
is what `writer.apply_delta` uses on a pack directory (step 5b): the same step per change, the base origins
read from the companion itself, the origins of written rows given by the trusted caller beside the delta.

Origins are explicitly supplied by the trusted caller. VerifiedBasePin checks supplied bytes/hashes;
it does not prove Git history or turn stored/serialized data into a real origin (owner principle 10).
Transport and proposal context stay separate from the real-origin SourceEntry leaves.
"""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from datetime import datetime
from hashlib import sha256
from pathlib import Path, PurePosixPath
import copy
import re
from typing import Mapping

import yaml
from rezono_canon import canonical_json

from . import facts, source_format, sources, strict_yaml, writer

Ref = tuple[str, str]


@dataclass(frozen=True)
class PinnedFile:
    content: bytes
    sha256: str


@dataclass(frozen=True)
class VerifiedBasePin:
    """The caller verified the commit-to-bytes relationship; this helper checks their consistency only."""
    repository: str
    commit: str
    pack_path: str
    files: Mapping[str, PinnedFile]


@dataclass(frozen=True)
class ProposalSource:
    """An actual open proposal/manifest identity, used as change context, never as accepted-decision proof."""
    id: str
    manifest_id: str


@dataclass(frozen=True)
class OriginEvidence:
    """Explicit trusted-caller input, not independently verified or reviewed proof. No client bypass flag."""
    base: Mapping[str, tuple[dict, ...]]
    changes: Mapping[int, tuple[dict, ...]]


@dataclass(frozen=True)
class TransportAnchor:
    repository: str
    commit: str
    path: str
    row: Ref
    lines: tuple[int, ...]


@dataclass(frozen=True)
class SourceUndo:
    before: Mapping[str, bytes | None]
    after_sha256: Mapping[str, str | None]
    delta: dict

    def restore(self, current: Mapping[str, bytes]) -> dict[str, bytes | None]:
        """Plan exact restoration, including prior absence, only against the expected unchanged result."""
        for name, want in self.after_sha256.items():
            data = current.get(name)
            if (None if data is None else sha256(data).hexdigest()) != want:
                raise writer.WriteError(f"{name}: stale source undo; no files changed")
        return dict(self.before)


@dataclass(frozen=True)
class SourceWritePlan:
    files: Mapping[str, bytes | None]
    undo: SourceUndo
    origins: Mapping[str, tuple[dict, ...]]
    transport: tuple[TransportAnchor, ...]
    proposal: ProposalSource


def companion(name: str) -> str:
    return name.removesuffix(".yaml") + ".sources.yaml"


def _inputs(base: VerifiedBasePin, proposal: ProposalSource) -> dict[str, bytes]:
    if (not isinstance(base.repository, str) or not base.repository.strip()
            or not isinstance(base.commit, str) or not re.fullmatch("[0-9a-f]{40}", base.commit)):
        raise writer.WriteError("a caller-verified repository and commit pin are required")
    if not isinstance(base.pack_path, str):
        raise writer.WriteError("base pack_path must be repository-relative text")
    path = PurePosixPath(base.pack_path)
    if ("\\" in base.pack_path or ":" in base.pack_path
            or path.is_absolute() or ".." in path.parts or (base.pack_path and path.as_posix() != base.pack_path)):
        raise writer.WriteError("base pack_path must be a canonical repository-relative path")
    if (not isinstance(proposal.id, str) or not re.fullmatch("[1-9][0-9]*", proposal.id)
            or not isinstance(proposal.manifest_id, str)
            or not re.fullmatch(f"p-{proposal.id}-[1-9][0-9]*", proposal.manifest_id)):
        raise writer.WriteError("the actual proposal id and matching manifest id are required")
    out = {}
    for name, pinned in base.files.items():
        if not isinstance(name, str):
            raise writer.WriteError("supplied base file paths must be text")
        fact = name.removesuffix(".sources.yaml") + ".yaml" if name.endswith(".sources.yaml") else name
        if not writer.FACT_FILE.fullmatch(fact):
            raise writer.WriteError(f"{name}: not a fact file or its derived source companion")
        if (not isinstance(pinned, PinnedFile) or not isinstance(pinned.content, bytes)
                or not isinstance(pinned.sha256, str) or sha256(pinned.content).hexdigest() != pinned.sha256):
            raise writer.WriteError(f"{name}: supplied base bytes do not match their pin")
        out[name] = pinned.content
    if any(name.endswith(".sources.yaml") and name.removesuffix(".sources.yaml") + ".yaml" not in out for name in out):
        raise writer.WriteError("a source companion has no fact file in the supplied base")
    return out


def _origins(entries, where: str) -> dict[Ref, dict]:
    rows = sources.collected(sources.source_entry(copy.deepcopy(e), where) for e in entries)
    for e in rows:
        if any(s["kind"] in {"pack", "proposal", "scenario"} for s in e["sources"]):
            raise writer.WriteError(f"{where}: storage, change or scenario context is not a real origin")
    return {(e["row"]["relation"], e["row"]["key"]): e for e in rows}


def _rows(model, data: dict) -> Counter:
    out = Counter()
    def row(table, values, *_):
        out[(table, canonical_json(values))] += 1
    judged = facts.schema(model)
    for kind, records in data.items():
        for record in records or []:
            facts.walk(judged, kind, record, on_row=row)
    return out


def _affected(lay, data: dict, change: dict) -> Counter:
    kind = change["kind"]
    ident, sql_type = lay.identifier(kind)
    key = writer.scalar(sql_type, change["key"], f"{kind}.{ident}")
    records = [r for r in data.get(kind) or [] if writer.same(r.get(ident), key)]
    if not records:
        return Counter()
    record, out = records[0], Counter()
    partial = change["op"] in {"set", "unset"}
    if partial:
        slot = change["slot"]
        record = {ident: key, **({slot: record[slot]} if slot in record else {})}
    def row(table, values, row_kind, row_key, row_slot, _):
        if not (partial and row_kind == kind and row_key == key and row_slot is None):
            out[(table, canonical_json(values))] += 1
    facts.walk(facts.schema(lay.pack), kind, record, on_row=row)
    return out


CHANGE_KEYS = {"op", "file", "kind", "key", "slot", "value", "values", "restore"}


def step(lay: writer.Layout, name: str, text: str, change: dict, ledger: dict[Ref, dict], origin, where: str) -> tuple[str, dict]:
    """One change on a fact file whose every row has an explicit origin in `ledger`, which follows the change.
    `origin(rows)` gives the entries of exactly the rows the change writes. Returns the new text and the undo."""
    data = strict_yaml.load(text, name) or {}
    before_rows, before = _rows(lay.pack, data), _affected(lay, data, change)
    new_text, inverse = source_format.of(name).edit_fact(lay, text, change)
    new_data = strict_yaml.load(new_text, name) or {}
    after_rows, after = _rows(lay.pack, new_data), _affected(lay, new_data, change)
    if any(before_rows[r] > before[r] for r in before) or any(after_rows[r] > after[r] for r in after):
        raise writer.WriteError(f"{name}: ambiguous shared-row source contribution")
    supplied = origin(set(after))
    if set(supplied) != set(after):
        raise writer.WriteError(f"{where}: real origins must cover exactly the touched result rows")
    for ref in before:
        ledger.pop(ref, None)
    ledger.update(supplied)
    if set(ledger) != set(after_rows):
        raise writer.WriteError(f"{name}: unexplained source loss or new fact")
    return new_text, inverse


def plan(lay: writer.Layout, delta: dict, base: VerifiedBasePin, proposal: ProposalSource,
         origins: OriginEvidence) -> SourceWritePlan:
    """Return fact/source byte changes and exact undo. No origin is inferred from transport or a proposal."""
    original = _inputs(base, proposal)
    changes = writer.check_delta(delta)
    if set(delta) - {"format", "pack", "base_manifest", "changes"}:
        raise writer.WriteError("a delta cannot supply origin or review authority")
    if delta.get("pack", lay.pack.meta["name"]) != lay.pack.meta["name"]:
        raise writer.WriteError("delta pack does not match the model")
    if any(type(i) is not int or i < 0 or i >= len(changes) for i in origins.changes):
        raise writer.WriteError("origin input names no delta step")
    if any(not writer.FACT_FILE.fullmatch(n) or n not in original for n in origins.base):
        raise writer.WriteError("base origin input names no supplied fact file")
    current, ledger, transport, undo_changes, touched = dict(original), {}, [], [], set()
    for index, raw in enumerate(changes):
        if set(raw) - CHANGE_KEYS:
            raise writer.WriteError("a change cannot supply origin or review authority")
        change = dict(raw)
        if "file" not in change:
            ident, sql_type = lay.identifier(change["kind"])
            key = writer.scalar(sql_type, change["key"], ident)
            found = [n for n, data in current.items() if writer.FACT_FILE.fullmatch(n)
                     and any(writer.same(r.get(ident), key) for r in (strict_yaml.load(data, n) or {}).get(change["kind"], []) or [])]
            if len(found) != 1:
                raise writer.WriteError("name the one fact file for this change")
            change["file"] = found[0]
        name = change["file"]
        if not writer.FACT_FILE.fullmatch(name):
            raise writer.WriteError("a change needs a canonical fact-file path")
        text = current.get(name, b"").decode("utf-8")
        if name not in ledger:
            ledger[name] = _origins(origins.base.get(name, ()), name)
            sources.canonical_sidecar_text(lay.pack, name, text, list(ledger[name].values()))
            if companion(name) in original:
                prior = sources.text_entries(lay.pack, name, text, metadata=strict_yaml.load(original[companion(name)], companion(name)))
                if sources.collected(ledger[name].values()) != prior:
                    raise writer.WriteError(f"{name}: explicit base origins would be replaced")
            for e in sources.text_entries(lay.pack, name, text):
                transport.append(TransportAnchor(base.repository, base.commit,
                    "/".join(p for p in (base.pack_path, name) if p), (e["row"]["relation"], e["row"]["key"]),
                    tuple(sorted(int(s["position"]) for s in e["sources"]))))
        new_text, inverse = step(lay, name, text, change, ledger[name],
                                 lambda _: _origins(origins.changes.get(index, ()), f"change {index}"), f"change {index}")
        current[name] = new_text.encode("utf-8")
        current[companion(name)] = sources.canonical_sidecar_text(lay.pack, name, new_text, list(ledger[name].values())).encode("utf-8")
        touched.add(name)
        undo_changes.insert(0, inverse)
    files = {n: data for n, data in current.items() if n not in original or data != original[n]}
    inverse = {"format": writer.FORMAT, **{k: delta[k] for k in ("pack", "base_manifest") if k in delta}, "changes": undo_changes}
    footprint = {n for f in touched for n in (f, companion(f))}
    undo = SourceUndo({n: original.get(n) for n in files}, {n: sha256(current[n]).hexdigest() for n in footprint}, inverse)
    return SourceWritePlan(files, undo, {n: tuple(sources.collected(ledger[n].values())) for n in sorted(touched)}, tuple(transport), proposal)


IDENTIFIER = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:|+=-]{0,127}")
INSTANT = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}Z")


def stated(who: str, at: str) -> dict:
    """The origin of a value a person states, for `writer.apply_delta(stated=...)`: one source of kind
    `person`, named by a plain identifier (never a display name or an address), positioned by the UTC instant of
    the statement, to the second. It means "stated by": no decision, publication or observation stands behind it."""
    if not isinstance(who, str) or not IDENTIFIER.fullmatch(who):
        raise writer.WriteError("who states a value is named by a plain identifier, not a display name or an address")
    try:
        if not isinstance(at, str) or not INSTANT.fullmatch(at):
            raise ValueError
        datetime.fromisoformat(at[:-1])
    except ValueError:
        raise writer.WriteError("when a value was stated is a real UTC instant to the second, such as "
                                "2026-11-10T21:03:11Z") from None
    return {"sources": [{"kind": "person", "name": who, "position": at}]}


def kept_text(old: str, drop: set[int], rows: list[dict]) -> str | None:
    """The companion text `old` in the form it has: every line as it is, without the `records` items `drop`
    (by index) and without its `rows` section, and then `rows` as the last section, one exact row per line.
    None where the layout is not one to edit line by line; the caller checks what the result reads as."""
    if re.search("\r(?!\n)|[\x85  ]", old):  # line breaks of YAML that are not this file's line end
        return None
    root = yaml.compose(old)
    if not isinstance(root, yaml.MappingNode) or root.flow_style:
        return None
    keys = {k.value: (k, v) for k, v in root.value if isinstance(k, yaml.ScalarNode)}
    if len(keys) != len(root.value):
        return None
    *whole, last = old.split("\n")
    lines, gone = [line + "\n" for line in whole] + [last] * bool(last), set()
    if drop:
        key, items = keys["records"]
        if not isinstance(items, yaml.SequenceNode) or items.flow_style:
            return None
        for i in drop:  # only an item that is one whole line: `- {...}`, then nothing or a comment
            start, end = items.value[i].start_mark, items.value[i].end_mark
            line = lines[start.line].rstrip("\r\n")
            if (start.line != end.line or not re.fullmatch(" *- +", line[:start.column])
                    or not re.fullmatch(r"\s*(#.*)?", line[end.column:])):
                return None
            gone.add(start.line)
        if len(drop) == len(items.value):  # a section without items would read as null
            if key.start_mark.column or not re.fullmatch(r"records:\s*(#.*)?", lines[key.start_mark.line].rstrip("\r\n")):
                return None
            gone.add(key.start_mark.line)
    if "rows" in keys:  # only as the last section, so that it ends where the file ends
        key = keys["rows"][0]
        if key is not root.value[-1][0] or key.start_mark.column:
            return None
        del lines[key.start_mark.line:]
    end = "\r\n" if "\r\n" in old else "\n"
    lines = [line for n, line in enumerate(lines) if n not in gone]
    if lines and not lines[-1].endswith("\n"):
        lines[-1] += end
    if rows:
        lines += ["rows:" + end, *(f"  - {canonical_json(e)}{end}" for e in rows)]
    return "".join(lines)


RESTORED = object()
RESTORE_KEYS = {"file", "sources_sha256", "facts_sha256", "restored_facts_sha256", "text"}


def _sha(text: str) -> str:
    return sha256(text.encode("utf-8")).hexdigest()


class Companions:
    """The source companions of the fact files one delta touches, for `writer.apply_delta` (step 5b).

    A fact file without a companion is written as before: its rows have the file and line as their source.
    A fact file with one needs, per change that writes rows, the real origin of those rows from the trusted
    caller, never from the delta: `origins` (step -> {sources, reason?}), or else `stated`, the one origin of
    every row the delta writes that `origins` does not name. Its companion keeps its form: `default`
    and `records` stay as they are, a selector that names no record or cell any more goes, and the rows the
    delta wrote are exact `rows` (`_kept`); a companion of rows only, or one whose layout cannot be kept, is
    the canonical rows form. The one thing a delta may carry is `sources` on the writer's own undo, honoured
    only with `undo` and only on the exact bytes that undo was made for: then the companion goes back byte
    for byte.
    """

    def __init__(self, pack_dir, lay: writer.Layout, steps: int, restore, origins, undo: bool, stated=None):
        self.pack_dir, self.lay = Path(pack_dir), lay
        self.origins = dict(origins or {})
        if any(type(i) is not int or not 0 <= i < steps for i in self.origins):
            raise writer.WriteError("origin input names no delta step")
        self.stated = stated
        if any(not isinstance(o, dict) or set(o) - {"sources", "reason"} or "sources" not in o
               for o in [*self.origins.values(), *([] if stated is None else [stated])]):
            raise writer.WriteError("an origin is {sources, reason?}: the sources of every row its step writes")
        if restore is not None and not undo:
            raise writer.WriteError("a delta cannot supply origins; only the writer's own undo carries 'sources' "
                                    "(apply it with undo); no facts changed")
        self.restore = {}
        for e in restore or []:
            if (not isinstance(e, dict) or set(e) != RESTORE_KEYS
                    or any(not isinstance(v, str) for v in e.values()) or not writer.SOURCES_FILE.match(e["file"])
                    or e["file"] in self.restore):
                raise writer.WriteError(f"an undo's 'sources' entry has {sorted(RESTORE_KEYS)}, one per companion")
            self.restore[e["file"]] = e
        self.files: dict[str, object] = {}  # fact file -> its ledger, RESTORED, or None without a companion
        self.before: dict[str, tuple[str, str]] = {}  # companion -> its text and its fact file's hash, before the delta
        self.docs: dict[str, dict] = {}  # fact file -> its companion as read, before the delta
        self.exact: dict[str, set[Ref]] = {}  # fact file -> the rows that have or get an exact entry
        self.used: set[int] = set()

    def _open(self, name: str, text: str):
        comp = companion(name)
        path = writer.fact_path(self.pack_dir, comp)
        if not path.exists():
            return None
        raw = path.read_bytes()
        self.before[comp] = (raw.decode("utf-8"), _sha(text))
        entry = self.restore.get(comp)
        if entry is not None:
            if sha256(raw).hexdigest() != entry["sources_sha256"] or _sha(text) != entry["facts_sha256"]:
                raise writer.WriteError(f"{comp}: stale source undo; no files changed")
            return RESTORED
        doc = strict_yaml.load(raw.decode("utf-8"), comp)
        ledger = _origins(sources.text_entries(self.lay.pack, name, text, metadata=doc), comp)
        self.docs[name], self.exact[name] = doc, {(e["row"]["relation"], e["row"]["key"]) for e in doc.get("rows", [])}
        return ledger

    def _written(self, n: int, name: str, rows: set) -> dict[Ref, dict]:
        origin = self.origins.get(n, self.stated)
        if origin is None and rows:
            raise writer.WriteError(f"{name} has a source companion: the rows this change writes need their real "
                                    "origin from the caller (origins); a proposal or a file position is not one")
        if origin is None or not rows:  # an origin for a step that writes no rows stays unused, and blocks at the end
            return {}
        if n in self.origins:
            self.used.add(n)
        self.exact[name] |= rows
        return _origins(({"row": {"relation": r, "key": k}, **origin} for r, k in sorted(rows)), f"change {n}")

    def _kept(self, name: str, text: str, ledger: dict[Ref, dict]) -> str | None:
        """The companion of fact file `name` (now `text`) in the form it had, or None for the canonical rows
        form: a companion of rows only, a layout `kept_text` does not edit, or a result that would not give
        every row exactly the sources of `ledger`. That last check is what makes keeping the form safe."""
        doc, comp = self.docs[name], companion(name)
        if not set(doc) - {"rows"}:
            return None
        try:
            data = strict_yaml.load(text, name) or {}
            rows = sources.collected(ledger[ref] for ref in self.exact[name] if ref in ledger)
            orphans = set()
            try:  # the selectors of records and cells the delta removed
                sources.text_entries(self.lay.pack, name, text, data, metadata={**doc, "rows": rows})
            except sources.Unmatched as e:
                orphans = e.selectors
            drop = {i for i, entry in enumerate(doc.get("records", []))
                    if sources.selector(self.lay.pack, entry, comp) in orphans}
            kept = kept_text(self.before[comp][0], drop, rows)
            if kept is None or (sources.text_entries(self.lay.pack, name, text, data, metadata=strict_yaml.load(kept, comp))
                                != sources.collected(ledger.values())):
                return None
            return kept
        except (facts.LoadError, yaml.YAMLError):
            return None

    def step(self, n: int, name: str, text: str, change: dict) -> tuple[str, dict]:
        """Apply change `n` to the text of fact file `name`; its companion's rows follow."""
        try:
            if name not in self.files:
                self.files[name] = self._open(name, text)
            ledger = self.files[name]
            if ledger is None or ledger is RESTORED:
                return source_format.of(name).edit_fact(self.lay, text, change)
            if set(change) - CHANGE_KEYS:
                raise writer.WriteError("a change cannot supply origin or review authority")
            return step(self.lay, name, text, change, ledger, lambda rows: self._written(n, name, rows), f"change {n}")
        except (facts.LoadError, yaml.YAMLError, UnicodeDecodeError) as e:
            raise writer.WriteError(f"{companion(name)}: {e}") from e

    def finish(self, texts: dict[str, str], undo: dict) -> None:
        """Add each touched companion's new text to `texts`, and to `undo` what puts it back exactly."""
        if set(self.origins) - self.used:
            raise writer.WriteError(f"origin input for change {min(set(self.origins) - self.used)} is not used: its step "
                                    "writes no rows in a fact file with a source companion; no facts changed")
        if set(self.restore) - {companion(n) for n, ledger in self.files.items() if ledger is RESTORED}:
            raise writer.WriteError("an undo's 'sources' entry names no source companion this delta touches")
        back = []
        for name in sorted(n for n, ledger in self.files.items() if ledger is not None):
            comp, ledger = companion(name), self.files[name]
            try:
                if ledger is RESTORED:  # only with the fact bytes it described; then it must still read
                    text = self.restore[comp]["text"]
                    if _sha(texts[name]) != self.restore[comp]["restored_facts_sha256"]:
                        raise writer.WriteError(f"{comp}: the undo's changes do not give back the facts its companion describes")
                    sources.text_entries(self.lay.pack, name, texts[name], metadata=strict_yaml.load(text, comp))
                else:
                    text = self._kept(name, texts[name], ledger)
                    if text is None:
                        text = sources.canonical_sidecar_text(self.lay.pack, name, texts[name], list(ledger.values()))
            except (facts.LoadError, yaml.YAMLError) as e:
                raise writer.WriteError(f"{comp}: {e}") from e
            texts[comp] = text
            back.append({"file": comp, "sources_sha256": _sha(text), "facts_sha256": _sha(texts[name]),
                         "restored_facts_sha256": self.before[comp][1], "text": self.before[comp][0]})
        if back:
            undo["sources"] = back
