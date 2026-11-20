"""Calculation rules (contracts/calc.yaml): read a CalcProgram into a checked IR.

Templates are filled in, every expression gets a type (number or boolean), every leaf is bound to
where the engine reads it, overrides and rule references are checked, and rule versions are put in
dependency order. The SQL translator (calc_sql) reads only this IR. Error messages start with a
stable code (`calc.<code>`), so a test or the viewer can tell them apart.

Units (P10.3): a constant may carry a unit the pack declares, a rule may state one as its `unit`, and an
attribute has the unit of its type. Every operator checks dimensions (`check_units`); what the compiler does not
know the unit of yet (a parameter, an input concept, a derived relation's column, a rule whose `unit` is no
declared unit) is not checked.
"""

from __future__ import annotations

import datetime
import re
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import cast


from . import rules_dl, spans, strict_yaml, types
from .names import ISO_DATE
from .pack import CompileError, Pack, Slot, located, renamed

NUMBER, BOOLEAN = types.NUMBER, types.BOOLEAN
BOUND = 2**63 - 1  # every numerator and denominator fits a signed BIGINT, symmetric around zero
DECIMAL = re.compile(r"^(0|-?[1-9][0-9]*)$")
# Arity per operator: (minimum, maximum); None is unbounded.
ARITY = {
    "add": (2, None), "sub": (2, 2), "ratio": (3, 3), "min": (2, None), "max": (2, None),
    "floor": (1, 1), "ceil": (1, 1), "round": (1, 1), "pow": (2, 2), "if": (3, 3),
    "and": (2, None), "or": (2, None), "eq": (2, 2), "lt": (2, 2), "lte": (2, 2), "gte": (2, 2),
}
ARITHMETIC = {"add", "sub", "ratio", "min", "max", "floor", "ceil", "round", "pow"}
ORDERING = {"lt", "lte", "gte"}
LEAVES = ("rule", "fact", "parameter", "integer", "boolean", "arg")
PREFIX = "calc"


@dataclass(frozen=True)
class Node:
    """An expression: an operator with arguments, or a leaf.

    Leaves: `integer` (value int, and the unit it is written with, if any), `boolean` (value bool), `fact` and
    `parameter` (value: id), `rule` (value: (rule, version or None)). `arg` only occurs inside a template."""
    op: str
    args: tuple = ()
    value: object = None
    unit: str | None = None  # an integer constant's unit, a unit the pack declares (P10.3); never converted


@dataclass
class Definition:
    id: str  # <rule>@<version>#<name>
    name: str
    when: Node
    value: Node
    before: list[str] = field(default_factory=list)  # ids of the definitions this one goes before
    reasons: list[str] = field(default_factory=list)


@dataclass
class Version:
    id: str  # <rule>@<version>
    rule: str
    version: str
    output: str
    unit: str
    valid_from: str
    valid_until: str
    known_from: str
    definitions: list[Definition]
    template: str | None = None
    engine: str = ""  # engine name of its view


@dataclass
class Fact:
    """How a fact leaf is read: an attribute of the subject kind, a column of a derived relation (M2)
    whose first column is the subject, whether such a relation holds for the subject, or a row of
    the input kind."""
    id: str
    type: str
    table: str | None  # the attribute table or derived relation, or None for an input concept
    optional: bool = False  # a missing optional attribute is not_applicable, not unknown
    key: str = "id"  # the column with the subject
    column: str = "v"  # the column with the value
    presence: bool = False  # true when the relation has a row for the subject, false otherwise
    derived: bool = False  # read from a derived relation of the rules (M2): its row is a premise of the witness
    index: int = 1  # the position of the value column in a row of `table` (the subject is at 0)


@dataclass
class Program:
    pack: str
    subject: str  # kind
    subject_type: str  # its SQL id type
    subject_table: str
    parameters: Slot | None
    choice: dict[str, Slot] | None  # name, valid_from, valid_until, and known_from when the kind has knowledge time
    inputs: dict[str, Slot | None] | None  # subject, fact, integer, boolean slots of the input kind
    as_of: tuple[str, str] | None
    versions: dict[str, Version]
    rules: dict[str, list[str]]  # rule -> its version ids, sorted
    types: dict[str, str]  # rule -> number or boolean
    facts: dict[str, Fact]
    order: list[tuple[str, str]]  # ("version", id) or ("rule", name), dependencies first
    engine: dict[str, str]  # rule -> engine name of its selection view

    def version_order(self, rule: str) -> list[str]:
        """The versions of a rule from most to least preferred: lex posterior on knowledge date,
        then on validity, then on the version text (a fixed order, no tie left open)."""
        vs = [self.versions[v] for v in self.rules[rule]]
        return [v.id for v in sorted(vs, key=lambda v: (v.known_from, v.valid_from, v.version), reverse=True)]

    def result(self, rule: str) -> types.Type:
        """The type of a rule's value: derived by the rule, a number or a boolean. A number carries the unit
        its versions state when they agree on one; a boolean has none."""
        units = {self.versions[v].unit for v in self.rules[rule]}
        unit = units.pop() if len(units) == 1 and self.types[rule] == NUMBER else None
        return types.Type(self.types[rule], unit=unit, derived=rule)


def expression(node: Node) -> dict:
    """A node in the form of contracts/calc.yaml (Expression)."""
    if node.op == "integer":
        return {"integer": str(node.value)}
    if node.op == "rule":
        name, version = node.value
        return {"rule": f"{name}@{version}" if version else name}
    if node.op in LEAVES:
        return {node.op: node.value}
    return {"op": node.op, "args": [expression(a) for a in node.args]}


