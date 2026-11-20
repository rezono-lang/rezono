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
from typing import TYPE_CHECKING, TypedDict

import yaml

from rezono_compiler import modules, pack, rules_dl

if TYPE_CHECKING:
    from rezono_publisher.publish import Epoch


READER = Path(__file__).resolve().parents[1] / "rezono/src/write-form.ts"
WORD = re.compile(r"[a-z][a-z0-9_]*")
TYPE = re.compile(r"[A-Z][A-Za-z0-9]*")
TYPES = {"string": "Text", "integer": "Int", "boolean": "Bool", "date": "Date"}
MAPPING_FIELDS = (
    ("exact_mappings", "exact mapping"),
    ("close_mappings", "close mapping"),
    ("broad_mappings", "broad mapping"),
)
MAPPING_KEYS = frozenset(field for field, _ in MAPPING_FIELDS)


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


@dataclass(frozen=True)
class PublicationMeaning:
    rows: dict
    columns: tuple
    grounds: dict
    visible: dict
    messages: tuple


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


def valid_annotation_value(value: object, where: str) -> None:
    if isinstance(value, (str, bool, int)):
        return
    if isinstance(value, list):
        for item in value:
            valid_annotation_value(item, where)
        return
    if isinstance(value, dict) and all(isinstance(key, str) for key in value):
        for item in value.values():
            valid_annotation_value(item, where)
        return
    raise ConversionError(f"{where}: unsupported annotation value {value!r}")


def annotation_json(value: object, where: str) -> str:
    valid_annotation_value(value, where)
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


def metadata_lines(doc: dict, where: str, indent: str, *, annotations: dict | None = None) -> list[str]:
    lines = []
    if "description" in doc:
        lines.append(f"{indent}description {quoted(doc['description'], where)}")
    for field, keyword in MAPPING_FIELDS:
        if field in doc:
            values = doc[field]
            if not isinstance(values, list):
                raise ConversionError(f"{where}: expected a list of {keyword}s")
            lines.extend(f"{indent}{keyword} {quoted(value, where)}" for value in values)
    for tag in sorted(annotations or ()):
        lines.append(f"{indent}annotation {name(tag, WORD, where)} = {annotation_json(annotations[tag], where)}")
    return lines


def header_lines(doc: dict, identity: str, module: str, where: str) -> list[str]:
    imports = doc.get("imports", ["linkml:types"])
    default = doc.get("default_range", "string")
    metadata_keys = {"in_language", "prefixes", "description"} | MAPPING_KEYS
    if (doc.get("id") == f"https://rezono.org/rezono/{identity}/{module}"
            and doc.get("name") == module.replace("/", "_") and imports == ["linkml:types"]
            and default == "string" and not metadata_keys & doc.keys()):
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


def world(node: object, where: str, default: str, *, allow_extra: bool = False) -> str:
    annotations = mapping(node, where) if allow_extra else supported(node, {"world"}, where)
    if "world" not in annotations:
        return default
    value = annotations["world"]
    if value not in ("closed", "open"):
        raise ConversionError(f"{where}: expected world closed or open")
    return value


def slot_lines(slot: str, body: object, where: str) -> list[str]:
    doc = supported(body, {"range", "required", "multivalued", "identifier", "minimum_value", "maximum_value",
                           "pattern", "annotations", "description", "slot_uri"} | MAPPING_KEYS, where)
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


def path_equation_lines(equations: object, where: str) -> list[str]:
    if not isinstance(equations, list):
        raise ConversionError(f"{where}: expected a list of path equations")
    lines = []
    for index, entry in enumerate(equations):
        place = f"{where}.path_equations[{index}]"
        doc = supported(entry, {"name", "left", "right"}, place)
        eq_name = name(doc.get("name"), WORD, place)
        paths = []
        for side in ("left", "right"):
            raw = doc.get(side)
            if not isinstance(raw, str) or not raw:
                raise ConversionError(f"{place}: {side} must be a non-empty slot path")
            paths.append(".".join(name(step, WORD, place) for step in raw.split(".")))
        lines.append(f"  equal {eq_name} = {paths[0]}, {paths[1]}")
    return lines


def unique_key_lines(keys: object, where: str) -> list[str]:
    lines = []
    for key_name, definition in mapping(keys, where).items():
        place = f"{where}.unique_keys.{key_name}"
        doc = supported(definition, {"unique_key_slots"}, place)
        slots = doc.get("unique_key_slots")
        if not isinstance(slots, list) or not slots:
            raise ConversionError(f"{place}: expected a non-empty list of unique_key_slots")
        lines.append(f"  unique {name(key_name, WORD, place)} = {', '.join(name(s, WORD, place) for s in slots)}")
    return lines


