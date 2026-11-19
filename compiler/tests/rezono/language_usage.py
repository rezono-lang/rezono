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
NATIVE_RULE_EVIDENCE = (
    ("reader", ("rezono/test/test_native_rule_reader_roundtrip.py", "test_native_rule_reader_roundtrip")),
    ("form", ("compiler/tests/rezono/test_native_rule_form_contract.py", "test_native_rule_form_contract")),
    ("IR and witness", ("compiler/tests/rezono/test_native_rule_ir_listed.py", "test_native_rule_ir_listed")),
)
NATIVE_RULE_DESIGN = "27ff4dc926166484e549e4da0c95d400d067a18b"
NATIVE_RULE_TESTS = "bd9a459f0e8c4934c92bd39b862208e25eb64363"
NATIVE_RULE_SIGNATURES = "cb086e32909e616fdca40541c9d61c7a7401e14d"
NATIVE_PACK_EVIDENCE = {
    "native-rule-signatures": ("compiler/tests/rezono/test_native_rule_signatures.py", "test_native_rule_signatures"),
    "native-rule-publication-parity": (
        "compiler/tests/rezono/test_native_rule_publication_parity.py", "test_native_rule_publication_parity",
    ),
}
RULE_SPELLINGS = {"relational-rule", "native-rule"}


def paired(reader, lowerer):
    return (f"rezono/test/test_{reader}.py", f"test_{reader}"), (
        f"compiler/tests/rezono/test_{lowerer}.py", f"test_{lowerer}",
    )


# The required tests must exist without an expected-failure marker. The ordinary
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
    "native-rule": tuple(test for _, test in NATIVE_RULE_EVIDENCE),
    "boolean-slot": (BASIC_READER, ("compiler/tests/rezono/test_library_boolean.py", "test_library_boolean_slot")),
    "decision-table": (BASIC_READER, ("compiler/tests/test_rezono_table.py", "test_the_oracle_runs_the_text_the_compiler_reads")),
}


def reader(name):
    return f"rezono/test/test_{name}.py", f"test_{name}"


def lowering(name, test=None):
    return f"compiler/tests/rezono/test_{name}.py", test or f"test_{name}"


# A feature may need several reader and lowering tests; each must pass. Reader tests live under rezono/.
EVIDENCE |= {
    "schema-metadata": (reader("schema_metadata"), reader("schema_mappings"), lowering("lower_schema_metadata"),
                        lowering("lower_schema_mappings"), lowering("lower_schema_annotations")),
    "fact-table": (BASIC_READER, lowering("lower_fact_table")),
    "named-dataset": (reader("named_dataset"), lowering("named_dataset_discovery", "test_lower_named_dataset")),
    "extended-scalar": (BASIC_READER, lowering("lower_extended_scalar")),
    "fact-provenance": (reader("fact_provenance"), lowering("lower_fact_provenance")),
    "conditional-check": (reader("conditional_check"), lowering("lower_conditional_check")),
    "enum-metadata": (reader("schema_metadata"), lowering("lower_enum_metadata")),
    "repeated-slot": (BASIC_READER, ("compiler/tests/test_rezono_module.py",
                                     "test_unbounded_lists_compile_like_written_linkml")),
    "structured-fact": (reader("structured_fact"), lowering("structured_library_dataset")),
    "time-policy": (BASIC_READER, reader("time_policy"), lowering("lower_time_policy")),
    "open-world": (BASIC_READER, lowering("lower_open_world")),
    "rule-metadata": (reader("rule_metadata"), lowering("lower_rule_metadata")),
    "relationship-kind": (reader("relationship_kind"), lowering("lower_relationship_kind")),
    "calculation": (reader("calculation"), lowering("lower_calculation")),
    "parameters": (reader("parameters"), reader("version_replaces"), lowering("lower_parameters")),
    "module-import": (reader("module_import"), lowering("lower_module_import")),
    "inverse-reference": (reader("inverse_reference"), lowering("lower_inverse_reference")),
    "dated-fact": (reader("dated_fact"), reader("fact_context_axes"), lowering("lower_dated_fact")),
    "units": (reader("units"), reader("unit_definition"), lowering("lower_units")),
    "exceptions": (reader("exceptions"), lowering("lower_exceptions")),
    "table-policy": (reader("table_policy"), lowering("lower_table_policy", "test_lower_table_first"),
                     lowering("lower_table_policy", "test_lower_table_collect")),
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
    "exceptions": r"^\s*unless\b", "decision-table": r"^\s*table\b", "table-policy": r"^\s*table\s+(?!unique\b)\w+", "conditional-check": r"^(?:check|require|warn)\b",
    "relational-rule": r"^rules\b", "native-rule": r"^rule\b",
    "time-policy": r"^\s+(?:applies|sealed) at:", "schema-metadata": r"^reason\b",
}
RULE_DECLARATION = re.compile(r"^rule\b[^\n]*(?:\n[ \t][^\n]*)*", re.MULTILINE)
STATE_PREDICATE = re.compile(r"\bis\s+(?:known\b|unknown\b|invalid\b|n/a(?![\w/]))")
STATE_REVIEW = "native-rule-state-review"


