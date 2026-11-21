"""Lower `derived` written in a `rezono 1` module to the rule IR `rezono.rules/2`.

The decision is decisions/language-rezono-1.md (sections 2 and 4), refined by
decisions/language-rezono-1-refinements.md (sections 1, 3.1 and 3.3) and decisions/language-readable-rules.md
(section 2). What is lowered:

- A derived property `d` of kind `K` (in `kind K` or `extend s: K`) is the relation `<k>_<d>`. A `Bool` property is
  a plain set of elements; any other is a functional relation over `k` with co-located (key, state, reason, value).
- A module-level `derived name(k1: T1, ...)` is a plain set when it is `Bool`, and otherwise a functional relation
  over its `over` relation, whose key columns are the declared parameters in order.
- A functional value is a slot path (a missing slot gives `no_value`: `unknown` when the path is required,
  `not_applicable` when it is optional), `S.count(pred)` or `S.count()` (rows where `pred` is true, `known 0` for none),
  or `S.one()` / `S.one(expr)` (`no_match` for no row: `unknown` for `T`, `not_applicable` for `T?`; `invalid
  multiple_values` for two distinct values). `S` is a kind, a `.where(...)` of one, or a relation read as its tuple set.
- A row of `S` whose predicate reads a missing required slot, and is not already false, is undecided; so is a row
  of `.one(expr)` whose `expr` slot is missing. An undecided row makes the count or the `.one()` `unknown no_value`
  through the engines' state-bearing aggregate: unknown is never read as false.
- `means` lowers to the message of every rule of the derivation, `@` to the `source` of its bundle rule entries.

Anything else is refused with a diagnostic at its place, never lowered approximately. Numeric and Boolean
calculations that carry calculation members, or that stand in a module with `as of`, keep lowering to
`rezono.calc/1` (rezono_calc.py) until that IR retires (decisions/language-rezono-1.md section 5.6).
"""

from __future__ import annotations

import json
import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, NoReturn

from . import rules, rules_dl, spans
from .diagnostics import Diagnostic

if TYPE_CHECKING:
    from . import modules

REZONO_1_FORMAT = "rezono.module/5"
SCALARS = {"Int": "integer", "Text": "string", "Bool": "boolean", "Date": "date"}
COMPARE = rules_dl.COMPARE
ARITH = rules_dl.ARITH
NEGATED = {"eq": "ne", "ne": "eq", "lt": "ge", "le": "gt", "gt": "le", "ge": "lt"}
KNOWN, UNKNOWN = ("const", "known", "string"), ("const", "unknown", "string")
NOT_APPLICABLE, INVALID = ("const", "not_applicable", "string"), ("const", "invalid", "string")
EMPTY, NO_VALUE = ("const", "", "string"), ("const", "no_value", "string")
EXCEPTION_CONFLICT = ("const", "exception_conflict", "string")
VERSIONS_OVERLAP = ("const", "versions_overlap", "string")
SENTINEL = {"string": ("const", "", "string"), "boolean": ("const", "false", "boolean"),
            "rational": ("const", "0", "rational")}


def module_as_of(form: dict) -> tuple[str, str] | None:
    """The `(valid_at, known_at)` evaluation date declared by `as of` in `form`, if any."""
    for d in form["module"]["decls"]:
        if isinstance(d, dict) and "asOf" in d and "known" in d:
            return d["asOf"], d["known"]
    return None


def is_derivation(form: dict | None, derived: object) -> bool:
    """Whether a derived value of a kind or an extension in `form` lowers here to rezono.rules/2."""
    return form is not None and form.get("format") == REZONO_1_FORMAT and isinstance(derived, dict)


def is_module_derived(decl: object) -> bool:
    """A module-level `derived name(params): T` declaration."""
    return isinstance(decl, dict) and isinstance(decl.get("derived"), str)


Note = rules_dl.RuleNote


@dataclass
class Lowered:
    sources: tuple[rules_dl.NativeSource, ...] = ()
    notes: dict[str, Note] = field(default_factory=dict)  # relation -> its sentence and source
    properties: dict[str, tuple[str, str]] = field(default_factory=dict)  # relation `<k>_<d>` -> (k, d)
    note_owners: dict[str, str] = field(default_factory=dict)  # relation -> owning pack name


class Refused(Exception):
    def __init__(self, diagnostic: Diagnostic):
        super().__init__(str(diagnostic))
        self.diagnostic = diagnostic


@dataclass(frozen=True)
class Site:
    file: str
    text: str
    offsets: dict[str, str]

    def place(self, at: str) -> tuple[int, int]:
        while at not in self.offsets and "/" in at:
            at = at.rsplit("/", 1)[0]
        offset = int(self.offsets.get(at, "0"))
        return self.text.count("\n", 0, offset) + 1, offset - self.text.rfind("\n", 0, offset)

    def refuse(self, at: str, message: str, code: str = "R049") -> NoReturn:
        line, column = self.place(at)
        raise Refused(Diagnostic(code, message, f"{self.file}#{at}", (self.file, line, column)))


@dataclass
class Signature:
    """One derivation: its relation, key, result and where it is written."""

    relation: str
    at: str
    decl: dict
    site: Site
    module: modules.Module
    key: list[tuple[str, tuple]]  # (variable, type) per key column; a type is ("kind", k) or ("scalar", t)
    result: str  # "set" or "functional"
    value_type: str | None = None  # the IR type of a functional value
    optional: bool = False  # `T?`
    domain: str | None = None  # the closed domain relation of a functional derivation
    kind: str | None = None  # for a property: its kind
    property: str | None = None  # for a property: its name
    binder: str | None = None  # for a property: the subject variable
    key_column: str | None = None  # for a property: the name of its key column
    enum_type: str | None = None  # for an enum result: the pack enum id
    note_source: str | None = None  # optional @ source from declaration or selected version
    as_of: tuple[str, str] | None = None  # (valid_at, known_at) evaluation date


def _use_scope(module: modules.Module) -> tuple[tuple[str, ...], dict[str, str]]:
    """Return `(unaliased_packs, alias_to_pack)` from a rezono module's `use` lines."""
    unaliased: list[str] = []
    aliases: dict[str, str] = {}
    form_module = (module.form or {}).get("module") or {}
    for line_ in form_module.get("use") or ():
        if not isinstance(line_, dict) or not isinstance(line_.get("use"), str):
            continue
        target = line_["use"]
        if "as" in line_:
            if isinstance(line_["as"], str):
                aliases[line_["as"]] = target
        elif target not in unaliased:
            unaliased.append(target)
    return tuple(unaliased), aliases


def _resolve_schema_name(
    site: Site,
    names: modules.Names,
    module: modules.Module,
    at: str,
    text: str,
) -> str | None:
    """Resolve an unqualified or `alias.Name` schema kind/enum visible in `module`, held to `interface`."""
    unaliased, aliases = _use_scope(module)
    if "." in text:
        prefix, _, local = text.partition(".")
        if prefix not in aliases:
            site.refuse(at, f"{prefix} is not an imported alias in this module", "R046")
        target_pack = aliases[prefix]
        candidates = [
            mid for mid, mod in names.modules.items()
            if mod.pack == target_pack and local in names.declared.get(mid, ())
        ]
        if len(candidates) == 1:
            return names.resolve(module.id, local, owner=candidates[0])
        if len(candidates) > 1:
            site.refuse(at, f"{text} is declared by more than one module of {target_pack}", "R046")
        return None
    visible = {module.pack, *unaliased}
    candidates = [
        mid for mid, mod in names.modules.items()
        if mod.pack in visible and text in names.declared.get(mid, ())
    ]
    if len(candidates) == 1:
        return names.resolve(module.id, text, owner=candidates[0])
    if len(candidates) > 1:
        site.refuse(at, f"{text} is declared by multiple used packs; qualify it with an import alias", "R046")
    return None


def _resolve_relation(
    module: modules.Module,
    signatures: Mapping[str, Signature],
    site: Site,
    at: str,
    name: str,
) -> Signature | None:
    """Resolve an unqualified or `alias.name` derived relation visible in `module`."""
    unaliased, aliases = _use_scope(module)
    if "." in name:
        prefix, _, local = name.partition(".")
        if prefix not in aliases:
            site.refuse(at, f"{prefix} is not an imported alias in this module", "R046")
        target = signatures.get(local)
        if target is None or target.module.pack != aliases[prefix]:
            return None
        return target
    target = signatures.get(name)
    if target is None:
        return None
    if target.module.pack != module.pack and target.module.pack not in unaliased:
        site.refuse(at, f"{name} is not visible here; import it with `use`", "R046")
    return target


def lower_pack(root: str, mods: Iterable[modules.Module], names: modules.Names, pack) -> Lowered:
    """The rules of every rezono 1 derivation of the pack and its imported packs, as native sources."""
    from .pack import CompileError

    as_ofs_by_pack: dict[str, set[tuple[str, str]]] = {}
    for m in mods:
        if m.form is not None and m.form.get("format") == REZONO_1_FORMAT:
            if (ao := module_as_of(m.form)) is not None:
                as_ofs_by_pack.setdefault(m.pack, set()).add(ao)
    default_by_pack = {p: next(iter(aos)) for p, aos in as_ofs_by_pack.items() if len(aos) == 1}
    root_as_of = default_by_pack.get(root)
    found = [m for m in mods if m.form is not None and m.form.get("format") == REZONO_1_FORMAT
             and any(_derivations(m.form))]
    if not found:
        return Lowered()
    refused: list[Diagnostic] = []
    signatures: dict[str, Signature] = {}
    sites: dict[str, Site] = {}
    for module in found:
        where = spans.where(module.pack, root, module.rel)
        try:
            text = module.file.read_bytes().decode("utf-8")
        except (OSError, UnicodeError) as error:
            message = f"{where}: cannot read the positions of its derivations"
            raise CompileError(message, [Diagnostic("R000", message, where)]) from error
        site = Site(where, text, {place["at"]: place["start"] for place in module.form["spans"]})
        sites[module.id] = site
        mod_as_of = module_as_of(module.form) or default_by_pack.get(module.pack) or root_as_of
        for at, decl, owner in _derivations(module.form):
            try:
                signature = _signature(site, module, names, pack, at, decl, owner, mod_as_of)
                if signature.relation in signatures:
                    site.refuse(at, f"{signature.relation} is derived twice")
                signatures[signature.relation] = signature
            except Refused as error:
                refused.append(error.diagnostic)
    if refused:
        raise CompileError("\n".join(map(str, refused)), refused)
    for signature in signatures.values():
        if signature.result != "functional" or signature.property is not None:
            continue
        raw_domain = signature.domain
        assert raw_domain is not None
        try:
            kind_domain = _resolve_schema_name(signature.site, names, signature.module, f"{signature.at}/over", raw_domain)
            if kind_domain is not None and kind_domain in pack.kinds:
                signature.domain = kind_domain
                continue
            target = _resolve_relation(signature.module, signatures, signature.site, f"{signature.at}/over", raw_domain)
            if target is None:
                signature.site.refuse(
                    f"{signature.at}/over",
                    f"`over` names a set this pack or a used pack derives in rezono 1, not {raw_domain}",
                )
            if target.result != "set":
                signature.site.refuse(
                    f"{signature.at}/over",
                    f"the domain {raw_domain} is a Bool set, not a functional derivation",
                )
            signature.domain = target.relation
        except Refused as error:
            refused.append(error.diagnostic)
    if refused:
        raise CompileError("\n".join(map(str, refused)), refused)
    lowered = Lowered()
    statements: dict[str, tuple[list, list]] = {}
    tables = rules_dl.base_tables(pack)
    taken = set(tables) | set(signatures)
    ordered = sorted(signatures.items(), key=lambda item: (item[1].result != "set", item[0]))
    opened: set[str] | None = None
    for name, signature in ordered:
        out = statements.setdefault(signature.module.id, ([], []))
        if signature.result == "functional" and opened is None:
            opened = _opened(statements, pack)
        if signature.result == "functional" and signature.domain in opened:
            refused.append(_open_domain(name, signature))
            continue
        try:
            Lowering(signature, signatures, pack, names, taken, out).run()
        except Refused as error:
            refused.append(error.diagnostic)
            continue
        decl = signature.decl
        if "means" in decl or signature.note_source is not None:
            line, column = signature.site.place(f"{signature.at}/means" if "means" in decl else signature.at)
            lowered.notes[name] = Note(decl.get("means"), signature.note_source, signature.site.file, line, column,
                                       f"{signature.at}/means")
            lowered.note_owners[name] = signature.module.pack
        if signature.property is not None:
            lowered.properties[name] = (signature.kind, signature.property)
    if refused:
        raise CompileError("\n".join(map(str, refused)), refused)
    sources = []
    for module in found:
        stmts, columns = statements.get(module.id, ([], []))
        if stmts:
            site = sites[module.id]
            sources.append(rules_dl.NativeSource(module.pack, module.file.stem, site.file, site.text,
                                                 tuple(stmts), tuple(columns)))
    lowered.sources = tuple(sources)
    return lowered


