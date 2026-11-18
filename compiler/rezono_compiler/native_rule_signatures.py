"""Link checked native rule trees against the schema of their pinned pack closure."""

from __future__ import annotations

from collections.abc import Iterator, Mapping
from dataclasses import dataclass, field
import json
from pathlib import Path, PurePosixPath
import re

from . import modules, pack, rezono_module, rules_dl, spans, types
from .diagnostics import Diagnostic

Column = tuple[str, str, str]
ClauseKey = tuple[str, str, str]
ResolvedPath = tuple[str | None, str]
SCALARS = {"Text": "string", "Int": "integer"}


@dataclass(frozen=True)
class Signature:
    key: tuple[Column, ...]
    module: str
    owner: str
    source: str
    extend: bool = False


@dataclass(frozen=True)
class LinkedClause:
    relation: str
    module: str
    calls: dict[str, str]
    paths: dict[str, ResolvedPath]
    memberships: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class Linked:
    signatures: dict[str, Signature]
    clauses: dict[ClauseKey, LinkedClause]


class Refusal(Exception):
    def __init__(self, code: str, message: str, at: str):
        super().__init__(message)
        self.code, self.at = code, at


@dataclass(frozen=True)
class Source:
    owner: str
    path: str
    file: str
    module: str
    lines: dict[str, int]
    aliases: dict[str, str]
    unqualified: tuple[str, ...]

    def diagnose(self, error: Refusal) -> Diagnostic:
        at = error.at
        while at and at not in self.lines:
            at = at.rpartition("/")[0]
        line = self.lines.get(at)
        return Diagnostic(error.code, str(error), f"{self.file}#{error.at}",
                          (self.file, line, 1) if line is not None else None)

    def scope(self, name: str, at: str) -> tuple[str, tuple[str, ...]]:
        alias, dot, local = name.rpartition(".")
        if not dot:
            return name, (self.owner, *self.unqualified)
        if alias not in self.aliases:
            raise Refusal("R046", f"{alias!r} is not an imported name in {self.file}", at)
        return local, (self.aliases[alias],)