def to_doc(prog: Program) -> dict:
    """ir/calc.json (contracts/calc.yaml, CalcIR): the program as the compiler bound it, templates filled
    in and every fact bound to where it is read. The publisher and the checker read it;
    neither reads calc/*.yaml again, and the checker evaluates it on its own."""
    def reads(f: Fact) -> str:
        if f.table is None:
            return "input"
        if f.presence:
            return "presence"
        if f.derived:
            return "column"
        return "optional" if f.optional else "attribute"

    facts = [{"id": f.id, "type": f.type, "reads": reads(f), "table": f.table or "", "index": f.index if f.table and not f.presence else 0}
             for f in sorted(prog.facts.values(), key=lambda f: f.id)]
    inputs = {role: prog.inputs[role].table for role in ("subject", "fact", "integer", "boolean")
              if prog.inputs and prog.inputs[role] is not None}
    return {
        "format": "rezono.calc-ir/1", "pack": prog.pack, "subject": prog.subject, "subject_table": prog.subject_table,
        "as_of": f"{PREFIX}__as_of", "parameters": prog.parameters.table if prog.parameters else "",
        **({"parameter_choice": {role: s.table for role, s in prog.choice.items()}} if prog.choice else {}),
        **({"inputs": inputs} if inputs else {}),  # a program without input concepts has no input tables
        "facts": facts,
        "rules": [{"rule": r, "view": prog.engine[r], "type": prog.types[r], "versions": vs} for r, vs in prog.rules.items()],
        "versions": [{"id": v.id, "rule": v.rule, "version": v.version, "view": v.engine, "valid_from": v.valid_from,
                      "valid_until": v.valid_until, "known_from": v.known_from,
                      "definitions": [{"name": d.name, "when": expression(d.when), "value": expression(d.value),
                                       "before": [b.split("#", 1)[1] for b in d.before]} for d in v.definitions]}
                     for v in sorted(prog.versions.values(), key=lambda v: v.id)],
    }


def engine_part(text: str) -> str:
    """A rule or version id as part of an engine name: lower snake case, no '__'."""
    s = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", "_", text).lower()
    return re.sub(r"[^a-z0-9]+", "_", s).strip("_") or "x"


def selection_name(rule: str) -> str:
    return f"{PREFIX}__{engine_part(rule)}"


def rule_input_columns(pack: Pack, doc: dict) -> dict:
    """Selection signatures for rule binding. The checked program must still confirm their types."""
    subject = doc.get("subject")
    if not isinstance(subject, str) or subject not in pack.kinds:
        return {}
    subject_type = types.rule_type(pack.kinds[pack.root(subject)].id_type)
    if subject_type is None:
        return {}
    columns = [("subject", subject_type), ("value", "integer"), ("state", "string"), ("reason", "string")]
    return {selection_name(version["rule"]): columns for version in doc.get("rules", [])
            if isinstance(version, dict) and isinstance(version.get("rule"), str)}


def merge_docs(entries: list[tuple[str, dict]], source: str | None = None) -> dict | None:
    """Merge calc/*.yaml files and lowered Rezono calculation modules of one pack into one program document."""
    if not entries:
        return None
    merged: dict = {"rules": [], "templates": []}
    for rel, doc in entries:
        where = rel if source is None else f"{source}:{rel}"
        if source is not None and "as_of" in doc:
            raise CompileError(f"calc.import: {where}: an imported calculation carries no as_of: its rules are "
                               "definition, and the date they are evaluated on is the importing pack's")
        for k, v in doc.items():
            if k in ("rules", "templates"):
                merged[k] += v or []
            elif k in merged and merged[k] != v:
                raise CompileError(f"calc.program: {where}: '{k}' differs from another calc file")
            else:
                merged[k] = v
    return merged


def read_doc(pack_dir: str | Path, source: str | None = None) -> dict | None:
    """Every calc/*.yaml as one program document, as written. None without calc/. `source` names the
    imported pack the files belong to: such a file states no evaluation date."""
    files = sorted(Path(pack_dir, "calc").glob("*.yaml"))
    return merge_docs([(f"calc/{f.name}", load_yaml(f) or {}) for f in files], source)


def _doc_rules_by_subject(docs: list[dict], out: dict[str, set[str]]) -> None:
    for doc in docs:
        subject = doc.get("subject")
        if not isinstance(subject, str):
            continue
        names = out.setdefault(subject, set())
        for version in doc.get("rules") or []:
            if isinstance(version, dict) and isinstance(version.get("rule"), str):
                names.add(version["rule"])


def read_closure(
    pack: Pack,
    pack_dir: str | Path,
    imports: dict,
    renames: dict,
    *,
    mods: list | None = None,
    bare_leaves: list[tuple[str, str, str, str]] | None = None,
) -> tuple[dict | None, dict[str, dict]]:
    """The program of the pinned import closure, and each imported pack's part of it: the
    calc files and Rezono calculation modules of the imported packs (`imports`, in dependency order,
    each pack once), then the pack's own, as one document under this pack's names. An imported file
    states no evaluation date; this pack states it, for the whole program. A pack that imports no
    calculation gets its own document, as written."""
    from . import rezono_calc

    parts: dict[str, dict] = {}
    visible: dict[str, set[str]] = {}
    visible_params: dict[str, set[str]] = {}
    for name, imported in imports.items():
        visible[name] = {name}.union(*(visible[dep] for dep in imported.imports))
        yaml_entries = [(f"calc/{f.name}", load_yaml(f) or {}) for f in sorted(Path(imported.dir, "calc").glob("*.yaml"))]
        calc_mods = rezono_calc.calc_modules(mods or (), name)
        own_params: set[str] = set()
        for m in calc_mods:
            own_params.update(rezono_calc.module_parameters(m.form))
        visible_params[name] = own_params.union(*(visible_params[dep] for dep in imported.imports))
        mod_entries: list[tuple[str, dict]] = []
        if calc_mods:
            rules_by_subject: dict[str, set[str]] = {}
            inv_rename: dict[str, list[str]] = {}
            for own_id, root_id in renames[name].items():
                inv_rename.setdefault(root_id, []).append(own_id)
            for dep in visible[name] - {name}:
                if dep in parts and isinstance(parts[dep].get("subject"), str):
                    for own_id in inv_rename.get(parts[dep]["subject"], []):
                        names = rules_by_subject.setdefault(own_id, set())
                        for version in parts[dep].get("rules") or []:
                            if isinstance(version, dict) and isinstance(version.get("rule"), str):
                                names.add(version["rule"])
            _doc_rules_by_subject([doc for _, doc in yaml_entries], rules_by_subject)
            for m in calc_mods:
                cls_name, rnames = rezono_calc.module_rules(m.form)
                if cls_name is not None:
                    own_id, _ = rezono_calc.resolve_subject(pack, name, cls_name, renames)
                    rules_by_subject.setdefault(own_id, set()).update(rnames)
            mod_entries = [
                (m.rel, rezono_calc.lower_module(
                    pack, m, rules_by_subject, visible_params[name],
                    renames=renames, bare_leaves=bare_leaves,
                ))
                for m in calc_mods
            ]
            rezono_calc.check_parameter_sources(yaml_entries, mod_entries)
        doc = merge_docs(yaml_entries + mod_entries, name)
        if doc is not None:
            parts[name] = under(pack, doc, renames[name])

    root_name = pack.meta["name"]
    yaml_entries = [(f"calc/{f.name}", load_yaml(f) or {}) for f in sorted(Path(pack_dir, "calc").glob("*.yaml"))]
    calc_mods = rezono_calc.calc_modules(mods or (), root_name)
    root_params = set().union(*(visible_params[dep] for dep in visible_params))
    for m in calc_mods:
        root_params.update(rezono_calc.module_parameters(m.form))
    mod_entries = []
    if calc_mods:
        rules_by_subject = {}
        _doc_rules_by_subject(list(parts.values()) + [doc for _, doc in yaml_entries], rules_by_subject)
        for m in calc_mods:
            cls_name, rnames = rezono_calc.module_rules(m.form)
            if cls_name is not None:
                own_id, _ = rezono_calc.resolve_subject(pack, root_name, cls_name)
                rules_by_subject.setdefault(own_id, set()).update(rnames)
        mod_entries = [
            (m.rel, rezono_calc.lower_module(
                pack, m, rules_by_subject, root_params, bare_leaves=bare_leaves,
            ))
            for m in calc_mods
        ]
        rezono_calc.check_parameter_sources(yaml_entries, mod_entries)
    own = merge_docs(yaml_entries + mod_entries)
    if not parts:
        return own, parts
    if own is None or own.get("as_of") is None:
        raise CompileError(f"calc.import: {root_name} imports the calculation of {', '.join(parts)} and states "
                           "no evaluation date: give as_of in a calc file of its own")
    return union([*parts.items(), (root_name, own)]), parts


