"""Link checked native rule trees against the schema of their pinned pack closure."""

from __future__ import annotations

from collections.abc import Iterator, Mapping
from dataclasses import dataclass, field, replace
import json
from pathlib import Path, PurePosixPath
import re

import yaml

from . import modules, pack, rezono_module, rezono_step, rules, rules_dl, spans, types
from .diagnostics import Diagnostic

Column = tuple[str, str, str]
ClauseKey = tuple[str, str, str]
ResolvedPath = tuple[str | None, str]
Place = dict[str, str]
SCALARS = {"Text": "string", "Int": "integer"}
# The value states in code order (publication section 2.1).
STATES = ("known", "not_applicable", "unknown", "invalid")


@dataclass(frozen=True)
class Signature:
    key: tuple[Column, ...]
    module: str
    owner: str
    source: str
    extend: bool = False
    invariant: bool = False
    # Linked evidence for a ground call: relation, owner, columns, world, the states it can take and the
    # places that explain each undecided state (decisions/language-expression-semantics.md section 2).
    predicate: dict | None = None
    semantics: tuple[dict | None, ...] = ()


@dataclass(frozen=True)
class LinkedClause:
    relation: str
    module: str
    calls: dict[str, str]
    paths: dict[str, ResolvedPath]
    memberships: dict[str, str] = field(default_factory=dict)
    # The hops of each path node, as (subject type, slot), from which its possible states follow.
    hops: dict[str, tuple[tuple[str, str], ...]] = field(default_factory=dict)
    # Path pointers whose final slot is multivalued and therefore yields a collection rather than a scalar.
    collections: frozenset[str] = frozenset()