class Schema:
    def __init__(self, definitions: list[modules.Module], names: modules.Names):
        self.names = names
        self.classes: dict[str, tuple[modules.Module, str]] = {}
        self.enums: dict[str, tuple[modules.Module, str]] = {}
        self.by_owner: dict[tuple[str, str], list[str]] = {}
        self.aliases: dict[tuple[str, str], list[modules.Module]] = {}
        for definition in definitions:
            for authored, category in names.declared[definition.id].items():
                engine = names.name(definition.id, authored)
                language = self.classes if category == "class" else self.enums
                language[engine] = (definition, authored)
                self.by_owner.setdefault((definition.pack, authored), []).append(engine)
            for authored in definition.sv.all_types(imports=False):
                self.aliases.setdefault((definition.pack, authored), []).append(definition)

    def type(self, source: Source, spelling: str, at: str) -> tuple[str, str]:
        if spelling in SCALARS:
            return spelling, SCALARS[spelling]
        if spelling in {"Bool", "Date"}:
            raise Refusal("R049", f"{spelling} has no rule column representation", at)
        authored, owners = source.scope(spelling, at)
        candidates = [engine for owner in owners for engine in self.by_owner.get((owner, authored), ())]
        aliases = [definition for owner in owners for definition in self.aliases.get((owner, authored), ())]
        if len(candidates) + len(aliases) > 1:
            raise Refusal("R046", f"{spelling!r} is ambiguous; qualify it with an import alias", at)
        if candidates:
            name = candidates[0]
            definition, _ = (self.classes if name in self.classes else self.enums)[name]
            if definition.pack != source.owner and definition.interface is not None and authored not in definition.interface:
                raise Refusal("R046", f"{spelling!r} is outside its module's public interface", at)
            return name, self.storage(name, at)
        if aliases:
            return self.scalar_type(aliases[0], authored, at)
        raise Refusal("R001", f"Unknown schema type {spelling!r}", at)

    def scalar_type(self, definition: modules.Module, name: str, at: str) -> tuple[str, str]:
        errors: list[str] = []
        sql = pack.sql_type(definition.sv, name, name, errors)
        storage = types.rule_type(sql)
        if errors or storage is None:
            raise Refusal("R049", f"{name} has no rule column representation", at)
        if name in {"string", "integer"}:
            return ("Text" if storage == "string" else "Int"), storage
        owner = next((module for module in self.names.closures[definition.id]
                      if name in self.names.modules[module].sv.all_types(imports=False)), definition.id)
        module = self.names.modules[owner]
        return f"{module.pack}.{name}", storage

    def storage(self, name: str, at: str) -> str:
        if name in self.enums:
            return "string"
        definition, authored = self.classes[name]
        view = definition.sv
        identifiers = [slot for slot in view.class_induced_slots(authored) if slot.identifier]
        if len(identifiers) != 1:
            raise Refusal("R049", f"{authored} needs exactly one identifier to be used in a rule", at)
        identifier = identifiers[0]
        errors: list[str] = []
        sql = pack.identifier_type(view, identifier, identifier.range or view.schema.default_range,
                                   f"{authored}.{identifier.name}", errors)
        storage = types.rule_type(sql)
        if errors or storage is None:
            raise Refusal("R049", f"{authored} has no supported identifier: {'; '.join(errors)}", at)
        return storage

    def assignable(self, actual: str, expected: str) -> bool:
        if actual == expected:
            return True
        if actual not in self.classes or expected not in self.classes:
            return False
        definition, authored = self.classes[actual]
        return any(self.names.resolve(definition.id, ancestor) == expected
                   for ancestor in definition.sv.class_ancestors(authored, mixins=False))

    def slot(self, subject: str, name: str, at: str) -> tuple[ResolvedPath, bool]:
        if subject not in self.classes:
            raise Refusal("R003", f"{subject} is a value and has no slot {name!r}", at)
        definition, authored = self.classes[subject]
        view = definition.sv
        for ancestor in view.class_ancestors(authored, mixins=False):
            kind = view.get_class(ancestor)
            if name in (kind.attributes or {}) or name in (kind.slots or []):
                break
        else:
            raise Refusal("R001", f"{authored} has no slot {name!r}", at)
        owner = self.names.resolve(definition.id, ancestor)
        slot = view.induced_slot(name, ancestor)
        if slot.identifier:
            scalar = "Int" if self.storage(subject, at) == "integer" else "Text"
            return (None, scalar), False
        rng = slot.range or view.schema.default_range
        target = self.names.resolve(definition.id, rng)
        if target is None:
            target, _ = self.scalar_type(definition, rng, at)
        return (f"{owner}__{name}", target), bool(slot.multivalued)


def source_for(owner: str, path: str, form: dict, root: str, allowed: list[str],
               errors: list[Diagnostic]) -> tuple[Source, list[dict]]:
    name = PurePosixPath(path)
    aliases: dict[str, str] = {}
    unqualified: list[str] = []
    body = rezono_module.module_body(form, rezono_module.NATIVE_FORMAT)
    source = Source(owner, path, spans.where(owner, root, path), rules_dl.module_of(owner, root, name.stem),
                    rezono_module.lines(form) if body is not None else {}, aliases, ())
    if (body is None or body["pack"] != owner or name.is_absolute() or name.suffix != ".rezono"
            or ".." in name.parts or "\\" in path or name.as_posix() != path):
        errors.append(source.diagnose(Refusal("R046", "The native form does not identify this pack and source", "")))
        return source, []
    for index, use in enumerate(body["use"]):
        target, alias = use["use"], use.get("as", use["use"])
        at = f"/use/{index}"
        if target not in allowed:
            errors.append(source.diagnose(Refusal("R046", f"{target!r} is not in the verified import closure", at)))
        elif alias in aliases:
            errors.append(source.diagnose(Refusal("R046", f"Duplicate import alias {alias!r}", at)))
        else:
            aliases[alias] = target
            if "as" not in use:
                unqualified.append(target)
    return Source(owner, path, source.file, source.module, source.lines, aliases,
                  tuple(dict.fromkeys(unqualified))), body["decls"]


