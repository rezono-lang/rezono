"""Read module/2 metadata and translate its written names to LinkML fields."""

import re

from .rezono_lowering import Refuse

FIELDS = {"description", "exactMappings", "annotations"}
HEADER = FIELDS | {"schema", "iri", "language", "prefixes", "imports", "defaultRange"}
NAME = re.compile(r"[a-z][a-z0-9_]*")


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


def valid(body: dict) -> bool:
    if "description" in body and not isinstance(body["description"], str):
        return False
    if "exactMappings" in body and not text_list(body["exactMappings"]):
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
    if "exactMappings" in body:
        metadata["exact_mappings"] = list(body["exactMappings"])
    if "annotations" in body:
        metadata["annotations"] = {tag: {"value": value} for tag, value in body["annotations"].items()}
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
