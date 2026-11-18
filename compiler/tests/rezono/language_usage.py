"""List the source features used by packs and the evidence for lowering them."""

import ast
from collections import Counter
from dataclasses import dataclass
from functools import cache
from pathlib import Path
import re

import yaml


ROOT = Path(__file__).resolve().parents[3]
SCOPES = ("examples", "packs", "run")
BASIC_READER = ("rezono/test/module-json.test.ts", "the same text gives the same bytes, and they are the bytes of the contract fixture")
BASIC_LOWERER = ("compiler/tests/test_rezono_module.py", "test_a_module_gives_the_bundle_and_the_engine_of_the_schema_file_that_says_the_same")


def paired(reader, lowerer):
    return (f"rezono/test/test_{reader}.py", f"test_{reader}"), (
        f"compiler/tests/rezono/test_{lowerer}.py", f"test_{lowerer}",
    )


# Both tests must exist without an expected-failure marker. The ordinary
# component suites run these checks. An untested feature stays pending.
EVIDENCE = {
    feature: (BASIC_READER, BASIC_LOWERER)
    for feature in ("kind", "slot", "reference", "enum", "optional-slot")
} | {
    "abstract-kind": paired("abstract_kind", "lower_abstract_kind"),
    "parent-kind": paired("parent_kind", "lower_parent_kind"),
    "explicit-identifier": paired("explicit_identifier", "lower_explicit_identifier"),
    "embedded-kind": paired("embedded_kind", "lower_embedded_kind"),
    "embedded-reference": paired("embedded_relation", "lower_embedded_reference"),
    "bounded-slot": paired("bounded_slot", "lower_bounded_list"),
    "slot-pattern": paired("slot_pattern", "lower_slot_pattern"),
    "numeric-limit": paired("numeric_limits", "lower_numeric_limits"),
    "scalar-alias": paired("scalar_alias", "lower_scalar_alias"),
    "composite-key": paired("composite_key", "lower_composite_key"),
    "path-equation": paired("path_equation", "lower_path_equation"),
    "relational-rule": (
        ("rezono/test/test_relational_rule_block.py", "test_relational_rule_block"),
        ("compiler/tests/rezono/test_rule_witness.py", "test_rezono_rule_proves_listed_item"),
    ),
    "boolean-slot": (BASIC_READER, ("compiler/tests/rezono/test_library_boolean.py", "test_library_boolean_slot")),
    "decision-table": (BASIC_READER, ("compiler/tests/test_rezono_table.py", "test_the_oracle_runs_the_text_the_compiler_reads")),
}

KIND_FEATURES = {
    "abstract": "abstract-kind", "is_a": "parent-kind", "unique_keys": "composite-key",
    "rules": "conditional-check", "represents_relationship": "relationship-kind",
}
SLOT_FEATURES = {
    "pattern": "slot-pattern", "minimum_value": "numeric-limit", "maximum_value": "numeric-limit",
    "minimum_cardinality": "bounded-slot", "maximum_cardinality": "bounded-slot",
    "inlined": "embedded-reference", "inlined_as_list": "embedded-reference",
    "multivalued": "repeated-slot",
}
KIND_ANNOTATIONS = {"path_equations": "path-equation", "seal": "time-policy"}
SCALAR_TYPES = {"string", "integer", "date", "datetime", "boolean", "decimal", "float", "double", "uri", "uriorcurie", "ncname"}
BASE_KIND_FIELDS = {"attributes", "description", "annotations", *KIND_FEATURES}
BASE_SLOT_FIELDS = {"range", "identifier", "required", "annotations", *SLOT_FEATURES}
BASE_SCHEMA_FIELDS = {"id", "name", "in_language", "default_range", "imports", "classes", "enums", "types", "annotations"}


def yaml_document(path):
    value = yaml.safe_load(path.read_text(encoding="utf-8"))
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise ValueError(f"{path.name}: expected a mapping")
    return value