def columns(schema: Schema, source: Source, given: list[dict], at: str) -> tuple[Column, ...]:
    found: dict[str, tuple[str, str]] = {}
    for index, column in enumerate(given):
        pointer = f"{at}/{index}"
        name = column["name"]
        if name in found:
            raise Refusal("R040", f"Duplicate column or local {name!r}", pointer)
        found[name] = schema.type(source, column["type"], pointer)
    return tuple((name, *value) for name, value in found.items())


def signature_of(source: Source, rule: str, signatures: dict[str, Signature], at: str) -> tuple[str, Signature]:
    relation, owners = source.scope(rule, at)
    signature = signatures.get(relation)
    if signature is None:
        raise Refusal("R040", f"{rule!r} has no owning signature", at)
    if signature.owner not in owners:
        raise Refusal("R046", f"{rule!r} is not visible in {source.file}", at)
    return relation, signature


def call_of(schema: Schema, source: Source, name: str, signatures: dict[str, Signature], at: str) -> tuple[str, tuple[str, ...]]:
    subject, _, slot = name.rpartition(".")
    if subject.rpartition(".")[2][:1].isupper():
        kind, _ = schema.type(source, subject, at)
        (table, target), _ = schema.slot(kind, slot, at)
        return (table, (kind, target)) if table else (kind, (target,))
    relation, signature = signature_of(source, name, signatures, at)
    return relation, tuple(value for _, value, _ in signature.key)


def expressions(value: object, at: str) -> Iterator[tuple[str, dict]]:
    if isinstance(value, dict):
        yield at, value
        for name, child in value.items():
            yield from expressions(child, f"{at}/{name}")
    elif isinstance(value, list):
        for index, child in enumerate(value):
            yield from expressions(child, f"{at}/{index}")


def literal_type(schema: Schema, source: Source, literal: str, at: str) -> str | None:
    if re.fullmatch(r"-?[0-9]+", literal):
        return "Int"
    if literal in {"true", "false"}:
        return "Bool"
    if re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}", literal):
        return "Date"
    if literal.startswith('"'):
        return "Text"
    if match := re.fullmatch(r"([A-Za-z0-9_.]+):`([^`]+)`", literal):
        name, storage = schema.type(source, match[1], at)
        if name not in schema.classes or (storage == "integer" and not re.fullmatch(r"-?[0-9]+", match[2])):
            raise Refusal("R012", f"Invalid identifier of type {match[1]}", at)
        return name
    if match := re.fullmatch(r'([A-Za-z0-9_.]+)(".*")', literal):
        name, _ = schema.type(source, match[1], at)
        if name in schema.enums:
            definition, authored = schema.enums[name]
            try:
                member = json.loads(match[2])
            except ValueError:
                raise Refusal("R012", f"Invalid literal of type {match[1]}", at) from None
            if member not in (definition.sv.get_enum(authored).permissible_values or {}):
                raise Refusal("R012", f"{member!r} is not a member of {match[1]}", at)
            return name
    return None


