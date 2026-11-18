#!/usr/bin/env python3
"""Prepare a separate Rezono candidate from a pack's LinkML schemas and Datalog.

Requires an installed compiler and the checkout's Node 24 language reader with
its locked dependencies. Keep the original pack as the publication oracle.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass, replace
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
from typing import TypedDict

import yaml

from rezono_compiler import modules, pack, rules_dl


READER = Path(__file__).resolve().parents[1] / "rezono/src/write-form.ts"
WORD = re.compile(r"[a-z][a-z0-9_]*")
TYPE = re.compile(r"[A-Z][A-Za-z0-9]*")
TYPES = {"string": "Text", "integer": "Int", "boolean": "Bool", "date": "Date"}


class ModuleEntry(TypedDict):
    module: str
    form: str
    layer: str


class ConversionError(ValueError):
    pass


@dataclass(frozen=True)
class Source:
    layer: str
    lines: list[str]


def mapping(node: object, where: str) -> dict:
    if not isinstance(node, dict) or not all(isinstance(key, str) for key in node):
        raise ConversionError(f"{where}: expected a named mapping")
    return node


def supported(node: object, fields: set[str], where: str) -> dict:
    doc = mapping(node, where)
    extra = doc.keys() - fields
    if extra:
        raise ConversionError(f"{where}: no conversion for {', '.join(sorted(extra))}")
    return doc


def name(value: object, pattern: re.Pattern[str], where: str) -> str:
    if not isinstance(value, str) or not pattern.fullmatch(value):
        raise ConversionError(f"{where}: cannot keep the name {value!r} in Rezono")
    return value


def range_name(value: object, where: str) -> str:
    if not isinstance(value, str):
        raise ConversionError(f"{where}: expected a named range")
    return TYPES[value] if value in TYPES else name(value, TYPE, where)


def quoted(value: object, where: str) -> str:
    if not isinstance(value, str):
        raise ConversionError(f"{where}: expected text")
    return json.dumps(value, ensure_ascii=False)


def metadata_lines(doc: dict, where: str, indent: str) -> list[str]:
    lines = []
    if "description" in doc:
        lines.append(f"{indent}description {quoted(doc['description'], where)}")
    if "exact_mappings" in doc:
        values = doc["exact_mappings"]
        if not isinstance(values, list):
            raise ConversionError(f"{where}: expected a list of exact mappings")
        lines.extend(f"{indent}exact mapping {quoted(value, where)}" for value in values)
    return lines


def header_lines(doc: dict, identity: str, module: str, where: str) -> list[str]:
    imports = doc.get("imports", ["linkml:types"])
    default = doc.get("default_range", "string")
    if (doc.get("id") == f"https://rezono.org/rezono/{identity}/{module}"
            and doc.get("name") == module.replace("/", "_") and imports == ["linkml:types"]
            and default == "string" and not {"in_language", "prefixes", "description", "exact_mappings"} & doc.keys()):
        return []
    if not isinstance(imports, list):
        raise ConversionError(f"{where}: expected a list of imports")
    lines = [f"schema {name(doc.get('name'), WORD, where)}", f"  iri {quoted(doc.get('id'), where)}"]
    if "in_language" in doc:
        lines.append(f"  language {name(doc['in_language'], WORD, where)}")
    for prefix, iri in mapping(doc.get("prefixes", {}), where).items():
        lines.append(f"  prefix {name(prefix, WORD, where)} = {quoted(iri, where)}")
    lines.extend(f"  import {quoted(import_path, where)}" for import_path in imports)
    lines.append(f"  default range {range_name(default, where)}")
    lines.extend(metadata_lines(doc, where, "  "))
    if "layer" in doc.get("annotations", {}):
        lines.append(f"  annotation layer = {quoted(doc['annotations']['layer'], where)}")
    return [*lines, ""]


def flag(doc: dict, key: str, where: str) -> bool:
    value = doc.get(key, False)
    if type(value) is not bool:
        raise ConversionError(f"{where}: {key} must be a boolean")
    return value


def world(node: object, where: str, default: str) -> str:
    annotations = supported(node, {"world"}, where)
    if "world" not in annotations:
        return default
    value = annotations["world"]
    if value not in ("closed", "open"):
        raise ConversionError(f"{where}: expected world closed or open")
    return value


def slot_lines(slot: str, body: object, where: str) -> list[str]:
    doc = supported(body, {"range", "required", "multivalued", "identifier", "minimum_value", "maximum_value",
                           "pattern", "annotations", "description", "exact_mappings", "slot_uri"}, where)
    if slot == "id" and doc == {"identifier": True}:
        return []  # The implicit id has this exact definition.
    if slot == "id":
        raise ConversionError(f"{where}: only the implicit id can be omitted")
    value_type = range_name(doc.get("range", "string"), where)
    required = flag(doc, "required", where)
    multivalued = flag(doc, "multivalued", where)
    card = ("+" if required else "*") if multivalued else ("" if required else "?")
    prefix = f"  {name(slot, WORD, where)}: {value_type}{card}"
    own_world = world(doc.get("annotations", {}), where, "")
    if own_world:
        prefix += f" world {own_world}"
    if flag(doc, "identifier", where):
        prefix += " identifier"
    lines = [prefix]
    if "slot_uri" in doc:
        lines.append(f"    iri {quoted(doc['slot_uri'], where)}")
    lines.extend(metadata_lines(doc, where, "    "))
    for field, token in (("minimum_value", "minimum"), ("maximum_value", "maximum")):
        if field not in doc:
            continue
        if type(doc[field]) is not int:
            raise ConversionError(f"{where}: {field} requires an exact integer")
        lines.append(f"    {token} {doc[field]}")
    if "pattern" in doc:
        lines.append(f"    pattern {quoted(doc['pattern'], where)}")
    return lines


def schema_source(path: Path, identity: str, module: str) -> Source:
    where = f"schema/{module}.yaml"
    doc = supported(yaml.safe_load(path.read_text(encoding="utf-8")),
                    {"id", "name", "imports", "default_range", "annotations", "enums", "classes",
                     "in_language", "prefixes", "description", "exact_mappings"}, where)
    layer = supported(doc.get("annotations", {}), {"layer"}, where).get("layer", "facts")
    if layer not in pack.LAYERS:
        raise ConversionError(f"{where}: unknown layer {layer!r}")

    lines: list[str] = []
    for enum, definition in mapping(doc.get("enums", {}), where).items():
        place = f"{where}: {enum}"
        body = supported(definition, {"permissible_values", "annotations", "description", "exact_mappings"}, place)
        members = mapping(body.get("permissible_values"), place)
        if not members:
            raise ConversionError(f"{place}: expected at least one enum member")
        own_world = world(body.get("annotations", {}), place, "closed")
        words = " | ".join(name(member, WORD, place) for member in members)
        lines.append(f"enum {name(enum, TYPE, place)} world {own_world} = {words}")
        lines.extend(metadata_lines(body, place, "  "))
        for member, definition in members.items():
            member_where = f"{place}.{member}"
            metadata = supported(definition, {"description", "exact_mappings"}, member_where)
            if annotations := metadata_lines(metadata, member_where, "    "):
                lines.extend([f"  value {member}", *annotations])
        lines.append("")

    for kind, definition in mapping(doc.get("classes", {}), where).items():
        place = f"{where}: {kind}"
        body = supported(definition, {"abstract", "is_a", "annotations", "attributes", "description",
                                      "exact_mappings"}, place)
        abstract = "abstract " if flag(body, "abstract", place) else ""
        own_world = world(body.get("annotations", {}), place, "closed")
        parent = f" is {name(body['is_a'], TYPE, place)}" if "is_a" in body else ""
        lines.append(f"{abstract}kind {name(kind, TYPE, place)}{parent} world {own_world}")
        lines.extend(metadata_lines(body, place, "  "))
        attributes = mapping(body.get("attributes", {}), place)
        if not parent and not any(isinstance(value, dict) and value.get("identifier") is True
                                  for value in attributes.values()):
            raise ConversionError(f"{place}: cannot introduce an implicit identifier")
        for slot, value in attributes.items():
            lines.extend(slot_lines(slot, value, f"{place}.{slot}"))
        lines.append("")
    if not lines:
        raise ConversionError(f"{where}: no kind or enum declarations")
    return Source(layer, [*header_lines(doc, identity, module, where), *lines])


def rule_lines(path: Path) -> list[str]:
    where = f"rules/{path.name}"
    module = name(path.stem, WORD, where)
    text = path.read_text(encoding="utf-8")
    rules_dl.parse_file(text, where)
    # Split on actual LF only. Preserve whitespace and every blank line in the
    # block, including whitespace after the separator.
    return [f"rules {module}", *(f"  | {line}" for line in text.removesuffix("\n").split("\n")), ""]


def sources(directory: Path, identity: str) -> dict[str, Source]:
    result = {}
    for path in sorted((directory / "schema").rglob("*.yaml")):
        module = path.relative_to(directory / "schema").with_suffix("").as_posix()
        for part in module.split("/"):
            name(part, WORD, f"schema/{module}.yaml")
        result[module] = schema_source(path, identity, module)
    for path in sorted((directory / "rules").glob("*.dl")):
        lines = rule_lines(path)
        source = result.setdefault(path.stem, Source("facts", []))
        source.lines.extend(lines)
    if not result:
        raise ConversionError("pack has no YAML schemas or Datalog rules")
    return result


def kind_meaning(kind: pack.Kind) -> pack.Kind:
    slots = {name: replace(slot, span=None) for name, slot in kind.slots.items()}
    return replace(kind, slots=slots, span=None, spans={})


def rule_meaning(doc: dict | None) -> dict | None:
    if doc is None:
        return None
    return {**doc, "rules": [{key: value for key, value in rule.items() if key not in {"origin", "span"}}
                              for rule in doc["rules"]]}


def compare_imported(consumer: Path, original: Path, candidate: Path, identity: str) -> None:
    """Check a candidate library through the same pinned consumer as its baseline."""
    consumer = consumer.resolve()
    baseline = pack.read(consumer)
    meta = pack.read_meta(consumer)
    matches = [entry for entry in meta.get("imports", []) if entry.get("name") == identity]
    if len(matches) != 1 or (consumer / matches[0]["path"]).resolve() != original:
        raise ConversionError(f"consumer must import the original {identity} pack")
    with tempfile.TemporaryDirectory(prefix=".rezono-consumer-", dir=consumer.parent) as temporary:
        copy = Path(temporary)
        shutil.copytree(consumer, copy, dirs_exist_ok=True)
        matches[0]["path"] = Path(os.path.relpath(candidate, copy)).as_posix()
        matches[0]["sha256"] = modules.pack_hash(candidate)
        (copy / "pack.yaml").write_bytes(yaml.safe_dump(meta, sort_keys=False).encode("utf-8"))
        compare(baseline, pack.read(copy))


def compare(baseline: pack.Pack, trial: pack.Pack) -> None:
    original_schemas = [{key: value for key, value in schema.items() if key != "file"} for schema in baseline.schemas]
    trial_schemas = [{key: value for key, value in schema.items() if key != "file"} for schema in trial.schemas]
    if original_schemas != trial_schemas:
        raise ConversionError("the candidate changed the schema or module identity")
    if (list(map(kind_meaning, baseline.kinds.values())) != list(map(kind_meaning, trial.kinds.values()))
            or list(baseline.enums.items()) != list(trial.enums.items())):
        raise ConversionError("the candidate changed the typed schema")
    if (rule_meaning(baseline.rules) != rule_meaning(trial.rules)
            or baseline.rule_bodies != trial.rule_bodies):
        raise ConversionError("the candidate changed the rule IR beyond authored source locations")
    if (baseline.labels, baseline.messages, baseline.channels) != (trial.labels, trial.messages, trial.channels):
        raise ConversionError("the candidate changed presentation metadata")


def candidate(original: Path, destination: Path, node: str, consumer: Path | None = None) -> None:
    original = original.resolve()
    destination = destination.resolve()
    if original.parent != destination.parent or original == destination or destination.exists():
        raise ConversionError("choose an unused sibling directory for the candidate pack")
    meta = pack.read_meta(original)
    identity = name(meta.get("name"), modules.PACK_NAME, "pack.yaml")
    if meta.get("rezono") or (original / "rezono").exists():
        raise ConversionError("pack already contains Rezono modules")
    inputs = sources(original, identity)

    legacy = {*(original / "schema").rglob("*.yaml"), *(original / "rules").glob("*.dl")}

    def legacy_sources(path: str, filenames: list[str]) -> set[str]:
        return {filename for filename in filenames if Path(path, filename) in legacy}

    with tempfile.TemporaryDirectory(prefix=".rezono-convert-", dir=original.parent) as temporary:
        stage = Path(temporary)
        shutil.copytree(original, stage, ignore=legacy_sources, dirs_exist_ok=True)
        entries: list[ModuleEntry] = []
        for module, source in sorted(inputs.items()):
            module_path, form_path = f"rezono/{module}.rezono", f"rezono/{module}.json"
            path = stage / module_path
            path.parent.mkdir(parents=True, exist_ok=True)
            text = "\n".join(["rezono 0", f"pack {identity}", "", *source.lines])
            path.write_bytes(text.encode("utf-8"))
            result = subprocess.run([node, str(READER), str(path), str(stage / form_path)],
                                    capture_output=True, encoding="utf-8", check=False)
            if result.returncode:
                diagnostic = (result.stderr or result.stdout).replace(str(path), module_path).strip()
                raise ConversionError(f"language reader refused {module_path}\n{diagnostic}")
            entries.append({"module": module_path, "form": form_path, "layer": source.layer})
        meta["rezono"] = entries
        (stage / "pack.yaml").write_bytes(yaml.safe_dump(meta, sort_keys=False).encode("utf-8"))
        if consumer is None:
            compare(pack.read(original), pack.read(stage))
        else:
            compare_imported(consumer, original, stage, identity)
        stage.rename(destination)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("pack", type=Path)
    parser.add_argument("candidate", type=Path)
    parser.add_argument("--node", default=os.getenv("REZONO_NODE", "node"))
    parser.add_argument("--consumer", type=Path, help="existing pinned consumer of a library or theory pack")
    args = parser.parse_args()
    try:
        candidate(args.pack, args.candidate, args.node, args.consumer)
    except (OSError, ValueError, pack.CompileError, yaml.YAMLError) as error:
        parser.exit(1, f"{error}\n")
    print("Candidate compiled. Compare both publications before replacing the original pack.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
