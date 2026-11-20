"""S25: where base rows come from, outside the engine and its definition hash.

Only main's facts are read here. The canonical writer changes a fact file and its sidecar together
(source_writer), and a schema operation carries sources along (operate); scenario overlays follow.
"""
from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from functools import lru_cache
from datetime import datetime
import json
from pathlib import Path
import re

import yaml
from rezono_canon import canonical_json

from . import facts, strict_yaml
from .diagnostics import Diagnostic
from .pack import Pack, contract_dir

@lru_cache(None)
def contract() -> dict:
    return strict_yaml.read(contract_dir() / "source.yaml")


FIELDS = set(contract()["classes"]["Source"]["attributes"])
FILE_KINDS = {"git", "pack", "scenario"}
UNSET = object()


@lru_cache(None)
def kinds() -> set[str]:
    """The contract is the authority for source kinds; do not keep a second enum."""
    return set(contract()["enums"]["SourceKind"]["permissible_values"])


def source(value: dict, where: str) -> dict:
    if (not isinstance(value, dict) or set(value) - FIELDS or not {"kind", "name", "position"} <= set(value)
            or any(not isinstance(v, str) or not v.strip() for v in value.values())
            or value["kind"] not in kinds() or (value["kind"] in {"git", "proposal"} and "revision" not in value)):
        raise facts.LoadError(f"{where}: a source needs kind, name and position, and git/proposal a revision")
    schema = contract()
    for name, v in value.items():
        slot = schema["classes"]["Source"]["attributes"][name]
        range_ = slot.get("range")
        pattern = slot.get("pattern") or schema.get("types", {}).get(range_, {}).get("pattern")
        enum = schema.get("enums", {}).get(range_)
        if (pattern and not re.search(pattern, v)) or (enum and v not in enum["permissible_values"]):
            raise facts.LoadError(f"{where}: invalid source {name}")
    if "retrieved_at" in value:
        try:
            datetime.fromisoformat(value["retrieved_at"].replace("Z", "+00:00"))
        except ValueError:
            raise facts.LoadError(f"{where}: retrieved_at must be a real UTC calendar instant") from None
    if value["kind"] == "document":
        for rule in schema["classes"]["Source"].get("rules", []):
            if rule.get("preconditions", {}).get("slot_conditions", {}).get("kind", {}).get("equals_string") != "document":
                continue
            for name, condition in rule.get("postconditions", {}).get("slot_conditions", {}).items():
                if name in value and condition.get("pattern") and not re.search(condition["pattern"], value[name]):
                    raise facts.LoadError(f"{where}: invalid document {name}")
        required = {"url", "fragment_sha256", "licence", "attribution"}
        if not required <= set(value) or not ("revision" in value or "retrieved_at" in value):
            raise facts.LoadError(f"{where}: document needs URL, fragment hash, licence, attribution and revision or retrieved_at")
    if value.get("ownership") == "third_party" and not {"licence", "attribution"} <= set(value):
        raise facts.LoadError(f"{where}: third-party source needs licence and attribution")
    return value


def locator(default: dict | None, override: dict, where: str) -> dict:
    """A JSON-pointer shorthand keeps its inherited file; a full locator is never rewritten."""
    merged = (default or {}) | override
    position = override.get("position")
    if isinstance(position, str) and position.startswith("/") and merged.get("kind") in FILE_KINDS:
        base = (default or {}).get("position", "").partition("#")[0]
        parts = base.split("/")
        if (not default or any(merged.get(k) != default.get(k) for k in ("kind", "name"))
                or not base or base.isdecimal() or base.startswith(("/", "\\")) or ":" in base or "\\" in base
                or any(p in ("", ".", "..") for p in parts)):
            raise facts.LoadError(f"{where}: ambiguous source pointer; give the complete file#pointer locator")
        merged["position"] = base + "#" + position
    return source(merged, where)