@dataclass(frozen=True)
class Linked:
    signatures: dict[str, Signature]
    clauses: dict[ClauseKey, LinkedClause]
    intermediate_invariants: tuple[pack.IntermediateInvariant, ...] = ()
    steps: tuple[pack.CompiledStep, ...] = ()
    step_clauses: dict[ClauseKey, str] = field(default_factory=dict)


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
    format: str = rezono_module.NATIVE_FORMAT

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
    def __init__(self, definitions: list[modules.Module], names: modules.Names, root: str = ""):
        self.names = names
        self.root = root
        self.marks: dict[tuple[str, str], dict[tuple, tuple[int, int]]] = {}
        self.classes: dict[str, tuple[modules.Module, str]] = {}
        self.enums: dict[str, tuple[modules.Module, str]] = {}
        self.by_owner: dict[tuple[str, str], list[str]] = {}
        self.aliases: dict[tuple[str, str], list[modules.Module]] = {}
        self.scalar_storages: dict[str, str] = {}
        self.scalars: dict[str, tuple[modules.Module, str]] = {}
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
            found = sorted({
                *((self.classes if engine in self.classes else self.enums)[engine][0].id for engine in candidates),
                *(definition.id for definition in aliases),
            })
            raise Refusal(
                "R046",
                f"{spelling!r} is ambiguous (declared in {' and '.join(found)}); qualify it with an import alias",
                at,
            )
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
        resolved = f"{module.pack}.{name}"
        self.scalar_storages[resolved] = storage
        self.scalars[resolved] = (module, name)
        return resolved, storage

    def column_semantic(self, logical: str, physical: str, at: str) -> dict | None:
        """Project a linked rule column's logical type to its bundle SemanticType, or None for plain scalars."""
        if logical in SCALARS:
            return None
        if logical in self.classes:
            return types.ref(logical, physical).semantic
        if logical in self.enums:
            return types.enum(logical).semantic
        if logical in self.scalars:
            module, authored = self.scalars[logical]
            seen: set[str] = set()
            t = module.sv.get_type(authored)
            while t is not None and t.name not in seen:
                seen.add(t.name)
                if (curr := pack.ann(t, "currency")) is not None:
                    if not isinstance(curr, str) or not pack.CURRENCY.match(curr):
                        raise Refusal("R049", f"{authored}: currency {curr!r} is not an ISO 4217 code", at)
                    if physical != types.INTEGER:
                        raise Refusal("R049", f"{authored}: a currency goes on whole numbers (minor units)", at)
                    return types.money(curr, logical).semantic
                if any(tag in pack.tags(t) for tag in ("dimension", "unit")) and physical == types.INTEGER:
                    return types.quantity(t.name, physical, logical).semantic
                t = module.sv.get_type(t.typeof) if t.typeof else None
            return types.scalar(physical, logical).semantic
        raise Refusal("R049", f"Unsupported rule column type {logical!r}", at)

    def is_text(self, value: str) -> bool:
        return value == "Text" or self.scalar_storages.get(value) == "string"

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

    def _ancestors(self, subject: str) -> Iterator[tuple[str, modules.Module, str]]:
        """Yield `(engine_name, module, authored_name)` for `subject` and each ancestor in order."""
        current = subject
        seen: set[str] = set()
        while current in self.classes and current not in seen:
            seen.add(current)
            definition, authored = self.classes[current]
            yield current, definition, authored
            cls = definition.sv.get_class(authored)
            if cls is None or not cls.is_a:
                break
            parent_owner = definition.parent_targets.get(authored)
            parent = self.names.resolve(definition.id, cls.is_a, owner=parent_owner)
            if parent is None:
                break
            current = parent

    def assignable(self, actual: str, expected: str) -> bool:
        if actual == expected:
            return True
        if actual not in self.classes or expected not in self.classes:
            return False
        return any(engine == expected for engine, _, _ in self._ancestors(actual))

    def slot(self, subject: str, name: str, at: str) -> tuple[ResolvedPath, bool]:
        if subject not in self.classes:
            raise Refusal("R003", f"{subject} is a value and has no slot {name!r}", at)
        _, authored = self.classes[subject]
        for owner, owner_mod, ancestor in self._ancestors(subject):
            kind = owner_mod.sv.get_class(ancestor)
            if name in (kind.attributes or {}) or name in (kind.slots or []):
                break
        else:
            raise Refusal("R001", f"{authored} has no slot {name!r}", at)
        slot = owner_mod.sv.induced_slot(name, ancestor)
        if slot.identifier:
            scalar = "Int" if self.storage(subject, at) == "integer" else "Text"
            return (None, scalar), False
        rng = slot.range or owner_mod.sv.schema.default_range
        slot_owner = owner_mod.slot_targets.get((ancestor, name))
        target = self.names.resolve(owner_mod.id, rng, owner=slot_owner)
        if target is None:
            target_mod = self.names.modules[slot_owner] if slot_owner in self.names.modules else owner_mod
            target, _ = self.scalar_type(target_mod, rng, at)
        return (f"{owner}__{name}", target), bool(slot.multivalued)

    def slot_states(self, subject: str, name: str) -> tuple[tuple[str, ...], Place | None]:
        """The states one hop can give, and the slot that explains a state other than known.

        A missing required scalar is unknown and a missing optional one is not applicable. An identifier is
        always known, and a multivalued hop gives a collection whose fold decides its own state."""
        for _, owner_mod, ancestor in self._ancestors(subject):
            kind = owner_mod.sv.get_class(ancestor)
            if name in (kind.attributes or {}) or name in (kind.slots or []):
                slot = owner_mod.sv.induced_slot(name, ancestor)
                if slot.identifier or slot.multivalued:
                    return ("known",), None
                return (
                    ("known", "unknown" if slot.required else "not_applicable"),
                    self.slot_place(owner_mod, ancestor, name),
                )
        return ("known",), None

    def slot_place(self, module: modules.Module, kind: str, name: str) -> Place | None:
        key = module.pack, module.rel
        if key not in self.marks:
            try:
                self.marks[key] = (rezono_module.marks(module.file, module.form) if module.form is not None
                                   else spans.marks(module.file))
            except (OSError, UnicodeError, ValueError, yaml.YAMLError):
                self.marks[key] = {}
        found = self.marks[key]
        for path in (("classes", kind, "attributes", name), ("slots", name)):
            if path in found:
                line, column = found[path]
                return {"file": spans.where(module.pack, self.root, module.rel),
                        "at": "/" + "/".join(path), "line": str(line), "column": str(column)}
        return None