def union(docs: list[tuple[str, dict]]) -> dict:
    """The program documents of several packs as one: the rules and templates of all, each binding where the
    packs that give it agree, and the name of the last pack, which imports the others."""
    merged: dict = {"rules": [], "templates": []}
    first: dict[str, str] = {}
    for name, doc in docs:
        for k, v in doc.items():
            if k in ("rules", "templates"):
                merged[k] += v or []
            elif k != "pack" and k in merged and merged[k] != v:
                raise CompileError(f"calc.import: '{k}' of pack {name} differs from that of pack {first[k]}; "
                                   "one program has one")
            else:
                merged[k] = v
                first.setdefault(k, name)
    return merged


def under(pack: Pack, doc: dict, names: dict[str, str]) -> dict:
    """An imported program under the importing pack's names: the kinds its bindings name, and the kind
    of every fact leaf that reads an attribute. Any other fact leaf names a derived relation or an input
    concept, which keeps its name."""
    def leaves(e):
        if isinstance(e, list):
            return [leaves(x) for x in e]
        if not isinstance(e, dict):
            return e
        if isinstance(e.get("fact"), str):
            kind, _, name = e["fact"].partition(".")
            to = names.get(kind)
            return {**e, "fact": f"{to}.{name}"} if to in pack.kinds and pack.slot(to, name) is not None else e
        return {k: leaves(v) for k, v in e.items()}

    out = dict(doc, rules=leaves(doc["rules"]), templates=leaves(doc["templates"]))
    if isinstance(out.get("subject"), str):
        out["subject"] = names.get(out["subject"], out["subject"])
    if isinstance(out.get("parameters"), str):
        out["parameters"] = renamed(out["parameters"], names)
    if isinstance(out.get("inputs"), dict) and isinstance(out["inputs"].get("kind"), str):
        out["inputs"] = dict(out["inputs"], kind=names.get(out["inputs"]["kind"], out["inputs"]["kind"]))
    return out


def check_imports(pack: Pack, prog: Program, parts: dict[str, dict], imports: dict, renames: dict) -> None:
    """An imported calculation means in the union what it means in its own pack. The program
    of each imported pack is built once more on what that pack sees: its own kinds, relations and calc files
    and those of the packs it imports. It must be a program there, and the union must read each of its
    rules, facts and parameters the same way. So an importing pack reads an imported rule, and can neither
    add a version to it nor come between it and what it reads. A Datalog rule of an imported pack that reads
    a selection reads it there as here: a numeric rule of the program its pack sees."""
    root, derived, visible = pack.meta["name"], derived_relations(pack), {}
    selections = {r["name"] for r in (pack.rules or {}).get("relations", []) if r["role"] == "calc"}
    reads: dict[str, set[str]] = {}  # per imported pack, the selections its own rule files read
    for r in (pack.rules or {}).get("rules", []):
        owner, sep, _ = r.get("origin", {}).get("file", "").partition(":rules/")
        if sep:
            reads.setdefault(owner, set()).update(b["relation"] for b in r["body"] if b["relation"] in selections)
    for name, imported in imports.items():  # dependency order: a pack comes after the packs it imports
        visible[name] = {name}.union(*(visible[i] for i in imported.imports))
        if name not in parts and not reads.get(name):
            continue
        seen = [n for n in imports if n in visible[name]]
        modules = {rules_dl.module_of(n, root, f.stem) for n in seen for f in (imports[n].dir / "rules").glob("*.dl")}
        kinds = set(renames[name].values())
        try:
            alone = build(replace(pack, kinds={k: v for k, v in pack.kinds.items() if k in kinds}),
                          union([(n, parts[n]) for n in seen if n in parts]),
                          {r: d for r, d in derived.items() if d["module"] in modules})
        except CompileError as e:
            raise CompileError(f"calc.import: the calculation of pack {name} is no program on its own:\n{e}") from None
        for rule, versions in alone.rules.items():
            if prog.rules[rule] != versions:
                raise CompileError(f"calc.import: rule {rule} belongs to pack {name}: another pack reads it, and "
                                   f"adds no version to it ({', '.join(sorted(set(prog.rules[rule]) - set(versions)))})")
            if prog.types[rule] != alone.types[rule]:
                raise CompileError(f"calc.import: rule {rule} is a {alone.types[rule]} in pack {name} and a "
                                   f"{prog.types[rule]} in {root}")
        for fid, fact in alone.facts.items():
            if prog.facts[fid] != fact:
                there, here = ((f"{f.type} read from {f.table}" if f.table else f"{f.type} input concept")
                               for f in (fact, prog.facts[fid]))
                raise CompileError(f"calc.import: fact {fid} is a {there} in pack {name} and a {here} in {root}: "
                                   "an imported calculation reads only its own pack and the packs it imports")
        if alone.parameters is not None and alone.choice != prog.choice:
            raise CompileError(f"calc.import: parameter_choice of {root} differs from that of pack {name}, whose "
                               "calculation would choose its parameters differently")
        numeric = {alone.engine[rule] for rule in alone.rules if alone.types[rule] == NUMBER}
        if missing := sorted(reads.get(name, set()) - numeric):
            raise CompileError(f"calc.import: a rule of pack {name} reads {', '.join(missing)}, which is no numeric "
                               "selection of the calculation that pack sees")