def schema_features(doc, enum_names, alias_names, embedded_names):
    used = set()
    if (doc.keys() - BASE_SCHEMA_FIELDS or set(doc.get("annotations") or {}) - {"layer"}
            or set(doc.get("imports") or ()) - {"linkml:types"}):
        used.add("schema-metadata")
    if doc.get("enums"):
        used.add("enum")
        if any(enum.keys() - {"permissible_values"} or any(bool(value) for value in (enum.get("permissible_values") or {}).values())
               for enum in doc["enums"].values()):
            used.add("enum-metadata")
    if doc.get("types"):
        used.add("scalar-alias")
    for name, kind in (doc.get("classes") or {}).items():
        used.add("kind")
        if name in embedded_names:
            used.add("embedded-kind")
        used.update(feature for key, feature in KIND_FEATURES.items() if kind.get(key))
        annotations = kind.get("annotations") or {}
        used.update(feature for key, feature in KIND_ANNOTATIONS.items() if key in annotations)
        if kind.keys() - BASE_KIND_FIELDS or kind.get("description") or set(annotations) - {"layer", "world", *KIND_ANNOTATIONS}:
            used.add("schema-metadata")
        if annotations.get("world") == "open":
            used.add("open-world")
        if not kind.get("attributes"):
            continue
        for name, slot in kind["attributes"].items():
            slot = slot or {}
            type_name = slot.get("range", doc.get("default_range", "string"))
            used.update(feature for key, feature in SLOT_FEATURES.items() if slot.get(key) is not None and slot[key] is not False)
            if slot.get("identifier"):
                if name != "id" or type_name != "string":
                    used.add("explicit-identifier")
            else:
                used.add("slot")
                if not slot.get("required") and not slot.get("minimum_cardinality"):
                    used.add("optional-slot")
            if type_name in alias_names:
                used.add("scalar-alias")
            elif type_name in enum_names:
                used.add("enum")
            elif type_name not in SCALAR_TYPES:
                used.add("reference")
            elif type_name not in {"string", "boolean", "date"}:
                used.add("extended-scalar")
            if type_name == "boolean":
                used.add("boolean-slot")
            flags = slot.get("annotations") or {}
            if flags.get("world") == "open":
                used.add("open-world")
            if slot.keys() - BASE_SLOT_FIELDS or flags.keys() - {"world", "layer"}:
                used.add("schema-metadata")
    return used


MODULE_SYNTAX = {
    "kind": r"^kind\b", "slot": r"^\s+\w+\s*:", "enum": r"^enum\b",
    "abstract-kind": r"^abstract kind\b|^kind\b.*\babstract\b", "parent-kind": r"^kind\b.*\bis a\b",
    "embedded-kind": r"^embedded kind\b", "embedded-reference": r"^\s+\w+\s*:.*\bembedded\b",
    "optional-slot": r"^\s+\w+\s*:.*\?", "repeated-slot": r"^\s+\w+\s*:.*[+*]",
    "bounded-slot": r"^\s+\w+\s*:.*\{\d", "slot-pattern": r"^\s+\w+\s*:.*\bpattern\b",
    "numeric-limit": r"^\s+\w+\s*:.*\b(?:min|max)\b", "explicit-identifier": r"^\s+\w+\s*:.*\bidentifier\b",
    "boolean-slot": r"^\s+\w+\s*:\s*Bool\b", "extended-scalar": r"^\s+\w+\s*:\s*(?:Int|DateTime|Money|Ratio)\b",
    "inverse-reference": r"^\s+\w+\s*:.*\binverse\b", "open-world": r"\bworld open\b",
    "scalar-alias": r"^type\b", "composite-key": r"^\s+unique\b", "path-equation": r"^\s+equal\b",
    "module-import": r"^use\b", "fact-table": r"^\s*fact\b", "named-dataset": r"^dataset\b",
    "dated-fact": r"^\s*fact\b.*\b(?:valid|known)\b", "fact-provenance": r"^\s*fact\b.* @ ",
    "parameters": r"^param\b", "units": r"^(?:unit|rounding)\b", "calculation": r"^\s*derived\b",
    "exceptions": r"^\s*unless\b", "decision-table": r"^\s*table\b", "table-policy": r"^\s*table\s+(?!unique\b)\w+", "conditional-check": r"^(?:require|warn)\b",
    "relational-rule": r"^rules?\b", "time-policy": r"^\s+(?:applies|sealed) at:", "schema-metadata": r"^reason\b",
}