def _derivations(form: dict):
    """(pointer, declaration, owner) for each derivation of a rezono 1 module that lowers here; the owner is the
    `kind` or `extend` declaration of a property and None for a module-level declaration."""
    for index, decl in enumerate(form["module"]["decls"]):
        if not isinstance(decl, dict):
            continue
        if is_module_derived(decl):
            yield f"/decls/{index}", decl, None
        elif ("kind" in decl or "extend" in decl) and isinstance(decl.get("derived"), list):
            for position, derived in enumerate(decl["derived"]):
                if is_derivation(form, derived):
                    yield f"/decls/{index}/derived/{position}", derived, decl


def _enum_name(site: Site, names: modules.Names, pack, module: modules.Module, at: str, text: object) -> str | None:
    if not isinstance(text, str) or text in SCALARS:
        return None
    engine = _resolve_schema_name(site, names, module, at, text)
    return engine if engine in pack.enums else None


def _type(site: Site, names: modules.Names, pack, module: modules.Module, at: str, text: object) -> tuple:
    if not isinstance(text, str):
        site.refuse(at, "a derivation needs a type")
    if text in SCALARS:
        return "scalar", SCALARS[text]
    engine = _resolve_schema_name(site, names, module, at, text)
    if engine in pack.kinds:
        return "kind", engine
    if engine in pack.enums:
        return "scalar", "string"
    site.refuse(at, f"the type {text} has no rule column in rezono.rules/2 yet")


def ir_type(pack, typ: tuple) -> str:
    if typ[0] == "kind":
        return rules_dl.SQL.get(pack.kinds[pack.root(typ[1])].id_type) or "string"
    return typ[1]


def validate_note(site: Site, at: str, decl: Mapping[str, object]) -> tuple[str | None, str | None]:
    """Validate optional `means` and `source` note members as strings and return `(means, source)`."""
    for field_name, label in (("means", "sentence"), ("source", "source")):
        if field_name in decl and not isinstance(decl[field_name], str):
            site.refuse(f"{at}/{field_name}", f"a {label} is text", "R000")
    means = decl.get("means")
    source = decl.get("source")
    return means if isinstance(means, str) else None, source if isinstance(source, str) else None


VERSION_FIELDS = frozenset({"version", "replaces", "valid", "known", "value", "source", "definitions"})


def _validate_versions(site: Site, at: str, versions: object) -> None:
    if not isinstance(versions, list) or not versions:
        site.refuse(f"{at}/versions", "versions must be a non-empty list")
    by_number: dict[str, list[int]] = {}
    for index, ver in enumerate(versions):
        vat = f"{at}/versions/{index}"
        if not isinstance(ver, dict):
            site.refuse(vat, "a version must be an object")
        if extra := sorted(set(ver) - VERSION_FIELDS):
            site.refuse(vat, f"`{extra[0]}` on a rezono 1 version is not lowered yet")
        if "definitions" in ver:
            site.refuse(vat, "`definitions` on a rezono 1 version is not lowered yet")
        if not isinstance(ver.get("version"), str) or not ver["version"]:
            site.refuse(vat, "a version needs a version number")
        if not isinstance(ver.get("value"), dict):
            site.refuse(f"{vat}/value", "a version needs a `=` value")
        if "valid" in ver:
            valid = ver["valid"]
            if (not isinstance(valid, list) or len(valid) not in (1, 2)
                    or not all(isinstance(d, str) and rules.iso_date(d) for d in valid)
                    or (len(valid) == 2 and valid[0] >= valid[1])):
                site.refuse(vat, "version `valid` must be a valid date range")
        if "known" in ver and (not isinstance(ver["known"], str) or not rules.iso_date(ver["known"])):
            site.refuse(vat, "version `known` must be an ISO date")
        if "source" in ver and (not isinstance(ver["source"], str) or not ver["source"]):
            site.refuse(vat, "a version source must be non-empty text", "R000")
        by_number.setdefault(ver["version"], []).append(index)
    # Check replaces targets and acyclicity (R021).
    state = [0] * len(versions)
    for start in range(len(versions)):
        if state[start]:
            continue
        stack = [start]
        while stack:
            node = stack[-1]
            if state[node] == 0:
                state[node] = 1
                rep = versions[node].get("replaces")
                if rep is not None:
                    if not isinstance(rep, str) or rep not in by_number:
                        site.refuse(f"{at}/versions/{node}", f"version replaces unknown version {rep!r}", "R021")
                    for nxt in by_number[rep]:
                        if state[nxt] == 1:
                            site.refuse(f"{at}/versions/{node}", f"version {versions[node]['version']} replaces cycle", "R021")
                        if state[nxt] == 0:
                            stack.append(nxt)
            else:
                state[node] = 2
                stack.pop()


def _validate_unless(site: Site, at: str, blocks: object) -> None:
    if not isinstance(blocks, list) or not blocks:
        site.refuse(f"{at}/unless", "unless must be a non-empty list of blocks")
    for bi, block in enumerate(blocks):
        bat = f"{at}/unless/{bi}"
        if not isinstance(block, list) or not block:
            site.refuse(bat, "an unless block must be a non-empty list of clauses")
        for ci, clause in enumerate(block):
            cat = f"{bat}/{ci}"
            if not isinstance(clause, dict):
                site.refuse(cat, "an unless clause must be an object")
            if extra := sorted(set(clause) - {"when", "then", "source"}):
                site.refuse(cat, f"`{extra[0]}` in an unless clause is not lowered yet")
            if not isinstance(clause.get("when"), dict):
                site.refuse(f"{cat}/when", "an unless clause needs a `when` expression")
            if not isinstance(clause.get("then"), dict):
                site.refuse(f"{cat}/then", "an unless clause needs a `then` expression")
            if "source" in clause and (not isinstance(clause["source"], str) or not clause["source"]):
                site.refuse(cat, "an unless source must be non-empty text", "R000")


def _validate_table(site: Site, at: str, table: object, card: object) -> None:
    if not isinstance(table, dict):
        site.refuse(f"{at}/table", "a table must be an object")
    policy = table.get("table")
    if policy == "priority":
        site.refuse(f"{at}/table", "`table priority` is removed in `rezono 1` (R028); use `table first` instead", "R028")
    if policy == "collect":
        site.refuse(f"{at}/table", "`table collect` on a rezono 1 derivation is not lowered yet")
    if policy not in ("unique", "first"):
        site.refuse(f"{at}/table", f"a table `{policy}` is not lowered yet")
    if card is not None:
        site.refuse(at, f"a table derivation with cardinality `{card}` is not lowered yet")
    inputs = table.get("inputs")
    rows = table.get("rows")
    if not isinstance(inputs, list) or not inputs:
        site.refuse(f"{at}/table", "a table needs input columns")
    if not isinstance(rows, list) or not rows:
        site.refuse(f"{at}/table", "a table needs at least one row")
    for ri, row in enumerate(rows):
        rat = f"{at}/table/rows/{ri}"
        if (not isinstance(row, dict) or not isinstance(row.get("tests"), list)
                or len(row["tests"]) != len(inputs) or not isinstance(row.get("value"), dict)):
            site.refuse(rat, f"table row needs {len(inputs)} cells and a value")


def _signature(site: Site, module: modules.Module, names: modules.Names, pack, at: str, decl: dict,
               owner: dict | None, as_of: tuple[str, str] | None = None) -> Signature:
    allowed = ({"derived", "type", "card", "value", "means", "source", "unit", "unless", "versions", "table", "totality"}
               | ({"params", "over"} if owner is None else set()))
    if extra := sorted(set(decl) - allowed):
        site.refuse(at, f"`{extra[0]}` on a rezono 1 derivation is not lowered yet")
    if "table" in decl and any(k in decl for k in ("value", "versions", "unless")):
        site.refuse(at, "a `table` stands alone under its derived value")
    if "value" in decl and "versions" in decl:
        site.refuse(at, "a derivation cannot declare both `=` and `versions`")
    if not any(k in decl for k in ("value", "versions", "table", "unless")):
        site.refuse(at, "a derivation needs `=`, `versions`, `unless` or `table`")
    if "unit" in decl and (not isinstance(decl["unit"], str) or not decl["unit"]):
        site.refuse(f"{at}/unit", "unit must be non-empty text")
    card = decl.get("card")
    if card not in (None, "?"):
        site.refuse(at, f"a set-valued derivation `{decl.get('type')}{card}` is not lowered yet")
    if "versions" in decl:
        _validate_versions(site, at, decl["versions"])
    if "unless" in decl:
        _validate_unless(site, at, decl["unless"])
    if "table" in decl:
        _validate_table(site, at, decl["table"], card)
    result_type = _type(site, names, pack, module, at, decl.get("type"))
    boolean = result_type == ("scalar", "boolean") and card is None
    if "totality" in decl:
        if decl["totality"] != "total":
            site.refuse(at, f"invalid totality {decl['totality']!r}")
        if boolean:
            site.refuse(at, "`total` applies to functional derivations, not Bool sets")
    if owner is None:
        key = []
        for index, param in enumerate(decl.get("params") or []):
            key.append((param["name"], _type(site, names, pack, module, f"{at}/params/{index}", param.get("type"))))
        if not key:
            site.refuse(at, "a module-level derivation needs parameters")
        signature = Signature(decl["derived"], at, decl, site, module, key, "set" if boolean else "functional")
        if not boolean:
            over = decl.get("over")
            if not isinstance(over, dict):
                site.refuse(at, "a functional derivation needs its closed domain: `over <relation>(...)`")
            if list(over.get("args") or ()) != [name for name, _ in key]:
                site.refuse(f"{at}/over", "the arguments of `over` are the parameters, in their order")
            signature.domain = over["relation"]
    else:
        kind_name = owner.get("kind") or owner.get("extend")
        kind = _resolve_schema_name(site, names, module, at, kind_name) if isinstance(kind_name, str) else None
        if kind not in pack.kinds:
            site.refuse(at, f"the kind {kind_name} is not a kind of the pack")
        binder = owner.get("binder")
        subject = kind if kind not in ("state", "reason", "value") else "subject"
        key = [(binder or "it", ("kind", kind))]
        signature = Signature(f"{kind}_{decl['derived']}", at, decl, site, module, key,
                              "set" if boolean else "functional", kind=kind, property=decl["derived"],
                              binder=binder or "it")
        signature.domain = None if boolean else kind
        signature.key_column = subject
    if not boolean:
        signature.value_type = ir_type(pack, result_type)
        signature.optional = card == "?"
    signature.enum_type = _enum_name(site, names, pack, module, at, decl.get("type"))
    _, signature.note_source = validate_note(site, at, decl)
    signature.as_of = as_of
    return signature


def _opened(statements: dict, pack) -> set[str]:
    """The open tables of the pack and the sets lowered so far that read one positively."""
    opened = {name for name, world in rules_dl.base_worlds(pack).items() if world == "open"}
    rules = [s for stmts, _ in statements.values() for s in stmts if s[0] == "rule"]
    changed = True
    while changed:
        changed = False
        for _, (head, _, _), body, _ in rules:
            if head not in opened and any(item[0] == "lit" and item[1] == "positive" and item[2][0] in opened
                                          for item in body):
                opened.add(head)
                changed = True
    return opened


def _open_domain(name: str, signature: Signature) -> Diagnostic:
    """`functional_open_domain` (language-rezono-1.md section 2): a functional derivation over an open kind or set."""
    line, column = signature.site.place(signature.at)
    what = (f"its kind {signature.kind} is open" if signature.property is not None
            else f"its domain {signature.domain} reads an open world")
    message = (f"functional_open_domain: {name} has no finite closed domain, because {what}; a functional "
               "derivation needs a closed one (language-rezono-1.md section 2)")
    return Diagnostic("R004", message, f"{signature.site.file}#{signature.at}", (signature.site.file, line, column))