def source_entry(value, where: str) -> dict:
    """The shared SourceEntry shape; row existence and SQL typing are checked against emitted rows."""
    row = value.get("row") if isinstance(value, dict) else None
    if (not isinstance(value, dict) or set(value) - {"row", "sources", "reason"}
            or not isinstance(row, dict) or set(row) != {"relation", "key"}
            or any(not isinstance(v, str) or not v for v in row.values())
            or not isinstance(value.get("sources"), list) or not value["sources"]
            or ("reason" in value and (not isinstance(value["reason"], str) or not value["reason"].strip()))):
        raise facts.LoadError(f"{where}: an exact row needs a RowRef, nonempty sources and an optional reason")
    for s in value["sources"]:
        source(s, where)
    return value


class Unmatched(facts.LoadError):
    """Record or cell selectors of a sidecar that name no fact record or cell; `selectors` holds their keys."""

    def __init__(self, message: str, selectors: set):
        super().__init__(message)
        self.selectors = selectors


def selector(pack: Pack, entry, where: str) -> tuple:
    """The key of a `records` entry: the kind, the typed id and the slot (or None) its `of` names."""
    of = entry.get("of") if isinstance(entry, dict) else None
    if (not isinstance(of, dict) or not {"kind", "id"} <= set(of) or set(of) - {"kind", "id", "slot"}
            or not isinstance(of["kind"], str) or of["kind"] not in pack.kinds
            or set(entry) - (FIELDS | {"of", "reason"})):
        raise facts.LoadError(f"{where}: of needs a kind, id and optional slot of this pack")
    kind, slot = of["kind"], of.get("slot")
    if "slot" in of and (not isinstance(slot, str) or not pack.slot(kind, slot)):
        raise facts.LoadError(f"{where}: no slot {slot!r} of {kind}")
    return kind, canonical_json(facts.typed(pack.kinds[pack.root(kind)].id_type, of["id"], where)), slot


def sidecar(pack: Pack, path: Path, doc) -> tuple[dict | None, dict, dict]:
    """Default, compatible record/cell overrides and exact rows, without dropping duplicate sources."""
    if (not isinstance(doc, dict) or set(doc) - {"default", "records", "rows"}
            or any(not isinstance(doc.get(k, []), list) for k in ("records", "rows"))):
        raise facts.LoadError(f"{path.name}: a source sidecar has only default, records and exact rows")
    default = source(doc["default"], path.name) if "default" in doc else None
    entries = {}
    for i, entry in enumerate(doc.get("records", [])):
        where = f"{path.name} record {i}"
        key = selector(pack, entry, where)
        reason = entry.get("reason")
        if "reason" in entry and (not isinstance(reason, str) or not reason.strip()):
            raise facts.LoadError(f"{where}: reason is a message key")
        loc = locator(default, {k: v for k, v in entry.items() if k in FIELDS}, where)
        entries.setdefault(key, []).append(([loc], reason))
    exact = collected(source_entry(e, f"{path.name} row {i}") for i, e in enumerate(doc.get("rows", [])))
    return default, entries, {(e["row"]["relation"], e["row"]["key"]): e for e in exact}


def cited(form: dict, where: str) -> dict[tuple[str, int], dict]:
    """The source of each row of a fact table that cites a source declaration (decisions/language-fact-provenance.md),
    by kind and record index in the order of facts.located_scalar_dataset: the declaration's fields overridden by
    the row's source cells, validated as a sidecar default and a record of that row would be."""
    tables = facts.named_dataset_decls(form)
    declared = {}
    for decl in filter(facts.source_decl, tables):
        name, fields, at = decl["source"], decl["fields"], f"{where} source {decl['source']}"
        if not isinstance(name, str) or name in declared or not isinstance(fields, dict):
            raise facts.LoadError(f"{at}: a source is declared once, with its fields")
        declared[name] = source(fields, at)
    out, counts = {}, {}
    for decl in tables:
        if facts.source_decl(decl):
            continue
        kind, columns, rows, fields = facts.dataset_table(decl)
        start = counts.get(kind, 0)
        counts[kind] = start + len(rows)
        if "source" not in decl:
            continue
        if decl["source"] not in declared:
            raise facts.LoadError(f"{where}: {kind} cites {decl['source']!r}, which is no source of its dataset")
        for i, row in enumerate(rows):
            at = f"{where} {kind}[{start + i + 1}]"
            override = {}
            for field, cell in zip(fields, row[len(columns):], strict=True):
                if cell == {"boundary": "omitted"}:
                    continue
                if (not isinstance(cell, dict) or cell.keys() != {"lit"} or not isinstance(cell["lit"], str)
                        or not cell["lit"].startswith('"')):
                    raise facts.LoadError(f"{at}.@{field}: a source cell is a text literal or a dash")
                try:
                    override[field] = json.loads(cell["lit"])
                except ValueError:
                    raise facts.LoadError(f"{at}.@{field}: invalid quoted text literal") from None
            out[(kind, start + i)] = locator(declared[decl["source"]], override, at)
    return out