def source_for(owner: str, path: str, form: dict, root: str, allowed: list[str],
               errors: list[Diagnostic]) -> tuple[Source, list[dict]]:
    name = PurePosixPath(path)
    aliases: dict[str, str] = {}
    unqualified: list[str] = []
    body = (
        rezono_module.module_body(form, rezono_module.NATIVE_FORMAT)
        or rezono_module.module_body(form, rezono_module.SAFE_STEP_FORMAT)
        or rezono_module.module_body(form, rezono_module.REZONO_1_FORMAT)
    )
    form_format = form.get("format", rezono_module.NATIVE_FORMAT) if isinstance(form, dict) else rezono_module.NATIVE_FORMAT
    source = Source(owner, path, spans.where(owner, root, path), rules_dl.module_of(owner, root, name.stem),
                    rezono_module.lines(form) if body is not None else {}, aliases, (), form_format)
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
                  tuple(dict.fromkeys(unqualified)), form_format), body["decls"]


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
    if "columns" not in decl and decl.get("options"):
        raise Refusal("R048", "Rule options belong on the owning typed head", at)

    locals_ = columns(schema, source, decl.get("locals", []), f"{at}/locals")
    known = {name: value for name, value, _ in locals_}
    head = decl.get("args", [{"path": [name]} for name, _, _ in signature.key])
    if len(head) != len(signature.key):
        raise Refusal("R041", f"{relation!r} takes {len(signature.key)} columns, got {len(head)}", at)
    explicit = set(known)
    paths: dict[str, ResolvedPath] = {}
    hops: dict[str, tuple[tuple[str, str], ...]] = {}
    collections: set[str] = set()
    calls: dict[str, str] = {}
    memberships: dict[str, str] = {}
    arguments: list[tuple[dict, str, str, bool]] = []
    typed_calls: list[tuple[dict, str]] = []
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
            if name in rules.COMPARE_AS:
                if len(terms) != 1:
                    raise Refusal("R041", f"{name!r} takes 1 column, got {len(terms)}", pointer)
                typed_calls.append((terms[0], f"{pointer}/call/1/0"))
                continue
            target, expected = call_of(schema, source, name, signatures, pointer)
            if len(terms) != len(expected):
                raise Refusal("R041", f"{name!r} takes {len(expected)} columns, got {len(terms)}", pointer)
            calls[pointer] = target
            arguments.extend((arg, t, f"{pointer}/call/1/{i}", False)
                             for i, (arg, t) in enumerate(zip(terms, expected, strict=True)))
        if "in" not in node:
            continue
        subject, domain = node["in"]
        kind, slot = domain.get("dot", (domain, None))
        if "kind" not in kind:
            continue
        domain_at = f"{pointer}/in/1"
        target, _ = schema.type(source, kind["kind"], domain_at)
        if target not in schema.classes:
            raise Refusal("R003", f"{target!r} is not a kind for membership", domain_at)
        value = target
        if slot is not None:
            (table, value), _ = schema.slot(target, slot, domain_at)
            if table is not None:
                continue  # Only identifier projection is backed by the kind's membership relation.
        memberships[pointer] = target
        arguments.append((subject, value, f"{pointer}/in/0", False))

    def value_type(node: dict, pointer: str) -> str | None:
        if "neg" in node:
            return value_type(node["neg"], f"{pointer}/neg")
        if "call" in node and node["call"][0] in rules.COMPARE_AS and len(node["call"][1]) == 1:
            return value_type(node["call"][1][0], f"{pointer}/call/1/0")
        if "path" not in node:
            return literal_type(schema, source, node["lit"], pointer) if "lit" in node else None
        name, *steps = node["path"]
        value = known.get(name)
        if value is None or not steps:
            return value
        place = None
        visited = []
        for i, step in enumerate(steps):
            visited.append((value, step))
            (place, value), many = schema.slot(value, step, pointer)
            if many and i + 1 < len(steps):
                raise Refusal("R005", f"{step!r} gives a set where a single subject is required", pointer)
        paths[pointer] = (place, value)
        hops[pointer] = tuple(visited)
        if many:
            collections.add(pointer)
        return value

    for node, expected, pointer, _ in arguments:
        path = node.get("path", ())
        if len(path) == 1:
            name = path[0]
            actual = known.get(name)
            if actual is None or (name not in explicit and schema.assignable(expected, actual)):
                known[name] = expected
    for node, _ in typed_calls:
        path = node.get("path", ())
        if len(path) == 1 and path[0] not in known:
            known[path[0]] = "Text"

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
    for node, pointer in typed_calls:
        actual = value_type(node, pointer)
        if actual is not None and not schema.is_text(actual):
            raise Refusal("R003", f"Expected Text, found {actual}", pointer)

    for pointer, node in body:
        if "cmp" in node:
            _, left, right = node["cmp"]
            a, b = value_type(left, f"{pointer}/cmp/1"), value_type(right, f"{pointer}/cmp/2")
            if a is not None and b is not None and not (schema.assignable(a, b) or schema.assignable(b, a)):
                raise Refusal("R003", f"Cannot compare {a} with {b}", pointer)
        path = node.get("path", ())
        if len(path) > 1 and path[0] in known:
            value_type(node, pointer)
    return LinkedClause(relation, signature.module, calls, paths, memberships, hops, frozenset(collections))