def load_yaml(path: Path):
    """YAML with libyaml when it is there: a calc file of a large pack is a megabyte."""
    return strict_yaml.read(path)


def build(pack: Pack, doc: dict, derived: dict | None = None, files: list[tuple[str, Path]] | None = None) -> Program:
    """The checked program. `derived` gives the derived relations it may read, when those are not all of
    the pack's (`check_imports`). `files` are the calc files the program was read from, each with its name as a
    span names it, so that a unit error says where it is written (`files_of`)."""
    errors: list[str] = []
    if doc.get("format") != "rezono.calc/1":
        raise CompileError("calc.program: format must be rezono.calc/1")
    for key in ("pack", "subject"):
        if not doc.get(key):
            raise CompileError(f"calc.program: '{key}' is required")
    subject = doc["subject"]
    if subject not in pack.kinds:
        raise CompileError(f"calc.binding: subject '{subject}' is not a kind of the pack")
    root = pack.kinds[pack.root(subject)]
    if root.identifier is None:
        raise CompileError(f"calc.binding: subject '{subject}' has no identifier")
    parameters = bind_parameters(pack, doc.get("parameters"))
    choice = bind_choice(pack, parameters, doc.get("parameter_choice"), (doc.get("parameters") or "").partition(".")[0])
    inputs = bind_inputs(pack, subject, doc.get("inputs"))
    as_of = None
    if doc.get("as_of") is not None:
        a = doc["as_of"]
        as_of = (date_text(a.get("valid_at"), "as_of.valid_at"), date_text(a.get("known_at"), "as_of.known_at"))

    templates = {}
    for t in doc.get("templates") or []:
        tid = t.get("id")
        if not tid or tid in templates:
            errors.append(f"calc.template: template '{tid}' is missing an id or defined twice")
            continue
        templates[tid] = t

    versions: dict[str, Version] = {}
    for r in doc.get("rules") or []:
        try:
            v = read_version(r, templates)
        except CompileError as e:
            errors.append(str(e))
            continue
        if v.id in versions:
            errors.append(f"calc.rule: {v.id} is defined twice")
        versions[v.id] = v
    if errors:
        raise CompileError("\n".join(errors))

    rules: dict[str, list[str]] = {}
    for v in versions.values():
        rules.setdefault(v.rule, []).append(v.id)
    rules = {r: sorted(vs) for r, vs in sorted(rules.items())}
    for r, vs in rules.items():
        outputs = {versions[v].output for v in vs}
        if len(outputs) > 1:
            errors.append(f"calc.rule: the versions of {r} fill different outputs: {', '.join(sorted(outputs))}")

    facts: dict[str, Fact] = {}
    derived = derived_relations(pack) if derived is None else derived
    for v in versions.values():
        for d in v.definitions:
            for node in (d.when, d.value):
                check_leaves(pack, subject, inputs, parameters, versions, rules, node, d.id, facts, errors, derived)
            check_overrides(v, d, errors)
        check_override_cycles(v, errors)
    if errors:
        raise CompileError("\n".join(errors))

    rule_types = infer_types(versions, rules, facts, errors)
    for f in sorted(facts.values(), key=lambda f: f.id):
        if f.table is None and inputs[f.type if f.type == "boolean" else "integer"] is None:
            errors.append(f"calc.binding: fact {f.id} is a {f.type}, but inputs bind no {'boolean' if f.type == BOOLEAN else 'integer'} slot")
    order = dependency_order(versions, rules, errors)
    if errors:
        raise CompileError("\n".join(errors))
    if problems := check_units(pack, versions, rules, facts):
        raise UnitError(problems, files or [], versions)

    engine, seen = {}, {}
    for r, vs in rules.items():
        engine[r] = selection_name(r)
        for vid in vs:
            versions[vid].engine = f"{engine[r]}__{engine_part(versions[vid].version)}"
    # Every name the calculation adds to the engine, checked against the pack's tables and relations
    # and against each other: two generated names that meet are as wrong as one that meets a table.
    taken = {s.table for k in pack.kinds.values() for s in k.slots.values()} | set(pack.kinds) | set(derived)
    generated = [(f"{PREFIX}__as_of", "the evaluation date"), (f"{PREFIX}__input_integer", "the integer inputs"),
                 (f"{PREFIX}__input_boolean", "the boolean inputs")]
    if choice:
        generated.append((f"{PREFIX}__parameter", "the chosen parameters"))
    elif parameters is not None:
        generated.append((f"{PREFIX}__parameter_value", "the parameter values"))
    generated += [(n, r) for r, n in engine.items()] + [(v.engine, v.id) for v in versions.values()]
    generated += [(f"{v.engine}__witness", f"the witness of {v.id}") for v in versions.values()]
    for name, owner in generated:
        if name in seen or name in taken:
            errors.append(f"calc.name: engine name '{name}' of {owner} clashes with {seen.get(name, 'a table or relation of the pack')}")
        seen.setdefault(name, owner)
    if errors:
        raise CompileError("\n".join(errors))
    return Program(doc["pack"], subject, root.id_type, subject, parameters, choice, inputs, as_of, versions, rules,
                   rule_types, facts, order, engine)


def date_text(v, where: str) -> str:
    """A date, never a timestamp: a datetime is also a date in Python, so it is refused first."""
    if isinstance(v, datetime.datetime):
        raise CompileError(f"calc.date: {where}: '{v}' is a timestamp, not a date (YYYY-MM-DD)")
    if isinstance(v, datetime.date):
        return v.isoformat()
    if isinstance(v, str) and ISO_DATE.match(v):
        try:
            datetime.date.fromisoformat(v)
        except ValueError:
            raise CompileError(f"calc.date: {where}: '{v}' is no day of the calendar") from None
        return v
    raise CompileError(f"calc.date: {where}: '{v}' is not a date (YYYY-MM-DD)")


def attribute(pack: Pack, element: str, where: str) -> Slot:
    kind, _, name = (element or "").partition(".")
    s = pack.slot(kind, name) if kind in pack.kinds else None
    if s is None or s.arrow:
        raise CompileError(f"calc.binding: {where}: '{element}' is not an attribute of the pack")
    return s