def authored_features(path):
    raw = path.read_text(encoding="utf-8")
    # The usage inventory only looks for authored syntax, outside line comments.
    tokens = re.sub(r'"(?:\\.|[^"\\])*"|--[^\n]*', "", raw)
    found = {name for name, pattern in MODULE_SYNTAX.items() if re.search(pattern, tokens, re.MULTILINE)}
    known_lines = [r"^(?:rezono|pack|extend)\b", *MODULE_SYNTAX.values()]
    if any(line and not any(re.search(pattern, line) for pattern in known_lines)
           for line in tokens.splitlines() if not line.startswith((" ", "\t"))):
        found.add("unclassified-authored-syntax")
    return found


def path_features(path):
    if path.suffix == ".rezono":
        return authored_features(path)
    if path.suffix == ".dl":
        source = path.read_text(encoding="utf-8")
        used = {"relational-rule"}
        if re.search(r"^\s*//\s*@invariant\b", source, re.MULTILINE):
            used.add("conditional-check")
        if re.search(r"^\s*//\s*@(?:explain|closes|release)\b", source, re.MULTILINE):
            used.add("rule-metadata")
        return used
    if path.name.endswith(".sources.yaml"):
        return {"fact-provenance"}
    folder = path.parent.name
    if folder == "facts":
        used = {"fact-table", "named-dataset"}
        for rows in yaml_document(path).values():
            for row in rows if isinstance(rows, list) else ():
                if isinstance(row, dict) and any(isinstance(cell, (list, dict)) for cell in row.values()):
                    used.add("structured-fact")
        return used
    if folder == "calc":
        doc = yaml_document(path)
        used = {"calculation"}
        if doc.get("parameters"):
            used.add("parameters")
        if doc.get("as_of") or doc.get("parameter_choice"):
            used.add("time-policy")
        if any(isinstance(rule, dict) and ({"unless", "exceptions"} & rule.keys()) for rule in doc.get("rules", [])):
            used.add("exceptions")
        return used
    return {"unclassified-source"}


@dataclass
class PackUsage:
    files: dict[Path, set[str]]
    imports: tuple[Path, ...]
    missing_import: bool


def pack_paths(folder):
    yield from (folder / "schema").rglob("*.yaml")
    for subdir, suffix in (("facts", ".yaml"), ("calc", ".yaml"), ("rules", ".dl")):
        yield from (folder / subdir).glob(f"*{suffix}")
    yield from folder.glob("*.rezono")
    yield from (folder / "rezono").rglob("*.rezono")