def authored_features(path):
    raw = path.read_text(encoding="utf-8")
    # Look for authored syntax outside comments, literals and escaped names.
    tokens = re.sub(r'"(?:\\.|[^"\\])*"|\x60[^\x60\n]*\x60|--[^\n]*', " ", raw)
    found = {name for name, pattern in MODULE_SYNTAX.items() if re.search(pattern, tokens, re.MULTILINE)}
    if any(STATE_PREDICATE.search(rule[0]) for rule in RULE_DECLARATION.finditer(tokens)):
        found.add(STATE_REVIEW)
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
        declared = paths[folder].get("imports", [])
        if declared is None:
            declared = []
        if not isinstance(declared, list):
            return targets, True
        for item in declared:
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


def conversion_status(features, ready, native_pending, missing_import, owning_pack):
    if missing_import:
        return ("Pending: unresolved-pack-import",) * 2
    if not owning_pack:
        return ("No owning pack",) * 2
    if not features:
        return ("No language sources",) * 2

    common = features - ready - RULE_SPELLINGS
    mixed = common | ((features & {"relational-rule"}) - ready)
    if "native-rule" in features:
        mixed |= native_pending
    native = common | native_pending if features & RULE_SPELLINGS else common
    return tuple(f"Pending: {describe(missing)}" if missing else "Ready" for missing in (mixed, native))


def native_rule_link(root, label, path, review_head):
    target = f"../../{path}"
    if not (root / path).is_file():
        target = f"https://github.com/rezono-lang/rezono/blob/{review_head}/{path}"
    return f"[{label}]({target})"


def render_native_rules(root, packs, ready):
    rule_files = {
        path: features for usage in packs.values() for path, features in usage.files.items()
        if features & {"relational-rule", "native-rule"}
    }
    legacy = {path for path, features in rule_files.items() if "relational-rule" in features}
    native = {path for path, features in rule_files.items() if "native-rule" in features}
    evidence = ", ".join(native_rule_link(root, label, path, NATIVE_RULE_TESTS)
                         for label, (path, _) in NATIVE_RULE_EVIDENCE)
    design = native_rule_link(root, "Native rules decision", "decisions/language-native-rules.md", NATIVE_RULE_DESIGN)
    signatures = native_rule_link(root, "signature linking", NATIVE_PACK_EVIDENCE["native-rule-signatures"][0],
                                  NATIVE_RULE_SIGNATURES)
    parity = native_rule_link(root, "publication parity", NATIVE_PACK_EVIDENCE["native-rule-publication-parity"][0],
                              NATIVE_RULE_TESTS)
    states = native_rule_link(root, "state-evidence test",
                              "compiler/tests/rezono/test_native_rule_state_evidence.py", NATIVE_RULE_TESTS)
    status = "Supported" if "native-rule" in ready else "Pending"
    state_summary = ("The table identifies sources for state-evidence review."
                     if any(STATE_REVIEW in features for features in rule_files.values())
                     else "No pack has a confirmed general state blocker in this census.")
    lines = [
        "", "## Native rules in module form 3", "",
        f"The expression syntax and migration are specified in the language decision. {design}",
        f"The rule census includes {len(rule_files)} distinct source files, with {len(legacy)} using Datalog or interim pipes and {len(native)} using native rules.",
        "A mixed file counts once in the total and in each spelling it uses.",
        f"Native reader, form and IR proof gate: **{status}** ({evidence}).",
        f"This gate covers initial integration. Whole-pack migration also requires {signatures} and {parity}.",
        "",
        "An explicit state predicate needs a review of its evidence. "
        f"Keep the legacy rule where a general scalar state lacks authenticated evidence. {states}",
        "The census cannot infer general state checks from a legacy file. Ordinary relation negation and explicit outcome values are separate.",
        state_summary,
        "",
        "| Pack or source directory | Direct legacy files | Direct native files | General state evidence |",
        "| --- | ---: | ---: | --- |",
    ]
    for folder, usage in sorted(packs.items()):
        direct = usage.files.keys() & rule_files.keys()
        inherited = {path for dependency in usage.imports for path in packs[dependency].files} & rule_files.keys()
        if not (direct or inherited):
            continue
        state_sources = [path for path in sorted(direct | inherited) if STATE_REVIEW in rule_files[path]]
        if state_sources:
            sources = ", ".join(
                f"[{path.name}](../../{path.relative_to(root).as_posix()})" for path in state_sources
            )
            state = f"Review explicit state predicates ({sources})"
        elif (direct | inherited) & legacy:
            state = "Unknown until legacy conversion"
        else:
            state = "No explicit state predicate found"
        lines.append(
            f"| {folder.relative_to(root).as_posix()} | {len(direct & legacy)} | {len(direct & native)} | {state} |"
        )
    return lines