def bind_parameters(pack: Pack, element: str | None) -> Slot | None:
    if element is None:
        return None
    s = attribute(pack, element, "parameters")
    if s.sql_type != "BIGINT":
        raise CompileError(f"calc.binding: parameters: '{element}' is not an integer attribute")
    if pack.kinds[pack.root(s.kind)].id_type != "VARCHAR":
        raise CompileError(f"calc.binding: parameters: kind '{s.kind}' needs a text identifier")
    return s


CHOICE = (("name", "VARCHAR"), ("valid_from", "DATE"), ("valid_until", "DATE"), ("known_from", "DATE"))


def bind_choice(pack: Pack, parameters: Slot | None, b: dict | None, kind: str | None = None) -> dict[str, Slot] | None:
    """`parameter_choice`: the slots of the parameter kind that let a leaf name a parameter by its name
    and choose the row by validity and knowledge date (W10 for parameters). Without it a leaf names an
    element by its id."""
    if b is None:
        return None
    if parameters is None:
        raise CompileError("calc.binding: parameter_choice: the program binds no parameters")
    if not isinstance(b, dict) or set(b) not in ({"name"}, {role for role, _ in CHOICE}):
        raise CompileError(f"calc.binding: parameter_choice: give exactly {', '.join(r for r, _ in CHOICE)}, "
                           "or only name with validity slots declared by role (S26)")
    by_role = set(b) == {"name"}
    # Preserve the explicit binding's scope; a short binding can name a subtype with inherited value/roles.
    kind = (kind or parameters.kind) if by_role else parameters.kind
    out = {}
    for role, sql_type in CHOICE:
        if by_role and role != "name":
            slots = [s for s in pack.all_slots(kind) if s.role == role]
            if not slots and role == "known_from":
                continue  # S26: a kind without knowledge time has every row known from the start
            if len(slots) != 1:
                raise CompileError(f"calc.binding: parameter_choice: '{kind}' needs exactly one {role} role")
            s = slots[0]
            element = s.name
        else:
            element = b[role]
            s = pack.slot(kind, element) if isinstance(element, str) else None
        if s is None or s.arrow or s.multivalued or s.sql_type != sql_type:
            want = "a text" if sql_type == "VARCHAR" else "a date"
            raise CompileError(f"calc.binding: parameter_choice: {role}: '{element}' is not {want} attribute of '{kind}'")
        out[role] = s
    return out


def bind_inputs(pack: Pack, subject: str, b: dict | None) -> dict | None:
    if b is None:
        return None
    kind = b.get("kind")
    if kind not in pack.kinds:
        raise CompileError(f"calc.binding: inputs: '{kind}' is not a kind of the pack")

    def slot(role: str, sql_type: str | None, arrow: bool = False) -> Slot | None:
        name = b.get(role)
        if name is None:
            if role in ("subject", "fact"):
                raise CompileError(f"calc.binding: inputs: '{role}' is required")
            return None
        s = pack.slot(kind, name)
        ok = s is not None and s.arrow == arrow and (sql_type is None or s.sql_type == sql_type)
        if arrow and ok:
            ok = s.range in pack.ancestors(subject)
        if not ok:
            raise CompileError(f"calc.binding: inputs.{role}: '{kind}.{name}' does not fit")
        return s

    return {"kind": kind, "subject": slot("subject", None, arrow=True), "fact": slot("fact", "VARCHAR"),
            "integer": slot("integer", "BIGINT"), "boolean": slot("boolean", "BOOLEAN")}


def parse(e, where: str, in_template: bool = False) -> Node:
    if not isinstance(e, dict):
        raise CompileError(f"calc.expression: {where}: an expression is a mapping, not {e!r}")
    keys = [k for k in e if e[k] is not None]
    unit = e.get("unit")
    if unit is not None:  # P10.3: a constant with its unit, as Rezono writes `384 GiB`
        if set(keys) != {"integer", "unit"}:
            raise CompileError(f"calc.unit: {where}: a unit goes with an integer constant, not with {', '.join(sorted(set(keys) - {'unit'}))}")
        if not isinstance(unit, str) or not unit:
            raise CompileError(f"calc.unit: {where}: a unit is the name of a unit the pack declares, not {unit!r}")
        keys = ["integer"]
    if "op" in keys:
        if set(keys) - {"op", "args"}:
            raise CompileError(f"calc.expression: {where}: an operator has only op and args")
        op = e["op"]
        if op not in ARITY:
            raise CompileError(f"calc.operator: {where}: unknown operator '{op}'")
        args = e.get("args") or []
        lo, hi = ARITY[op]
        if len(args) < lo or (hi is not None and len(args) > hi):
            raise CompileError(f"calc.arity: {where}: {op} takes {lo}{'' if hi == lo else '+' if hi is None else f'-{hi}'} arguments, not {len(args)}")
        return Node(op, tuple(parse(a, where, in_template) for a in args))
    if len(keys) != 1 or keys[0] not in LEAVES:
        raise CompileError(f"calc.expression: {where}: exactly one of op or a leaf ({', '.join(LEAVES)})")
    k, v = keys[0], e[keys[0]]
    if k == "integer":
        text = str(v) if isinstance(v, int) and not isinstance(v, bool) else v
        if not isinstance(text, str) or not DECIMAL.match(text):
            raise CompileError(f"calc.integer: {where}: '{v}' is not an integer in decimal text")
        if abs(int(text)) > BOUND:
            raise CompileError(f"calc.integer: {where}: {text} does not fit 64 bits")
        return Node("integer", value=int(text), unit=unit)
    if k == "boolean":
        if not isinstance(v, bool):
            raise CompileError(f"calc.boolean: {where}: '{v}' is not a boolean")
        return Node("boolean", value=v)
    if not isinstance(v, str) or not v:
        raise CompileError(f"calc.expression: {where}: {k} needs an id")
    if k == "arg" and not in_template:
        raise CompileError(f"calc.template: {where}: arg '{v}' outside a template")
    if k == "rule":
        name, _, version = v.partition("@")
        return Node("rule", value=(name, version or None))
    return Node(k, value=v)


def substitute(node: Node, bindings: dict[str, Node]) -> Node:
    if node.op == "arg":
        return bindings[node.value]
    if not node.args:
        return node
    return Node(node.op, tuple(substitute(a, bindings) for a in node.args))


def arg_names(node: Node) -> set[str]:
    if node.op == "arg":
        return {node.value}
    return set().union(*(arg_names(a) for a in node.args)) if node.args else set()