def collected(entries) -> list[dict]:
    """One entry per RowRef, sources in canonical order without duplicates; conflicting reasons block."""
    rows = {}
    for e in entries:
        key = (e["row"]["relation"], e["row"]["key"])
        row = rows.setdefault(key, {"row": e["row"], "sources": {}, "reasons": set()})
        row["sources"].update({canonical_json(s): s for s in e["sources"]})
        if "reason" in e:
            row["reasons"].add(e["reason"])
        if len(row["reasons"]) > 1:
            raise facts.LoadError(f"sources: different reasons for {key[0]} {key[1]}")
    out = []
    for key in sorted(rows, key=lambda k: (k[0], k[1].encode("utf-16-be"))):
        row = rows[key]
        out.append({"row": row["row"], "sources": [row["sources"][s] for s in sorted(row["sources"], key=lambda s: s.encode("utf-16-be"))],
                    **({"reason": next(iter(row["reasons"]))} if row["reasons"] else {})})
    return out


def file_entries(pack: Pack, path: Path, data: dict | None = None, *, metadata=UNSET,
                 relative: Path | None = None, dataset=UNSET) -> list[dict]:
    companion = path.with_suffix(".sources.yaml")
    if metadata is UNSET and companion.exists():
        metadata = strict_yaml.read(companion)
    resolved_dataset = facts.dataset_at(path) if dataset is UNSET else dataset
    return text_entries(pack, relative.as_posix() if relative is not None else path.name,
                        "" if resolved_dataset is not None else path.read_text("utf-8"), data,
                        metadata=metadata, dataset=resolved_dataset)