def condition_expr(slot: str, body: object, where: str, *, allow_equals: bool) -> str:
    slot_name = name(slot, WORD, where)
    allowed = {"value_presence", "required"} | ({"equals_string"} if allow_equals else set())
    doc = supported(body, allowed, where)
    parts = []
    if "equals_string" in doc:
        parts.append(f"{slot_name} = {name(doc['equals_string'], WORD, where)}")
    if "value_presence" in doc:
        if doc["value_presence"] != "PRESENT":
            raise ConversionError(f"{where}: only value_presence PRESENT is supported")
        parts.append(f"{slot_name} is known")
    elif "required" in doc:
        if doc["required"] is not True:
            raise ConversionError(f"{where}: required must be true")
        parts.append(f"{slot_name} is known")
    if not parts:
        raise ConversionError(f"{where}: expected a slot condition")
    return " and ".join(parts)


def class_rule_lines(rules: object, where: str) -> list[str]:
    if not isinstance(rules, list):
        raise ConversionError(f"{where}: expected a list of class rules")
    lines = []
    for index, entry in enumerate(rules, 1):
        place = f"{where}.rules[{index}]"
        doc = supported(entry, {"description", "preconditions", "postconditions"}, place)
        pre = supported(doc.get("preconditions"), {"slot_conditions"}, f"{place}.preconditions")
        post = supported(doc.get("postconditions"), {"slot_conditions"}, f"{place}.postconditions")
        pre_slots = mapping(pre.get("slot_conditions"), f"{place}.preconditions")
        post_slots = mapping(post.get("slot_conditions"), f"{place}.postconditions")
        if not pre_slots:
            raise ConversionError(f"{place}: expected at least one precondition")
        if len(post_slots) != 1:
            raise ConversionError(f"{place}: expected exactly one postcondition slot")
        when_clause = " and ".join(
            condition_expr(slot, cond, f"{place}.preconditions.{slot}", allow_equals=True)
            for slot, cond in pre_slots.items()
        )
        then_slot, then_cond = next(iter(post_slots.items()))
        then_clause = condition_expr(then_slot, then_cond, f"{place}.postconditions.{then_slot}", allow_equals=False)
        lines.append(f"  require rule_{index} when {when_clause} then {then_clause}")
        if "description" in doc:
            lines.append(f"    description {quoted(doc['description'], place)}")
    return lines


def schema_source(path: Path, identity: str, module: str) -> Source:
    where = f"schema/{module}.yaml"
    doc = supported(yaml.safe_load(path.read_text(encoding="utf-8")),
                    {"id", "name", "imports", "default_range", "annotations", "types", "enums", "classes",
                     "in_language", "prefixes", "description"} | MAPPING_KEYS, where)
    layer = supported(doc.get("annotations", {}), {"layer"}, where).get("layer", "facts")
    if layer not in pack.LAYERS:
        raise ConversionError(f"{where}: unknown layer {layer!r}")

    lines: list[str] = []
    for scalar, definition in mapping(doc.get("types", {}), where).items():
        place = f"{where}: {scalar}"
        body = supported(definition, {"typeof", "description"}, place)
        typeof = body.get("typeof")
        if typeof not in TYPES:
            raise ConversionError(f"{place}: unsupported scalar base {typeof!r}")
        if "description" in body:
            quoted(body["description"], place)
        lines.extend([f"type {name(scalar, TYPE, place)} = {TYPES[typeof]}", ""])

    for enum, definition in mapping(doc.get("enums", {}), where).items():
        place = f"{where}: {enum}"
        body = supported(definition, {"permissible_values", "annotations", "description"} | MAPPING_KEYS, place)
        members = mapping(body.get("permissible_values"), place)
        if not members:
            raise ConversionError(f"{place}: expected at least one enum member")
        own_world = world(body.get("annotations", {}), place, "closed")
        words = " | ".join(name(member, WORD, place) for member in members)
        lines.append(f"enum {name(enum, TYPE, place)} world {own_world} = {words}")
        lines.extend(metadata_lines(body, place, "  "))
        for member, definition in members.items():
            member_where = f"{place}.{member}"
            metadata = supported({} if definition is None else definition, {"description"} | MAPPING_KEYS,
                                 member_where)
            if annotations := metadata_lines(metadata, member_where, "    "):
                lines.extend([f"  value {member}", *annotations])
        lines.append("")

    for kind, definition in mapping(doc.get("classes", {}), where).items():
        place = f"{where}: {kind}"
        body = supported(definition, {"abstract", "is_a", "represents_relationship", "annotations", "attributes",
                                      "unique_keys", "rules", "description"} | MAPPING_KEYS, place)
        abstract = "abstract " if flag(body, "abstract", place) else ""
        relationship = "relationship " if flag(body, "represents_relationship", place) else ""
        annotations = mapping(body.get("annotations", {}), place)
        own_world = world(annotations, place, "closed", allow_extra=True)
        extra_annotations = {key: value for key, value in annotations.items() if key not in {"world", "path_equations"}}
        parent = f" is {name(body['is_a'], TYPE, place)}" if "is_a" in body else ""
        lines.append(f"{abstract}{relationship}kind {name(kind, TYPE, place)}{parent} world {own_world}")
        lines.extend(metadata_lines(body, place, "  ", annotations=extra_annotations))
        attributes = mapping(body.get("attributes", {}), place)
        if not parent and not any(isinstance(value, dict) and value.get("identifier") is True
                                  for value in attributes.values()):
            raise ConversionError(f"{place}: cannot introduce an implicit identifier")
        for slot, value in attributes.items():
            lines.extend(slot_lines(slot, value, f"{place}.{slot}"))
        if "path_equations" in annotations:
            lines.extend(path_equation_lines(annotations["path_equations"], place))
        if "unique_keys" in body:
            lines.extend(unique_key_lines(body["unique_keys"], place))
        if "rules" in body:
            lines.extend(class_rule_lines(body["rules"], place))
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