def read_version(r: dict, templates: dict) -> Version:
    vid = r.get("id")
    for key in ("id", "rule", "version", "output", "unit"):
        if not r.get(key):
            raise CompileError(f"calc.rule: {vid}: '{key}' is required")
    if vid != f"{r['rule']}@{r['version']}":
        raise CompileError(f"calc.rule: {vid}: the id must be <rule>@<version>")
    if "@" in r["rule"] or "#" in r["rule"] or "#" in str(r["version"]):
        raise CompileError(f"calc.rule: {vid}: a rule or version has no '@' or '#'")
    dates = [date_text(r.get(k), f"{vid}.{k}") for k in ("valid_from", "valid_until", "known_from")]
    if dates[0] >= dates[1]:
        raise CompileError(f"calc.date: {vid}: valid_from must be before valid_until")
    defs_raw, tid, bindings = r.get("definitions"), None, {}
    if (defs_raw is None) == (r.get("template") is None):
        raise CompileError(f"calc.rule: {vid}: give definitions or a template, not both or neither")
    if defs_raw is None:
        use = r["template"]
        tid = use.get("template")
        if tid not in templates:
            raise CompileError(f"calc.template: {vid}: unknown template '{tid}'")
        t = templates[tid]
        args = list(t.get("arguments") or [])
        for b in use.get("bindings") or []:
            if b.get("arg") not in args or b["arg"] in bindings:
                raise CompileError(f"calc.template: {vid}: binding '{b.get('arg')}' is not an argument of {tid} or is given twice")
            bindings[b["arg"]] = parse(b.get("value"), f"{vid} binding {b['arg']}")
        if set(bindings) != set(args):
            raise CompileError(f"calc.template: {vid}: unbound arguments of {tid}: {', '.join(sorted(set(args) - set(bindings)))}")
        defs_raw = t.get("definitions") or []
    defs: list[Definition] = []
    for d in defs_raw:
        name = d.get("name")
        if not name or "#" in str(name):
            raise CompileError(f"calc.definition: {vid}: a definition needs a name without '#'")
        did = f"{vid}#{name}"
        when, value = (parse(d.get(k), f"{did}.{k}", in_template=tid is not None) for k in ("when", "value"))
        if tid is not None:
            unknown = (arg_names(when) | arg_names(value)) - set(bindings)
            if unknown:
                raise CompileError(f"calc.template: {tid}: undeclared argument {', '.join(sorted(unknown))}")
            when, value = substitute(when, bindings), substitute(value, bindings)
        before, reasons = [], []
        for o in d.get("overrides") or []:
            target = str(o.get("definition") or "")
            if tid is not None and target.startswith(f"{tid}#"):
                target = f"{vid}#{target.split('#', 1)[1]}"
            if not o.get("reason"):
                raise CompileError(f"calc.override: {did}: an override needs a reason")
            before.append(target)
            reasons.append(o["reason"])
        defs.append(Definition(did, name, when, value, before, reasons))
    if not defs:
        raise CompileError(f"calc.rule: {vid}: no definitions")
    if len({d.id for d in defs}) != len(defs):
        raise CompileError(f"calc.definition: {vid}: two definitions with the same name")
    return Version(vid, r["rule"], str(r["version"]), r["output"], r["unit"], *dates, defs, tid)


def leaves(node: Node):
    if node.args:
        for a in node.args:
            yield from leaves(a)
    else:
        yield node


def derived_relations(pack: Pack) -> dict[str, dict]:
    """The derived relations of the pack's rule program (M2), by name, as in its IR document."""
    if not getattr(pack, "rules", None):
        return {}
    from . import rules as rule_ir

    relations = rule_ir.load(pack.rules).relations
    return {
        r["name"]: {**r, "world": relations[r["name"]].world}
        for r in pack.rules["relations"]
        if r["role"] == "derived"
    }


def derived_fact(pack: Pack, subject: str, derived: dict, fid: str) -> Fact | str | None:
    """`r` (does relation r hold for the subject?) or `r.c` (column c of r for the subject), where the
    first column of r is the subject. A message when it names a relation but does not fit."""
    name, _, column = fid.partition(".")
    if name not in derived:
        return None
    key = derived[name]["key"]
    id_type = types.rule_type(pack.kinds[pack.root(subject)].id_type)
    if key[0]["type"] != id_type:
        return f"the first column of relation {name} is no {subject}"
    if not column:
        if len(key) != 1:
            return f"relation {name} has more columns than the subject; name one: {name}.<column>"
        if derived[name].get("world") == "open":  # a missing row is unknown, not false
            return f"relation {name} is open, so whether it holds is unknown when it has no row; test a closed relation"
        return Fact(fid, BOOLEAN, name, key=key[0]["name"], column="", presence=True, derived=True)
    cols = {c["name"]: c for c in key[1:]}
    if column not in cols or cols[column]["type"] != "integer":
        return f"relation {name} has no integer column {column} after the subject"
    return Fact(fid, NUMBER, name, key=key[0]["name"], column=column, derived=True,
                index=[c["name"] for c in key].index(column))


def check_leaves(pack, subject, inputs, parameters, versions, rules, node, where, facts, errors, derived=None) -> None:
    for leaf in leaves(node):
        if leaf.op == "rule":
            name, version = leaf.value
            if version is not None and f"{name}@{version}" not in versions:
                errors.append(f"calc.reference: {where}: no rule version {name}@{version}")
            elif version is None and name not in rules:
                errors.append(f"calc.reference: {where}: no rule {name}")
        elif leaf.op == "parameter" and parameters is None:
            errors.append(f"calc.binding: {where}: parameter {leaf.value} but the program binds no parameters")
        elif leaf.op == "fact" and leaf.value not in facts:
            kind, _, name = leaf.value.partition(".")
            s = pack.slot(kind, name) if kind in pack.kinds else None
            relation = derived_fact(pack, subject, derived or {}, leaf.value)
            if isinstance(relation, Fact):
                facts[leaf.value] = relation
            elif isinstance(relation, str):
                errors.append(f"calc.binding: {where}: fact {leaf.value}: {relation}")
            elif s is not None and kind in pack.ancestors(subject) and s.type.calc is not None:
                facts[leaf.value] = Fact(leaf.value, s.type.calc, s.table, optional=not s.required)
            elif s is not None:
                errors.append(f"calc.binding: {where}: fact {leaf.value} is not an integer or boolean attribute of {subject}")
            elif inputs is None:
                errors.append(f"calc.binding: {where}: fact {leaf.value} is no attribute of {subject} and the program binds no inputs")
            else:
                facts[leaf.value] = Fact(leaf.value, "", None)


