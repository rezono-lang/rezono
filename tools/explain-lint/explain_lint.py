"""Check for unfolded explanation helpers using the published bundle and rule IR."""

import json
import re
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import NamedTuple

import yaml


FOLD = re.compile(r"\s*//\s*@explain\s+fold\s*")
DECLARATION = re.compile(r"\s*\.decl\s+([A-Za-z_][A-Za-z_0-9]*)\s*\(")


class Finding(NamedTuple):
    cls: str
    what: str


class Report(NamedTuple):
    findings: tuple[Finding, ...]


def _folded_lines(lines: list[str]) -> set[str]:
    marks: set[str] = set()
    for previous, current in zip(lines, lines[1:]):
        if FOLD.fullmatch(previous) and (declaration := DECLARATION.match(current)):
            marks.add(declaration[1])
    return marks


def _annotation_value(annotations: object, key: str) -> object:
    if not isinstance(annotations, dict):
        return None
    value = annotations.get(key)
    if isinstance(value, dict):
        return value.get("value")
    return value


def _rezono_forms(pack: Path) -> list[dict]:
    """Read declared native Rezono module forms, using rezono_module when available."""
    meta_path = pack / "pack.yaml"
    meta = yaml.safe_load(meta_path.read_text(encoding="utf-8")) if meta_path.is_file() else None
    if isinstance(meta, dict) and meta.get("rezono"):
        try:
            from rezono_compiler import rezono_module
        except ImportError:
            rezono_module = None
        if rezono_module is not None:
            forms: list[dict] = []
            for entry in rezono_module.declared(meta, pack, [], reject_undeclared=False):
                form = rezono_module.effective_form(pack, entry, [])
                if form is None:
                    form = rezono_module.read_form(pack, entry, [])
                if form is not None:
                    forms.append(form)
            return forms
        forms = []
        for entry in meta.get("rezono") or ():
            if not isinstance(entry, dict) or not isinstance(entry.get("form"), str):
                continue
            form_path = pack / entry["form"]
            if form_path.is_file():
                doc = json.loads(form_path.read_text(encoding="utf-8"))
                if isinstance(doc, dict) and isinstance(doc.get("module"), dict):
                    forms.append(doc)
        return forms
    rezono_dir = pack / "rezono"
    if not rezono_dir.is_dir():
        return []
    forms = []
    for path in sorted(rezono_dir.rglob("*.json")):
        doc = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(doc, dict) and isinstance(doc.get("module"), dict):
            forms.append(doc)
    return forms


def _snake(name: str) -> str:
    return re.sub(r"(?<=[a-z0-9])(?=[A-Z])", "_", name).lower()


def _has_fold_mark(item: dict) -> bool:
    return (
        _annotation_value(item.get("annotations"), "explain") == "fold"
        or any(
            isinstance(opt, dict) and opt.get("explain") == "fold"
            for opt in (item.get("options") or ())
        )
    )


def _fold_marks_from_form(form: dict) -> set[str]:
    marks: set[str] = set()
    module = form.get("module")
    if not isinstance(module, dict):
        return marks
    for decl in module.get("decls") or ():
        if not isinstance(decl, dict):
            continue
        if isinstance(decl.get("kind"), str) and _annotation_value(decl.get("annotations"), "explain") == "fold":
            marks.add(decl["kind"])
        if "rules" in decl and isinstance(decl.get("lines"), list):
            marks.update(_folded_lines([line for line in decl["lines"] if isinstance(line, str)]))
        for key in ("rule", "derived"):
            name = decl.get(key)
            if isinstance(name, str) and _has_fold_mark(decl):
                marks.add(name)
        if ("kind" in decl or "extend" in decl) and isinstance(decl.get("derived"), list):
            owner = decl.get("kind") if isinstance(decl.get("kind"), str) else decl.get("extend")
            for item in decl["derived"]:
                if isinstance(item, dict) and isinstance(item.get("derived"), str) and _has_fold_mark(item):
                    name = item["derived"]
                    marks.add(name)
                    if isinstance(owner, str) and isinstance(item.get("table"), dict):
                        marks.add(f"{_snake(owner)}_{name}")
    return marks


def _decl_has_rules(decl: object) -> bool:
    if not isinstance(decl, dict):
        return False
    if any(key in decl for key in ("rules", "rule", "step")):
        return True
    if isinstance(decl.get("derived"), str):
        return any(key in decl for key in ("params", "options", "over"))
    if "kind" in decl or "extend" in decl:
        derived = decl.get("derived")
        return isinstance(derived, list) and any(isinstance(item, dict) for item in derived)
    return False


def folded(pack: Path) -> set[str]:
    """Read the class names and relation IDs marked for folding in the pack sources."""
    marks: set[str] = set()
    for path in sorted((pack / "schema").rglob("*.yaml")):
        document = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        for name, definition in (document.get("classes") or {}).items():
            if _annotation_value((definition or {}).get("annotations"), "explain") == "fold":
                marks.add(name)

    for path in sorted((pack / "rules").rglob("*.dl")):
        marks.update(_folded_lines(path.read_text(encoding="utf-8").splitlines()))

    for form in _rezono_forms(pack):
        marks.update(_fold_marks_from_form(form))
    return marks