def inventory(root=ROOT):
    root = root.resolve()
    paths = {
        path.parent: yaml_document(path)
        for scope in SCOPES for path in (root / scope).rglob("pack.yaml")
    }
    schema = {
        folder: {path: yaml_document(path) for path in (folder / "schema").rglob("*.yaml")}
        for folder in paths
    }

    @cache
    def dependencies(folder):
        targets = []
        missing = False
        for item in paths[folder].get("imports") or ():
            if (not isinstance(item, dict) or set(item) != {"name", "path", "sha256"}
                    or not isinstance(item["path"], str)
                    or not re.fullmatch(r"[0-9a-f]{64}", str(item["sha256"]))):
                missing = True
                continue
            target = (folder / item["path"]).resolve()
            if target in paths and paths[target].get("name") == item["name"]:
                targets.append(target)
            else:
                missing = True
        return targets, missing

    def closure(folder, active=frozenset()):
        if folder in active:
            return set(), True
        imports, unresolved = dependencies(folder)
        seen = set(imports)
        for target in imports:
            nested, missing = closure(target, active | {folder})
            seen.update(nested)
            unresolved |= missing
        return seen - {folder}, unresolved

    packs = {}
    tallied = set()
    for folder in sorted(paths):
        imported, unresolved = closure(folder)
        known_schema = [doc for name in imported | {folder} for doc in schema[name].values()]
        enums = {name for doc in known_schema for name in (doc.get("enums") or {})}
        aliases = {name for doc in known_schema for name in (doc.get("types") or {})}
        embedded = {
            slot["range"] for doc in known_schema for kind in (doc.get("classes") or {}).values()
            for slot in (kind.get("attributes") or {}).values()
            if slot and "range" in slot and (slot.get("inlined") or slot.get("inlined_as_list"))
        }
        files = {}
        for path in sorted(set(pack_paths(folder))):
            if path in schema[folder]:
                files[path] = schema_features(schema[folder][path], enums, aliases, embedded)
            else:
                files[path] = path_features(path)
        packs[folder] = PackUsage(files, tuple(sorted(imported)), unresolved)
        tallied.update(files)
    for scope in SCOPES:
        for path in sorted((root / scope).rglob("*.rezono")):
            if path not in tallied:
                packs.setdefault(path.parent, PackUsage({}, (), False)).files[path] = authored_features(path)
    return packs


def passing_test(root, evidence):
    path, name = evidence
    try:
        source = (root / path).read_text(encoding="utf-8")
    except FileNotFoundError:
        return False
    if path.endswith(".ts"):
        return re.search(r"(?m)^[ \t]*test\(['\"]" + re.escape(name) + r"['\"]\s*,\s*\(", source) is not None
    return any(
        isinstance(node, ast.FunctionDef) and node.name == name and not any(
            isinstance(item, ast.Attribute) and item.attr in {"xfail", "skip", "skipif"}
            for decorator in node.decorator_list for item in ast.walk(decorator)
        )
        for node in ast.parse(source).body
    )


def supported(root=ROOT):
    return {feature for feature, tests in EVIDENCE.items() if all(passing_test(root, test) for test in tests)}


def describe(features):
    return ", ".join(sorted(features)) if features else "—"


def render(root=ROOT):
    root = root.resolve()
    packs = inventory(root)
    ready = supported(root)
    counts = Counter(feature for usage in packs.values() for features in usage.files.values() for feature in features)
    lines = ["# Rezono language coverage", "",
             "Run `python compiler/tests/rezono/language_usage.py` from the repository root for the current inventory.",
             "Counts use each authored file once per feature. Higher counts give higher priority among available tasks.",
             "Support requires both reader and lowering tests without expected-failure markers.",
             "Pack readiness includes transitive local imports.",
             "Publication parity is checked separately.",
             "", "| Feature | Files | Reader and lowering |", "| --- | ---: | --- |"]
    for name, count in sorted(counts.items(), key=lambda item: (-item[1], item[0])):
        evidence = EVIDENCE.get(name)
        status = "Pending"
        if evidence:
            reader, lowerer = evidence
            status = ("Supported" if name in ready else "Pending") + f" ([reader](../../{reader[0]}), [lowering](../../{lowerer[0]}))"
        lines.append(f"| {name} | {count} | {status} |")
    lines.extend(["", "| Pack or source directory | Direct features | Imported features | Pending features |",
                  "| --- | --- | --- | --- |"])
    for folder, usage in sorted(packs.items()):
        direct = {feature for values in usage.files.values() for feature in values}
        imports = {feature for dependency in usage.imports for values in packs[dependency].files.values() for feature in values}
        pending = (direct | imports) - ready
        if usage.missing_import:
            pending.add("unresolved-pack-import")
        status = "Ready" if direct or imports else "No language sources"
        if pending:
            status = describe(pending)
        lines.append(f"| {folder.relative_to(root).as_posix()} | {describe(direct)} | {describe(imports)} | {status} |")
    return "\n".join(lines)


if __name__ == "__main__":
    print(render())