def check_overrides(v: Version, d: Definition, errors: list[str]) -> None:
    ids = {x.id for x in v.definitions}
    for target in d.before:
        if target not in ids:
            errors.append(f"calc.override: {d.id}: overrides {target}, which is no definition of {v.id}")
        elif target == d.id:
            errors.append(f"calc.override: {d.id}: overrides itself")


def check_override_cycles(v: Version, errors: list[str]) -> None:
    graph = {d.id: [t for t in d.before] for d in v.definitions}
    cycle = find_cycle(graph)
    if cycle:
        errors.append(f"calc.override: {v.id}: the overrides form a cycle: {' > '.join(cycle)}")


def find_cycle(graph: dict[str, list[str]]) -> list[str] | None:
    state: dict[str, int] = {}
    stack: list[str] = []

    def visit(n: str) -> list[str] | None:
        state[n] = 1
        stack.append(n)
        for m in sorted(graph.get(n, [])):
            if state.get(m) == 1:
                return stack[stack.index(m):] + [m]
            if m not in state:
                found = visit(m)
                if found:
                    return found
        stack.pop()
        state[n] = 2
        return None

    for n in sorted(graph):
        if n not in state:
            found = visit(n)
            if found:
                return found
    return None


def infer_types(versions: dict[str, Version], rules: dict, facts: dict[str, Fact], errors: list[str]) -> dict[str, str]:
    """Unification: every rule and every input concept has one type across all its uses."""
    parent: dict = {NUMBER: NUMBER, BOOLEAN: BOOLEAN}
    counter = [0]

    def find(x):
        parent.setdefault(x, x)
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def unify(a, b, where):
        ra, rb = find(a), find(b)
        if ra == rb:
            return
        if ra in (NUMBER, BOOLEAN) and rb in (NUMBER, BOOLEAN):
            errors.append(f"calc.type: {where}: a {ra} where a {rb} is needed")
            return
        if ra in (NUMBER, BOOLEAN):
            parent[rb] = ra
        else:
            parent[ra] = rb

    def fresh():
        counter[0] += 1
        return ("var", counter[0])

    def typ(n: Node, where: str):
        if n.op == "integer" or n.op == "parameter":
            return NUMBER
        if n.op == "boolean":
            return BOOLEAN
        if n.op == "fact":
            f = facts[n.value]
            return f.type if f.type else ("fact", n.value)
        if n.op == "rule":
            return ("rule", n.value[0])
        ts = [typ(a, where) for a in n.args]
        if n.op in ARITHMETIC:
            for t in ts:
                unify(t, NUMBER, f"{where} ({n.op})")
            return NUMBER
        if n.op in ("and", "or"):
            for t in ts:
                unify(t, BOOLEAN, f"{where} ({n.op})")
            return BOOLEAN
        if n.op in ORDERING:
            for t in ts:
                unify(t, NUMBER, f"{where} ({n.op})")
            return BOOLEAN
        if n.op == "eq":
            unify(ts[0], ts[1], f"{where} (eq)")
            return BOOLEAN
        unify(ts[0], BOOLEAN, f"{where} (if)")
        t = fresh()
        unify(ts[1], t, f"{where} (if)")
        unify(ts[2], t, f"{where} (if)")
        return t

    for vid in sorted(versions):
        for d in versions[vid].definitions:
            unify(typ(d.when, d.id), BOOLEAN, f"{d.id}.when")
            unify(typ(d.value, d.id), ("rule", versions[vid].rule), f"{d.id}.value")
    for f in facts.values():
        if not f.type:
            t = find(("fact", f.id))
            f.type = t if t in (NUMBER, BOOLEAN) else NUMBER
            unify(("fact", f.id), f.type, f.id)
    out = {}
    for r in rules:
        t = find(("rule", r))
        out[r] = t if t in (NUMBER, BOOLEAN) else NUMBER
    return out


def dependency_order(versions: dict[str, Version], rules: dict, errors: list[str]) -> list[tuple[str, str]]:
    graph: dict[tuple[str, str], set] = {}
    for r, vs in rules.items():
        graph[("rule", r)] = {("version", v) for v in vs}
    for vid, v in versions.items():
        deps = set()
        for d in v.definitions:
            for node in (d.when, d.value):
                for leaf in leaves(node):
                    if leaf.op == "rule":
                        name, version = leaf.value
                        deps.add(("version", f"{name}@{version}") if version else ("rule", name))
        graph[("version", vid)] = deps
    cycle = find_cycle({f"{k[0]}:{k[1]}": [f"{d[0]}:{d[1]}" for d in ds] for k, ds in graph.items()})
    if cycle:
        errors.append(f"calc.cycle: the rules depend on themselves: {' > '.join(cycle)}")
        return []
    order, done = [], set()

    def visit(n):
        if n in done:
            return
        done.add(n)
        for m in sorted(graph[n]):
            visit(m)
        order.append(n)

    for n in sorted(graph):
        visit(n)
    return order


# Units (P10.3, ticket D04). The dimension of every number the compiler knows the unit of, checked per operator.
SAME_UNIT = {"add": "+", "sub": "-", "min": "min", "max": "max", "eq": "=", "lt": "<", "lte": "<=", "gte": ">=",
             "if": "if"}
KEEPS_UNIT = {"floor", "ceil", "round"}


@dataclass(frozen=True)
class UnitProblem:
    """One unit error of a calculation, in the form of a diagnostic (D15): a code (Rezono's R003 for dimensions
    that differ, R001 for an unknown unit), the version and the place in it (`path`: the definition's index, `when`
    or `value`, then one argument index per level), the sentence and what to write instead."""
    code: str
    version: str
    path: tuple
    message: str
    hint: str = ""

    def where(self, versions: dict) -> str:
        d, part, *args = self.path
        return f"{versions[self.version].definitions[d].id}.{part}" + "".join(f"/{a}" for a in args)


class UnitError(CompileError):
    """The unit errors of a calculation, each with its place and, when the files are known, its span."""

    def __init__(self, problems: list[UnitProblem], files: list[tuple[str, Path]], versions: dict):
        self.problems = problems
        self.spans = [span_of(files, versions[p.version], p.path) for p in problems]
        super().__init__("\n".join(
            f"calc.unit: {located(span)}{p.where(versions)}: {p.message} ({p.code})" + (f"; {p.hint}" if p.hint else "")
            for p, span in zip(problems, self.spans)))