def condition_meaning(cond: pack.Condition) -> pack.Condition:
    facets = dict(cond.facets)
    if facets.get("value_presence") == "PRESENT":
        facets.pop("value_presence")
        facets["required"] = True
    return replace(cond, facets=facets)


def kind_meaning(kind: pack.Kind) -> pack.Kind:
    slots = {name: replace(slot, span=None) for name, slot in kind.slots.items()}
    rules = [
        replace(
            rule,
            pre=[condition_meaning(c) for c in rule.pre],
            post=[condition_meaning(c) for c in rule.post],
            otherwise=[condition_meaning(c) for c in rule.otherwise],
        )
        for rule in kind.rules
    ]
    return replace(kind, slots=slots, rules=rules, span=None, spans={})


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
    # A rules file named after no schema becomes a native module that only holds rules
    # (decisions/language-native-rules.md); it declares no type, so it is not an extra schema.
    known = {schema["module"] for schema in baseline.schemas}
    typed = {kind.module for kind in trial.kinds.values()}
    trial_schemas = [{key: value for key, value in schema.items() if key != "file"} for schema in trial.schemas
                     if schema["module"] in known or schema["module"] in typed]
    if original_schemas != trial_schemas:
        raise ConversionError("the candidate changed the schema or module identity")
    if (list(map(kind_meaning, baseline.kinds.values())) != list(map(kind_meaning, trial.kinds.values()))
            or list(baseline.enums.items()) != list(trial.enums.items())):
        raise ConversionError("the candidate changed the typed schema")
    if (baseline.labels, baseline.channels) != (trial.labels, trial.channels):
        raise ConversionError("the candidate changed presentation metadata")


def columns_in(epoch: Epoch, rules: dict, bundle: dict) -> tuple:
    """Typed column names and order, including columns of relations with no rows."""
    return (
        epoch.columns,
        {r["name"]: r.get("key", []) for r in rules["relations"]},
        {r["id"]: r["columns"] for r in bundle.get("relations", ())},
        [(kind["id"], kind.get("id_type")) for kind in bundle.get("kinds", ())],
        [(a["id"], a.get("semantic")) for a in bundle.get("attributes", ())],
        [(a["id"], a.get("semantic")) for a in bundle.get("arrows", ())],
        bundle.get("pages", ()),
    )


def message_entries(bundle: dict) -> dict:
    return {locale["lang"]: {key: value.split("=", 1)[1].strip() for key, value in pack.entries(locale["resource"])}
            for locale in bundle.get("messages", ())}


def message_meaning(template: str, bindings: dict[str, str]) -> tuple:
    parts = pack.VARIABLE.split(template)
    return tuple(("text", part) if i % 2 == 0 else
                 ("binding", bindings[part]) if part in bindings else ("argument", part)
                 for i, part in enumerate(parts))


def role_form(bucket, pack_name: str, manifest: str, role: str) -> tuple | None:
    """Read visible rows and ordered columns through the published form's index."""
    from pyarrow import ipc
    from rezono_publisher import forms

    current = bucket.get(forms.index_key(pack_name, manifest, role))
    if current is None:
        return None
    entries = {entry["name"]: entry["sha256"] for entry in json.loads(current)["objects"]}
    prefix = forms.prefix(pack_name, manifest, role)

    def read(name: str) -> bytes:
        return forms._named(prefix + name, bucket.get(prefix + name), entries[name])

    collection = json.loads(read("rows.json"))
    rows = {(row["$kind"], row["$id"]): {key: value for key, value in row.items() if key not in {"$src", "$why"}}
            for row in collection["$rows"]}
    columns = {name: ipc.open_file(read(name)).schema.names for name in entries
               if name.startswith("table.") and not name.startswith("table._") and name.endswith(".arrow")}
    return rows, columns