def _read_products(directory: Path, requires_rules: bool) -> tuple[dict, dict] | None:
    bundle = directory / "bundle" / "schema-bundle.json"
    rules = directory / "ir" / "rules.json"
    if not bundle.is_file() or (requires_rules and not rules.is_file()):
        return None
    return (json.loads(bundle.read_text(encoding="utf-8")),
            json.loads(rules.read_text(encoding="utf-8")) if rules.is_file() else {})


def _products(pack: Path) -> tuple[dict, dict]:
    requires_rules = any((pack / "rules").rglob("*.dl")) or any(
        _decl_has_rules(decl)
        for form in _rezono_forms(pack)
        for decl in (form.get("module") or {}).get("decls") or ()
    )
    committed = _read_products(pack / "expected" / "compiled", requires_rules)
    if committed is not None:
        return committed
    with tempfile.TemporaryDirectory() as output:
        subprocess.run([sys.executable, "-m", "rezono_compiler", "compile", str(pack), output],
                       check=True)
        fresh = _read_products(Path(output), requires_rules)
    if fresh is None:
        raise ValueError("Compile output is missing its schema bundle or rule IR")
    return fresh


def _mentions(value, relation: str) -> bool:
    if isinstance(value, dict):
        return relation in value or any(_mentions(item, relation) for item in value.values())
    if isinstance(value, list):
        return any(_mentions(item, relation) for item in value)
    return value == relation


def _computed_positions(rules: list[dict]) -> set[tuple[str, int]]:
    """Find positions that every producing clause fills with a computed value."""
    producers = {}
    for rule in rules:
        producers.setdefault(rule["head"]["relation"], []).append(rule)
    computed = set()
    while True:
        new = set()
        for relation, clauses in producers.items():
            positions = []
            for clause in clauses:
                values = _computed_terms(clause, computed)
                positions.append({index for index, term in enumerate(clause["head"]["terms"])
                                  if term in values})
            new.update((relation, index) for index in set.intersection(*positions))
        if new == computed:
            return computed
        computed = new


def _computed_terms(rule: dict, positions: set[tuple[str, int]]) -> set[str]:
    return ({item["var"] for item in rule.get("assignments", [])}
            | {item["as"] for item in rule.get("aggregates", [])}
            | {term for atom in rule["body"] for index, term in enumerate(atom["terms"])
               if (atom["relation"], index) in positions})


def _view_alias(rule: dict, kind_tables: dict[str, str]) -> str | None:
    if ((rule.get("origin") or {}).get("file") != "views.yaml"
            or len(rule["body"]) != 1
            or any(rule.get(field) for field in ("assignments", "conditions", "aggregates"))):
        return None
    atom = rule["body"][0]
    table = atom["relation"]
    head = rule["head"]
    name = f"{rule['module'].removeprefix('view_')}_{table.replace('__', '_')}"
    if (table in kind_tables and atom.get("polarity", "positive") == "positive"
            and head["terms"] == atom["terms"] and head["relation"] == name):
        return kind_tables[table]
    return None


def lint(pack: Path, root: Path, imported: set[str] | None = None) -> Report:
    """Report class B findings from rule structure and independently read source marks."""
    bundle, ir = _products(pack)
    kinds = {kind["id"]: kind for kind in bundle.get("kinds", [])}
    tables = {kind["table"]: name for name, kind in kinds.items()}
    slots = {slot["table"]: slot for field in ("arrows", "attributes")
             for slot in bundle.get(field, [])}
    rules = ir.get("rules", [])
    clauses = [rule for rule in rules if rule["head"]["relation"] != "may_read"]
    read = {atom["relation"] for rule in clauses for atom in rule["body"]}
    shown = [bundle.get(field) for field in ("channels", "questions", "checks")]
    helpers = {rel["name"] for rel in ir.get("relations", [])
               if rel["role"] == "derived" and not rel.get("invariant")
               and rel["name"] in read and not _mentions(shown, rel["name"])}
    aliases = {index: kind for index, rule in enumerate(clauses)
               if (kind := _view_alias(rule, tables)) is not None}
    kind_tables = tables | {clauses[index]["head"]["relation"]: kind for index, kind in aliases.items()}
    computed = _computed_positions(rules)
    joined = set()
    reaches = set()
    for index, rule in enumerate(clauses):
        if index in aliases:
            continue
        bindings = {}
        for atom in rule["body"]:
            relation = atom["relation"]
            terms = atom["terms"]
            if relation in kind_tables:
                bindings.setdefault(terms[0], set()).add(kind_tables[relation])
            elif relation in slots:
                slot = slots[relation]
                bindings.setdefault(terms[0], set()).add(slot["kind"])
                if "target" in slot:
                    bindings.setdefault(terms[1], set()).add(slot["target"])
        joined.update(kind for names in bindings.values() for kind in names)
        if rule["head"]["relation"] not in helpers:
            keys = set(rule["head"]["terms"]) - _computed_terms(rule, computed)
            reaches.update(kind for term in keys if term.startswith("?")
                           for kind in bindings.get(term, ()))

    marks = folded(pack)
    findings = [Finding("B", f"helper relation {name} is not folded (explain: fold)")
                for name in sorted(helpers - marks)]
    findings.extend(
        Finding("B", f"kind {name} is only reached through joins and is not folded (explain: fold)")
        for name in sorted(joined - reaches)
        if name in kinds and not kinds[name].get("name_attribute") and not kinds[name].get("name_arrows")
        and kinds[name]["class"] not in marks
    )
    return Report(tuple(findings))