def read_clause(schema: Schema, source: Source, at: str, decl: dict, signatures: dict[str, Signature]) -> LinkedClause:
    relation, signature = signature_of(source, decl["rule"], signatures, at)
    if "." in decl["rule"]:
        if signature.owner == source.owner or not signature.extend:
            raise Refusal("R046", f"{decl['rule']!r} is not an extendable imported relation", at)
    elif signature.source != source.path or signature.owner != source.owner:
        raise Refusal("R046", f"A clause for {relation!r} must be in its owning module", at)
    if "args" in decl and decl.get("options"):
        raise Refusal("R048", "Rule options belong on the owning typed head", at)

    locals_ = columns(schema, source, decl.get("locals", []), f"{at}/locals")
    known = {name: value for name, value, _ in locals_}
    head = decl.get("args", [{"path": [name]} for name, _, _ in signature.key])
    if len(head) != len(signature.key):
        raise Refusal("R041", f"{relation!r} takes {len(signature.key)} columns, got {len(head)}", at)
    explicit = set(known)
    paths: dict[str, ResolvedPath] = {}
    calls: dict[str, str] = {}
    memberships: dict[str, str] = {}
    arguments: list[tuple[dict, str, str, bool]] = []
    for index, (arg, (_, expected, _)) in enumerate(zip(head, signature.key, strict=True)):
        if "wildcard" in arg:
            raise Refusal("R042", "A rule head needs a value in each column", f"{at}/args/{index}")
        arguments.append((arg, expected, f"{at}/args/{index}", True))

    body = list(expressions(decl["when"], f"{at}/when"))
    for pointer, node in body:
        if "call" in node:
            name, terms = node["call"]
            if name == "quotient":  # Its arithmetic and safety checks belong to the body checker.
                continue
            target, expected = call_of(schema, source, name, signatures, pointer)
            if len(terms) != len(expected):
                raise Refusal("R041", f"{name!r} takes {len(expected)} columns, got {len(terms)}", pointer)
            calls[pointer] = target
            arguments.extend((arg, t, f"{pointer}/call/1/{i}", False)
                             for i, (arg, t) in enumerate(zip(terms, expected, strict=True)))
        if "in" in node and "kind" in node["in"][1]:
            target, _ = schema.type(source, node["in"][1]["kind"], f"{pointer}/in/1")
            if target not in schema.classes:
                raise Refusal("R003", f"{target!r} is not a kind for membership", f"{pointer}/in/1")
            memberships[pointer] = target
            arguments.append((node["in"][0], target, f"{pointer}/in/0", False))

    def value_type(node: dict, pointer: str) -> str | None:
        if "neg" in node:
            return value_type(node["neg"], f"{pointer}/neg")
        if "path" not in node:
            return literal_type(schema, source, node["lit"], pointer) if "lit" in node else None
        name, *steps = node["path"]
        value = known.get(name)
        if value is None or not steps:
            return value
        place = None
        for i, step in enumerate(steps):
            (place, value), many = schema.slot(value, step, pointer)
            if many and i + 1 < len(steps):
                raise Refusal("R005", f"{step!r} gives a set where a single subject is required", pointer)
        paths[pointer] = (place, value)
        return value

    for node, expected, pointer, _ in arguments:
        path = node.get("path", ())
        if len(path) == 1:
            name = path[0]
            actual = known.get(name)
            if actual is None or (name not in explicit and schema.assignable(expected, actual)):
                known[name] = expected

    # Equality carries type information, without making either operand a positive fact binding.
    equalities = [(pointer, *node["cmp"][1:]) for pointer, node in body if node.get("cmp", [None])[0] == "="]
    while True:
        size = len(known)
        for pointer, left, right in equalities:
            for candidate, expression, side in ((left, right, 2), (right, left, 1)):
                path = candidate.get("path", ())
                if len(path) == 1 and path[0] not in known:
                    value = value_type(expression, f"{pointer}/cmp/{side}")
                    if value is not None:
                        known[path[0]] = value
        if len(known) == size:
            break
    for node, expected, pointer, is_head in arguments:
        actual = value_type(node, pointer)
        if actual is not None and not schema.assignable(actual, expected):
            raise Refusal("R003", f"Expected {expected}, found {actual}", pointer)
        if is_head and "lit" in node and actual is None:
            raise Refusal("R049", "The rule head literal has no checked column representation", pointer)

    for pointer, node in body:
        if "cmp" in node:
            _, left, right = node["cmp"]
            a, b = value_type(left, f"{pointer}/cmp/1"), value_type(right, f"{pointer}/cmp/2")
            if a is not None and b is not None and not (schema.assignable(a, b) or schema.assignable(b, a)):
                raise Refusal("R003", f"Cannot compare {a} with {b}", pointer)
        path = node.get("path", ())
        if len(path) > 1 and path[0] in known:
            value_type(node, pointer)
    return LinkedClause(relation, signature.module, calls, paths, memberships)