def link(pack_dir: str | Path, forms: Mapping[tuple[str, str], dict]) -> Linked:
    """Link already-authored module/3 trees, keyed by pack and relative source path."""
    directory = Path(pack_dir)
    meta = pack.read_meta(directory)
    root = meta["name"]
    schema_errors: list[str] = []
    definitions, imported = modules.load(directory, meta, schema_errors)
    names = modules.Names(definitions, pack.snake, schema_errors, root=root)
    return link_modules(meta, definitions, imported, names, forms)


def read_head_options(source: Source, at: str, declaration: dict) -> tuple[bool, bool, tuple[str, str] | None]:
    """Validate and extract extend, invariant and intermediate coverage options from an owning typed head."""
    extend = False
    invariant = False
    intermediate_within: tuple[str, str] | None = None
    for index, option in enumerate(declaration.get("options") or []):
        opt_at = f"{at}/options/{index}"
        if not isinstance(option, dict):
            raise Refusal("R048", "Invalid rule option on rule head", opt_at)
        if "extend" in option:
            if set(option) != {"extend"} or option["extend"] is not True:
                raise Refusal("R048", "Invalid extend option on rule head", opt_at)
            if extend:
                raise Refusal("R048", "Repeated extend option on rule head", opt_at)
            extend = True
        elif "invariant" in option:
            if invariant:
                raise Refusal("R048", "Repeated invariant option on rule head", opt_at)
            invariant = True
            if set(option) == {"invariant"} and option["invariant"] is True:
                continue
            if set(option) == {"invariant", "within"} and option["invariant"] == "intermediate":
                if source.format != rezono_module.SAFE_STEP_FORMAT:
                    raise Refusal("R048", "Intermediate invariant requires rezono.module/4", opt_at)
                within = option["within"]
                within_at = f"{opt_at}/within"
                if (not isinstance(within, dict) or set(within) != {"relation"}
                        or not isinstance(within["relation"], str) or not within["relation"]):
                    raise Refusal("R048", "Intermediate invariant requires within.relation", within_at)
                intermediate_within = (within["relation"], within_at)
                continue
            raise Refusal("R048", "Invalid invariant option on rule head", opt_at)
    return extend, invariant, intermediate_within


def bind_intermediate_coverage(
    relation: str,
    violation: Signature,
    coverage_relation: str,
    coverage: Signature,
    at: str,
) -> tuple[tuple[str, str], ...]:
    """Bind each violation column to a coverage column of the same name and resolved schema type."""
    coverage_columns = {name: schema_type for name, schema_type, _ in coverage.key}
    binding: list[tuple[str, str]] = []
    for name, schema_type, _ in violation.key:
        if name not in coverage_columns:
            raise Refusal(
                "R003",
                f"Coverage relation {coverage_relation!r} for {relation!r} is missing key column {name!r}",
                at,
            )
        cov_type = coverage_columns[name]
        if cov_type != schema_type:
            raise Refusal(
                "R003",
                f"Coverage column {name!r} of {coverage_relation!r} has type {cov_type}, expected {schema_type}",
                at,
            )
        binding.append((name, name))
    return tuple(binding)


