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

from . import rules_dl, spans
from .diagnostics import Diagnostic

if TYPE_CHECKING:
    from . import modules

REZONO_1_FORMAT = "rezono.module/5"
# Members that only the calculation IR lowers; a derived value with one of them stays a calculation.
CALC_ONLY = frozenset({"unit", "versions", "definitions", "output", "totality", "unless", "table"})
SCALARS = {"Int": "integer", "Integer": "integer", "Text": "string", "Bool": "boolean", "Date": "date"}
COMPARE = rules_dl.COMPARE
NEGATED = {"eq": "ne", "ne": "eq", "lt": "ge", "le": "gt", "gt": "le", "ge": "lt"}
KNOWN, UNKNOWN = ("const", "known", "string"), ("const", "unknown", "string")
EMPTY, NO_VALUE = ("const", "", "string"), ("const", "no_value", "string")
SENTINEL = {"string": ("const", "", "string"), "boolean": ("const", "false", "boolean")}


def module_as_of(form: dict) -> bool:
    """Whether a module declares an evaluation date, which only the calculation IR reads."""
    return any(isinstance(d, dict) and "asOf" in d for d in form["module"]["decls"])


def is_derivation(form: dict | None, derived: object) -> bool:
    """Whether a derived value of a kind or an extension in `form` lowers here rather than to rezono.calc/1."""
    return (form is not None and form.get("format") == REZONO_1_FORMAT and isinstance(derived, dict)
            and not (CALC_ONLY & derived.keys()) and not module_as_of(form))


def is_module_derived(decl: object) -> bool:
    """A module-level `derived name(params): T` declaration."""
    return isinstance(decl, dict) and isinstance(decl.get("derived"), str)


Note = rules_dl.RuleNote


@dataclass
class Lowered:
    sources: tuple[rules_dl.NativeSource, ...] = ()
    notes: dict[str, Note] = field(default_factory=dict)  # relation -> its sentence and source
    properties: dict[str, tuple[str, str]] = field(default_factory=dict)  # relation `<k>_<d>` -> (k, d)


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


def lower_pack(root: str, mods: Iterable[modules.Module], names: modules.Names, pack) -> Lowered:
    """The rules of every rezono 1 derivation of the pack being compiled, as native sources for the assembler."""
    from .pack import CompileError

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
        sites[module.rel] = site
        for at, decl, owner in _derivations(module.form):
            try:
                if module.pack != root:
                    site.refuse(at, "a derivation of an imported rezono 1 pack is not lowered yet")
                signature = _signature(site, module, names, pack, at, decl, owner)
                if signature.relation in signatures:
                    site.refuse(at, f"{signature.relation} is derived twice")
                signatures[signature.relation] = signature
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
        out = statements.setdefault(signature.module.rel, ([], []))
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
        if "means" in decl or "source" in decl:
            line, column = signature.site.place(f"{signature.at}/means" if "means" in decl else signature.at)
            lowered.notes[name] = Note(decl.get("means"), decl.get("source"), signature.site.file, line, column,
                                       f"{signature.at}/means")
        if signature.property is not None:
            lowered.properties[name] = (signature.kind, signature.property)
    if refused:
        raise CompileError("\n".join(map(str, refused)), refused)
    sources = []
    for module in found:
        stmts, columns = statements.get(module.rel, ([], []))
        if stmts:
            site = sites[module.rel]
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


def _type(site: Site, names: modules.Names, pack, module: modules.Module, at: str, text: object) -> tuple:
    if not isinstance(text, str):
        site.refuse(at, "a derivation needs a type")
    if text in SCALARS:
        return "scalar", SCALARS[text]
    engine = names.resolve(module.id, text)
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


