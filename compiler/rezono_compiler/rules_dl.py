"""Read a pack's rules/*.dl (a Soufflé subset) into a rule IR document (contracts/rules.yaml).

The file is Soufflé syntax, so Soufflé can serve as the oracle. What it may contain:

    .decl relies_on(a: symbol, b: symbol)        derived relation: columns and types (symbol, number, boolean, date)
    .input k, k__a  /  .output relies_on         accepted; .input names a table, .output a derived relation
    head(x, y) :- p(x, z), !q(z), n = count : { r(x, _) }, s = sum v : { t(x, _, v) }, n > 1, m = n + 1.

Base predicates are the tables of the schema (M1): `k(id)` per kind and `k__a(id, v)` per arrow or
attribute, plus the parameter tables (enum values, bounds). A rule reads them by name; a `.decl` for a
table is optional and must agree with the schema. Columns can hold text, whole numbers, booleans or dates.

A variable inside an aggregate that no positive literal binds is local to the aggregate: it ranges over
the group, like '_'. The variable after `sum`, `min` or `max` names the column that is aggregated.

A rule id is the relation name, or `<relation>_<n>` (from 1, in file order) when a relation has more
rules. A comment line `// @explain materialize` or `// @explain on_demand` right above a `.decl` sets
the explain mode; without it, a relation whose rules project away a variable is explained on demand.
`// @explain fold` on the line right above a `.decl` (below a mode line, if there is one) marks a helper
relation. It is display only and kept beside the IR (fold.py): the IR, the witnesses and the checker never
see it.
A comment line `// @invariant` above a `.decl` makes it an invariant: it must be empty at the end of an
epoch, or the epoch is not published (correctness blocks). `// @release <role>` is reserved for a
delimited release under O8 and refused until it is built. `// @closes <relation>` above a `.decl` says that a
row of this relation states, for its key, that no row of that relation holds there: the
compiler adds the invariant `<this>_closes_<relation>`, the keys at which both hold.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from . import rules as ir
from .diagnostics import Diagnosed, Diagnostic

TOKEN = re.compile(r"""
    (?P<ws>[ \t\r]+) | (?P<nl>\n) | (?P<line>//[^\n]*) | (?P<block>/\*.*?\*/) |
    (?P<string>"(?:[^"\\\n]|\\.)*") | (?P<number>[0-9]+) | (?P<directive>\.[a-z]+) |
    (?P<ident>[A-Za-z_][A-Za-z0-9_]*) |
    (?P<op>:-|!=|<=|>=|[(),.:{}!=<>+\-*;|&^%/\[\]$@#])
""", re.X | re.S)
TYPES = {"symbol": "string", "number": "integer", "boolean": "boolean", "date": "date"}
SYMBOLS = {t: s for s, t in TYPES.items()}
SQL = {"VARCHAR": "string", "BIGINT": "integer", "BOOLEAN": "boolean", "DATE": "date"}
BOOLEAN_LITERALS = {"TRUE": "true", "FALSE": "false"}
COMPARE = {"=": "eq", "!=": "ne", "<": "lt", "<=": "le", ">": "gt", ">=": "ge"}
COMPARE_AS = ir.COMPARE_AS  # `binary_text(x) < binary_text(y)`: a comparison type, written on both operands
ARITH = {"+": "add", "-": "sub", "*": "mul", "/": "div"}
FUNCTIONS = ("count", "sum", "min", "max")
VARIABLE = re.compile(r"^[a-z][a-z0-9_]*$")
EXPLAIN = re.compile(r"^//\s*@explain\s+(\S+)\s*$")
FOLD = "fold"  # `// @explain fold`: no explain mode but a display mark (fold.py)
INVARIANT = re.compile(r"^//\s*@invariant\s*$")
ABSENCE = re.compile(r"^//\s*@absence\s*$")
RELEASE = re.compile(r"^//\s*@release\b")  # reserved (O8, delimited release): refused until it is built
OUTCOME = re.compile(r"^//\s*@outcome(?:\s+(\S+))?\s*$")
EXTEND = re.compile(r"^//\s*@extend\s*$")
CHECKED_ABSENCE = "absent_checked"  # reserved conclusion of decisions/scoped-completeness.md
RECEIPT_INPUT = "verified_receipt"  # protected: only admission fills it (decisions/admission-transport.md)
RECEIPT_LOOKUP = "registered_match"  # the lookup over the contents of one receipt
RECEIPT_MEMBER = "verified_member"  # protected: the admitted member keys of one receipt
# Protected admission inputs (decisions/admission-transport.md, section 6): a pack declares one with exactly
# this signature and no clause; only admission fills it, as base rows before the rules run.
PROTECTED = {
    RECEIPT_INPUT: [("receipt", "string"), ("source", "string"), ("scope", "string"), ("cut", "string"),
                    ("inventory", "string"), ("content", "string")],
    RECEIPT_MEMBER: [("receipt", "string"), ("member", "string"), ("part", "integer"), ("value", "string")],
    "verified_round": [("round", "string"), ("run", "string"), ("cut", "string"), ("batch", "string")],
    "verified_round_member": [("round", "string"), ("step", "string")],
}
CLOSES = re.compile(r"^//\s*@closes\s+(\S+)\s*$")


class RuleError(ValueError):
    pass


class ProtectedTable(RuleError, Diagnosed):
    """A schema table (kind, slot or enum) under the name of a protected admission input (PROTECTED). Only
    admission fills such a relation (decisions/admission-transport.md, section 6), so the name is reserved."""
    CODE = "schema_table_protected"

    def __init__(self, messages: list[str]):
        Diagnosed.__init__(self, "\n".join(messages), tuple(Diagnostic(self.CODE, message) for message in messages))


class DuplicateDerivation(RuleError, Diagnosed):
    """A functional derivation of a rezono 1 module under the name of a table or of another relation."""
    CODE = "duplicate_relation"

    def __init__(self, message: str):
        Diagnosed.__init__(self, message, (Diagnostic(self.CODE, message),))


@dataclass(frozen=True)
class Embedded:
    """Rule text placed at its original source lines and columns."""

    pack: str
    stem: str
    file: str
    text: str


@dataclass(frozen=True)
class RuleNote:
    """Optional sentence and source carried by a native rule clause."""

    means: str | None = None
    source: str | None = None
    means_at: str = ""
    means_line: int = 1
    means_column: int = 1


@dataclass(frozen=True)
class NativeSource:
    """Authored rule statements with their resolved names and head positions."""

    pack: str
    stem: str
    file: str
    text: str
    statements: tuple[tuple, ...]
    columns: tuple[int, ...]
    notes: tuple[RuleNote | None, ...] = ()
    semantics: tuple[tuple[str, tuple[dict | None, ...]], ...] = ()


@dataclass
class Tok:
    kind: str
    text: str
    line: int
    comments: tuple = ()  # the line comments right before this token
    start: int = -1  # the offset in the text, so a schema operation can edit just this token


def tokens(text: str, where: str) -> list[Tok]:
    out, line, pos, comments = [], 1, 0, []
    while pos < len(text):
        m = TOKEN.match(text, pos)
        if not m:
            raise RuleError(f"{where}:{line}: unexpected {text[pos]!r}")
        kind = m.lastgroup
        if kind == "line":
            comments.append(m.group())
        elif kind in ("string", "number", "directive", "ident", "op"):
            out.append(Tok(kind, m.group(), line, tuple(comments), m.start()))
            comments = []
        line += m.group().count("\n")
        pos = m.end()
    out.append(Tok("end", "", line))
    return out


def unescape(s: str) -> str:
    return re.sub(r"\\(.)", lambda m: {"n": "\n", "t": "\t"}.get(m.group(1), m.group(1)), s)


class Parser:
    def __init__(self, toks: list[Tok], where: str):
        self.toks, self.i, self.where = toks, 0, where

    def peek(self, k=0) -> Tok:
        return self.toks[self.i + k]

    def fail(self, msg: str, tok: Tok | None = None):
        raise RuleError(f"{self.where}:{(tok or self.peek()).line}: {msg}")

    def take(self, text: str | None = None, kind: str | None = None) -> Tok:
        t = self.peek()
        if (text is not None and t.text != text) or (kind is not None and t.kind != kind):
            self.fail(f"expected {text or kind}, found {t.text or 'end of file'!r}")
        self.i += 1
        return t

    def at(self, text: str) -> bool:
        return self.peek().text == text and self.peek().kind != "string"


def term(p: Parser):
    """('var', name) | ('wild',) | ('const', text, type) — a term of an atom or a comparison."""
    t = p.peek()
    if t.kind == "op" and t.text == "-" and p.peek(1).kind == "number":
        p.i += 2
        return ("const", str(-int(p.toks[p.i - 1].text)), "integer")
    p.i += 1
    if t.kind == "number":
        return ("const", str(int(t.text)), "integer")
    if t.kind == "string":
        text = unescape(t.text[1:-1])
        if text == "_" or text.startswith("?"):
            p.fail(f"the constant {t.text} cannot be written in the rule IR (it starts with '?' or is '_')", t)
        return ("const", text, "string")
    if t.kind == "ident":
        if t.text in BOOLEAN_LITERALS:
            return ("const", BOOLEAN_LITERALS[t.text], "boolean")
        if t.text == "_":
            return ("wild",)
        if not VARIABLE.match(t.text):
            p.fail(f"variable '{t.text}': variables are lower snake case", t)
        return ("var", t.text)
    p.fail(f"expected a term, found {t.text!r}", t)


def atom(p: Parser):
    name = p.take(kind="ident")
    p.take("(")
    terms = []
    if not p.at(")"):
        terms.append(term(p))
        while p.at(","):
            p.take(",")
            terms.append(term(p))
    p.take(")")
    return name.text, terms, name.line


def annotation(p: Parser, left: bool = True):
    """`binary_text(x)` or `utc_instant(x)` before a comparison operator: (mode, variable term)."""
    name = p.take(kind="ident")
    p.take("(")
    t = term(p)
    if t[0] != "var":
        p.fail(f"{name.text}(…) takes one variable", name)
    p.take(")")
    if left and not (p.peek().kind == "op" and p.peek().text in COMPARE):
        p.fail(f"{name.text}(…) only as an operand of a comparison", name)
    return name.text, t


def body_item(p: Parser):
    """One body element: ('lit', polarity, atom) | ('agg', var, fn, target, atom) | ('cmp', op, l, r) | ('arith', var, op, l, r)."""
    if p.at("!"):
        p.take("!")
        return ("lit", "negative", atom(p))
    mode = None
    if p.peek().kind == "ident" and p.peek(1).text == "(":
        if p.peek().text not in COMPARE_AS:
            return ("lit", "positive", atom(p))
        mode = annotation(p)
        left = mode[1]
    else:
        left = term(p)
    op = p.take(kind="op").text
    if op not in COMPARE:
        p.fail(f"'{op}' is not a comparison")
    nxt, after = p.peek(), p.peek(1)
    if (op == "=" and left[0] == "var" and nxt.kind == "ident" and nxt.text in FUNCTIONS
            and (after.text == ":" or after.kind == "ident")):
        fn = p.take(kind="ident").text
        target = None
        if fn != "count":
            target = term(p)
            if target[0] != "var":
                p.fail(f"{fn} aggregates a variable of the aggregate")
        p.take(":")
        p.take("{")
        a = atom(p)
        if p.at(","):
            p.fail("an aggregate ranges over one atom; derive a relation first")
        p.take("}")
        return ("agg", left[1], fn, target and target[1], a)
    if mode:
        if not (p.peek().kind == "ident" and p.peek().text == mode[0] and p.peek(1).text == "("):
            p.fail(f"{mode[0]}(…) on one side of a comparison only; write it on both operands")
        right = annotation(p, False)[1]
        if p.peek().kind == "op" and p.peek().text in ARITH:
            p.fail(f"{mode[0]}(…) does not take arithmetic")
        return ("cmp", COMPARE[op], left, right, mode[0])
    if p.peek().kind == "ident" and p.peek().text in COMPARE_AS and p.peek(1).text == "(":
        p.fail(f"{p.peek().text}(…) on one side of a comparison only; write it on both operands")
    if op == "=" and left[0] == "var" and nxt.text == "@":
        p.take("@")
        name = p.take(kind="ident")
        if name.text != ir.DAYS:
            p.fail(f"@{name.text} is not a functor; the only one is @{ir.DAYS}(text, \"YYYY-MM-DD\")")
        p.take("(")
        text_term = term(p)
        p.take(",")
        origin = term(p)
        p.take(")")
        return ("arith", left[1], ir.DAYS, text_term, origin)
    right = term(p)
    if p.peek().kind == "op" and p.peek().text in ARITH:
        if op != "=" or left[0] != "var":
            p.fail("arithmetic only as 'variable = term op term'")
        aop = ARITH[p.take().text]
        third = term(p)
        return ("arith", left[1], aop, right, third)
    return ("cmp", COMPARE[op], left, right)


def parse_file(text: str, where: str, columns: list | None = None):
    """Statements of one file: ('decl', name, cols, line, explain, …, fold) | ('io', kind, names, line) |
    ('rule', head, body, line). `columns` receives the column of each rule's head, from 1, in order (MOD2)."""
    p = Parser(tokens(text, where), where)
    lines = text.split("\n")
    out = []
    while p.peek().kind != "end":
        t = p.peek()
        if t.kind == "directive":
            p.i += 1
            if t.text == ".decl":
                name = p.take(kind="ident").text
                p.take("(")
                cols = []
                while not p.at(")"):
                    c = p.take(kind="ident").text
                    p.take(":")
                    ty = p.take(kind="ident").text
                    if ty not in TYPES:
                        p.fail(f"{name}.{c}: type '{ty}' is not supported (symbol, number, boolean or date)")
                    cols.append((c, TYPES[ty]))
                    if not p.at(")"):
                        p.take(",")
                p.take(")")
                if not cols:
                    p.fail(f"{name}: a relation needs at least one column")
                if p.peek().kind == "ident" and p.peek().text in ("btree", "brie", "eqrel", "inline", "magic", "overridable"):
                    p.fail(f"{name}: relation qualifiers are not supported")
                explain, invariant, absence, outcome, extend, closes, fold = None, False, False, None, False, None, False
                for c in t.comments:
                    if re.match(r"^//\s*@closes\b", c.strip()):
                        m = CLOSES.match(c.strip())
                        if not m or closes is not None:
                            p.fail(f"{name}: @closes names one relation, once per .decl", t)
                        closes = m.group(1)
                    if re.match(r"^//\s*@extend\b", c.strip()) and not EXTEND.match(c.strip()):
                        p.fail(f"{name}: @extend takes no argument", t)
                    if RELEASE.match(c.strip()):
                        p.fail(f"{name}: @release is not supported yet: a role reads a negation or an aggregate only over relations it reads in full (docs/formal.md, section 3; decisions/language-native-rules.md: delimited release stays reserved)", t)
                    m = EXPLAIN.match(c.strip())
                    if m and m.group(1) == FOLD:
                        fold = True
                    elif m:
                        explain = m.group(1)
                    invariant = invariant or bool(INVARIANT.match(c.strip()))
                    absence = absence or bool(ABSENCE.match(c.strip()))
                    extend = extend or bool(EXTEND.match(c.strip()))
                    m = OUTCOME.match(c.strip())
                    if m:
                        outcome = m.group(1) or ""
                above = EXPLAIN.match(lines[t.line - 2].strip()) if fold else None
                if fold and not (above and above.group(1) == FOLD):  # where the explanation lint reads the mark
                    p.fail(f"{name}: @explain fold goes on the line right above the .decl", t)
                out.append(("decl", name, cols, t.line, explain, invariant, absence, outcome, extend, closes, fold))
            elif t.text in (".input", ".output"):
                names = [p.take(kind="ident").text]
                while p.at(","):
                    p.take(",")
                    names.append(p.take(kind="ident").text)
                if p.at("("):
                    p.fail(f"{t.text} takes relation names only; facts come from facts/")
                out.append(("io", t.text[1:], names, t.line))
            else:
                p.fail(f"directive {t.text} is not supported", t)
            continue
        start = p.peek().start
        head = atom(p)
        if p.at("."):
            p.fail(f"{head[0]}: a fact in a rule file; facts belong in facts/")
        p.take(":-")
        body = [body_item(p)]
        while p.at(","):
            p.take(",")
            body.append(body_item(p))
        if p.at(";"):
            p.fail("disjunction is not supported; write two rules")
        p.take(".")
        out.append(("rule", head, body, head[2]))
        if columns is not None:
            columns.append(start - text.rfind("\n", 0, start))
    return out


def base_tables(pack) -> dict[str, list[tuple[str, str | None]]]:
    """Every table a rule may read, with its columns: (name, IR type or None if rules cannot read it)."""
    out = {}
    for k, kind in pack.kinds.items():
        idt = pack.kinds[pack.root(k)].id_type
        out[k] = [("id", SQL.get(idt))]
        for s in kind.slots.values():
            out[s.table] = [("id", SQL.get(idt)), ("v", SQL.get(s.sql_type))]
    for e in pack.enums:
        out[e] = [("id", "string")]
    for kind in pack.kinds.values():
        for s in kind.slots.values():
            for b in ("minimum", "maximum", "minimum_cardinality", "maximum_cardinality"):
                if getattr(s, b) is not None:
                    out[f"{s.table}__{b}"] = [("v", "integer")]
            if s.constant is not None:
                out[f"{s.table}__constant"] = [("v", SQL.get(s.sql_type))]
    for seal in pack.seals:  # refused and accepted input, made by the compiler
        idt = SQL.get(pack.kinds[seal.kind].id_type)
        out[seal.refused] = [("id", idt), ("period_close", SQL.get(pack.kinds[pack.root("period_close")].id_type))]
        out[seal.accepted] = [("id", idt)]
        for part in seal.parts:  # a part counts when the element it is part of does
            out[part.accepted] = [("id", SQL.get(pack.kinds[part.kind].id_type))]
    return out


def reserved(pack) -> list[str]:
    """The tables of the schema whose name is a protected admission input. Such a name is reserved: a kind,
    slot or enum table under it would be read as the admitted relation, whose rows only admission gives
    (decisions/admission-transport.md, section 6), so the pack's own facts would silently be replaced."""
    return [f"schema: the table {name} (a kind, slot or enum) has the name of a protected admission input; "
            "that name is reserved, rename it" for name in sorted(PROTECTED.keys() & base_tables(pack).keys())]


def seal_docs(pack) -> list[dict]:
    """The seals of the rule IR: the tables the checker recomputes refused and accepted input from.
    Written also for a pack without rules (emit), so the check never falls away. `parts` only when the seal
    has parts (`sealed_with`), so a seal without them reads as before."""
    def doc(s):
        d = {"kind": s.kind, "period": s.period.table, "row_sha256": s.row_sha256, "tables": s.tables,
             "closed_until": "period_close__closed_until", "covers": "period_close__covers",
             "element": f"{s.cover}__element", "sha256": f"{s.cover}__sha256",
             "refused": s.refused, "accepted": s.accepted}
        if s.parts:
            d["parts"] = [{"kind": p.kind, "arrow": p.arrow.table, "owner": p.owner, "tables": p.tables,
                           "accepted": p.accepted} for p in s.parts]
        return d
    return [doc(s) for s in pack.seals]


def base_worlds(pack) -> dict[str, str]:
    """What a missing row means per table: the kind's world for k(id), the slot's for k__a.
    Parameter tables are closed."""
    out = {}
    for k, kind in pack.kinds.items():
        out[k] = kind.world
        for s in kind.slots.values():
            out[s.table] = s.world
    return out


def remap_statement(stmt, names):
    """Bind an imported statement to the consumer's schema names without touching text or variables."""
    def name(n):
        head, sep, tail = n.partition("__")
        return names.get(head, head) + sep + tail

    def kind_constant(t):
        return ("const", names.get(t[1], t[1]), "string") if t[0] == "const" and t[2] == "string" else t

    def atom(a):
        n, terms, line = a
        terms = list(terms)
        # The access vocabulary's second column names a schema kind, rather than an ordinary value.
        if n in ("may_read", "may_read_full", "may_propose", "may_review", "may_publish") and len(terms) > 1:
            t = terms[1]
            terms[1] = kind_constant(t)
        return name(n), terms, line

    if stmt[0] == "decl":
        s = list(stmt)
        s[1] = name(s[1])
        if s[7] is not None:
            s[7] = names.get(s[7], s[7])
        if s[9] is not None:
            s[9] = name(s[9])
        return tuple(s)
    if stmt[0] == "io":
        return stmt[0], stmt[1], [name(n) for n in stmt[2]], stmt[3]
    atoms = [stmt[1]] + [s[-1] for s in stmt[2] if s[0] in ("lit", "agg")]
    kind_vars = {a[1][1][1] for a in atoms if a[0] in ("may_read", "may_read_full", "may_propose", "may_review", "may_publish")
                 and len(a[1]) > 1 and a[1][1][0] == "var"}
    # Equality aliases keep the typed meaning of an access-kind column.
    changed = True
    while changed:
        before = len(kind_vars)
        for s in stmt[2]:
            if s[0:2] == ("cmp", "eq") and s[2][0] == s[3][0] == "var":
                if s[2][1] in kind_vars or s[3][1] in kind_vars:
                    kind_vars.update((s[2][1], s[3][1]))
        changed = len(kind_vars) != before
    body = []
    for s in stmt[2]:
        if s[0] in ("lit", "agg"):
            s = (*s[:-1], atom(s[-1]))
        elif s[0] == "cmp":
            _, op, left, right, *typed = s
            if left[0] == "var" and left[1] in kind_vars:
                right = kind_constant(right)
            if right[0] == "var" and right[1] in kind_vars:
                left = kind_constant(left)
            s = "cmp", op, left, right, *typed
        body.append(s)
    return stmt[0], atom(stmt[1]), body, stmt[3]


def at_line(stmt, at: list[int]):
    """A statement of generated text at the line of its source: `at[n - 1]` for its line n, and its head's."""
    s = list(stmt)
    s[3] = at[s[3] - 1]
    if s[0] == "rule":
        s[1] = (*s[1][:-1], at[s[1][-1] - 1])
    return tuple(s)


def module_of(source: str, root: str, stem: str) -> str:
    """The module of a rule file: its name in the pack `root` itself, `import_<pack>_<file>` in an imported pack."""
    return stem if source == root else f"import_{source.replace('-', '_')}_{stem}"


def read(pack, pack_dir: Path, imports=None, renames=None, *, calc_inputs=None, calc_parts=None,
         folds: dict | None = None, bodies: dict | None = None, spans: dict | None = None,
         rule_sources: dict[str, str] | None = None,
         rule_sentences: dict[str, tuple[str, RuleNote, str]] | None = None,
         generated: list | None = None, embedded: tuple[Embedded, ...] = (),
         native: tuple[NativeSource, ...] = (),
         semantics: dict | None = None) -> tuple[dict | None, list[str]]:
    """The IR of the pinned rule closure (None when every rules/ is empty), and warnings. Raises RuleError.

    `calc_parts` is each imported pack's part of the calculation (`calc.read_closure`): a rule reads a
    selection that its own pack or a pack it imports gives. `folds` receives, per derived relation marked
    `// @explain fold`, where its `.decl` is: the mark is no part of the IR. `bodies` receives, per rule id, the
    kind of each body literal in source order (LITERAL): the IR splits them over four lists, and the bundle
    publishes the body as written (MOD14). `spans` receives, per rule id, its (file, line, column): of its head,
    or for a rule `@closes` generates, of the `.decl` that has the mark (MOD2). `generated` is the rule text of the
    decision tables of the pack's modules written in Rezono (rezono_table.Generated): each is read as a rule file
    of the pack is, its module the module's id, its file and lines the module's (docs/rezono/publication.md §9.1).
    `embedded` contains relational block text aligned to its source coordinates; `native` holds checked
    statements and head columns from authored Rezono rule modules."""
    from .calc import selection_name  # calc reads this module, so it is imported here

    imports, renames = imports or {}, renames or {}
    calc_inputs = calc_inputs or {}
    root = pack.meta["name"]
    if clash := reserved(pack):  # before any rule is read: also a pack without rules may not take the name
        raise ProtectedTable(clash)
    givers = {}  # selection -> the packs whose calc files give its rule; any other is the root's own
    for name, doc in (calc_parts or {}).items():
        for version in doc.get("rules") or []:
            if isinstance(version, dict) and isinstance(version.get("rule"), str):
                givers.setdefault(selection_name(version["rule"]), []).append(name)
    sources = [(p.name, p.dir) for p in imports.values()] + [(root, Path(pack_dir))]
    files = [(owner, f) for owner, at in sources for f in sorted((at / "rules").glob("*.dl"))]
    entries = [(source, f.stem, f"rules/{f.name}" if source == root else f"{source}:rules/{f.name}", f, None)
               for source, f in files]
    entries += [(item.pack, item.stem, item.file if item.pack == root else f"{item.pack}:{item.file}",
                 item.text, None) for item in embedded]
    entries += [(item.pack, item.stem, item.file, item, None) for item in native]
    # Process dependency packs first so their relations can be extended by importers.
    source_order = {owner: index for index, (owner, _) in enumerate(sources)}
    entries.sort(key=lambda entry: (source_order[entry[0]], entry[1]))
    entries += [(root, g.stem, g.module, g.text, g.at) for g in generated or []]
    if not entries:
        return None, []
    tables = base_tables(pack)
    decls, owners, explains, io, rules_src, errors, warnings = {}, {}, {}, [], [], [], []
    functional = {}  # name -> (key columns, its domain, value and policies): a rezono 1 functional derivation
    invariants, absences, outcomes = set(), set(), {}
    extensions, declared_in, options, closing = set(), {}, {}, {}
    visible = {root: {root, *imports}}
    for n, p in imports.items():
        visible[n] = {n}
        for dep in p.imports:
            visible[n] |= visible[dep]
    worlds = base_worlds(pack)
    module_sources, texts = {}, {}
    for source, stem, where, contents, at in entries:
        module = module_of(source, root, stem)
        if not ir.NAME.match(stem):
            errors.append(f"{where}: module name '{stem}' is not lower snake case")
            continue
        if module_sources.setdefault(module, where) != where:
            errors.append(f"{where}: module {module} collides with {module_sources[module]}")
            continue
        try:
            if isinstance(contents, NativeSource):
                text, stmts, starts = contents.text, contents.statements, list(contents.columns)
                notes: list[RuleNote | None] = list(contents.notes) if contents.notes else [None] * len(starts)
                if semantics is not None:
                    semantics.update(contents.semantics)
            else:
                text = contents.read_text(encoding="utf-8") if isinstance(contents, Path) else contents
                starts = []
                stmts = [remap_statement(s, renames.get(source, {})) for s in parse_file(text, where, starts)]
                if at is not None:  # a column of the generated text is no place in the module
                    stmts, starts = [at_line(s, at) for s in stmts], [1] * len(starts)
                notes = [None] * len(starts)
            # The same module can also supply generated rules. Keep its aligned authored text.
            texts.setdefault(where, text)
        except RuleError as e:
            errors.append(str(e))
            continue
        for s in stmts:
            if s[0] == "decl":
                _, name, cols, line, explain, invariant, absence, outcome, extend, closes, fold = s
                if name in calc_inputs:
                    errors.append(f"{where}:{line}: {name} is a calculation selection and cannot be declared in rules")
                    continue
                if name in tables:
                    if extend:
                        errors.append(f"{where}:{line}: @extend is for derived relations, not the table {name}")
                    if invariant:
                        errors.append(f"{where}:{line}: @invariant is for derived relations, not the table {name}")
                    if absence or outcome is not None:
                        errors.append(f"{where}:{line}: @absence and @outcome are for derived relations, not the table {name}")
                    if fold:
                        errors.append(f"{where}:{line}: @explain fold is for derived relations, not the table {name}")
                    if closes is not None:
                        errors.append(f"{where}:{line}: @closes is for derived relations, not the table {name}")
                    want = [t for _, t in tables[name]]
                    if [t for _, t in cols] != want:
                        errors.append(f"{where}:{line}: .decl {name} does not match its table "
                                      f"({', '.join(f'{c}: {t}' for c, t in tables[name])})")
                    continue
                if name in decls:
                    if declared_in[name] == source or declared_in[name] not in visible[source] or name not in extensions:
                        errors.append(f"{where}:{line}: {name} is declared twice (also in {owners[name]}); "
                                      "only an imported @extend relation may be redeclared")
                    elif cols != decls[name] or (explain is not None and explain != options[name][0]) or \
                            (invariant, absence, outcome, closes, fold) != options[name][1:]:
                        errors.append(f"{where}:{line}: .decl {name} must match the imported declaration and annotations")
                    continue
                if name in PROTECTED and (cols != PROTECTED[name] or extend or invariant or absence or fold
                                          or outcome is not None or closes is not None or explain is not None):
                    errors.append(f"{where}:{line}: {name} is a protected admission input; declare it as "
                                  f".decl {name}({', '.join(f'{c}: {SYMBOLS[t]}' for c, t in PROTECTED[name])}) "
                                  "without annotations")
                    continue
                if not ir.NAME.match(name):
                    errors.append(f"{where}:{line}: derived relation '{name}' is not lower snake case without '__'")
                decls[name], owners[name] = cols, module
                declared_in[name] = source
                options[name] = (explain, invariant, absence, outcome, closes, fold)
                if fold and folds is not None:
                    folds[name] = f"{where}:{line}"
                if closes is not None:
                    closing[name] = (closes, where, line, source)
                if extend:
                    extensions.add(name)
                if invariant:
                    invariants.add(name)
                if absence:
                    absences.add(name)
                if outcome is not None:
                    if outcome not in pack.kinds:
                        errors.append(f"{where}:{line}: @outcome names a kind of the pack, not '{outcome}'")
                    outcomes[name] = outcome
                if explain is not None:
                    if explain not in ("materialize", "on_demand"):
                        errors.append(f"{where}:{line}: @explain is materialize, on_demand or fold, not '{explain}'")
                    explains[name] = explain
            elif s[0] == "functional":
                # A functional derivation of a rezono 1 module (rezono_derived.py): its key columns are its
                # declaration; a rule's head adds the value, a body reads (key..., state, reason, value).
                _, name, cols, line, meta = s
                if name in decls or name in tables or name in calc_inputs:
                    raise DuplicateDerivation(f"{where}:{line}: {name} is declared twice (also in "
                                              f"{owners.get(name, 'the schema')})")
                decls[name], owners[name], declared_in[name] = list(cols), module, source
                options[name] = (None, False, False, None, None, False)
                functional[name] = meta
            elif s[0] == "io":
                io.append((where, source, *s[1:]))
            else:
                rules_src.append((module, where, s[1], s[2], s[3], source, starts.pop(0), notes.pop(0)))
    for name, (closed, where, line, source) in closing.items():
        # The invariant the marker stands for, as the rule a pack would write for it, so it is
        # read, typed, compiled and proved as any rule. The IR holds its shape (rules.load); here only what
        # the rule needs: a target, and a name that is free.
        check = ir.closes_check(name, closed)
        if closed not in decls or closed == name:
            errors.append(f"{where}:{line}: @closes names another derived relation of the pack, not '{closed}'")
        elif declared_in[closed] not in visible[source]:
            errors.append(f"{where}:{line}: {source} does not import the owner of {closed}")
        elif check in decls or check in tables or check in calc_inputs:
            errors.append(f"{where}:{line}: {check} is the name of the check that @closes generates; "
                          "rename the relation that has it")
        else:
            key = [("var", c) for c, _ in decls[name]]
            rest = [("wild",)] * (len(decls[closed]) - len(key))
            decls[check], owners[check], declared_in[check] = decls[name], owners[name], declared_in[name]
            invariants.add(check)
            rules_src.append((owners[name], where, (check, key, line),
                              [("lit", "positive", (name, key, line)),
                               ("lit", "positive", (closed, key[:len(decls[closed])] + rest, line))], line, source,
                              texts[where].split("\n")[line - 1].find(".decl") + 1, None))
    if errors:
        raise RuleError("\n".join(errors))
    for where, source, kind, names, line in io:
        for n in names:
            if kind == "input" and n not in tables:
                errors.append(f"{where}:{line}: .input {n}: rules read only the tables of the schema")
            if kind == "input" and source != root and n.partition("__")[0] not in set(renames.get(source, {}).values()):
                errors.append(f"{where}:{line}: {n} is not a table visible to pack {source}")
            if kind == "output" and n not in decls:
                errors.append(f"{where}:{line}: .output {n} is not a derived relation")

    def columns(name):
        """The column types of a relation as a rule reads it, or None if it is unknown (reported later)."""
        if name in functional:
            return [t for _, t in decls[name]] + ["string", "string", functional[name]["value"]["type"]]
        if name in decls:
            return [t for _, t in decls[name]]
        if name in tables:
            return [t for _, t in tables[name]]
        if name in calc_inputs:
            return [t for _, t in calc_inputs[name]]
        return None

    count = {}
    for _, _, head, *_ in rules_src:
        count[head[0]] = count.get(head[0], 0) + 1
    seen, used = {}, set()
    relations, rules = {}, []
    for module, where, head, body, line, source, column, note in rules_src:
        rel = head[0]
        if rel not in decls:
            errors.append(f"{where}:{line}: {rel} has no .decl" + (" (it is a table; rules cannot define facts)" if rel in tables else ""))
            continue
        if declared_in[rel] != source:
            if declared_in[rel] not in visible[source] or rel not in extensions:
                errors.append(f"{where}:{line}: {rel} belongs to pack {declared_in[rel]}; "
                              "only its owner can mark it @extend")
                continue
            module = owners[rel]
        if rel in PROTECTED:
            errors.append(f"{where}:{line}: {rel} is a protected admission input; only admission fills it, "
                          "so no rule may derive it")
            continue
        if rel == CHECKED_ABSENCE and not checked_absence(head, body, rules_src):
            errors.append(f"{where}:{line}: {rel} needs a positive premise from the verified receipt "
                          f"({RECEIPT_INPUT}, or a projection of it such as complete) with the head's source, "
                          f"scope, cut and receipt, and a negative {RECEIPT_LOOKUP}(receipt, key) of the head that only "
                          f"projects {RECEIPT_MEMBER} of that same receipt; "
                          "a lookup alone proves no absence")
            continue
        accessible = set(renames.get(source, {}).values())
        atoms = [head] + [s[-1] for s in body if s[0] in ("lit", "agg")]
        for n, _, _ in atoms:
            if n in decls and declared_in[n] not in visible[source]:
                errors.append(f"{where}:{line}: {source} does not import the owner of {n}")
            if n in calc_inputs and not visible[source].intersection(givers.get(n, [root])):
                errors.append(f"{where}:{line}: {n} is a local calculation selection of {givers.get(n, [root])[0]}")
            if source != root and n in tables and n.partition("__")[0] not in accessible:
                errors.append(f"{where}:{line}: {n} is not a table visible to pack {source}")
        seen[rel] = seen.get(rel, 0) + 1
        rid = rel if count[rel] == 1 else f"{rel}_{seen[rel]}"
        try:
            rule = to_rule(rid, module, where, head, body, line, columns,
                           head_columns=lambda name: ([t for _, t in decls[name]] + [functional[name]["value"]["type"]]
                                                      if name in functional else columns(name)))
        except RuleError as e:
            errors.append(str(e))
            continue
        rules.append(rule)
        if bodies is not None:
            bodies[rid] = tuple(LITERAL[b[0]] for b in body)
        if spans is not None:
            spans[rid] = (where, line, column)
        if note is not None:
            if note.source is not None and rule_sources is not None:
                rule_sources[rid] = note.source
            if note.means is not None and rule_sentences is not None:
                rule_sentences[rid] = (source, note, where)
        for a in [rule["head"], *rule["body"], *rule.get("aggregates", [])]:
            used.add(a["relation"])
    used |= {k for k in outcomes.values() if k in tables}  # totality reads every element of the kind
    for name in sorted(used):
        if name in decls:
            continue
        if name in calc_inputs:
            relations[name] = {"name": name, "role": "calc", "world": "open",
                               "key": [{"name": c, "type": t} for c, t in calc_inputs[name]]}
            continue
        if name not in tables:
            errors.append(f"rules: {name} is neither a table of the schema nor a declared relation")
            continue
        bad = [c for c, t in tables[name] if t is None]
        if bad:
            errors.append(f"rules: {name} has a column that is not text, a whole number, a boolean or a date; "
                          "rules cannot read it yet")
            continue
        relations[name] = {"name": name, "role": "base", "key": [{"name": c, "type": t} for c, t in tables[name]],
                           "world": worlds.get(name, "closed")}
    for name, cols in decls.items():
        if name in functional:
            relations[name] = {"name": name, "role": "functional", "module": owners[name],
                               "key": [{"name": c, "type": t} for c, t in cols], **functional[name]}
            continue
        if name in PROTECTED:  # admitted rows enter as base rows; an empty relation leaves what needs it unknown
            relations[name] = {"name": name, "role": "base", "key": [{"name": c, "type": t} for c, t in cols],
                               "world": "closed"}
            continue
        relations[name] = {"name": name, "role": "derived", "module": owners[name],
                           "key": [{"name": c, "type": t} for c, t in cols]}
        if name in invariants:
            relations[name]["invariant"] = True
        if name in absences:
            relations[name]["absence"] = True
        if name in outcomes:
            relations[name]["outcome"] = outcomes[name]
        if name in extensions:
            relations[name]["extend"] = True
        if name in closing:
            relations[name]["closes"] = closing[name][0]
    if errors:
        raise RuleError("\n".join(errors))
    for r in rules:
        for a in r.get("aggregates", []):
            if isinstance(a.get("over"), dict):
                a["over"] = relations[a["relation"]]["key"][a["over"]["position"]]["name"]
        if relations[r["head"]["relation"]]["module"] != r["module"]:
            errors.append(f"{r['origin']['file']}:{r['origin']['line']}: a rule for {r['head']['relation']} "
                          f"belongs in rules/{relations[r['head']['relation']]['module']}.dl")
    if errors:
        raise RuleError("\n".join(errors))
    seals = seal_docs(pack)
    doc = {"format": ir.FORMAT_V2 if functional else ir.FORMAT, "pack": pack.meta["name"],
           "relations": sorted(relations.values(), key=lambda r: r["name"]),
           "rules": sorted(rules, key=lambda r: r["id"])}
    if seals:
        doc["seals"] = seals
    try:
        doc = ir.with_strata(doc)
        prog = ir.load(doc)
    except ir.IRError as e:
        raise RuleError(f"rules: {e}") from None
    for name, rel in relations.items():
        if rel["role"] not in ("derived", "functional"):
            continue
        projecting = [r.id for r in prog.rules_for(name) if r.projects]
        mode = explains.get(name) or ("on_demand" if projecting else "materialize")
        if mode == "materialize" and projecting:
            warnings.append(f"rules: {name} is materialized, but {', '.join(projecting)} projects a variable away; "
                            "its witnesses can be many per conclusion (consider @explain on_demand)")
        rel["explain"] = mode
    doc["relations"] = sorted(relations.values(), key=lambda r: r["name"])
    ir.load(doc)
    return doc, warnings


# The kind of a body element as the bundle names it (MOD14); to_rule keeps each kind in source order.
LITERAL = {"lit": "atom", "agg": "aggregate", "arith": "assignment", "cmp": "comparison"}


def receipt_binding(atom, rules_src, *, unfold=True):
    """The (source, scope, cut, receipt) terms a positive premise verifies, or None.

    Only the protected admission input verified_receipt(receipt, source, scope, cut, inventory, content)
    verifies a read; a pack cannot fill it. A derived relation such as std-completeness's `complete`
    counts only when every clause of it merely projects that input, so naming a relation `complete`
    and filling it proves nothing (decisions/scoped-completeness.md, section 2).
    """
    name, args, _ = atom
    if name == RECEIPT_INPUT:
        bound = (args[1], args[2], args[3], args[0]) if len(args) == 6 else None
        return None if bound is None or ("wild",) in bound else bound
    clauses = [(h, b) for _, _, h, b, *_ in rules_src if h[0] == name]
    if not unfold or not clauses or len(args) != 4 or ("wild",) in args:
        return None
    for clause_head, clause_body in clauses:
        if (len(clause_body) != 1 or clause_body[0][:2] != ("lit", "positive")
                or receipt_binding(clause_body[0][2], rules_src, unfold=False) != tuple(clause_head[1])):
            return None
    return tuple(args)


def checked_absence(head, body, rules_src) -> bool:
    """absent_checked(source, scope, cut, key, receipt) holds only on a verified read of that receipt
    and a negative lookup in the contents of that same receipt."""
    terms = tuple(head[1])
    if len(terms) != 5:
        return False
    bound = (*terms[:3], terms[4])
    verified = any(s[:2] == ("lit", "positive") and receipt_binding(s[2], rules_src) == bound for s in body)
    lookups = [s for s in body if s[0] == "lit" and s[2][0] == RECEIPT_LOOKUP]
    return verified and bool(lookups) and member_lookup(rules_src) and all(
        s[1] == "negative" and list(s[2][1]) == [terms[4], terms[3]] for s in lookups)


def member_lookup(rules_src) -> bool:
    """registered_match(receipt, key) reads the admitted contents of that receipt and nothing else.

    Every clause has the single premise verified_member(receipt, ...) with the head's receipt and key,
    so the pack cannot narrow the lookup until it never matches (decisions/scoped-completeness.md,
    section 2; decisions/admission-transport.md).
    """
    clauses = [(h, b) for _, _, h, b, *_ in rules_src if h[0] == RECEIPT_LOOKUP]
    for clause_head, clause_body in clauses:
        args = list(clause_head[1])
        if len(args) != 2 or ("wild",) in args or len(clause_body) != 1:
            return False
        premise = clause_body[0]
        if premise[:2] != ("lit", "positive") or premise[2][0] != RECEIPT_MEMBER or len(premise[2][1]) != 4:
            return False
        member = list(premise[2][1])
        if member[0] != args[0] or args[1] not in (member[1], member[3]):
            return False
    return bool(clauses)


def _terms(item):
    if item[0] == "lit":
        return item[2][1]
    if item[0] == "agg":
        return item[4][1]
    if item[0] == "arith":
        return [("var", item[1]), item[3], item[4]]
    return [item[2], item[3]]


def to_rule(rid, module, where, head, body, line, columns=lambda name: None, head_columns=None) -> dict:
    """One parsed rule as an IR rule (without strata and witness; with_strata fills them in).

    Constants keep the type they are written in: "2" is text and 2 a number, also in a comparison. `head_columns`
    gives the columns a head writes where they differ from those a body reads (a functional derivation)."""
    def fail(msg):
        raise RuleError(f"{where}:{line}: {msg}")

    def show(t):
        if t[0] == "wild":
            return "_"
        if t[0] == "const" and t[2] == "boolean":
            return t[1].upper()
        return '"' + t[1] + '"' if t[0] == "const" and t[2] == "string" else t[1]

    # Types: a constant has its own; a variable the column of its positive literal, or integer as a result.
    vtypes = {}
    for b in body:
        if b[0] == "lit" and b[1] == "positive":
            for t, ct in zip(b[2][1], columns(b[2][0]) or []):
                if t[0] == "var":
                    vtypes.setdefault(t[1], ct)
        elif b[0] in ("agg", "arith"):
            vtypes[b[1]] = "integer"

    def typ(t):
        return t[2] if t[0] == "const" else vtypes.get(t[1]) if t[0] == "var" else None

    atoms = [head] + [b[2] for b in body if b[0] == "lit"] + [b[4] for b in body if b[0] == "agg"]
    for position, (name, terms, _) in enumerate(atoms):
        typed = (head_columns or columns)(name) if position == 0 else columns(name)
        for i, (t, ct) in enumerate(zip(terms, typed or [])):
            if t[0] == "const" and t[2] != ct:
                fail(f"{show(t)} is {t[2]}, but column {i + 1} of {name} is {ct}")
    for b in body:
        if b[0] in ("cmp", "arith") and any(t[0] == "wild" for t in _terms(b)):
            fail("'_' only inside an aggregate, not in a comparison or arithmetic")
        if b[0] == "cmp":
            kinds = {typ(t) for t in (b[2], b[3])} - {None}
            if len(b) > 4 and kinds - {"string"}:
                fail(f"{b[4]}(…) compares two text variables")
            if len(b) == 4 and b[1] not in ("eq", "ne") and kinds - {"integer"}:
                fail(f"{show(b[2])} {b[1]} {show(b[3])}: an order comparison needs whole numbers, not {next(iter(kinds - {'integer'}))}")
            if len(kinds) > 1:
                fail(f"{show(b[2])} and {show(b[3])} have different types")
        elif b[0] == "arith" and b[2] == ir.DAYS:
            if b[3][0] != "var" or typ(b[3]) not in (None, "string"):
                fail(f"{b[1]} = @days(…): the first argument is a variable bound by a positive literal to text")
            if b[4][0] != "const" or b[4][2] != "string":
                fail(f"{b[1]} = @days(…): the origin is a constant ISO date in quotes")
        elif b[0] == "arith":
            for t in (b[3], b[4]):
                if typ(t) not in (None, "integer"):
                    fail(f"{b[1]} = …: arithmetic needs whole numbers, and {show(t)} is {typ(t)}")

    positive = {t[1] for kind, *rest in body if kind == "lit" and rest[0] == "positive"
                for t in rest[1][1] if t[0] == "var"}
    defined = set(positive) | {b[1] for b in body if b[0] in ("agg", "arith")}

    def text(t, *, aggregate=False):
        if t[0] == "wild":
            if not aggregate:
                fail("'_' only inside an aggregate")
            return "_"
        if t[0] == "var":
            return "?" + t[1]
        return t[1]

    names = {t[1] for b in body for t in _terms(b) if t[0] == "var"} | {t[1] for t in head[1] if t[0] == "var"}
    anonymous = iter(f"anon_{k}" for k in range(1, 10**6) if f"anon_{k}" not in names)
    lits, aggs, conds, assigns = [], [], [], []
    for b in body:
        if b[0] == "lit":
            name, terms, _ = b[2]
            if b[1] == "negative" and any(t[0] == "wild" for t in terms):
                fail(f"'_' in !{name}(…): a negation needs every column; derive a relation without it first")
            # '_' in a positive literal is a variable of its own that nothing else uses
            lits.append({"relation": name, "polarity": b[1],
                         "terms": ["?" + next(anonymous) if t[0] == "wild" else text(t) for t in terms]})
        elif b[0] == "agg":
            _, var, fn, target, (name, terms, _) = b
            # Local: in this aggregate only (the head, the other body elements and the results of
            # other aggregates do not use it). Any other variable is a group key, and the safety rule
            # wants it bound by a positive literal, not by arithmetic or another aggregate.
            elsewhere = {t[1] for t in head[1] if t[0] == "var"}
            for o in body:
                if o is b:
                    continue
                if o[0] == "agg":
                    elsewhere.add(o[1])
                else:
                    elsewhere |= {t[1] for t in _terms(o) if t[0] == "var"}
            for t in terms:
                if t[0] == "var" and t[1] in elsewhere and t[1] not in positive:
                    fail(f"{t[1]} in the aggregate over {name} is not bound by a positive literal; "
                         "a group key must be")
            local = [t[1] for t in terms if t[0] == "var" and t[1] not in elsewhere]
            if len(set(local)) != len(local):
                fail(f"a variable local to the aggregate over {name} occurs twice")
            if target is not None and target not in local:
                fail(f"{fn} {target}: the aggregated variable must be local to the aggregate")
            over = None
            out = []
            for i, t in enumerate(terms):
                if t[0] == "var" and t[1] in local:
                    out.append("_")
                    if t[1] == target:
                        over = i
                else:
                    out.append(text(t, aggregate=True))
            a = {"relation": name, "terms": out, "function": fn, "as": "?" + var}
            if over is not None:
                a["over"] = {"position": over}
            aggs.append(a)
        elif b[0] == "arith":
            _, var, op, left, right = b
            if var in positive:
                fail(f"{var} = …: arithmetic binds a fresh variable")
            assigns.append({"var": "?" + var, "op": op, "left": text(left), "right": text(right)})
        else:
            _, op, left, right, *typed = b
            for t in (left, right):
                if t[0] == "var" and t[1] not in defined:
                    fail(f"{t[1]} in a comparison is not bound (bind it with a positive literal)")
                if t[0] == "wild":
                    fail("'_' only inside an aggregate")
            conds.append({"op": op, "left": text(left), "right": text(right),
                          **({"compare_as": typed[0]} if typed else {})})
    rule = {"id": rid, "module": module, "head": {"relation": head[0], "terms": [text(t) for t in head[1]]},
            "body": lits, "origin": {"file": where, "line": str(line)}}
    if aggs:
        rule["aggregates"] = aggs
    if conds:
        rule["conditions"] = conds
    if assigns:
        rule["assignments"] = assigns
    return rule


def read_program(text: str, where: str, inputs: dict, name: str) -> dict:
    """The IR document of one compiler-owned program (not a pack's rules), such as a `trace` program.

    Its base relations are given in `inputs` ({name: [(column, type)]}), not read from a schema: R4 binds
    a pack's rules to its tables, and these programs read compiler inputs (the proof graph, R10). Every
    declared relation that is not an input is derived, in the module `name`. Raises RuleError."""
    decls, rules_src = {}, []
    for s in parse_file(text, where):
        if s[0] == "decl" and s[1] not in inputs:
            decls[s[1]] = s[2]
        elif s[0] == "rule":
            rules_src.append(s)

    def columns(rel):
        cols = decls.get(rel) or inputs.get(rel)
        return [t for _, t in cols] if cols else None

    count, seen, rules = {}, {}, []
    for _, head, _, _ in rules_src:
        count[head[0]] = count.get(head[0], 0) + 1
    for _, head, body, line in rules_src:
        if head[0] not in decls:
            raise RuleError(f"{where}:{line}: {head[0]} has no .decl")
        seen[head[0]] = seen.get(head[0], 0) + 1
        rid = head[0] if count[head[0]] == 1 else f"{head[0]}_{seen[head[0]]}"
        rules.append(to_rule(rid, name, where, head, body, line, columns))
    relations = [{"name": n, "role": "base", "key": [{"name": c, "type": t} for c, t in cols], "world": "closed"}
                 for n, cols in inputs.items()]
    relations += [{"name": n, "role": "derived", "module": name, "explain": "materialize",
                   "key": [{"name": c, "type": t} for c, t in cols]} for n, cols in decls.items()]
    keys = {r["name"]: r["key"] for r in relations}
    for r in rules:   # an aggregate over a key column names it, as for a pack
        for a in r.get("aggregates", []):
            if isinstance(a.get("over"), dict):
                a["over"] = keys[a["relation"]][a["over"]["position"]]["name"]
    doc = {"format": ir.FORMAT, "pack": name, "relations": sorted(relations, key=lambda r: r["name"]),
           "rules": sorted(rules, key=lambda r: r["id"])}
    try:
        doc = ir.with_strata(doc)
        ir.load(doc)
    except ir.IRError as e:
        raise RuleError(f"{where}: {e}") from None
    return doc