def render(root=ROOT):
    root = root.resolve()
    packs = inventory(root)
    ready = supported(root)
    native_pending = ({"native-rule"} - ready) | {
        name for name, test in NATIVE_PACK_EVIDENCE.items() if not passing_test(root, test)
    }
    counts = Counter(feature for usage in packs.values() for features in usage.files.values()
                     for feature in features - {STATE_REVIEW, "native-rule"})
    lines = ["# Rezono language coverage", "",
             "Run `python compiler/tests/rezono/language_usage.py` from the repository root for the current inventory.",
             "Counts use each authored file once per feature. Higher counts give higher priority among available tasks.",
             "Support requires the applicable reader, form and lowering tests without expected-failure markers.",
             "Pack readiness includes transitive local imports.",
             "Mixed conversion uses legacy pipe blocks. Native conversion uses typed rules.",
             "Native conversion requires reader, form, IR, signature and publication evidence. Review explicit state predicates.",
             "", "| Feature | Files | Reader and lowering |", "| --- | ---: | --- |"]
    for name, count in sorted(counts.items(), key=lambda item: (-item[1], item[0])):
        evidence = EVIDENCE.get(name)
        status = "Pending"
        if evidence:
            links = ", ".join(f"[{'reader' if path.startswith('rezono/') else 'lowering'}](../../{path})"
                              for path, _ in evidence)
            status = ("Supported" if name in ready else "Pending") + f" ({links})"
        lines.append(f"| {name} | {count} | {status} |")
    lines.extend(["", "| Pack or source directory | Direct features | Imported features | Pending features | Mixed conversion | Native conversion |",
                  "| --- | --- | --- | --- | --- | --- |"])
    for folder, usage in sorted(packs.items()):
        direct = {feature for values in usage.files.values() for feature in values}
        imports = {feature for dependency in usage.imports for values in packs[dependency].files.values()
                   for feature in values}
        features = direct | imports
        pending = features - ready
        if usage.missing_import:
            pending.add("unresolved-pack-import")
        status = "Ready" if direct or imports else "No language sources"
        if pending:
            status = describe(pending)
        mixed, native = conversion_status(features, ready, native_pending, usage.missing_import,
                                          (folder / "pack.yaml").is_file())
        lines.append(f"| {folder.relative_to(root).as_posix()} | {describe(direct - {STATE_REVIEW})} | "
                     f"{describe(imports - {STATE_REVIEW})} | {status} | {mixed} | {native} |")
    lines.extend(render_native_rules(root, packs, ready))
    return "\n".join(lines)


if __name__ == "__main__":
    print(render())