def text_entries(pack: Pack, name: str, text: str, data: dict | None = None, *, metadata=UNSET,
                 dataset: facts.DatasetForm | None = None) -> list[dict]:
    """The same row/source reader on supplied text, without file or network access."""
    path = Path(name)
    judged = facts.schema(pack)
    raw = data
    if dataset is not None:
        raw = dataset.form
    elif data is None or path.suffix == ".json":
        raw = strict_yaml.load(text, name) or {}
    pointers = None
    authored_lines = {span["at"]: span["line"] for span in dataset.form["spans"]} if dataset and dataset.source else {}
    own_sources = {}
    if isinstance(raw, dict) and raw.get("format") in facts.DATASET_FORMATS:
        data, pointers = facts.located_scalar_dataset(judged, raw)
        own_sources = cited(raw, path.name)
    elif data is None:
        data = raw
    if not isinstance(data, dict):
        raise facts.LoadError(f"{path.name}: fact data is a mapping of kinds to records")
    companion = path.with_suffix(".sources.yaml")
    explicit = metadata is not UNSET
    default, overrides, exact = sidecar(pack, companion, metadata) if explicit else (None, {}, {})
    # Implicit sources cite the containing record's line, including any inlined facts it supplies.
    tree = yaml.compose(text) if not explicit and pointers is None else None
    sections = {k.value: v for k, v in tree.value} if isinstance(tree, yaml.MappingNode) else {}
    out, matched, matched_rows = [], set(), set()

    def choices(kind, key, slot):
        selected = None
        for k in pack.ancestors(kind):
            candidate = (k, canonical_json(key), slot)
            if candidate in overrides:
                matched.add(candidate)
                if selected is None:
                    selected = overrides[candidate]
        return selected

    def both(kind, index):
        return facts.LoadError(f"{companion.name}: {kind} record {index + 1} has a source from both its "
                               "fact table's citation and the sidecar")

    for kind, records in data.items():
        if kind not in pack.kinds or not isinstance(records or [], list):
            raise facts.LoadError(f"{path.name}: unknown kind or non-list records {kind!r}")
        nodes = sections[kind].value if kind in sections else []
        for i, record in enumerate(records or []):
            if not isinstance(record, dict):
                raise facts.LoadError(f"{path.name}: {kind} record {i} is no mapping")
            fallback = [([default], None)] if default else None
            if not explicit:
                if pointers is None:
                    name, position = f"facts/{path.name}", str(nodes[i].start_mark.line + 1)
                elif dataset is not None and dataset.source is not None:
                    pointer = pointers[kind][i].removeprefix("/module")
                    name, position = dataset.source, authored_lines[f"{pointer}/0"]
                else:
                    name = path.as_posix() if path.parent.parts else f"rezono/{path.name}"
                    position = f"{name}#{pointers[kind][i]}"
                fallback = [([{"kind": "pack", "name": name, "position": position}], None)]
            own = own_sources.get((kind, i))
            if own is not None:
                if default:
                    raise both(kind, i)
                fallback = [([own], None)]

            def record_context(row_kind, row_key, parent):
                selected = choices(row_kind, row_key, None)
                if selected and own is not None:
                    raise both(kind, i)
                return selected or parent

            def row(table, values, row_kind, row_key, slot, context):
                ref = {"relation": table, "key": canonical_json(values)}
                exact_key = (table, ref["key"])
                if exact_key in exact:
                    if own is not None:
                        raise both(kind, i)
                    matched_rows.add(exact_key)
                    out.append(exact[exact_key])
                    # A cell selector can still name this fact even when exact rows override it.
                    if slot is not None:
                        choices(row_kind, row_key, slot)
                    return
                selected = choices(row_kind, row_key, slot) if slot is not None else None
                if selected and own is not None:
                    raise both(kind, i)
                selected = selected or context
                if not selected:
                    raise facts.LoadError(f"{companion.name}: no source for {row_kind} {row_key!r}")
                for sources, reason in selected:
                    out.append({"row": ref, "sources": sources,
                                **({"reason": reason} if reason else {})})

            facts.walk(judged, kind, record, on_row=row, on_record=record_context, context=fallback)
    if set(overrides) - matched:
        raise Unmatched(f"{companion.name}: source entry names no fact record or cell: {sorted(set(overrides) - matched, key=repr)}",
                        set(overrides) - matched)
    if set(exact) - matched_rows:
        raise facts.LoadError(f"{companion.name}: exact source RowRef is not an emitted canonical row: {sorted(set(exact) - matched_rows)}")
    return collected(out)


def read(pack: Pack, pack_dir: str | Path) -> list[dict]:
    pack_dir = Path(pack_dir)
    return collected(e for path, dataset in facts.files_with_datasets(pack_dir)
                     for e in file_entries(pack, path, relative=path.relative_to(pack_dir), dataset=dataset))


def compile_sources(pack: Pack, pack_dir: str | Path) -> str:
    return canonical_json(read(pack, pack_dir)) + "\n"


NO_ORIGIN = frozenset({"pack", "scenario"})
ORIGIN_WARNING_CODE = "W113"
ORIGIN_ERROR_CODE = "R053"
ORIGIN_MESSAGES = {
    ORIGIN_WARNING_CODE: (
        "`{0}` `{1}` has no origin: only its file and line name it; give it an `@` citation, "
        "a `decide` block, a `Decision` it is bound to, or an entry in its `.sources.yaml` "
        "(kind `synthetic` for generated example data)"
    ),
    ORIGIN_ERROR_CODE: (
        "`{0}` `{1}` has no origin, and a `rezono 1` pack refuses a fact without one; give it an `@` citation, "
        "a `decide` block, a `Decision` it is bound to, or an entry in its `.sources.yaml` "
        "(kind `synthetic` for generated example data)"
    ),
}