def resolve_intermediate_invariants(
    specs: list[tuple[str, Source, str, str]],
    signatures: Mapping[str, Signature],
) -> tuple[tuple[pack.IntermediateInvariant, ...], list[Diagnostic]]:
    """Resolve and validate intermediate invariant coverage relations and key bindings."""
    resolved: list[pack.IntermediateInvariant] = []
    found: list[Diagnostic] = []
    for relation, source, cov_ref, within_at in specs:
        try:
            coverage_relation, coverage_sig = signature_of(source, cov_ref, signatures, within_at)
            key_binding = bind_intermediate_coverage(
                relation, signatures[relation], coverage_relation, coverage_sig, within_at,
            )
            resolved.append(pack.IntermediateInvariant(relation, coverage_relation, key_binding))
        except Refusal as error:
            found.append(source.diagnose(error))
    return tuple(resolved), found


def _register_steps(
    root: str,
    schema: Schema,
    step_decls_raw: list[tuple[Source, str, dict]],
    signatures: dict[str, Signature],
    owners: dict[str, tuple[Source, str]],
    rules_list: list[tuple[Source, str, dict]],
) -> tuple[list[tuple[Source, str, dict, str, tuple[Column, ...]]], dict[ClauseKey, str], list[Diagnostic]]:
    """Register positive-match signatures for step declarations and report any header diagnostics."""
    step_specs: list[tuple[Source, str, dict, str, tuple[Column, ...]]] = []
    step_clauses: dict[ClauseKey, str] = {}
    seen_steps: dict[tuple[str, str, str], tuple[Source, str]] = {}
    found: list[Diagnostic] = []
    for source, at, decl in step_decls_raw:
        try:
            if source.format not in (rezono_module.SAFE_STEP_FORMAT, rezono_module.REZONO_1_FORMAT):
                raise Refusal("R048", "Step declaration requires rezono.module/4 or rezono.module/5", at)
            if (set(decl) - {"step", "columns", "when", "forbid", "effect", "confirm"}
                    or not {"step", "columns", "when", "effect", "confirm"} <= set(decl)):
                raise Refusal("R048", "Invalid step declaration shape", at)
            step_name = decl["step"]
            if not rules.NAME.match(step_name) or "__" in step_name:
                raise Refusal("R040", f"Step name {step_name!r} must be lower snake case without '__'", at)
            step_key = (source.owner, source.path, step_name)
            if step_key in seen_steps:
                other, pointer = seen_steps[step_key]
                found.append(other.diagnose(Refusal("R040", f"Duplicate step {step_name!r} in module", pointer)))
                raise Refusal("R040", f"Duplicate step {step_name!r} in module", at)
            seen_steps[step_key] = (source, at)
            key = columns(schema, source, decl["columns"], f"{at}/columns")
            semantics = tuple(schema.column_semantic(logical, physical, f"{at}/columns/{index}")
                              for index, (_, logical, physical) in enumerate(key))
            try:
                match_relation = rezono_step.match_relation_name(
                    source.owner, root, source.path, step_name, signatures,
                )
            except ValueError as error:
                raise Refusal("R040", str(error), at) from None
            owners[match_relation] = source, at
            signatures[match_relation] = Signature(
                key, source.module, source.owner, source.path, semantics=semantics,
            )
            step_specs.append((source, at, decl, match_relation, key))
            step_clauses[source.owner, source.path, at] = match_relation
            rules_list.append((source, at, {"rule": match_relation, "columns": decl["columns"], "when": decl["when"]}))
        except Refusal as error:
            found.append(source.diagnose(error))
    return step_specs, step_clauses, found