def _signature(site: Site, module: modules.Module, names: modules.Names, pack, at: str, decl: dict,
               owner: dict | None) -> Signature:
    allowed = {"derived", "type", "card", "value", "means", "source"} | ({"params", "over"} if owner is None else set())
    if extra := sorted(set(decl) - allowed):
        site.refuse(at, f"`{extra[0]}` on a rezono 1 derivation is not lowered yet")
    if "value" not in decl:
        site.refuse(at, "a derivation without `=` is not lowered yet")
    card = decl.get("card")
    if card not in (None, "?"):
        site.refuse(at, f"a set-valued derivation `{decl.get('type')}{card}` is not lowered yet")
    result_type = _type(site, names, pack, module, at, decl.get("type"))
    boolean = result_type == ("scalar", "boolean") and card is None
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
        kind = names.resolve(module.id, kind_name) if isinstance(kind_name, str) else None
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
    validate_note(site, at, decl)
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

    def run(self) -> None:
        sig, value = self.sig, self.sig.decl["value"]
        at = f"{sig.at}/value"
        key_columns = [(sig.key_column or name, ir_type(self.pack, typ)) for name, typ in sig.key]
        if sig.result == "set":
            self.declare(sig.relation, key_columns)
            for alternative in self.alternatives(at, value):
                self.rule(sig.relation, self.key_terms(), self.domain() + alternative)
            return
        if sig.domain not in self.pack.kinds and sig.domain not in self.signatures and sig.property is None:
            self.site.refuse(f"{sig.at}/over", f"`over` names a set this pack derives in rezono 1, not {sig.domain}")
        if sig.domain in self.signatures and self.signatures[sig.domain].result != "set":
            self.site.refuse(f"{sig.at}/over", f"the domain {sig.domain} is a Bool set, not a functional derivation")
        meta = {"domain": sig.domain, "value": {"name": "value", "type": sig.value_type}, "conflict_policy": "publish"}
        if set(value) == {"agg"} and isinstance(value["agg"], list) and value["agg"][:1] == ["one"]:
            meta |= {"empty_state": "not_applicable" if sig.optional else "unknown", "empty_reason": "no_match"}
            self.statements.append(("functional", sig.relation, key_columns, self.line, meta))
            self.one(at, value["agg"])
        elif set(value) == {"agg"} and isinstance(value["agg"], list) and value["agg"][:1] == ["count"]:
            if sig.value_type != "integer":
                self.site.refuse(at, "a count is a whole number: declare the derivation `Int`", "R003")
            self.statements.append(("functional", sig.relation, key_columns, self.line, meta))
            self.count(at, value["agg"])
        elif set(value) == {"path"}:
            literals, term, optional = self.path(at, value["path"])
            meta |= {"empty_state": "not_applicable" if optional else "unknown", "empty_reason": "no_value"}
            self.statements.append(("functional", sig.relation, key_columns, self.line, meta))
            self.rule(sig.relation, self.key_terms() + [term], self.domain() + literals)
        else:
            self.site.refuse(at, "only a slot path, `.count(...)` and `.one(...)` lower to a functional derivation yet")

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
        if token in ("yes", "true"):
            return "const", "true", "boolean"
        if token in ("no", "false"):
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
        relation = self.names.resolve(self.sig.module.id, name) if name not in self.signatures else name
        target = self.signatures.get(relation)
        if target is None or target.result != "set":
            self.site.refuse(at, f"{name} is not a Bool set derived in this pack", "R001")
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
            kind = self.names.resolve(self.sig.module.id, node["kind"])
            if kind not in self.pack.kinds:
                self.site.refuse(at, f"{node['kind']} is not a kind of the pack", "R001")
            if self.pack.kinds[kind].world == "open":
                self.site.refuse(at, f"{node['kind']} is open, so a count or `.one()` over it is only what is "
                                     "recorded; it is not lowered", "R004")
            member = ("var", self.fresh("m"))
            return Member([member], self.lit(kind, [member]), kind, {}, pred)
        if set(node) == {"path"} and len(node["path"]) == 1 and node["path"][0] not in self.env:
            name = node["path"][0]
            target = self.signatures.get(name)
            if target is None or target.result != "set" or target.property is not None:
                self.site.refuse(at, f"{name} is not a relation derived in this pack", "R001")
            terms = [("var", self.fresh(column)) for column, _ in target.key]
            columns = {column: (index, typ) for index, (column, typ) in enumerate(target.key)}
            return Member(terms, self.lit(name, terms), None, columns, pred)
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
            owner, note = root, derived_note
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