def link(pack_dir: str | Path, forms: Mapping[tuple[str, str], dict]) -> Linked:
    """Link already-authored module/3 trees, keyed by pack and relative source path."""
    directory = Path(pack_dir)
    meta = pack.read_meta(directory)
    root = meta["name"]
    schema_errors: list[str] = []
    definitions, imported = modules.load(directory, meta, schema_errors)
    names = modules.Names(definitions, pack.snake, schema_errors, root=root)
    return link_modules(meta, definitions, imported, names, forms)


def link_modules(meta: dict, definitions: list[modules.Module], imported: dict[str, modules.Imported],
                 names: modules.Names, forms: Mapping[tuple[str, str], dict]) -> Linked:
    """Link native forms using the schema and import pins already read by pack compilation."""
    root = meta["name"]
    schema_errors = names.errors
    schema = Schema(definitions, names)
    errors: list[Diagnostic] = []
    rules: list[tuple[Source, str, dict]] = []
    for (owner, path), form in sorted(forms.items()):
        dependencies = modules.direct(meta) if owner == root else imported[owner].imports if owner in imported else []
        source, declarations = source_for(owner, path, form, root, modules.dependency_order(imported, dependencies), errors)
        if owner != root and owner not in imported:
            errors.append(source.diagnose(Refusal("R046", f"{owner!r} is not a pinned pack", "/decls/0")))
            continue
        rules.extend((source, f"/decls/{i}", decl) for i, decl in enumerate(declarations) if "rule" in decl)
    if schema_errors:
        errors.extend(Diagnostic("R046", message) for message in schema_errors)
    if errors:
        raise pack.CompileError("\n".join(map(str, errors)), errors)

    signatures: dict[str, Signature] = {}
    owners: dict[str, tuple[Source, str]] = {}
    for source, at, declaration in rules:
        if "columns" not in declaration:
            continue
        rule = declaration["rule"]
        try:
            if "." in rule:
                raise Refusal("R046", "Only the owning pack can declare a rule signature", at)
            if rule in owners:
                other, pointer = owners[rule]
                message = f"{rule!r} has two owning signatures"
                errors.append(other.diagnose(Refusal("R040", message, pointer)))
                raise Refusal("R040", message, at)
            key = columns(schema, source, declaration["columns"], f"{at}/columns")
            extend = any(option.get("extend") is True for option in declaration.get("options", []))
            owners[rule] = source, at
            signatures[rule] = Signature(key, source.module, source.owner, source.path, extend)
        except Refusal as error:
            errors.append(source.diagnose(error))

    clauses: dict[ClauseKey, LinkedClause] = {}
    for source, at, decl in rules:
        try:
            if "when" in decl:
                clauses[source.owner, source.path, at] = read_clause(schema, source, at, decl, signatures)
            elif "columns" not in decl:
                raise Refusal("R040", "A positional rule head needs a guard", at)
        except Refusal as error:
            errors.append(source.diagnose(error))
    errors.extend(Diagnostic("R046", message) for message in schema_errors)
    defined = {clause.relation for clause in clauses.values()}
    if not errors:
        for relation, signature in signatures.items():
            if not signature.extend and relation not in defined:
                source, at = owners[relation]
                errors.append(source.diagnose(Refusal("R048", f"{relation!r} has no defining clause", at)))
    if errors:
        raise pack.CompileError("\n".join(map(str, errors)), errors)
    return Linked(signatures, clauses)