@dataclass
class Member:
    """The rows of a collection: the elements of a kind, or the tuples of a relation."""

    terms: list[tuple]  # its columns, as rule terms
    literal: tuple  # the positive literal that ranges over it
    kind: str | None  # the kind of an element; None for a tuple
    columns: dict[str, tuple[int, tuple]]  # a tuple's column -> (position, type)
    pred: list[tuple[str, dict]]  # (pointer, atom) of its conjunctive predicate


@dataclass(frozen=True)
class BoolEval:
    """Four-valued evaluation of a Boolean condition over the derivation's key."""

    t_rel: str | None  # (key...) where true
    f_rel: str | None  # (key...) where false
    s_rel: str | None  # (key..., state, reason) where non-known
    t_all: bool = False
    f_all: bool = False


@dataclass(frozen=True)
class ValBranch:
    """One known-value branch in a rule body."""

    lits: tuple[tuple, ...]
    assigns: tuple[tuple, ...]
    conds: tuple[tuple, ...]
    term: tuple


@dataclass(frozen=True)
class ValEval:
    """Four-valued evaluation of a value expression over the derivation's key."""

    typ: str
    branches: tuple[ValBranch, ...]
    state_rel: str | None  # (key..., state, reason) where non-known


class Lowering:
    """The statements of one derivation."""

    def __init__(self, signature: Signature, signatures: Mapping[str, Signature], pack, names: modules.Names,
                 taken: set[str], out: tuple[list, list]):
        self.sig, self.signatures, self.pack, self.names = signature, signatures, pack, names
        self.site = signature.site
        self.taken, (self.statements, self.columns) = taken, out
        self.line, self.column = self.site.place(signature.at)
        self.used = {name for name, _ in signature.key}
        self.env = dict(signature.key)
        unaliased, aliases = _use_scope(signature.module)
        self._aliases = aliases
        self._used_packs = {signature.module.pack, *unaliased, *aliases.values()}
        self._declared_helpers: set[str] = set()
        self._helper_seq = 0
        self._has_cache: dict[str, str] = {}
        self._key_cols = [(self.sig.key_column or name, ir_type(self.pack, typ)) for name, typ in self.sig.key]
        self._state_cols = self._key_cols + [("state", "string"), ("reason", "string")]

    # -- output ---------------------------------------------------------------------------------------------------

    def fresh(self, base: str = "v") -> str:
        index = 1
        while (name := f"{base}{index}") in self.used:
            index += 1
        self.used.add(name)
        return name

    def helper(self, suffix: str) -> str:
        name = f"{self.sig.relation}_{suffix}"
        if name in self.taken:
            self.site.refuse(self.sig.at, f"{name} is already a relation; it is the name of a relation this "
                                          f"derivation needs")
        self.taken.add(name)
        return name

    def next_helper(self, tag: str) -> str:
        self._helper_seq += 1
        return self.helper(f"h{self._helper_seq}_{tag}")

    def add_helper(self, name: str, columns: list[tuple[str, str]], terms: list[tuple], body: list[tuple]) -> None:
        if name not in self._declared_helpers:
            self.declare(name, columns)
            self._declared_helpers.add(name)
        self.rule(name, terms, body)

    def helper_or_none(self, name: str) -> str | None:
        return name if name in self._declared_helpers else None

    def declare(self, name: str, columns: list[tuple[str, str]]) -> None:
        self.statements.append(("decl", name, columns, self.line, None, False, False, None, False, None, False))

    def rule(self, head: str, terms: list[tuple], body: list[tuple]) -> None:
        self.statements.append(("rule", (head, terms, self.line), body, self.line))
        self.columns.append(self.column)

    def lit(self, relation: str, terms: list[tuple], positive: bool = True) -> tuple:
        return "lit", "positive" if positive else "negative", (relation, terms, self.line)

    def key_terms(self) -> list[tuple]:
        return [("var", name) for name, _ in self.sig.key]

    def domain(self) -> list[tuple]:
        """The positive literals that range over the key: the subject's kind, or the `over` relation."""
        if self.sig.property is not None:
            return [self.lit(self.sig.kind, self.key_terms())]
        if self.sig.result == "functional":
            return [self.lit(self.sig.domain, self.key_terms())]
        return [self.lit(typ[1], [("var", name)]) for name, typ in self.sig.key if typ[0] == "kind"]

    # -- the derivation -------------------------------------------------------------------------------------------

    def select_version(self, at: str, versions: list[dict]) -> tuple[str, tuple[int, dict] | None]:
        """Pick the active version against the module's `as of` (Rule 4a/4b/4c in v0.md §5a)."""
        valid_at, known_at = self.sig.as_of if self.sig.as_of is not None else (None, None)

        def matches(ver: dict) -> bool:
            if "known" in ver and known_at is not None and ver["known"] > known_at:
                return False
            if "valid" in ver:
                if valid_at is None:
                    return False
                bounds = ver["valid"]
                if valid_at < bounds[0]:
                    return False
                if len(bounds) == 2 and valid_at >= bounds[1]:
                    return False
            return True

        active = [(idx, ver) for idx, ver in enumerate(versions) if matches(ver)]
        if not active:
            return "none", None
        active_nums = {ver["version"] for _, ver in active}
        replaced = {ver["replaces"] for _, ver in active if ver.get("replaces") in active_nums}
        remaining = [(idx, ver) for idx, ver in active if ver["version"] not in replaced] or active
        max_known = max(ver.get("known", "") for _, ver in remaining)
        latest = [(idx, ver) for idx, ver in remaining if ver.get("known", "") == max_known]
        if len(latest) > 1:
            return "overlap", None
        return "one", latest[0]

    def sentinel_term(self, at: str) -> tuple:
        if self.sig.value_type not in SENTINEL and self.sig.value_type != "integer":
            self.site.refuse(at, f"a {self.sig.value_type} derivation that can be undecided is not lowered yet")
        return ("const", "0", "integer") if self.sig.value_type == "integer" else SENTINEL[self.sig.value_type]

    def emit_state_rule(self, at: str, state_rel: str) -> None:
        if self.sig.value_type not in SENTINEL and self.sig.value_type != "integer":
            self.site.refuse(at, f"a {self.sig.value_type} derivation that can be undecided is not lowered yet")
        total = self.fresh("n")
        state_v, reason_v = ("var", self.fresh("st")), ("var", self.fresh("rsn"))
        sentinel = ("var", total) if self.sig.value_type == "integer" else SENTINEL[self.sig.value_type]
        self.statements.append((
            "rule", (self.sig.relation, self.key_terms() + [sentinel], self.line),
            self.domain() + [
                self.lit(state_rel, self.key_terms() + [state_v, reason_v]),
                ("agg", total, "count", None,
                 (state_rel, self.key_terms() + [("wild",), ("wild",)], self.line)),
            ],
            self.line,
        ))
        self.columns.append(self.column)

    def emit_functional(self, at: str, meta: dict, branches: tuple[ValBranch, ...], state_rel: str | None) -> None:
        if self.sig.decl.get("totality") == "total":
            meta["conflict_policy"] = "block"
        self.statements.append(("functional", self.sig.relation, self._key_cols, self.line, meta))
        if not branches and state_rel is None:
            self.rule(self.sig.relation, self.key_terms() + [self.sentinel_term(at)],
                      self.domain() + [("cmp", "eq", ("const", "1", "integer"), ("const", "0", "integer"))])
            return
        for branch in branches:
            self.rule(self.sig.relation, self.key_terms() + [branch.term],
                      self.domain() + list(branch.lits) + list(branch.assigns) + list(branch.conds))
        if state_rel is not None:
            self.emit_state_rule(at, state_rel)

    def run(self) -> None:
        sig, decl = self.sig, self.sig.decl
        key_columns = self._key_cols
        value_at = f"{sig.at}/value"
        value = decl.get("value")
        if "versions" in decl:
            status, picked = self.select_version(sig.at, decl["versions"])
            if sig.result == "set":
                if "table" in decl or "unless" in decl:
                    self.site.refuse(sig.at, "`table` and `unless` on a Bool set derivation are not lowered yet")
                self.declare(sig.relation, key_columns)
                if status == "one":
                    ver_idx, ver = picked
                    for alternative in self.alternatives(f"{sig.at}/versions/{ver_idx}/value", ver["value"]):
                        self.rule(sig.relation, self.key_terms(), self.domain() + alternative)
                elif status == "none":
                    self.rule(sig.relation, self.key_terms(),
                              self.domain() + [("cmp", "eq", ("const", "1", "integer"), ("const", "0", "integer"))])
                elif status == "overlap":
                    self.site.refuse(f"{sig.at}/versions", "versions overlap on a Bool set derivation")
                return
            self._check_functional_domain()
            meta = {"domain": sig.domain, "value": {"name": "value", "type": sig.value_type},
                    "conflict_policy": "publish", "empty_state": "unknown", "empty_reason": "no_version_applies"}
            if status == "none":
                if "unless" in decl:
                    self.lower_unless(sig.at, None, decl["unless"], meta, empty_reason="no_version_applies")
                else:
                    self.emit_functional(sig.at, meta, (), None)
                return
            if status == "overlap":
                meta["conflict_policy"] = "block"
                overlap = self.next_helper("overlap")
                self.add_helper(overlap, self._state_cols, self.key_terms() + [INVALID, VERSIONS_OVERLAP],
                                self.domain())
                self.emit_functional(sig.at, meta, (), overlap)
                return
            ver_idx, ver = picked
            if sig.note_source is None and "source" in ver:
                sig.note_source = ver["source"]
            value_at = f"{sig.at}/versions/{ver_idx}/value"
            value = ver["value"]
        if sig.result == "set":
            if "table" in decl or "unless" in decl:
                self.site.refuse(sig.at, "`table` and `unless` on a Bool set derivation are not lowered yet")
            self.declare(sig.relation, key_columns)
            for alternative in self.alternatives(value_at, value):
                self.rule(sig.relation, self.key_terms(), self.domain() + alternative)
            return
        self._check_functional_domain()
        meta = {"domain": sig.domain, "value": {"name": "value", "type": sig.value_type}, "conflict_policy": "publish"}
        if "table" in decl:
            self.lower_table(f"{sig.at}/table", decl["table"], meta)
            return
        if "unless" in decl:
            fallback = (value_at, value) if value is not None else None
            self.lower_unless(sig.at, fallback, decl["unless"], meta)
            return
        if set(value) == {"agg"} and isinstance(value["agg"], list) and value["agg"][:1] == ["one"]:
            meta |= {"empty_state": "not_applicable" if sig.optional else "unknown", "empty_reason": "no_match"}
            if decl.get("totality") == "total":
                meta["conflict_policy"] = "block"
            self.statements.append(("functional", sig.relation, key_columns, self.line, meta))
            self.one(value_at, value["agg"])
        elif set(value) == {"agg"} and isinstance(value["agg"], list) and value["agg"][:1] == ["count"]:
            if sig.value_type != "integer":
                self.site.refuse(value_at, "a count is a whole number: declare the derivation `Int`", "R003")
            if decl.get("totality") == "total":
                meta["conflict_policy"] = "block"
            self.statements.append(("functional", sig.relation, key_columns, self.line, meta))
            self.count(value_at, value["agg"])
        elif (inline := self.try_inline_value(value_at, value)) is not None:
            lits, assigns, conds, term, missing, typ = inline
            if typ != sig.value_type:
                self.site.refuse(value_at, f"expression has type {typ}, expected {sig.value_type}", "R003")
            meta |= {"empty_state": "not_applicable" if missing == "not_applicable" else "unknown",
                     "empty_reason": "no_value"}
            self.emit_functional(value_at, meta, (ValBranch(tuple(lits), tuple(assigns), tuple(conds), term),), None)
        else:
            evaluated = self.eval_value(value_at, value)
            if evaluated.typ != sig.value_type:
                self.site.refuse(value_at, f"expression has type {evaluated.typ}, expected {sig.value_type}", "R003")
            meta |= {"empty_state": "not_applicable" if sig.optional else "unknown", "empty_reason": "no_value"}
            self.emit_functional(value_at, meta, evaluated.branches, evaluated.state_rel)

    def _check_functional_domain(self) -> None:
        sig = self.sig
        if sig.domain not in self.pack.kinds and sig.domain not in self.signatures and sig.property is None:
            self.site.refuse(f"{sig.at}/over", f"`over` names a set this pack or a used pack derives in rezono 1, not {sig.domain}")
        if sig.domain in self.signatures and self.signatures[sig.domain].result != "set":
            self.site.refuse(f"{sig.at}/over", f"the domain {sig.domain} is a Bool set, not a functional derivation")

    # -- inline fast path & 4-state expression lowering -----------------------------------------------------------

    def _prop_sig(self, kind: str, name: str) -> Signature | None:
        while kind is not None:
            if (sig := self.signatures.get(f"{kind}_{name}")) is not None and sig.module.pack in self._used_packs:
                return sig
            kind = self.pack.kinds[kind].parent
        return None

    def _enum_literal(self, name: str) -> tuple | None:
        if self.sig.enum_type is not None and name in self.pack.enums[self.sig.enum_type]:
            return "const", name, "string"
        matches = [e for e, vals in self.pack.enums.items() if name in vals]
        if len(matches) == 1:
            return "const", name, "string"
        return None

    def try_inline_value(self, at: str, node: dict) -> tuple[list, list, list, tuple, str | None, str] | None:
        """Single-rule inline lowering when the expression is a simple literal, slot path, or integer arithmetic
        whose missing slots (if any) all share the same missingness (`unknown` vs `not_applicable`)."""
        if not isinstance(node, dict) or len(node) != 1:
            return None
        key = next(iter(node))
        if key == "lit":
            term = self.literal(at, node["lit"])
            return [], [], [], term, None, term[2]
        if key == "path":
            path = node["path"]
            if len(path) == 1 and path[0] in self.env:
                return [], [], [], ("var", path[0]), None, ir_type(self.pack, self.env[path[0]])
            if len(path) == 1:
                if self.sig.binder == "it" and path[0] != "it" and self.slot(at, self.env["it"][1], path[0]) is not None:
                    slot = self.slot(at, self.env["it"][1], path[0])
                    if slot.multivalued or slot.world == "open":
                        return None
                    lits, term, optional = self.path(at, path)
                    return lits, [], [], term, ("not_applicable" if optional else "unknown"), ir_type(self.pack, self.slot_type(slot))
                if (enum_term := self._enum_literal(path[0])) is not None:
                    return [], [], [], enum_term, None, "string"
                return None
            head = path[0]
            if head not in self.env:
                return None
            typ = self.env[head]
            opt_flags: set[bool] = set()
            for part in path[1:]:
                if typ[0] != "kind":
                    return None
                slot = self.slot(at, typ[1], part)
                if slot is None or slot.multivalued or slot.world == "open":
                    return None
                opt_flags.add(not slot.required)
                typ = self.slot_type(slot)
            if len(opt_flags) > 1:
                return None
            lits, term, optional = self.path(at, path)
            return lits, [], [], term, ("not_applicable" if optional else "unknown"), ir_type(self.pack, typ)
        if key == "neg":
            inner = node["neg"]
            if isinstance(inner, dict) and set(inner) == {"lit"}:
                term = self.literal(f"{at}/neg", inner["lit"])
                if term[2] != "integer":
                    self.site.refuse(at, "unary `-` requires an integer", "R003")
                return [], [], [], ("const", str(-int(term[1])), "integer"), None, "integer"
            sub = self.try_inline_value(f"{at}/neg", inner)
            if sub is None:
                return None
            lits, assigns, conds, term, missing, typ = sub
            if typ != "integer":
                self.site.refuse(at, "unary `-` requires an integer", "R003")
            res = self.fresh()
            return lits, assigns + [("arith", res, "sub", ("const", "0", "integer"), term)], conds, ("var", res), missing, "integer"
        if key == "arith":
            op, left, right = node["arith"]
            if op not in ARITH:
                return None
            sl = self.try_inline_value(f"{at}/arith/1", left)
            sr = self.try_inline_value(f"{at}/arith/2", right)
            if sl is None or sr is None:
                return None
            ll, al, cl, tl, ml, typ_l = sl
            lr, ar, cr, tr, mr, typ_r = sr
            if typ_l != "integer" or typ_r != "integer":
                self.site.refuse(at, f"arithmetic `{op}` requires integer operands", "R003")
            if ml is not None and mr is not None and ml != mr:
                return None
            if op == "/":
                if tr[0] != "const" or tr[2] != "integer" or int(tr[1]) == 0:
                    return None
            res = self.fresh()
            missing = ml or mr
            return ll + lr, al + ar + [("arith", res, ARITH[op], tl, tr)], cl + cr, ("var", res), missing, "integer"
        return None

    def _has_slot(self, kind: str, slot) -> str:
        if slot.table not in self._has_cache:
            name = self.next_helper(f"has_{slot.name}")
            elem = ("var", self.fresh("e"))
            self.add_helper(name, [("element", ir_type(self.pack, ("kind", kind)))], [elem],
                            [self.lit(kind, [elem]), self.lit(slot.table, [elem, ("var", self.fresh())])])
            self._has_cache[slot.table] = name
        return self._has_cache[slot.table]

    def _undecided_keys(self, state_rel: str | None) -> str | None:
        """Keys in `state_rel` whose state is `unknown` or `invalid`."""
        if state_rel is None:
            return None
        und = self.next_helper("und")
        rsn = ("var", self.fresh("rsn"))
        for st in (UNKNOWN, INVALID):
            self.add_helper(und, self._key_cols, self.key_terms(),
                            self.domain() + [self.lit(state_rel, self.key_terms() + [st, rsn])])
        return self.helper_or_none(und)

    def _any_keys(self, state_rel: str | None) -> str | None:
        if state_rel is None:
            return None
        any_rel = self.next_helper("any")
        st, rsn = ("var", self.fresh("st")), ("var", self.fresh("rsn"))
        self.add_helper(any_rel, self._key_cols, self.key_terms(),
                        self.domain() + [self.lit(state_rel, self.key_terms() + [st, rsn])])
        return self.helper_or_none(any_rel)

    def combine_states(self, sources: list[str | None], *, exclude: tuple[str, ...] = ()) -> str | None:
        """Combine multiple `(key..., state, reason)` relations with priority `invalid > unknown > not_applicable`."""
        rels = [s for s in sources if s is not None]
        if not rels:
            return None
        if len(rels) == 1 and not exclude:
            return rels[0]
        has_inv = self.next_helper("has_inv")
        has_unk = self.next_helper("has_unk")
        for s in rels:
            self.add_helper(has_inv, self._key_cols, self.key_terms(),
                            self.domain() + [self.lit(s, self.key_terms() + [INVALID, ("var", self.fresh("r"))])])
            self.add_helper(has_unk, self._key_cols, self.key_terms(),
                            self.domain() + [self.lit(s, self.key_terms() + [UNKNOWN, ("var", self.fresh("r"))])])
        best = self.next_helper("state")
        for s in rels:
            rsn = ("var", self.fresh("r"))
            if "invalid" not in exclude:
                self.add_helper(best, self._state_cols, self.key_terms() + [INVALID, rsn],
                                self.domain() + [self.lit(s, self.key_terms() + [INVALID, rsn])])
            if "unknown" not in exclude:
                self.add_helper(best, self._state_cols, self.key_terms() + [UNKNOWN, rsn],
                                self.domain() + [self.lit(s, self.key_terms() + [UNKNOWN, rsn]),
                                                 self.lit(has_inv, self.key_terms(), False)])
            if "not_applicable" not in exclude:
                self.add_helper(best, self._state_cols, self.key_terms() + [NOT_APPLICABLE, rsn],
                                self.domain() + [self.lit(s, self.key_terms() + [NOT_APPLICABLE, rsn]),
                                                 self.lit(has_inv, self.key_terms(), False),
                                                 self.lit(has_unk, self.key_terms(), False)])
        return self.helper_or_none(best)

    def gate_state(self, state_rel: str | None, guard_lits: list[tuple]) -> str | None:
        if state_rel is None:
            return None
        if not guard_lits:
            return state_rel
        gated = self.next_helper("gated")
        st, rsn = ("var", self.fresh("st")), ("var", self.fresh("rsn"))
        self.add_helper(gated, self._state_cols, self.key_terms() + [st, rsn],
                        self.domain() + [self.lit(state_rel, self.key_terms() + [st, rsn])] + guard_lits)
        return self.helper_or_none(gated)

    def _materialize_val(self, val: ValEval) -> ValBranch | None:
        if not val.branches:
            return None
        if len(val.branches) == 1:
            return val.branches[0]
        rel = self.next_helper("val")
        cols = self._key_cols + [("value", val.typ)]
        for branch in val.branches:
            self.add_helper(rel, cols, self.key_terms() + [branch.term],
                            self.domain() + list(branch.lits) + list(branch.assigns) + list(branch.conds))
        v = ("var", self.fresh())
        return ValBranch((self.lit(rel, self.key_terms() + [v]),), (), (), v)

    def eval_path_val(self, at: str, path: list) -> ValEval:
        head = path[0]
        if head not in self.env:
            if (self.sig.binder == "it" and head != "it"
                    and (self.slot(at, self.env["it"][1], head) is not None
                         or self._prop_sig(self.env["it"][1], head) is not None)):
                path, head = ["it", *path], "it"
            elif len(path) == 1 and (enum_term := self._enum_literal(head)) is not None:
                return ValEval("string", (ValBranch((), (), (), enum_term),), None)
        if head not in self.env:
            self.site.refuse(at, f"{head} is not a variable here", "R001")
        if len(path) == 1:
            return ValEval(ir_type(self.pack, self.env[head]), (ValBranch((), (), (), ("var", head)),), None)
        lits: list[tuple] = []
        term: tuple = ("var", head)
        typ = self.env[head]
        state_rel_name = self.next_helper("path_st")
        for index, name in enumerate(path[1:], 1):
            if typ[0] != "kind":
                self.site.refuse(at, f"{'.'.join(path[:index])} is no element, so it has no slot {name}", "R003")
            slot = self.slot(at, typ[1], name)
            if slot is not None:
                if slot.multivalued:
                    self.site.refuse(at, f"{'.'.join(path[:index + 1])} is a set; read it with a method such as "
                                         "`.count()` or `.one()`", "R005")
                if slot.world == "open":
                    self.site.refuse(at, f"{slot.table} is open, so a missing value is unknown; it is not lowered yet",
                                     "R004")
                has_name = self._has_slot(typ[1], slot)
                miss_state = NOT_APPLICABLE if not slot.required else UNKNOWN
                self.add_helper(state_rel_name, self._state_cols, self.key_terms() + [miss_state, NO_VALUE],
                                self.domain() + list(lits) + [self.lit(has_name, [term], False)])
                nxt = ("var", self.fresh())
                lits.append(self.lit(slot.table, [term, nxt]))
                term, typ = nxt, self.slot_type(slot)
                continue
            prop = self._prop_sig(typ[1], name)
            if prop is not None and prop.result == "functional":
                if prop.relation == self.sig.relation:
                    self.site.refuse(at, f"{prop.relation} cannot read itself recursively", "R043")
                val_var = ("var", self.fresh())
                for st_lit in (NOT_APPLICABLE, UNKNOWN, INVALID):
                    rsn_v = ("var", self.fresh("rsn"))
                    self.add_helper(state_rel_name, self._state_cols, self.key_terms() + [st_lit, rsn_v],
                                    self.domain() + list(lits)
                                    + [self.lit(prop.relation, [term, st_lit, rsn_v, ("var", self.fresh())])])
                lits.append(self.lit(prop.relation, [term, KNOWN, EMPTY, val_var]))
                term = val_var
                typ = ("scalar", prop.value_type)
                continue
            self.site.refuse(at, f"{'.'.join(path[:index])} has no slot {name} lowered here", "R001")
        return ValEval(ir_type(self.pack, typ), (ValBranch(tuple(lits), (), (), term),),
                       self.helper_or_none(state_rel_name))

    def eval_value(self, at: str, node: dict) -> ValEval:
        if not isinstance(node, dict) or len(node) != 1:
            self.site.refuse(at, "expression must be a single-key object")
        key = next(iter(node))
        if key == "lit":
            term = self.literal(at, node["lit"])
            return ValEval(term[2], (ValBranch((), (), (), term),), None)
        if key == "path":
            return self.eval_path_val(at, node["path"])
        if key == "neg":
            inner = node["neg"]
            if isinstance(inner, dict) and set(inner) == {"lit"}:
                term = self.literal(f"{at}/neg", inner["lit"])
                if term[2] != "integer":
                    self.site.refuse(at, "unary `-` requires an integer", "R003")
                return ValEval("integer", (ValBranch((), (), (), ("const", str(-int(term[1])), "integer")),), None)
            sub = self.eval_value(f"{at}/neg", inner)
            if sub.typ != "integer":
                self.site.refuse(at, "unary `-` requires an integer", "R003")
            b = self._materialize_val(sub)
            if b is None:
                return sub
            res = self.fresh()
            return ValEval("integer", (ValBranch(b.lits, b.assigns + (("arith", res, "sub", ("const", "0", "integer"), b.term),),
                                                 b.conds, ("var", res)),), sub.state_rel)
        if key == "arith":
            op, left, right = node["arith"]
            if op not in ARITH:
                self.site.refuse(at, f"arithmetic operator {op!r} is not lowered")
            vl = self.eval_value(f"{at}/arith/1", left)
            vr = self.eval_value(f"{at}/arith/2", right)
            if vl.typ != "integer" or vr.typ != "integer":
                self.site.refuse(at, f"arithmetic `{op}` requires integer operands", "R003")
            bl, br = self._materialize_val(vl), self._materialize_val(vr)
            st_rel = self.combine_states([vl.state_rel, vr.state_rel])
            if bl is None or br is None:
                return ValEval("integer", (), st_rel)
            if op == "/" and (br.term[0] != "const" or br.term[2] != "integer" or int(br.term[1]) == 0):
                self.site.refuse(f"{at}/arith/2", "division requires a non-zero integer constant divisor")
            res = self.fresh()
            branch = ValBranch(
                bl.lits + br.lits,
                bl.assigns + br.assigns + (("arith", res, ARITH[op], bl.term, br.term),),
                bl.conds + br.conds,
                ("var", res),
            )
            return ValEval("integer", (branch,), st_rel)
        if key == "when":
            cond_node, then_node, else_node = node["when"]
            cond = self.eval_bool(f"{at}/when/0", cond_node)
            vt = self.eval_value(f"{at}/when/1", then_node)
            ve = self.eval_value(f"{at}/when/2", else_node)
            if vt.typ != ve.typ:
                self.site.refuse(at, f"`when` branches have different types ({vt.typ} vs {ve.typ})", "R003")
            branches: list[ValBranch] = []
            states: list[str | None] = [cond.s_rel]
            if cond.t_all:
                branches.extend(vt.branches)
                states.append(vt.state_rel)
            elif cond.t_rel is not None:
                t_lit = self.lit(cond.t_rel, self.key_terms())
                branches.extend(ValBranch((t_lit,) + b.lits, b.assigns, b.conds, b.term) for b in vt.branches)
                states.append(self.gate_state(vt.state_rel, [t_lit]))
            if cond.f_all:
                branches.extend(ve.branches)
                states.append(ve.state_rel)
            elif cond.f_rel is not None:
                f_lit = self.lit(cond.f_rel, self.key_terms())
                branches.extend(ValBranch((f_lit,) + b.lits, b.assigns, b.conds, b.term) for b in ve.branches)
                states.append(self.gate_state(ve.state_rel, [f_lit]))
            return ValEval(vt.typ, tuple(branches), self.combine_states(states))
        if key == "otherwise":
            left_node, right_node = node["otherwise"]
            vl = self.eval_value(f"{at}/otherwise/0", left_node)
            vr = self.eval_value(f"{at}/otherwise/1", right_node)
            if vl.typ != vr.typ:
                self.site.refuse(at, f"`otherwise` operands have different types ({vl.typ} vs {vr.typ})", "R003")
            branches = list(vl.branches)
            states: list[str | None] = [self.combine_states([vl.state_rel], exclude=("not_applicable",))]
            if vl.state_rel is not None:
                na_rel = self.next_helper("na")
                self.add_helper(na_rel, self._key_cols, self.key_terms(),
                                self.domain() + [self.lit(vl.state_rel, self.key_terms() + [NOT_APPLICABLE, ("var", self.fresh("r"))])])
                na_lit = self.lit(na_rel, self.key_terms())
                branches.extend(ValBranch((na_lit,) + b.lits, b.assigns, b.conds, b.term) for b in vr.branches)
                states.append(self.gate_state(vr.state_rel, [na_lit]))
            return ValEval(vl.typ, tuple(branches), self.combine_states(states))
        if key in ("cmp", "and", "or", "not", "imply", "is", "call"):
            b = self.eval_bool(at, node)
            branches = []
            if b.t_all:
                branches.append(ValBranch((), (), (), ("const", "true", "boolean")))
            elif b.t_rel is not None:
                branches.append(ValBranch((self.lit(b.t_rel, self.key_terms()),), (), (), ("const", "true", "boolean")))
            if b.f_all:
                branches.append(ValBranch((), (), (), ("const", "false", "boolean")))
            elif b.f_rel is not None:
                branches.append(ValBranch((self.lit(b.f_rel, self.key_terms()),), (), (), ("const", "false", "boolean")))
            return ValEval("boolean", tuple(branches), b.s_rel)
        self.site.refuse(at, f"expression `{key}` is not lowered in a rezono 1 functional derivation yet")

    def _and_bool(self, a: BoolEval, b: BoolEval) -> BoolEval:
        if a.f_all or b.f_all:
            return BoolEval(None, None, None, f_all=True)
        if a.t_all and b.t_all:
            return BoolEval(None, None, None, t_all=True)
        t_rel = self.next_helper("and_t")
        if a.t_all and b.t_rel is not None:
            t_rel_out: str | None = b.t_rel
        elif b.t_all and a.t_rel is not None:
            t_rel_out = a.t_rel
        elif a.t_rel is not None and b.t_rel is not None:
            self.add_helper(t_rel, self._key_cols, self.key_terms(),
                            self.domain() + [self.lit(a.t_rel, self.key_terms()),
                                             self.lit(b.t_rel, self.key_terms())])
            t_rel_out = self.helper_or_none(t_rel)
        else:
            t_rel_out = None
        f_rel = self.next_helper("and_f")
        for side in (a.f_rel, b.f_rel):
            if side is not None:
                self.add_helper(f_rel, self._key_cols, self.key_terms(),
                                self.domain() + [self.lit(side, self.key_terms())])
        sa = self.gate_state(a.s_rel, [] if b.f_rel is None else [self.lit(b.f_rel, self.key_terms(), False)])
        sb = self.gate_state(b.s_rel, [] if a.f_rel is None else [self.lit(a.f_rel, self.key_terms(), False)])
        return BoolEval(t_rel_out, self.helper_or_none(f_rel), self.combine_states([sa, sb]))

    def _or_bool(self, a: BoolEval, b: BoolEval) -> BoolEval:
        if a.t_all or b.t_all:
            return BoolEval(None, None, None, t_all=True)
        if a.f_all and b.f_all:
            return BoolEval(None, None, None, f_all=True)
        t_rel = self.next_helper("or_t")
        for side in (a.t_rel, b.t_rel):
            if side is not None:
                self.add_helper(t_rel, self._key_cols, self.key_terms(),
                                self.domain() + [self.lit(side, self.key_terms())])
        if a.f_all and b.f_rel is not None:
            f_rel_out: str | None = b.f_rel
        elif b.f_all and a.f_rel is not None:
            f_rel_out = a.f_rel
        elif a.f_rel is not None and b.f_rel is not None:
            f_rel = self.next_helper("or_f")
            self.add_helper(f_rel, self._key_cols, self.key_terms(),
                            self.domain() + [self.lit(a.f_rel, self.key_terms()),
                                             self.lit(b.f_rel, self.key_terms())])
            f_rel_out = self.helper_or_none(f_rel)
        else:
            f_rel_out = None
        sa = self.gate_state(a.s_rel, [] if b.t_rel is None else [self.lit(b.t_rel, self.key_terms(), False)])
        sb = self.gate_state(b.s_rel, [] if a.t_rel is None else [self.lit(a.t_rel, self.key_terms(), False)])
        return BoolEval(self.helper_or_none(t_rel), f_rel_out, self.combine_states([sa, sb]))

    def _cmp_bool(self, at: str, op: str, left_val: ValEval, right_val: ValEval) -> BoolEval:
        if op not in COMPARE:
            self.site.refuse(at, f"the comparison {op} is not lowered", "R016")
        if left_val.typ != right_val.typ:
            self.site.refuse(at, f"cannot compare {left_val.typ} with {right_val.typ}", "R003")
        if op not in ("=", "!=") and left_val.typ != "integer":
            self.site.refuse(at, f"order comparison `{op}` requires integers", "R003")
        bl, br = self._materialize_val(left_val), self._materialize_val(right_val)
        s_rel = self.combine_states([left_val.state_rel, right_val.state_rel])
        if bl is None or br is None:
            return BoolEval(None, None, s_rel)
        t_rel = self.next_helper("cmp_t")
        f_rel = self.next_helper("cmp_f")
        common = self.domain() + list(bl.lits + br.lits) + list(bl.assigns + br.assigns) + list(bl.conds + br.conds)
        ir_op = COMPARE[op]
        self.add_helper(t_rel, self._key_cols, self.key_terms(), common + [("cmp", ir_op, bl.term, br.term)])
        self.add_helper(f_rel, self._key_cols, self.key_terms(), common + [("cmp", NEGATED[ir_op], bl.term, br.term)])
        return BoolEval(self.helper_or_none(t_rel), self.helper_or_none(f_rel), s_rel)

    def eval_bool(self, at: str, node: dict) -> BoolEval:
        if not isinstance(node, dict) or len(node) != 1:
            self.site.refuse(at, "condition must be a single-key object")
        key = next(iter(node))
        if key == "lit":
            term = self.literal(at, node["lit"])
            if term[2] != "boolean":
                self.site.refuse(at, "expected a Boolean literal", "R003")
            return BoolEval(None, None, None, t_all=(term[1] == "true"), f_all=(term[1] == "false"))
        if key == "cmp":
            op, left, right = node["cmp"]
            return self._cmp_bool(at, op, self.eval_value(f"{at}/cmp/1", left),
                                  self.eval_value(f"{at}/cmp/2", right))
        if key == "and":
            parts = [self.eval_bool(f"{at}/and/{i}", item) for i, item in enumerate(node["and"])]
            acc = parts[0]
            for part in parts[1:]:
                acc = self._and_bool(acc, part)
            return acc
        if key == "or":
            parts = [self.eval_bool(f"{at}/or/{i}", item) for i, item in enumerate(node["or"])]
            acc = parts[0]
            for part in parts[1:]:
                acc = self._or_bool(acc, part)
            return acc
        if key == "not":
            inner = self.eval_bool(f"{at}/not", node["not"])
            return BoolEval(inner.f_rel, inner.t_rel, inner.s_rel, t_all=inner.f_all, f_all=inner.t_all)
        if key == "imply":
            left, right = node["imply"]
            nl = self.eval_bool(f"{at}/imply/0", left)
            return self._or_bool(BoolEval(nl.f_rel, nl.t_rel, nl.s_rel, t_all=nl.f_all, f_all=nl.t_all),
                                 self.eval_bool(f"{at}/imply/1", right))
        if key == "is":
            target_node, state_name = node["is"]
            mapped = "not_applicable" if state_name == "n/a" else state_name
            if mapped not in ("known", "not_applicable", "unknown", "invalid"):
                self.site.refuse(at, f"unknown state {state_name!r}")
            val = self.eval_value(f"{at}/is/0", target_node)
            t_rel = self.next_helper("is_t")
            f_rel = self.next_helper("is_f")
            if mapped == "known":
                for b in val.branches:
                    self.add_helper(t_rel, self._key_cols, self.key_terms(),
                                    self.domain() + list(b.lits) + list(b.assigns) + list(b.conds))
                if val.state_rel is not None:
                    self.add_helper(f_rel, self._key_cols, self.key_terms(),
                                    self.domain() + [self.lit(val.state_rel, self.key_terms()
                                                              + [("var", self.fresh("st")), ("var", self.fresh("r"))])])
            else:
                if val.state_rel is not None:
                    self.add_helper(t_rel, self._key_cols, self.key_terms(),
                                    self.domain() + [self.lit(val.state_rel, self.key_terms()
                                                              + [("const", mapped, "string"), ("var", self.fresh("r"))])])
                if (t_out := self.helper_or_none(t_rel)) is not None:
                    self.add_helper(f_rel, self._key_cols, self.key_terms(),
                                    self.domain() + [self.lit(t_out, self.key_terms(), False)])
                else:
                    return BoolEval(None, None, None, f_all=True)
            return BoolEval(self.helper_or_none(t_rel), self.helper_or_none(f_rel), None)
        if key == "call":
            lit = self.call(at, node["call"], True)
            rel_name = lit[2][0]
            target = self.signatures[rel_name]
            t_rel = self.next_helper("call_t")
            f_rel = self.next_helper("call_f")
            self.add_helper(t_rel, self._key_cols, self.key_terms(), self.domain() + [lit])
            neg_lit = self.call(at, node["call"], False)
            self.add_helper(f_rel, self._key_cols, self.key_terms(), self.domain() + [neg_lit])
            return BoolEval(self.helper_or_none(t_rel), self.helper_or_none(f_rel), None)
        if key == "path":
            val = self.eval_path_val(at, node["path"])
            if val.typ != "boolean":
                self.site.refuse(at, f"condition path must be Bool, got {val.typ}", "R003")
            t_rel = self.next_helper("bt")
            f_rel = self.next_helper("bf")
            for b in val.branches:
                common = self.domain() + list(b.lits) + list(b.assigns) + list(b.conds)
                self.add_helper(t_rel, self._key_cols, self.key_terms(), common + [("cmp", "eq", b.term, ("const", "true", "boolean"))])
                self.add_helper(f_rel, self._key_cols, self.key_terms(), common + [("cmp", "eq", b.term, ("const", "false", "boolean"))])
            return BoolEval(self.helper_or_none(t_rel), self.helper_or_none(f_rel), val.state_rel)
        self.site.refuse(at, f"Boolean condition `{key}` is not lowered yet")

    def lower_unless(self, at: str, fallback: tuple[str, dict] | None, blocks: list[list[dict]], meta: dict,
                     *, empty_reason: str | None = None) -> None:
        """Lower ordered `unless` blocks (last block has highest priority) with sibling conflict detection."""
        default_reason = empty_reason or ("no_value" if fallback is not None else "no_row_applies")
        meta |= {"empty_state": "unknown", "empty_reason": default_reason}
        if any(len(block) > 1 for block in blocks):
            meta["conflict_policy"] = "block"
        branches: list[ValBranch] = []
        states: list[str | None] = []
        prior_ref: str | None = None
        for bi in range(len(blocks) - 1, -1, -1):
            block = blocks[bi]
            prior_guard = [] if prior_ref is None else [self.lit(prior_ref, self.key_terms(), False)]
            conds: list[BoolEval] = []
            und_rels: list[str | None] = []
            for ci, clause in enumerate(block):
                cat = f"{at}/unless/{bi}/{ci}"
                c_eval = self.eval_bool(f"{cat}/when", clause["when"])
                conds.append(c_eval)
                und_rels.append(self._undecided_keys(c_eval.s_rel))
            # Sibling clash inside this block when >= 2 clauses apply.
            clash_rel: str | None = None
            if len(block) > 1:
                clash_name = self.next_helper(f"clash_b{bi}")
                for i in range(len(block)):
                    for j in range(i + 1, len(block)):
                        ci, cj = conds[i], conds[j]
                        if (not ci.t_all and ci.t_rel is None) or (not cj.t_all and cj.t_rel is None):
                            continue
                        body = self.domain() + prior_guard
                        if ci.t_rel is not None:
                            body.append(self.lit(ci.t_rel, self.key_terms()))
                        if cj.t_rel is not None:
                            body.append(self.lit(cj.t_rel, self.key_terms()))
                        self.add_helper(clash_name, self._key_cols, self.key_terms(), body)
                clash_rel = self.helper_or_none(clash_name)
                if clash_rel is not None:
                    clash_st = self.next_helper(f"clash_st_b{bi}")
                    self.add_helper(clash_st, self._state_cols, self.key_terms() + [INVALID, EXCEPTION_CONFLICT],
                                    self.domain() + [self.lit(clash_rel, self.key_terms())])
                    states.append(clash_st)
            # Undecided conditions in this block (when not blocked by higher blocks or clash).
            block_und_guard: list[tuple] = []
            clash_guard = [] if clash_rel is None else [self.lit(clash_rel, self.key_terms(), False)]
            for ci_idx, (c_eval, u_rel) in enumerate(zip(conds, und_rels)):
                if c_eval.s_rel is not None and u_rel is not None:
                    gated = self.gate_state(c_eval.s_rel, prior_guard + clash_guard)
                    states.append(self.combine_states([gated], exclude=("not_applicable",)))
                    block_und_guard.append(self.lit(u_rel, self.key_terms(), False))
            # Each clause that applies alone without undecided siblings.
            for ci_idx, clause in enumerate(block):
                c_eval = conds[ci_idx]
                if not c_eval.t_all and c_eval.t_rel is None:
                    continue
                other_guard = [self.lit(conds[k].t_rel, self.key_terms(), False)
                               for k in range(len(block)) if k != ci_idx and conds[k].t_rel is not None]
                if any(conds[k].t_all for k in range(len(block)) if k != ci_idx):
                    continue
                clause_guard = (prior_guard + clash_guard + block_und_guard + other_guard
                                + ([] if c_eval.t_all else [self.lit(c_eval.t_rel, self.key_terms())]))
                then_val = self.eval_value(f"{at}/unless/{bi}/{ci_idx}/then", clause["then"])
                if then_val.typ != self.sig.value_type:
                    self.site.refuse(f"{at}/unless/{bi}/{ci_idx}/then",
                                     f"expected {self.sig.value_type}, got {then_val.typ}", "R003")
                for b in then_val.branches:
                    branches.append(ValBranch(tuple(clause_guard) + b.lits, b.assigns, b.conds, b.term))
                states.append(self.gate_state(then_val.state_rel, clause_guard))
            # Accumulate handled keys into a fresh relation so lower blocks and fallback never self-negate.
            next_handled = self.next_helper(f"unless_handled_b{bi}")
            if prior_ref is not None:
                self.add_helper(next_handled, self._key_cols, self.key_terms(),
                                self.domain() + [self.lit(prior_ref, self.key_terms())])
            for c_eval in conds:
                if c_eval.t_all:
                    self.add_helper(next_handled, self._key_cols, self.key_terms(), self.domain())
                elif c_eval.t_rel is not None:
                    self.add_helper(next_handled, self._key_cols, self.key_terms(),
                                    self.domain() + [self.lit(c_eval.t_rel, self.key_terms())])
            for u_rel in und_rels:
                if u_rel is not None:
                    self.add_helper(next_handled, self._key_cols, self.key_terms(),
                                    self.domain() + [self.lit(u_rel, self.key_terms())])
            prior_ref = self.helper_or_none(next_handled)
        if fallback is not None:
            fb_at, fb_node = fallback
            fb_guard = [] if prior_ref is None else [self.lit(prior_ref, self.key_terms(), False)]
            fb_val = self.eval_value(fb_at, fb_node)
            if fb_val.typ != self.sig.value_type:
                self.site.refuse(fb_at, f"expected {self.sig.value_type}, got {fb_val.typ}", "R003")
            for b in fb_val.branches:
                branches.append(ValBranch(tuple(fb_guard) + b.lits, b.assigns, b.conds, b.term))
            states.append(self.gate_state(fb_val.state_rel, fb_guard))
        self.emit_functional(at, meta, tuple(branches), self.combine_states(states))

    def _table_cell_bool(self, at: str, inp: ValEval, inp_node: dict, cell: object) -> BoolEval | None:
        if cell == "-":
            return None
        if not isinstance(cell, list) or not cell:
            self.site.refuse(at, "table cell must be `-` or a list of tests")
        slot_enum = self._input_slot_enum(inp_node)
        tests: list[BoolEval] = []
        for ti, test in enumerate(cell):
            tat = f"{at}/{ti}"
            if isinstance(test, dict) and set(test) == {"lit"}:
                lit_term = self.literal(tat, test["lit"])
                if slot_enum is not None and lit_term[1] not in self.pack.enums[slot_enum]:
                    self.site.refuse(tat, f"{test['lit']} is not a value of {slot_enum}", "R001")
                if lit_term[2] != inp.typ:
                    self.site.refuse(tat, f"table cell value {test['lit']!r} is {lit_term[2]}, input is {inp.typ}", "R003")
                lit_val = ValEval(lit_term[2], (ValBranch((), (), (), lit_term),), None)
                tests.append(self._cmp_bool(tat, "=", inp, lit_val))
            elif isinstance(test, dict) and set(test) == {"between"}:
                if inp.typ != "integer":
                    self.site.refuse(tat, "a range test requires an integer input", "R003")
                b = test["between"]
                parts: list[BoolEval] = []
                for side, op in (("from", ">="), ("to", "<=" if b.get("op") == ".." else "<")):
                    if side in b:
                        bound = self.literal(tat, b[side]["lit"])
                        if bound[2] != "integer":
                            self.site.refuse(tat, "range bound must be an integer", "R003")
                        parts.append(self._cmp_bool(tat, op, inp, ValEval("integer", (ValBranch((), (), (), bound),), None)))
                if not parts:
                    self.site.refuse(tat, "range test needs at least one bound")
                acc = parts[0]
                for p in parts[1:]:
                    acc = self._and_bool(acc, p)
                tests.append(acc)
            else:
                self.site.refuse(tat, "unsupported table test")
        acc = tests[0]
        for t in tests[1:]:
            acc = self._or_bool(acc, t)
        return acc

    def _input_slot_enum(self, node: dict) -> str | None:
        if not isinstance(node, dict) or set(node) != {"path"}:
            return None
        path = node["path"]
        if len(path) == 1 and self.sig.binder == "it" and path[0] != "it":
            path = ["it", path[0]]
        if not path or path[0] not in self.env:
            return None
        typ = self.env[path[0]]
        slot = None
        for part in path[1:]:
            if typ[0] != "kind":
                return None
            slot = self.slot("", typ[1], part)
            if slot is None:
                return None
            typ = self.slot_type(slot)
        return slot.enum if slot is not None else None

    def lower_table(self, at: str, table: dict, meta: dict) -> None:
        """Lower `table unique` or `table first` directly to functional rules in rezono.rules/2."""
        policy = table["table"]
        meta |= {"conflict_policy": "block" if policy == "unique" else "publish",
                 "empty_state": "unknown", "empty_reason": "no_row_applies"}
        inputs = [self.eval_value(f"{at}/inputs/{j}", expr) for j, expr in enumerate(table["inputs"])]
        row_bools: list[BoolEval] = []
        row_unds: list[str | None] = []
        outputs: list[tuple] = []
        for ri, row in enumerate(table["rows"]):
            rat = f"{at}/rows/{ri}"
            cell_evals = []
            for j, cell in enumerate(row["tests"]):
                if (ce := self._table_cell_bool(f"{rat}/tests/{j}", inputs[j], table["inputs"][j], cell)) is not None:
                    cell_evals.append(ce)
            if not cell_evals:
                rb = BoolEval(None, None, None, t_all=True)
            else:
                rb = cell_evals[0]
                for ce in cell_evals[1:]:
                    rb = self._and_bool(rb, ce)
            row_bools.append(rb)
            row_unds.append(self._undecided_keys(rb.s_rel))
            raw_val = row["value"]
            lit_tok = raw_val.get("lit") if isinstance(raw_val, dict) and set(raw_val) == {"lit"} else None
            if lit_tok is None:
                self.site.refuse(f"{rat}/value", "table output must be a literal")
            if self.sig.enum_type is not None and lit_tok not in self.pack.enums[self.sig.enum_type]:
                self.site.refuse(f"{rat}/value", f"{lit_tok} is not a value of {self.sig.enum_type}", "R001")
            out_term = self.literal(f"{rat}/value", lit_tok)
            if out_term[2] != self.sig.value_type:
                self.site.refuse(f"{rat}/value", f"table output {lit_tok!r} is {out_term[2]}, expected {self.sig.value_type}", "R003")
            outputs.append(out_term)

        branches: list[ValBranch] = []
        states: list[str | None] = []
        if policy == "unique":
            clash_name = self.next_helper("tbl_clash")
            for i in range(len(row_bools)):
                for j in range(i + 1, len(row_bools)):
                    ri_b, rj_b = row_bools[i], row_bools[j]
                    if (not ri_b.t_all and ri_b.t_rel is None) or (not rj_b.t_all and rj_b.t_rel is None):
                        continue
                    body = self.domain()
                    if ri_b.t_rel is not None:
                        body.append(self.lit(ri_b.t_rel, self.key_terms()))
                    if rj_b.t_rel is not None:
                        body.append(self.lit(rj_b.t_rel, self.key_terms()))
                    self.add_helper(clash_name, self._key_cols, self.key_terms(), body)
            clash_rel = self.helper_or_none(clash_name)
            clash_guard = [] if clash_rel is None else [self.lit(clash_rel, self.key_terms(), False)]
            if clash_rel is not None:
                clash_st = self.next_helper("tbl_clash_st")
                self.add_helper(clash_st, self._state_cols, self.key_terms() + [INVALID, EXCEPTION_CONFLICT],
                                self.domain() + [self.lit(clash_rel, self.key_terms())])
                states.append(clash_st)
            und_guard = [self.lit(u, self.key_terms(), False) for u in row_unds if u is not None]
            for rb, u_rel in zip(row_bools, row_unds):
                if rb.s_rel is not None and u_rel is not None:
                    states.append(self.combine_states([self.gate_state(rb.s_rel, clash_guard)],
                                                      exclude=("not_applicable",)))
            for ri_idx, (rb, out_term) in enumerate(zip(row_bools, outputs)):
                if not rb.t_all and rb.t_rel is None:
                    continue
                if any(row_bools[k].t_all for k in range(len(row_bools)) if k != ri_idx):
                    continue
                others = [self.lit(row_bools[k].t_rel, self.key_terms(), False)
                          for k in range(len(row_bools)) if k != ri_idx and row_bools[k].t_rel is not None]
                guard = clash_guard + und_guard + others + ([] if rb.t_all else [self.lit(rb.t_rel, self.key_terms())])
                branches.append(ValBranch(tuple(guard), (), (), out_term))
        else:  # policy == "first"
            any_t_name = self.next_helper("tbl_any_t")
            win_rels: list[str | None] = []
            for ri_idx, rb in enumerate(row_bools):
                if rb.t_all:
                    self.add_helper(any_t_name, self._key_cols, self.key_terms(), self.domain())
                elif rb.t_rel is not None:
                    self.add_helper(any_t_name, self._key_cols, self.key_terms(),
                                    self.domain() + [self.lit(rb.t_rel, self.key_terms())])
                if not rb.t_all and rb.t_rel is None:
                    win_rels.append(None)
                    continue
                if any(row_bools[m].t_all for m in range(ri_idx)):
                    win_rels.append(None)
                    continue
                earlier_neg = [self.lit(row_bools[m].t_rel, self.key_terms(), False)
                               for m in range(ri_idx) if row_bools[m].t_rel is not None]
                win_name = self.next_helper(f"win_{ri_idx}")
                body = self.domain() + earlier_neg + ([] if rb.t_all else [self.lit(rb.t_rel, self.key_terms())])
                self.add_helper(win_name, self._key_cols, self.key_terms(), body)
                win_rels.append(self.helper_or_none(win_name))
            any_t_rel = self.helper_or_none(any_t_name)
            for ri_idx, (w_rel, out_term) in enumerate(zip(win_rels, outputs)):
                if w_rel is None:
                    continue
                blockers = [self.lit(row_unds[m], self.key_terms(), False)
                            for m in range(ri_idx) if row_unds[m] is not None and outputs[m] != out_term]
                branches.append(ValBranch((self.lit(w_rel, self.key_terms()),) + tuple(blockers), (), (), out_term))
            for m_idx, (rb, u_rel) in enumerate(zip(row_bools, row_unds)):
                if rb.s_rel is None or u_rel is None:
                    continue
                # Case 1: no row applied at all.
                if any_t_rel is None:
                    states.append(self.combine_states([rb.s_rel], exclude=("not_applicable",)))
                else:
                    states.append(self.combine_states(
                        [self.gate_state(rb.s_rel, [self.lit(any_t_rel, self.key_terms(), False)])],
                        exclude=("not_applicable",),
                    ))
                    # Case 2: a later winning row has a different output than this undecided row.
                    for r_idx in range(m_idx + 1, len(win_rels)):
                        if win_rels[r_idx] is not None and outputs[r_idx] != outputs[m_idx]:
                            states.append(self.combine_states(
                                [self.gate_state(rb.s_rel, [self.lit(win_rels[r_idx], self.key_terms())])],
                                exclude=("not_applicable",),
                            ))
        self.emit_functional(at, meta, tuple(branches), self.combine_states(states))

    # -- paths ----------------------------------------------------------------------------------------------------

    def slot(self, at: str, kind: str, name: str):
        """The slot `name` of `kind` or of an ancestor, or None."""
        while kind is not None:
            found = self.pack.kinds[kind].slots.get(name)
            if found is not None:
                return found
            kind = self.pack.kinds[kind].parent
        return None

    def slot_type(self, slot) -> tuple:
        if slot.arrow:
            return "kind", slot.range if slot.range in self.pack.kinds else self.names.resolve(
                self.sig.module.id, slot.range)
        return "scalar", rules_dl.SQL.get(slot.sql_type)

    def path(self, at: str, path: list, target: tuple | None = None) -> tuple[list[tuple], tuple, bool]:
        """The literals that read a slot path from a variable, its value term and whether it is optional.
        Every hop is a single-valued slot; a path that mixes optional and required hops is not lowered yet. A value
        is not read from an open slot, where a missing value is unknown; a Bool set may read one and is then open."""
        head = path[0]
        if head not in self.env and self.sig.binder == "it" and head != "it":
            path, head = ["it", *path], "it"
        if head not in self.env:
            self.site.refuse(at, f"{head} is not a variable here", "R001")
        literals, term, typ, optional = [], ("var", head), self.env[head], set()
        for index, name in enumerate(path[1:], 1):
            if typ[0] != "kind":
                self.site.refuse(at, f"{'.'.join(path[:index])} is no element, so it has no slot {name}", "R003")
            slot = self.slot(at, typ[1], name)
            if slot is None:
                self.site.refuse(at, f"{'.'.join(path[:index])} has no slot {name} lowered here", "R001")
            if slot.multivalued:
                self.site.refuse(at, f"{'.'.join(path[:index + 1])} is a set; read it with a method such as "
                                     "`.count()` or `.one()`", "R005")
            if slot.world == "open" and self.sig.result == "functional":
                self.site.refuse(at, f"{slot.table} is open, so a missing value is unknown; it is not lowered yet",
                                 "R004")
            optional.add(not slot.required)
            last = index == len(path) - 1
            value = target if last and target is not None else ("var", self.fresh())
            literals.append(self.lit(slot.table, [term, value]))
            term, typ = value, self.slot_type(slot)
        if len(optional) > 1:
            self.site.refuse(at, "a path with optional and required hops is not lowered yet")
        return literals, term, optional == {True}

    # -- predicates of a set (Bool) -------------------------------------------------------------------------------

    def alternatives(self, at: str, node: dict) -> list[list[tuple]]:
        """One premise list per alternative of a Bool expression, each with the literals it needs."""
        if set(node) == {"and"}:
            result: list[list[tuple]] = [[]]
            for index, member in enumerate(node["and"]):
                result = [left + right for left in result
                          for right in self.alternatives(f"{at}/and/{index}", member)]
            return result
        if set(node) == {"or"}:
            return [branch for index, member in enumerate(node["or"])
                    for branch in self.alternatives(f"{at}/or/{index}", member)]
        return [self.premise(at, node)]

    def operand(self, at: str, node: dict) -> tuple[list[tuple], tuple]:
        if set(node) == {"lit"}:
            return [], self.literal(at, node["lit"])
        if set(node) == {"path"} and node["path"] and node["path"][0] in self.env:
            literals, term, _ = self.path(at, node["path"])
            return literals, term
        self.site.refuse(at, "an operand is a variable, a slot path or a literal here")

    def literal(self, at: str, token: object) -> tuple:
        if isinstance(token, str) and re.fullmatch(r"-?[0-9]+", token.replace("_", "")):
            return "const", str(int(token.replace("_", ""))), "integer"
        if isinstance(token, str) and token.startswith('"'):
            value = json.loads(token)
            if isinstance(value, str) and value != "_" and not value.startswith("?"):
                return "const", value, "string"
        if token == "true":
            return "const", "true", "boolean"
        if token == "false":
            return "const", "false", "boolean"
        if isinstance(token, str) and re.fullmatch(r"[A-Za-z][A-Za-z0-9_-]*", token):
            return "const", token, "string"  # an element id or a value of an enum
        self.site.refuse(at, f"the literal {token!r} has no rule term yet", "R012")

    def premise(self, at: str, node: dict) -> list[tuple]:
        if set(node) == {"cmp"}:
            op, left, right = node["cmp"]
            if op not in COMPARE:
                self.site.refuse(at, f"the comparison {op} is not lowered", "R016")
            if op == "=":
                for side, var, other in ((1, left, right), (2, right, left)):
                    name = var.get("path", [None])[0] if set(var) == {"path"} and len(var["path"]) == 1 else None
                    if (name in self.env and set(other) == {"path"} and len(other["path"]) > 1
                            and other["path"][0] in self.env):
                        literals, _, _ = self.path(f"{at}/cmp/{3 - side}", other["path"], target=("var", name))
                        return literals
            left_literals, left_term = self.operand(f"{at}/cmp/1", left)
            right_literals, right_term = self.operand(f"{at}/cmp/2", right)
            return left_literals + right_literals + [("cmp", COMPARE[op], left_term, right_term)]
        if set(node) == {"call"}:
            return [self.call(at, node["call"], True)]
        if set(node) == {"not"} and isinstance(node["not"], dict) and set(node["not"]) == {"call"}:
            return [self.call(f"{at}/not", node["not"]["call"], False)]
        if set(node) == {"path"} and len(node["path"]) > 1 and node["path"][0] in self.env:
            literals, term, _ = self.path(at, node["path"])
            return literals + [("cmp", "eq", term, ("const", "true", "boolean"))]
        self.site.refuse(at, "this Bool expression is not lowered to rezono.rules/2 yet")

    def call(self, at: str, call: list, positive: bool) -> tuple:
        name, args = call
        target = _resolve_relation(self.sig.module, self.signatures, self.site, at, name)
        if target is None or target.result != "set":
            self.site.refuse(at, f"{name} is not a Bool set derived in this pack or a used pack", "R001")
        relation = target.relation
        if len(args) != len(target.key):
            self.site.refuse(at, f"{name} takes {len(target.key)} arguments", "R041")
        terms = []
        for index, arg in enumerate(args):
            if arg == {"wildcard": True}:
                if not positive:
                    self.site.refuse(f"{at}/call/1/{index}", "`_` in a negation: every column is needed")
                terms.append(("wild",))
            elif set(arg) == {"path"} and len(arg["path"]) == 1 and arg["path"][0] in self.env:
                terms.append(("var", arg["path"][0]))
            elif set(arg) == {"lit"}:
                terms.append(self.literal(f"{at}/call/1/{index}", arg["lit"]))
            else:
                self.site.refuse(f"{at}/call/1/{index}", "an argument is a variable, `_` or a literal here")
        return self.lit(relation, terms, positive)

    # -- collections ----------------------------------------------------------------------------------------------

    def collection(self, at: str, node: dict) -> Member:
        pred: list[tuple[str, dict]] = []
        while set(node) == {"filter"}:
            base, condition, *binder = node["filter"]
            if binder:
                self.site.refuse(at, "a binder on `.where(...)` is not lowered yet")
            pred = self._conjuncts(f"{at}/filter/1", condition) + pred
            at, node = f"{at}/filter/0", base
        if set(node) == {"kind"}:
            kind = _resolve_schema_name(self.site, self.names, self.sig.module, at, node["kind"])
            if kind not in self.pack.kinds:
                self.site.refuse(at, f"{node['kind']} is not a kind of the pack", "R001")
            if self.pack.kinds[kind].world == "open":
                self.site.refuse(at, f"{node['kind']} is open, so a count or `.one()` over it is only what is "
                                     "recorded; it is not lowered", "R004")
            member = ("var", self.fresh("m"))
            return Member([member], self.lit(kind, [member]), kind, {}, pred)
        if set(node) == {"path"}:
            path = node["path"]
            rel_name = (
                path[0] if len(path) == 1 and path[0] not in self.env
                else f"{path[0]}.{path[1]}" if len(path) == 2 and path[0] in self._aliases
                else None
            )
            if rel_name is not None:
                target = _resolve_relation(self.sig.module, self.signatures, self.site, at, rel_name)
                if target is None or target.result != "set" or target.property is not None:
                    self.site.refuse(at, f"{rel_name} is not a relation derived in this pack or a used pack", "R001")
                terms = [("var", self.fresh(column)) for column, _ in target.key]
                columns = {column: (index, typ) for index, (column, typ) in enumerate(target.key)}
                return Member(terms, self.lit(target.relation, terms), None, columns, pred)
        self.site.refuse(at, "a collection is a kind, a relation or a `.where(...)` of one here")

    def _conjuncts(self, at: str, node: dict) -> list[tuple[str, dict]]:
        if set(node) == {"and"}:
            return [item for index, member in enumerate(node["and"])
                    for item in self._conjuncts(f"{at}/and/{index}", member)]
        return [(at, node)]

    def member_side(self, member: Member, node: dict):
        """('it',) for the element itself, ('slot', slot) for an element's slot, ('column', i, type) for a column
        of a tuple, or None for an outer value."""
        path = node.get("path") if set(node) == {"path"} else None
        if not path:
            return None
        if path == ["it"]:
            return ("it",) if member.kind is not None else None
        name = path[1] if path[0] == "it" and len(path) == 2 else path[0] if len(path) == 1 else None
        if name is None:
            return None
        if member.kind is not None:
            slot = self.slot("", member.kind, name)
            if slot is not None:
                return "slot", slot
        elif name in member.columns:
            return ("column", *member.columns[name])
        return None

    def atoms(self, member: Member) -> list[dict]:
        """Each conjunct of the predicate as the literals that make it true and false, and the slot whose absence
        leaves it undecided (a required slot of the element; None when it is always decided)."""
        out = []
        for at, node in member.pred:
            if set(node) != {"cmp"} or node["cmp"][0] not in COMPARE:
                self.site.refuse(at, "a predicate of `.where(...)`, `.count(...)` or `.one()` is a conjunction of "
                                     "comparisons here")
            op, left, right = node["cmp"]
            op = COMPARE[op]
            sides = [self.member_side(member, left), self.member_side(member, right)]
            if (sides[0] is None) == (sides[1] is None):
                self.site.refuse(at, "a comparison here has the row on one side and an outer value on the other")
            if sides[0] is None:  # the row on the left
                left, right, sides = right, left, sides[::-1]
                op = {"lt": "gt", "le": "ge", "gt": "lt", "ge": "le"}.get(op, op)
            name = (right.get("path") or [None])[0] if set(right) == {"path"} else None
            if set(right) == {"path"} and len(right["path"]) == 1 and name in self.env:
                if self.member_side(member, right) is not None:
                    self.site.refuse(at, f"{name} is a column of the row and a variable outside it; write "
                                         f"`it.{name}`", "R011")
                outer = ("var", name)
            elif set(right) == {"lit"}:
                outer = self.literal(at, right["lit"])
            else:
                self.site.refuse(at, "the outer side of a comparison is a variable or a literal here")
            side = sides[0]
            if side[0] == "it":
                out.append({"true": [("cmp", op, member.terms[0], outer)],
                            "false": [("cmp", NEGATED[op], member.terms[0], outer)], "missing": None})
            elif side[0] == "column":
                term = member.terms[side[1]]
                out.append({"true": [("cmp", op, term, outer)], "false": [("cmp", NEGATED[op], term, outer)],
                            "missing": None})
            else:
                slot = side[1]
                if slot.multivalued:
                    self.site.refuse(at, f"{slot.name} is a set; compare it with a method", "R005")
                if not slot.required:
                    self.site.refuse(at, f"{slot.name} is optional; a predicate on an optional slot is not lowered "
                                         "yet")
                if slot.world == "open":
                    self.site.refuse(at, f"{slot.table} is open; a predicate on it is not lowered", "R004")
                value = ("var", self.fresh())
                read = self.lit(slot.table, [member.terms[0], value])
                out.append({"true": [read, ("cmp", op, value, outer)],
                            "false": [read, ("cmp", NEGATED[op], value, outer)], "missing": slot})
        return out

    def undecided(self, member: Member, atoms: list[dict], rows: str, missing_projection=None) -> None:
        """Rules for the rows of `rows` (key..., row..., state, reason) whose membership is undecided: a missing
        required slot of the predicate where no other conjunct is false, or a missing projected slot."""
        missing = [atom["missing"] for atom in atoms if atom["missing"] is not None]
        keys = self.key_terms()
        present: dict[str, str] = {}

        def has(slot) -> str:
            if slot.table not in present:
                name = self.helper(f"has_{slot.name}")
                self.declare(name, [("element", ir_type(self.pack, ("kind", member.kind)))])
                value = ("var", self.fresh())
                self.rule(name, [member.terms[0]], [self.lit(member.kind, [member.terms[0]]),
                                                    self.lit(slot.table, [member.terms[0], value])])
                present[slot.table] = name
            return present[slot.table]

        if missing:
            false = self.helper("false")
            self.declare(false, self.row_columns(member, state=False))
            for atom in atoms:
                self.rule(false, keys + member.terms, self.domain() + [member.literal] + atom["false"])
            for slot in {slot.table: slot for slot in missing}.values():
                self.rule(rows, keys + member.terms + [UNKNOWN, NO_VALUE],
                          self.domain() + [member.literal, self.lit(has(slot), [member.terms[0]], False),
                                           self.lit(false, keys + member.terms, False)])
        if missing_projection is not None:
            true = [literal for atom in atoms for literal in atom["true"]]
            self.rule(rows, keys + member.terms + [UNKNOWN, NO_VALUE],
                      self.domain() + [member.literal] + true
                      + [self.lit(has(missing_projection), [member.terms[0]], False)])

    def row_columns(self, member: Member, state: bool = True) -> list[tuple[str, str]]:
        columns = [(self.sig.key_column or name, ir_type(self.pack, typ)) for name, typ in self.sig.key]
        if member.kind is not None:
            columns.append(("element", ir_type(self.pack, ("kind", member.kind))))
        else:
            target = next(s for s in self.signatures.values() if s.relation == member.literal[2][0])
            columns += [(f"row_{column}", ir_type(self.pack, typ)) for column, typ in target.key]
        if state:
            columns += [("state", "string"), ("reason", "string")]
        return columns

    def count(self, at: str, agg: list) -> None:
        if len(agg) not in (2, 3):
            self.site.refuse(at, "a binder on `.count(...)` is not lowered yet")
        member = self.collection(f"{at}/agg/1", agg[1])
        if len(agg) == 3:
            member.pred = member.pred + self._conjuncts(f"{at}/agg/2", agg[2])
        atoms = self.atoms(member)
        rows = self.helper("rows")
        self.declare(rows, self.row_columns(member))
        keys = self.key_terms()
        self.rule(rows, keys + member.terms + [KNOWN, EMPTY],
                  self.domain() + [member.literal] + [literal for atom in atoms for literal in atom["true"]])
        self.undecided(member, atoms, rows)
        total = self.fresh("n")
        self.statements.append(("rule", (self.sig.relation, keys + [("var", total)], self.line),
                                self.domain() + [("agg", total, "count", None,
                                                  (rows, keys + [("wild",)] * (len(member.terms) + 2), self.line))],
                                self.line))
        self.columns.append(self.column)

    def one(self, at: str, agg: list) -> None:
        if len(agg) not in (2, 3):
            self.site.refuse(at, "a binder on `.one(...)` is not lowered yet")
        member = self.collection(f"{at}/agg/1", agg[1])
        atoms = self.atoms(member)
        keys = self.key_terms()
        true = [literal for atom in atoms for literal in atom["true"]]
        projection = None
        if len(agg) == 2:
            if member.kind is None:
                self.site.refuse(at, "`.one()` of a tuple set names the column: `.one(column)`")
            value, reads = member.terms[0], []
        else:
            side = self.member_side(member, agg[2])
            if side is None or side[0] == "it":
                self.site.refuse(f"{at}/agg/2", "`.one(expr)` names a slot or a column of the row here")
            if side[0] == "column":
                value, reads = member.terms[side[1]], []
            else:
                slot = side[1]
                if slot.multivalued:
                    self.site.refuse(f"{at}/agg/2", f"{slot.name} is a set", "R005")
                if not slot.required:
                    self.site.refuse(f"{at}/agg/2", f"{slot.name} is optional; `.one()` of an optional slot is not "
                                                    "lowered yet")
                value = ("var", self.fresh())
                reads = [self.lit(slot.table, [member.terms[0], value])]
                projection = slot
        self.rule(self.sig.relation, keys + [value], self.domain() + [member.literal] + true + reads)
        if projection is not None or any(atom["missing"] is not None for atom in atoms):
            if self.sig.value_type not in SENTINEL and self.sig.value_type != "integer":
                self.site.refuse(at, f"`.one()` of a {self.sig.value_type} that can be undecided is not lowered yet")
            undecided = self.helper("undecided")
            self.declare(undecided, self.row_columns(member))
            self.undecided(member, atoms, undecided, projection)
            total = self.fresh("n")
            row = [("var", self.fresh("r")) for _ in member.terms]
            state, reason = ("var", self.fresh("st")), ("var", self.fresh("rsn"))
            sentinel = ("var", total) if self.sig.value_type == "integer" else SENTINEL[self.sig.value_type]
            self.statements.append((
                "rule", (self.sig.relation, keys + [sentinel], self.line),
                self.domain() + [self.lit(undecided, keys + row + [state, reason]),
                                 ("agg", total, "count", None,
                                  (undecided, keys + [("wild",)] * (len(member.terms) + 2), self.line))],
                self.line))
            self.columns.append(self.column)