def link_modules(meta: dict, definitions: list[modules.Module], imported: dict[str, modules.Imported],
                 names: modules.Names, forms: Mapping[tuple[str, str], dict],
                 *, pack_dir: Path | None = None,
                 pack_kinds: Mapping[str, pack.Kind] | None = None) -> Linked:
    """Link native forms using the schema and import pins already read by pack compilation."""
    root = meta["name"]
    schema_errors = names.errors
    schema = Schema(definitions, names, root)
    errors: list[Diagnostic] = []
    rules_list: list[tuple[Source, str, dict]] = []
    step_decls_raw: list[tuple[Source, str, dict]] = []
    for (owner, path), form in sorted(forms.items()):
        dependencies = modules.direct(meta) if owner == root else imported[owner].imports if owner in imported else []
        source, declarations = source_for(owner, path, form, root, modules.dependency_order(imported, dependencies), errors)
        if owner != root and owner not in imported:
            errors.append(source.diagnose(Refusal("R046", f"{owner!r} is not a pinned pack", "/decls/0")))
            continue
        rules_list.extend((source, f"/decls/{i}", decl) for i, decl in enumerate(declarations) if "rule" in decl)
        step_decls_raw.extend((source, f"/decls/{i}", decl) for i, decl in enumerate(declarations) if "step" in decl)
    if schema_errors:
        errors.extend(Diagnostic("R046", message) for message in schema_errors)
    if errors:
        raise pack.CompileError("\n".join(map(str, errors)), errors)

    signatures: dict[str, Signature] = {}
    owners: dict[str, tuple[Source, str]] = {}
    intermediate_specs: list[tuple[str, Source, str, str]] = []
    for source, at, declaration in rules_list:
        if "columns" not in declaration:
            continue
        rule = declaration["rule"]
        try:
            if "args" in declaration:
                raise Refusal("R048", "A rule head cannot have both columns and positional arguments", at)
            if "." in rule:
                raise Refusal("R046", "Only the owning pack can declare a rule signature", at)
            if rule in owners:
                other, pointer = owners[rule]
                message = f"{rule!r} has two owning signatures"
                errors.append(other.diagnose(Refusal("R040", message, pointer)))
                raise Refusal("R040", message, at)
            key = columns(schema, source, declaration["columns"], f"{at}/columns")
            semantics = tuple(schema.column_semantic(logical, physical, f"{at}/columns/{index}")
                              for index, (_, logical, physical) in enumerate(key))
            extend, invariant, intermediate_within = read_head_options(source, at, declaration)
            owners[rule] = source, at
            signatures[rule] = Signature(key, source.module, source.owner, source.path, extend, invariant,
                                         semantics=semantics)
            if intermediate_within is not None:
                intermediate_specs.append((rule, source, *intermediate_within))
        except Refusal as error:
            errors.append(source.diagnose(error))

    step_specs, step_clauses, step_errors = _register_steps(
        root, schema, step_decls_raw, signatures, owners, rules_list,
    )
    errors.extend(step_errors)

    intermediate, intermediate_errors = resolve_intermediate_invariants(intermediate_specs, signatures)
    errors.extend(intermediate_errors)

    clauses: dict[ClauseKey, LinkedClause] = {}
    for source, at, decl in rules_list:
        try:
            if "when" in decl:
                clauses[source.owner, source.path, at] = read_clause(schema, source, at, decl, signatures)
            elif "columns" not in decl:
                raise Refusal("R040", "A positional rule head needs a guard", at)
        except Refusal as error:
            errors.append(source.diagnose(error))
    compiled_steps = rezono_step.lower_steps(
        meta, pack_dir, imported, schema, signatures, step_specs, pack_kinds, errors,
    )
    errors.extend(Diagnostic("R046", message) for message in schema_errors)
    defined = {clause.relation for clause in clauses.values()}
    if not errors:
        for relation, signature in signatures.items():
            if not signature.extend and relation not in defined:
                source, at = owners[relation]
                errors.append(source.diagnose(Refusal("R048", f"{relation!r} has no defining clause", at)))
    if errors:
        raise pack.CompileError("\n".join(map(str, errors)), errors)
    places = Places(definitions, forms)
    guards = {key: (source, decl["when"]) for source, at, decl in rules_list
              if (key := (source.owner, source.path, at)) in clauses}
    return Linked(
        predicates(schema, signatures, clauses, guards, places, defined),
        clauses,
        intermediate,
        compiled_steps,
        step_clauses,
    )


class Places:
    """The line and column of native rule nodes, from the authored text of each linked form."""

    def __init__(self, definitions: list[modules.Module], forms: Mapping[tuple[str, str], dict]):
        self.directories = {module.pack: module.pack_dir for module in definitions}
        self.forms = forms
        self.texts: dict[tuple[str, str], str | None] = {}

    def of(self, source: Source, at: str) -> Place:
        key = source.owner, source.path
        if key not in self.texts:
            directory = self.directories.get(source.owner)
            try:
                self.texts[key] = (directory / source.path).read_bytes().decode("utf-8") if directory else None
            except (OSError, UnicodeError):
                self.texts[key] = None
        text = self.texts[key]
        start = next((place.get("start") for place in self.forms[key]["spans"] if place.get("at") == at), None)
        line, column = source.lines.get(at), None
        # A form can describe a different text. Only map an offset that lies in this source.
        if text is not None and isinstance(start, str) and start.isdigit() and int(start) < len(text):
            offset = int(start)
            line, column = text.count("\n", 0, offset) + 1, offset - text.rfind("\n", 0, offset)
        place = {"file": source.file, "at": at}
        if line is not None:
            place["line"] = str(line)
            if column is not None:
                place["column"] = str(column)
        return place