@dataclass(frozen=True)
class MissingOrigin:
    """Base rows of one record at one place that have no origin (decisions/fact-origin-required.md)."""
    kind: str
    identifier: str
    file: str
    position: str
    rows: tuple[dict, ...]

    @property
    def place(self) -> str:
        if self.position.isdecimal():
            return f"{self.file}:{self.position}"
        if self.position.startswith(f"{self.file}#") or self.position == self.file:
            return self.position
        return f"{self.file}:{self.position}" if self.file and self.position else (self.file or self.position)

    @property
    def span(self) -> tuple[str, int, int] | None:
        if self.file and self.position.isdecimal() and int(self.position) >= 1:
            return (self.file, int(self.position), 1)
        return None


def _own_fact_files(pack_dir: str | Path | None) -> list[tuple[tuple[str, ...], int]]:
    """Resolved path parts and pack-relative depth of the pack's own fact files."""
    if pack_dir is None:
        return []
    resolved_pack = Path(pack_dir).resolve()
    facts_dir = resolved_pack / "facts"
    if not facts_dir.is_dir():
        return []
    out = []
    for path in sorted(facts_dir.glob("*.yaml")):
        if path.name.endswith(".sources.yaml"):
            continue
        resolved = path.resolve()
        out.append((resolved.parts, len(resolved.relative_to(resolved_pack).parts)))
    return out


def _is_own_fact_file(src: dict, own_files: list[tuple[tuple[str, ...], int]]) -> bool:
    """A `git` source whose position before `#` names one of this pack's own fact files."""
    if src.get("kind") != "git" or not own_files:
        return False
    raw_path = str(src.get("position", "")).partition("#")[0]
    if not raw_path or raw_path.startswith(("/", "\\")):
        return False
    parts = tuple(p for p in Path(raw_path).parts if p not in ("", "."))
    if not parts or ".." in parts:
        return False
    return any(len(parts) >= min_depth and file_parts[-len(parts):] == parts for file_parts, min_depth in own_files)


def _has_origin_source(entry: dict, own_files: list[tuple[tuple[str, ...], int]]) -> bool:
    return any(
        src.get("kind") not in NO_ORIGIN and not _is_own_fact_file(src, own_files)
        for src in entry.get("sources", [])
    )


def _record_key(pack: Pack, relation: str, key: list) -> tuple[str, str]:
    owner = relation.split("__", 1)[0]
    root = pack.root(owner) if owner in pack.kinds else owner
    identifier = str(key[0]) if key else ""
    return root, identifier


def _decision_roots(pack: Pack) -> set[str]:
    """std-decision's Decision root kind(s) present in this pack."""
    return {
        k for k, kind in pack.kinds.items()
        if kind.cls == "Decision"
        and (kind.module.startswith("std-decision:") or pack.meta.get("name") == "std-decision")
    }


def _source_places(entry: dict) -> list[tuple[str, str]]:
    """Distinct (file, position) places of an entry's non-origin sources, in order."""
    places: list[tuple[str, str]] = []
    seen: set[tuple[str, str]] = set()
    for src in entry.get("sources", []):
        if src.get("kind") == "git":
            pos = str(src.get("position", ""))
            pair = (pos.partition("#")[0] or str(src.get("name", "")), pos)
        else:
            pair = (str(src.get("name", "")), str(src.get("position", "")))
        if pair not in seen:
            seen.add(pair)
            places.append(pair)
    return places or [(entry["row"]["relation"], "")]


