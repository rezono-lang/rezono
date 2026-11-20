"""Read module/2 metadata and translate its written names to LinkML fields."""

import datetime
import re

from .names import ISO_DATE
from .rezono_lowering import Refuse

MAPPINGS = (("exactMappings", "exact_mappings"), ("closeMappings", "close_mappings"), ("broadMappings", "broad_mappings"))
FIELDS = {"description", "annotations"} | {written for written, _ in MAPPINGS}
HEADER = FIELDS | {"schema", "iri", "language", "prefixes", "imports", "defaultRange"}
NAME = re.compile(r"[a-z][a-z0-9_]*")
WHOLE = re.compile(r"-?(0|[1-9][0-9]*)")
# Fields that the named annotation's schema types as whole numbers (pack.explore); all other values stay as written.
WHOLE_FIELDS = {"explore": frozenset({"min", "max", "step"})}


def name(value: object) -> bool:
    return isinstance(value, str) and NAME.fullmatch(value) is not None


def text_list(value: object) -> bool:
    return isinstance(value, list) and all(isinstance(item, str) for item in value)


def annotation_value(value: object) -> bool:
    if isinstance(value, list):
        return all(annotation_value(item) for item in value)
    if isinstance(value, dict):
        return all(annotation_value(item) for item in value.values())
    return isinstance(value, (str, bool))


def annotation_literal(tag: str, value: object) -> object:
    """The module form writes numbers as exact decimal text; LinkML holds a whole number as an integer.
    Only fields the named annotation's schema types as whole numbers convert; other text stays text."""
    fields = WHOLE_FIELDS.get(tag)
    if not fields or not isinstance(value, dict):
        return value
    return {key: int(item) if key in fields and isinstance(item, str) and WHOLE.fullmatch(item) else item
            for key, item in value.items()}


def valid(body: dict) -> bool:
    if "description" in body and not isinstance(body["description"], str):
        return False
    if any(written in body and not text_list(body[written]) for written, _ in MAPPINGS):
        return False
    if "annotations" in body:
        annotations = body["annotations"]
        if not isinstance(annotations, dict) or not all(
            name(key) and annotation_value(value) for key, value in annotations.items()
        ):
            return False
    return True


def valid_header(body: dict) -> bool:
    if not HEADER.intersection(body):
        return True
    if not name(body.get("schema")):
        return False
    if any(field in body and not isinstance(body[field], str) for field in ("iri", "language", "defaultRange")):
        return False
    if "prefixes" in body:
        prefixes = body["prefixes"]
        if not isinstance(prefixes, dict) or not all(
            name(key) and isinstance(iri, str) for key, iri in prefixes.items()
        ):
            return False
    return ("imports" not in body or text_list(body["imports"])) and valid(body)


def lower(body: dict) -> dict:
    metadata = {}
    if "description" in body:
        metadata["description"] = body["description"]
    for written, target in MAPPINGS:
        if written in body:
            metadata[target] = list(body[written])
    if "annotations" in body:
        annotations = body["annotations"]
        metadata["annotations"] = {tag: {"value": annotation_literal(tag, value)} for tag, value in annotations.items()}
    return metadata


def header(body: dict, schema: dict, layer: str, default_range: str | None, refuse: Refuse) -> dict:
    metadata = lower(body)
    if body.get("annotations", {}).get("layer", layer) != layer:
        refuse("", f"the schema layer must agree with the pack's declared layer, {layer}", "§3")
    metadata["annotations"] = metadata.get("annotations", {}) | {"layer": {"value": layer}}
    for field, target in (("schema", "name"), ("iri", "id"), ("language", "in_language")):
        if field in body:
            metadata[target] = body[field]
    if "prefixes" in body:
        metadata["prefixes"] = dict(body["prefixes"])
    if "imports" in body:
        metadata["imports"] = list(body["imports"])
    if "defaultRange" in body:
        if default_range is None:
            refuse("", f"{body['defaultRange']} is not a built-in default schema range", "§3")
        else:
            metadata["default_range"] = default_range
    return schema | metadata


def deprecated(decl: dict, at: str, refuse: Refuse, section: str) -> tuple[str, str] | tuple[()] | None:
    """Validate a kind or enum `deprecated` member; return `()` when absent or `None` on refusal."""
    if "deprecated" not in decl:
        return ()
    entry = decl["deprecated"]
    if not isinstance(entry, dict) or entry.keys() != {"note", "until"}:
        refuse(f"{at}/deprecated", "`deprecated` needs `note` and `until`", section)
        return None
    note, until = entry["note"], entry["until"]
    if not isinstance(note, str) or "\n" in note or "\r" in note:
        refuse(f"{at}/deprecated", "a `deprecated` note must be a single-line string", section)
        return None
    if not isinstance(until, str) or not ISO_DATE.fullmatch(until):
        refuse(f"{at}/deprecated", f"`deprecated` date must be YYYY-MM-DD, not {until!r}", section)
        return None
    try:
        datetime.date.fromisoformat(until)
    except ValueError:
        refuse(f"{at}/deprecated", f"`deprecated` date is not a calendar date: {until!r}", section)
        return None
    return note, until


def with_deprecated(target: dict, entry: tuple[str, str] | tuple[()]) -> dict:
    """Attach lowered LinkML `deprecated` and `annotations.deprecated_until` when present."""
    if entry:
        note, until = entry
        target["deprecated"] = note
        target.setdefault("annotations", {})["deprecated_until"] = until
    return target
