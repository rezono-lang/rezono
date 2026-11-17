"""S25: where base rows come from, outside the engine and its definition hash.

Only main's facts are read here. The canonical writer changes a fact file and its sidecar together
(source_writer), and a schema operation carries sources along (operate); scenario overlays follow.
"""
from __future__ import annotations

from functools import lru_cache
from datetime import datetime
from pathlib import Path
import re

import yaml
from rede_canon import canonical_json

from . import facts
from .pack import Pack, contract_dir

@lru_cache(None)
def contract() -> dict:
    return yaml.safe_load((contract_dir() / "source.yaml").read_text("utf-8"))


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


def file_entries(pack: Pack, path: Path, data: dict | None = None, *, metadata=UNSET) -> list[dict]:
    companion = path.with_suffix(".sources.yaml")
    if metadata is UNSET and companion.exists():
        metadata = yaml.safe_load(companion.read_text("utf-8"))
    return text_entries(pack, path.name, path.read_text("utf-8"), data, metadata=metadata)


def text_entries(pack: Pack, name: str, text: str, data: dict | None = None, *, metadata=UNSET) -> list[dict]:
    """The same row/source reader on supplied text, without file or network access."""
    path = Path(name)
    data = (yaml.safe_load(text) or {}) if data is None else data
    if not isinstance(data, dict):
        raise facts.LoadError(f"{path.name}: fact data is a mapping of kinds to records")
    companion = path.with_suffix(".sources.yaml")
    explicit = metadata is not UNSET
    default, overrides, exact = sidecar(pack, companion, metadata) if explicit else (None, {}, {})
    # Implicit sources cite the containing record's line, including any inlined facts it supplies.
    tree = yaml.compose(text) if not explicit else None
    sections = {k.value: v for k, v in tree.value} if isinstance(tree, yaml.MappingNode) else {}
    out, matched, matched_rows = [], set(), set()
    judged = facts.schema(pack)

    def choices(kind, key, slot):
        selected = None
        for k in pack.ancestors(kind):
            candidate = (k, canonical_json(key), slot)
            if candidate in overrides:
                matched.add(candidate)
                if selected is None:
                    selected = overrides[candidate]
        return selected

    for kind, records in data.items():
        if kind not in pack.kinds or not isinstance(records or [], list):
            raise facts.LoadError(f"{path.name}: unknown kind or non-list records {kind!r}")
        nodes = sections[kind].value if kind in sections else []
        for i, record in enumerate(records or []):
            if not isinstance(record, dict):
                raise facts.LoadError(f"{path.name}: {kind} record {i} is no mapping")
            fallback = [([default], None)] if default else None
            if not explicit:
                fallback = [([{"kind": "pack", "name": f"facts/{path.name}", "position": str(nodes[i].start_mark.line + 1)}], None)]

            def record_context(row_kind, row_key, parent):
                return choices(row_kind, row_key, None) or parent

            def row(table, values, row_kind, row_key, slot, context):
                ref = {"relation": table, "key": canonical_json(values)}
                exact_key = (table, ref["key"])
                if exact_key in exact:
                    matched_rows.add(exact_key)
                    out.append(exact[exact_key])
                    # A cell selector can still name this fact even when exact rows override it.
                    if slot is not None:
                        choices(row_kind, row_key, slot)
                    return
                selected = choices(row_kind, row_key, slot) if slot is not None else None
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
    return collected(e for path in facts.files(pack_dir) for e in file_entries(pack, path))


def compile_sources(pack: Pack, pack_dir: str | Path) -> str:
    return canonical_json(read(pack, pack_dir)) + "\n"


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