def merged(native: tuple[rules_dl.NativeSource, ...], derived: tuple[rules_dl.NativeSource, ...]
           ) -> tuple[rules_dl.NativeSource, ...]:
    """The native sources with the derivations of the same module added to its own: a rezono 1 module that declares
    steps and derivations is one rule module."""
    by_module = {(source.pack, source.stem): source for source in native}
    for source in derived:
        if (own := by_module.get((source.pack, source.stem))) is None:
            by_module[source.pack, source.stem] = source
        else:
            merged_notes = (
                (own.notes or (None,) * len(own.columns)) + (source.notes or (None,) * len(source.columns))
                if own.notes or source.notes else ()
            )
            by_module[source.pack, source.stem] = rules_dl.NativeSource(
                own.pack, own.stem, own.file, own.text, own.statements + source.statements,
                own.columns + source.columns, own.semantics, merged_notes)
    return tuple(by_module.values())


PLACEHOLDER = re.compile(r"(\{\$[A-Za-z_][A-Za-z0-9_]*\})")


def message_line(key: str, text: str) -> str:
    """`<key> = {{TEXT}}` in MessageFormat 2, keeping `{$name}` placeholders and escaping any other `\\`, `{`, `}`."""
    parts = PLACEHOLDER.split(text)
    escaped = "".join(part if index % 2 else part.replace("\\", "\\\\").replace("{", "\\{").replace("}", "\\}")
                      for index, part in enumerate(parts))
    return f"{key} = {{{{{escaped}}}}}\n"