Outcome = tuple[frozenset[str], tuple[Place, ...]]
DECIDED: Outcome = (frozenset({"known"}), ())


def merge(*outcomes: Outcome) -> Outcome:
    states = frozenset().union(*(states for states, _ in outcomes))
    related: dict[tuple, Place] = {}
    for _, found in outcomes:
        for place in found:
            related.setdefault(tuple(sorted(place.items())), place)
    return states, tuple(related.values())


def outcome(node: object, at: str, schema: Schema, source: Source, clause: LinkedClause,
            relations: Mapping[str, Outcome], places: Places) -> Outcome:
    """The states a guard can take by the truth tables, with the places that explain an undecided state."""
    if not isinstance(node, dict):
        return DECIDED

    def part(child: object, pointer: str) -> Outcome:
        return outcome(child, pointer, schema, source, clause, relations, places)

    for op, dominant in (("and", "false"), ("or", "true")):
        if op in node:
            terms = node[op]
            # A constant false conjunct, or true disjunct, decides the connective whatever the others give.
            if any(isinstance(term, dict) and term.get("lit") == dominant for term in terms):
                return DECIDED
            return merge(DECIDED, *(part(term, f"{at}/{op}/{i}") for i, term in enumerate(terms)))
    if "is" in node:
        return DECIDED  # A state test is a decided Boolean about its operand.
    if "path" in node:
        states, related = set(DECIDED[0]), []
        for subject, slot in clause.hops.get(at, ()):
            possible, place = schema.slot_states(subject, slot)
            states.update(possible)
            if place is not None and set(possible) != {"known"}:
                related.append(place)
        return frozenset(states), tuple(related)
    if "call" in node:
        _, terms = node["call"]
        found = [part(term, f"{at}/call/1/{i}") for i, term in enumerate(terms)]
        target = clause.calls.get(at)
        if target in relations:
            found.append(relations[target])
        return merge(DECIDED, *found)
    children = [part(child, f"{at}/{key}") for key, child in node.items() if isinstance(child, dict)]
    children += [part(item, f"{at}/{key}/{i}") for key, child in node.items() if isinstance(child, list)
                 for i, item in enumerate(child)]
    found = merge(DECIDED, *children)
    if "cmp" in node and found[0] != DECIDED[0]:
        # The comparison is where an undecided operand reaches the predicate.
        return found[0], (places.of(source, at), *found[1])
    return found


def predicates(schema: Schema, signatures: dict[str, Signature], clauses: dict[ClauseKey, LinkedClause],
               guards: Mapping[ClauseKey, tuple[Source, dict]], places: Places,
               defined: set[str]) -> dict[str, Signature]:
    """Attach to each signature the states its ground predicate can take: a least fixed point over every
    clause in the closure, through wrappers, positive recursion and authorized extensions."""
    relations: dict[str, Outcome] = {name: (frozenset(), ()) for name in signatures}
    changed = True
    while changed:
        changed = False
        for key, clause in sorted(clauses.items()):
            source, guard = guards[key]
            previous = relations[clause.relation]
            combined = merge(previous, outcome(guard, f"{key[2]}/when", schema, source, clause, relations, places))
            if combined != previous:
                relations[clause.relation] = combined
                changed = True
    linked = {}
    for name, signature in signatures.items():
        states, related = relations[name]
        states = states or DECIDED[0]
        linked[name] = replace(signature, predicate={
            "relation": name,
            "owner": signature.owner,
            "columns": [{"name": column, "logical": logical, "physical": physical}
                        for column, logical, physical in signature.key],
            # An extension point that no clause in the closure defines can still gain rows from elsewhere.
            "world": "open" if signature.extend and name not in defined else "closed",
            "states": [state for state in STATES if state in states],
            "related": [dict(place) for place in related] if states != DECIDED[0] else [],
        })
    return linked