def missing_origins(pack: Pack, entries: list[dict], pack_dir: str | Path | None = None) -> list[MissingOrigin]:
    """Main base rows without an origin, grouped by record and place (decisions/fact-origin-required.md §§1, 2, 4, 5)."""
    if not entries:
        return []
    own_files = _own_fact_files(pack_dir)
    parsed_rows = [(e["row"]["relation"], json.loads(e["row"]["key"])) for e in entries]
    decision_roots = _decision_roots(pack)
    decision_kinds = {k for k in pack.kinds if any(r in pack.ancestors(k) for r in decision_roots)}
    decision_arrows = {
        slot.table
        for k, kind in pack.kinds.items()
        if k not in decision_kinds
        for slot in kind.slots.values()
        if slot.arrow and slot.range in decision_kinds
    }
    bound = {_record_key(pack, rel, key) for rel, key in parsed_rows if rel in decision_arrows}
    for root in decision_roots:
        deciders = {str(key[0]) for rel, key in parsed_rows if rel == f"{root}__decider" and key}
        dates = {str(key[0]) for rel, key in parsed_rows if rel == f"{root}__decided_on" and key}
        bound |= {(root, identifier) for identifier in deciders & dates}

    groups: dict[tuple[str, str, str, str], list[dict]] = {}
    specific_kind: dict[tuple[str, str, str, str], str] = {}
    for entry, (rel, key) in zip(entries, parsed_rows, strict=True):
        rec_root, identifier = _record_key(pack, rel, key)
        if (rec_root, identifier) in bound or _has_origin_source(entry, own_files):
            continue
        owner = rel.split("__", 1)[0]
        for file, position in _source_places(entry):
            group_key = (rec_root, identifier, file, position)
            groups.setdefault(group_key, []).append(entry["row"])
            current = specific_kind.get(group_key)
            if owner in pack.kinds and (
                current is None
                or current not in pack.kinds
                or len(pack.ancestors(owner)) > len(pack.ancestors(current))
            ):
                specific_kind[group_key] = owner
            elif current is None:
                specific_kind[group_key] = owner

    out = [
        MissingOrigin(
            kind=specific_kind[group_key],
            identifier=group_key[1],
            file=group_key[2],
            position=group_key[3],
            rows=tuple(rows),
        )
        for group_key, rows in groups.items()
    ]
    out.sort(key=lambda item: (item.file, int(item.position) if item.position.isdecimal() else 0,
                               item.position, item.kind, item.identifier))
    return out


def missing_origin_count(missing: Iterable[MissingOrigin]) -> int:
    """Count of distinct main base rows (by RowRef) without an origin (decisions/fact-origin-required.md §5)."""
    return len({(row["relation"], row["key"]) for item in missing for row in item.rows})


def origin_diagnostics(pack: Pack, missing: Iterable[MissingOrigin]) -> tuple[Diagnostic, ...]:
    """W113 warnings on rezono 0, R053 refusals from rezono 1 on (decisions/fact-origin-required.md §4)."""
    refuse = pack.language_version != "0"
    code = ORIGIN_ERROR_CODE if refuse else ORIGIN_WARNING_CODE
    severity = "error" if refuse else "warning"
    template = ORIGIN_MESSAGES[code]
    return tuple(
        Diagnostic(
            code=code,
            message=template.format(item.kind, item.identifier),
            where=f"{item.kind} {item.identifier}",
            span=item.span,
            severity=severity,
        )
        for item in missing
    )


def format_origin_diagnostic(item: MissingOrigin, diagnostic: Diagnostic) -> str:
    """One command-line line without severity prefix: `<code> <place>: <sentence>`."""
    return f"{diagnostic.code} {item.place}: {diagnostic.message}"


def canonical_sidecar(pack: Pack, path: Path, entries: list[dict]) -> str:
    """Lossless rows-only metadata for unchanged fact bytes; never rewrite facts or their locators."""
    return canonical_sidecar_text(pack, path.name, path.read_text("utf-8"), entries)


def canonical_sidecar_text(pack: Pack, name: str, text: str, entries: list[dict]) -> str:
    """Validate and render complete exact sources against supplied fact bytes, without writing either."""
    path = Path(name)
    rows = collected(source_entry(e, f"{path.name} row {i}") for i, e in enumerate(entries))
    doc = {"rows": rows}
    if text_entries(pack, path.name, text, metadata=doc) != rows:
        raise facts.LoadError(f"{path.name}: sidecar does not preserve every source entry")
    return canonical_json(doc) + "\n"  # canonical JSON is also YAML, with no second rendering convention