def notes(
    pack,
    pack_dir,
    meta: dict,
    lowered: Lowered,
    *,
    packs: Mapping[str, object] | None = None,
    rule_notes: Mapping[str, tuple[str, Note]] | None = None,
) -> dict[str, list[str]]:
    """Give every rule of a clause or derivation the source written after `@` (pack.rule_sources) and return the
    message lines of their sentences per owning pack, in each pack's default language (language-readable-rules.md
    section 2). A sentence that the message file of its pack's default language also gives is refused: a sentence
    has one source."""
    from . import rezono_reason
    from .pack import CompileError

    if (not lowered.notes and not rule_notes) or not pack.rules:
        return {}
    root = meta["name"]
    catalogs: dict[tuple, set[str]] = {}
    lines: dict[str, list[str]] = {}
    refused: list[Diagnostic] = []
    for rule in sorted(pack.rules["rules"], key=lambda r: r["id"]):
        rid = rule["id"]
        if rule_notes and rid in rule_notes:
            owner, note = rule_notes[rid]
        elif (derived_note := lowered.notes.get(rule["head"]["relation"])) is not None:
            owner = lowered.note_owners.get(rule["head"]["relation"], root)
            note = derived_note
        else:
            continue
        if note.source is not None:
            pack.rule_sources[rid] = note.source
        if note.means is None:
            continue
        if owner == root:
            directory, default_lang = pack_dir, meta.get("default_language")
        else:
            imported = (packs or {})[owner]
            directory, default_lang = imported.dir, imported.meta.get("default_language")
        catalog_key = (directory, default_lang)
        if catalog_key not in catalogs:
            catalogs[catalog_key] = rezono_reason.defined_in_catalog(directory, default_lang)
        key = f"rule.{rid}"
        if key in catalogs[catalog_key]:
            refused.append(Diagnostic(
                "R000",
                f"{note.where}:{note.line}: the sentence of {rule['head']['relation']} "
                f"is also given as {key} in messages/{default_lang}.mf2; "
                "a sentence has one source",
                f"{note.where}#{note.at}",
                (note.where, note.line, note.column),
            ))
        lines.setdefault(owner, []).append(message_line(key, note.means))
    if refused:
        raise CompileError("\n".join(map(str, refused)), refused)
    return lines