def files_of(pack_dir: str | Path, root: str, imports: dict) -> list[tuple[str, Path]]:
    """The calc files of a program's closure, each with its name as a span gives it (spans.where)."""
    out = []
    for name, d in [(root, Path(pack_dir)), *((n, p.dir) for n, p in imports.items())]:
        out += [(spans.where(name, root, f"calc/{f.name}"), f) for f in sorted(Path(d, "calc").glob("*.yaml"))]
    return out


def span_of(files: list[tuple[str, Path]], version: Version, path: tuple) -> spans.Span | None:
    """Where the node at `path` of `version` is written: in the version's definitions, or in its template's. A node a
    template argument stands for is placed at the argument."""
    section, target = ("templates", version.template) if version.template else ("rules", version.id)
    for name, f in files:
        entries = (load_yaml(f) or {}).get(section) or []
        for i, e in enumerate(entries):
            if isinstance(e, dict) and e.get("id") == target:
                d, part, *args = path
                full = (section, i, "definitions", d, part, *(x for a in args for x in ("args", a)))
                return spans.first(spans.marks(f), name, *(full[:n] for n in range(len(full), 1, -1)))
    return None


def declared_unit(pack: Pack, text: str | None) -> types.Unit | None:
    return pack.units.get(text) if text else None


def fact_unit(pack: Pack, fact: Fact) -> types.Unit | None:
    """The unit of an attribute a fact leaf reads: money in its currency, or its declared unit. A derived relation's
    column and an input concept have none the compiler knows yet."""
    if fact.table is None or fact.derived or fact.presence:
        return None
    kind, _, name = fact.id.partition(".")
    s = pack.slot(kind, name)
    if s is None:
        return None
    return declared_unit(pack, s.unit) or (types.money_unit(s.currency) if s.currency else None)


def check_units(pack: Pack, versions: dict[str, Version], rules: dict, facts: dict[str, Fact]) -> list[UnitProblem]:
    """The dimension checks of P10.3 (Rezono v0 §7.3, R003): the arguments of `add`, `sub`, `min`, `max`, a
    comparison and the branches of `if` have one unit; `ratio` multiplies and divides units; `pow` raises one by a
    constant; a rounding keeps it; a definition's value has the unit its rule states. A constant without a unit is
    a plain number, except 0, which is zero in every unit. Units of one dimension that differ by a factor are an
    error too: calc converts nothing yet."""
    problems: list[UnitProblem] = []
    for rule, vs in rules.items():
        if len({declared_unit(pack, versions[v].unit) for v in vs}) > 1:
            problems.append(UnitProblem("R003", vs[0], (0, "value"), f"the versions of {rule} state the units "
                                        f"{', '.join(sorted({versions[v].unit for v in vs}))}; a rule has one"))

    def named(n: Node | None, u: types.Unit) -> str:
        return str(n.value) if n is not None and n.op == "integer" and u.plain else u.name

    def differ(na: Node | None, ua: types.Unit, nb: Node | None, ub: types.Unit) -> tuple[str, str]:
        """Why two units do not meet, and what to write instead."""
        if ua.plain or ub.plain:
            n, u = (na, ub) if ua.plain else (nb, ua)
            if n is not None and n.op == "integer":
                return (f"{n.value} has no unit and {u.name} is {u.text}",
                        f'write the constant with its unit: {{integer: "{n.value}", unit: {u.name}}}')
            return f"a number without a unit meets {u.name}, which is {u.text}", ""
        if ua.dimension != ub.dimension:
            return f"dimensions differ ({ua.text}, {ub.text})", ""
        return (f"one dimension ({ua.text}), but the units differ by a factor, and calc converts nothing yet",
                "state both in one unit")

    def unit(n: Node, vid: str, path: tuple) -> types.Unit | None:
        if n.op == "integer":
            if n.unit is not None and n.unit not in pack.units:
                problems.append(UnitProblem("R001", vid, path, f"unit {n.unit} is no unit the pack declares",
                                            "declare it on a type of the schema (annotation dimension or unit)"))
            return pack.units.get(n.unit) if n.unit is not None else None if n.value == 0 else types.PLAIN
        if n.op == "fact":
            return fact_unit(pack, facts[str(n.value)])
        if n.op == "rule":
            rule, version = cast(tuple, n.value)
            found = {declared_unit(pack, versions[v].unit) for v in ([f"{rule}@{version}"] if version else rules[rule])}
            return found.pop() if len(found) == 1 else None
        if not n.args:
            return None  # a boolean, a parameter
        us = [unit(a, vid, path + (i,)) for i, a in enumerate(n.args)]
        if n.op in SAME_UNIT:
            known = [(i, n.args[i], u) for i, u in enumerate(us) if u is not None and (n.op != "if" or i > 0)]
            for i, a, u in known[1:]:
                _, first, ufirst = known[0]
                if u != ufirst:
                    sides = (named(first, ufirst), named(a, u))
                    what = f"{n.op}({', '.join(sides)})" if n.op in ("min", "max", "if") else f" {SAME_UNIT[n.op]} ".join(sides)
                    reason, hint = differ(first, ufirst, a, u)
                    problems.append(UnitProblem("R003", vid, path + (i,), f"{what}: {reason}", hint))
                    return None
            return known[0][2] if known and n.op not in ("eq", "lt", "lte", "gte") else None
        x = us[0]
        if n.op in KEEPS_UNIT or x is None:
            return x
        if n.op == "ratio":
            factor, divisor = us[1:]
            return None if factor is None or divisor is None else x.times(factor).over(divisor)
        if n.op == "pow":
            if us[1] is not None and not us[1].plain:
                problems.append(UnitProblem("R003", vid, path + (1,), f"an exponent has no unit, and this one is {us[1].name}"))
                return None
            if x.plain:
                return x
            if n.args[1].op != "integer":
                problems.append(UnitProblem("R003", vid, path, f"a power of {x.name} needs a constant exponent"))
                return None
            return x.power(int(cast(int, n.args[1].value)))
        return None  # and, or: truth values

    for vid in sorted(versions):
        v = versions[vid]
        want = declared_unit(pack, v.unit)
        for i, d in enumerate(v.definitions):
            unit(d.when, vid, (i, "when"))
            got = unit(d.value, vid, (i, "value"))
            if want is not None and got is not None and got != want:
                reason, hint = differ(d.value, got, None, want)
                problems.append(UnitProblem("R003", vid, (i, "value"), f"{named(d.value, got)} as the value of "
                                            f"{v.rule}, which states {want.name}: {reason}", hint))
    return problems