def read_publication(epoch: Epoch, directory: Path, roles: dict[str, str]) -> PublicationMeaning:
    """Read the exact snapshots the ordinary checked publisher makes for each role."""
    from rezono_checker.grounds import checked_grounds, reference
    from rezono_publisher import publish, store

    bucket = store.FileStore(directory)
    requested = dict(roles)
    complete_role = next((role for role, mode in roles.items() if mode == "complete"), None)
    if complete_role is None:
        complete_role = "conversion_checker"
        while complete_role in requested:
            complete_role += "_check"
        requested[complete_role] = "complete"
    with_forms = bool(epoch.bundle and not epoch.proposal and not epoch.variant and "may_read" in roles.values())
    manifest = publish.publish(epoch, bucket, requested, forms=with_forms)
    rows, witnesses = publish.frozen(epoch)
    rules_doc, rules, _ = publish.rule_ir(epoch)
    bundle = json.loads(epoch.bundle) if epoch.bundle else {}
    complete = {"id": manifest["id"], "snapshots": [s for s in manifest["snapshots"] if s["role"] == complete_role]}
    prefix = bucket.uri("")
    grounds = checked_grounds(witnesses, complete, rules, lambda uri: bucket.get(uri.removeprefix(prefix)),
                              calc_ir=publish.calc_ir(epoch), calc_witnesses=epoch.calc_witnesses)

    resources = message_entries(bundle)
    messages = {rule["id"]: rule.get("message") for rule in bundle.get("rules", ())}
    rule_messages = set(messages.values())
    static = {lang: {key: value for key, value in entries.items()
                     if key not in rule_messages and not key.startswith("rule.")}
              for lang, entries in resources.items()}
    visible = {}
    for role in roles:
        objects = publish.role_objects(bucket, epoch.pack, manifest["id"], role)
        snapshots = {path: bucket.get(key) for path, key in objects.items() if path.startswith("relations/")}
        full = {entry["relation"] for entry in manifest["snapshots"] if entry["role"] == role and entry["full"]}
        sees = json.loads(bucket.get(objects["witnesses.json"]))
        dynamic = {}
        for witness in sees["witnesses"]:
            message = messages.get(witness["rule_id"])
            bindings = {pair["variable"].removeprefix("?"): pair["value"] for pair in witness.get("bindings", ())}
            body = {lang: message_meaning(entries[message], bindings)
                    for lang, entries in resources.items() if message in entries}
            if body:
                dynamic[reference(witness["conclusion"])] = body
        form = role_form(bucket, epoch.pack, manifest["id"], role) if with_forms and roles[role] == "may_read" else None
        visible[role] = (snapshots, full, dynamic, form)
    presentation = (static, bundle.get("labels"), bundle.get("channels"))
    return PublicationMeaning(rows, columns_in(epoch, rules_doc, bundle), grounds, visible, presentation)


def compare_publications(baseline: Epoch, trial: Epoch, roles: dict[str, str]) -> None:
    """Compare checked facts, conclusions, role views and the union of verified grounds."""
    from rezono_publisher.publish import Blocked

    with tempfile.TemporaryDirectory(prefix="rezono-comparison-") as temporary:
        root = Path(temporary)
        try:
            left = read_publication(baseline, root / "original", roles)
            right = read_publication(trial, root / "candidate", roles)
        except (Blocked, ValueError) as error:
            raise ConversionError(f"publication evidence is invalid: {error}") from error
    if (left.rows, left.columns) != (right.rows, right.columns):
        raise ConversionError("the candidate changed the facts, conclusions or typed columns")
    if left.grounds != right.grounds:
        changed = min(key for key in left.grounds.keys() | right.grounds.keys()
                      if left.grounds.get(key) != right.grounds.get(key))
        raise ConversionError(f"the candidate changed the grounds for {changed[0]} {changed[1]}")
    if (left.visible, left.messages) != (right.visible, right.messages):
        raise ConversionError("the candidate changed role rows or presentation")


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
    # The compiler uses this runtime to read the authored source again.
    os.environ["REZONO_NODE"] = args.node
    try:
        candidate(args.pack, args.candidate, args.node, args.consumer)
    except (OSError, ValueError, pack.CompileError, yaml.YAMLError) as error:
        parser.exit(1, f"{error}\n")
    print("Candidate compiled. Compare both publications before replacing the original pack.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
