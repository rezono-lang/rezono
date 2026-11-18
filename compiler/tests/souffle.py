"""Rule IR -> Soufflé, the oracle (tests only). Runs `souffle` and reads every derived relation as a set.

The IR as a program (`program`), or a pack's rule text as written, over its import closure (`pack_source`).
What the compiler lowers a view to has no text: those rules come from the IR (`lowered`, `view_bound`).
A value column is an extra column at the end of the Soufflé relation; a literal leaves it out with '_'.
An aggregate over a key column puts the aggregated variable at that position.
Soufflé has 32-bit numbers by default; the generated programs stay far below that.
"""

import re
import subprocess
import tempfile
from itertools import accumulate
from pathlib import Path

from rezono_compiler.gap import days_text
from rezono_compiler.rules import const_type, is_var

TYPE = {"string": "symbol", "integer": "number"}
INPUT = ("base", "calc")  # what the rules read: a table, and a calculation selection with the rows given
OPS = {"eq": "=", "ne": "!=", "lt": "<", "le": "<=", "gt": ">", "ge": ">=", "add": "+", "sub": "-", "mul": "*", "div": "/"}


def _term(t, typ):
    if t == "_":
        return "_"
    if is_var(t):
        return "V_" + t[1:]
    return t if typ == "integer" else '"' + t.replace('"', '\\"') + '"'


def _atom(prog, atom, over=None):
    rel = prog.relations[atom.relation]
    terms = ["W_" if over == c.name and t == "_" else _term(t, c.type) for t, c in zip(atom.terms, rel.key)]
    terms += ["W_" if over == c.name else "_" for c in rel.values]
    return f"{atom.relation}({', '.join(terms)})"


def _decl(rel):
    return f".decl {rel.name}({', '.join(f'{c.name}:{TYPE[c.type]}' for c in rel.key + rel.values)})"


def _rule(prog, r):
    types = {}
    for b in r.body:
        for t, c in zip(b.atom.terms, prog.relations[b.atom.relation].key):
            types.setdefault(t, c.type)
    parts = []
    for b in r.body:
        parts.append(("!" if b.polarity == "negative" else "") + _atom(prog, b.atom))
    for a in r.aggregates:
        inner = _atom(prog, a.atom, over=a.over)
        fn = "count" if a.function == "count" else f"{a.function} W_"
        parts.append(f"{_term(a.var, 'integer')} = {fn} : {{ {inner} }}")
    for s in r.assignments:
        if s.op == "days":  # the oracle's own count, from the digits of the text: no date library on this side
            parts.append(f"{_term(s.var, 'integer')} = {days_text(_term(s.left, 'string'))} - {days_text(_term(s.right, 'string'))}")
            continue
        parts.append(f"{_term(s.var, 'integer')} = {_term(s.left, 'integer')} {OPS[s.op]} {_term(s.right, 'integer')}")
    for c in r.conditions:
        t = types.get(c.left) or types.get(c.right) or const_type(c.left)
        if any(a.var in (c.left, c.right) for a in r.aggregates) or any(s.var in (c.left, c.right) for s in r.assignments):
            t = "integer"
        parts.append(f"{_term(c.left, t)} {OPS[c.op]} {_term(c.right, t)}")
    return f"{_atom(prog, r.head)} :- {', '.join(parts)}."


def program(prog):
    lines = []
    for rel in sorted(prog.relations.values(), key=lambda r: r.name):
        lines.append(_decl(rel))
        lines.append(f".input {rel.name}" if rel.role in INPUT else f".output {rel.name}")
    lines += [_rule(prog, r) for r in sorted(prog.rules.values(), key=lambda r: r.id)]
    return "\n".join(lines) + "\n"


ACCESS = ("may_read", "may_propose", "may_review", "may_publish")  # their second column names a kind
_TOKEN = re.compile(r'//[^\n]*|/\*.*?\*/|"(?:[^"\\]|\\.)*"|[A-Za-z_][A-Za-z0-9_]*|:-|<=|>=|!=|\s+|.', re.S)
_NAME = re.compile(r"[A-Za-z_][A-Za-z0-9_]*\Z")
COMPARE = ("=", "!=", "<", "<=", ">", ">=")
_DECL = re.compile(r"\.decl\s+([a-z0-9_]+)\s*\(([^)]*)\)")
VIEW = "views.yaml"  # the origin of a rule the compiler lowers a view to (view_rules.bind): it is in no rule file


def _code(text):
    """The tokens of a rule text, and which of them are code: no space, no comment."""
    toks = _TOKEN.findall(text)
    return toks, [i for i, t in enumerate(toks) if not t.isspace() and not t.startswith(("//", "/*"))]


def _rules(toks, code):
    """The rules of a text, each as its code tokens. A rule ends at a full stop outside brackets. A full stop
    with a word right behind it starts a directive (.decl, .input, .output); a .decl ends at its closing
    bracket and is no rule."""
    current, depth, decl = [], 0, False
    for k, i in enumerate(code):
        t = toks[i]
        if t == "." and depth == 0:
            if k + 1 < len(code) and code[k + 1] == i + 1 and _NAME.match(toks[i + 1]):
                decl = toks[i + 1] == "decl"
            else:
                yield current
            current = []
            continue
        depth += (t in ("(", "{")) - (t in (")", "}"))
        current.append(i)
        if decl and depth == 0 and t == ")":
            current, decl = [], False


def bound(text, names):
    """The rule text of an imported pack under the names its tables have in the importing pack.
    The compiler binds the statements its parser made (rules_dl.remap_statement); this rewrites the
    text itself, token by token, so that Soufflé still reads what was written and not what the parser read.
    `names` maps a class or enum of the imported pack to its name in the importing pack. What follows it:
    a relation `kind` or `kind__slot`; the kind constant in the second column of an access atom; and a
    constant that a variable in that column is compared with, also through an equality between variables.
    Nothing else: not a value, not a variable."""
    names = {old: new for old, new in names.items() if old != new}
    if not names:
        return text
    toks, code = _code(text)

    def kind(i):
        if toks[i].startswith('"') and toks[i][1:-1] in names:
            toks[i] = '"' + names[toks[i][1:-1]] + '"'

    def var(i):
        return toks[i] != "_" and _NAME.match(toks[i])

    def rule(s):
        """One rule, `s` its code tokens: the kind constants of its access atoms."""
        kind_vars, compared = set(), []
        for p, i in enumerate(s):
            if toks[i] in ACCESS and p + 1 < len(s) and toks[s[p + 1]] == "(":
                depth, term = 0, 0
                for j in s[p + 1:]:
                    depth += (toks[j] == "(") - (toks[j] == ")")
                    if depth == 0:
                        break
                    if depth == 1 and toks[j] == ",":
                        term += 1
                    elif depth == 1 and term == 1 and var(j):
                        kind_vars.add(toks[j])
                    elif depth == 1 and term == 1:
                        kind(j)
            elif toks[i] in COMPARE and 0 < p < len(s) - 1:
                compared.append((toks[i], s[p - 1], s[p + 1]))
        before = None
        while before != len(kind_vars):  # an equality between variables keeps the meaning of the column
            before = len(kind_vars)
            for op, a, b in compared:
                if op == "=" and var(a) and var(b) and {toks[a], toks[b]} & kind_vars:
                    kind_vars |= {toks[a], toks[b]}
        for _, a, b in compared:
            if toks[a] in kind_vars:
                kind(b)
            if toks[b] in kind_vars:
                kind(a)

    for s in _rules(toks, code):
        rule(s)
    # The relations: a name right before an opening bracket (a declaration, a head, a premise, an aggregate).
    for k, i in enumerate(code[:-1]):
        if _NAME.match(toks[i]) and toks[code[k + 1]] == "(":
            head, sep, tail = toks[i].partition("__")
            toks[i] = names.get(head, head) + sep + tail
    return "".join(toks)


def view_bound(text, where, prog):
    """The rule text of the file `where` (its name in a rule's origin) with the atoms that the compiler bound
    to a relation of a view under that relation's name (docs/compiler.md, "Views that execute"). The compiler
    lowers a view to rules: per theory table the view maps, a relation that takes in the table and what the
    view supplies; and it binds the rules that read the table to that relation. Which atoms it bound is not
    decided again here. It is read from the compiled rule with the same origin: a relation that the text
    names and the compiled rule does not read stands for the one relation the compiled rule reads that a
    lowered rule fills from it alone. What the rule says still comes from its text."""
    lowered_rules = [r for r in prog.rules.values() if r.origin[0] == VIEW]
    if not lowered_rules:
        return text
    reads = {}
    for r in prog.rules.values():
        atoms = [r.head, *(b.atom for b in r.body), *(a.atom for a in r.aggregates)]
        reads.setdefault(r.origin, set()).update(a.relation for a in atoms)
    toks, code = _code(text)
    line = list(accumulate((t.count("\n") for t in toks), initial=1))  # of each token, as the compiler counts
    for s in _rules(toks, code):
        named = [i for p, i in enumerate(s[:-1]) if _NAME.match(toks[i]) and toks[s[p + 1]] == "("]
        have = reads.get((where, line[named[0]]), set()) if named else set()  # the first name is the head
        for i in named:
            if toks[i] in prog.relations and toks[i] not in have:  # exactly one, or this harness cannot tell
                toks[i], = {r.head.relation for r in lowered_rules
                            if r.head.relation in have and [b.atom.relation for b in r.body] == [toks[i]]}
    return "".join(toks)


def lowered(prog):
    """The rules the compiler lowers a view to, with the declarations of their relations, as one more text
    (none without a view). No rule file holds them, so they come from the IR, written as `program` does."""
    rules = sorted((r for r in prog.rules.values() if r.origin[0] == VIEW), key=lambda r: r.id)
    made = sorted({r.head.relation for r in rules})
    return ["\n".join([_decl(prog.relations[n]) for n in made] + [_rule(prog, r) for r in rules]) + "\n"] if rules else []


def closure(pack_dir, prog=None):
    """The rule texts of a pack's import closure (an imported pack brings its rules, and the
    program is the union over the closure): rules/*.dl of every imported pack, each pack after the packs it
    imports and under the importing pack's names (`bound`), then the pack's own, then the rules of the pack's
    decision tables (rezono_table, docs/rezono/publication.md §9.1): a table is a rule file of its pack whose
    text the compiler makes, so the oracle runs that text too. The names come from the compiler's binding of
    the schemas, as the tables in `source` do; what a rule says comes from its text.
    With `prog`, the compiled program, the texts read the relations of a view where the compiler bound them
    (`view_bound`), and the rules of the view follow (`lowered`)."""
    from rezono_compiler import modules, pack, rezono_table

    pack_dir = Path(pack_dir)
    meta, errors = pack.read_meta(pack_dir), []
    mods, imported = modules.load(pack_dir, meta, errors)
    names = modules.Names(mods, pack.snake, errors)
    assert not errors, errors
    texts = []  # (the file's name in a rule's origin, as rules_dl.read gives it; its text)
    for name in modules.dependency_order(imported, modules.direct(meta)):
        renames = pack.rename(mods, imported[name], names)
        texts += [(f"{imported[name].name}:rules/{f.name}", bound(f.read_text(encoding="utf-8"), renames))
                  for f in sorted((imported[name].dir / "rules").glob("*.dl"))]
    texts += [(f"rules/{f.name}", f.read_text(encoding="utf-8")) for f in sorted((pack_dir / "rules").glob("*.dl"))]
    # A table reads the tables of its kind, never a view, so its text is not bound to one (`view_bound`).
    tables = [g.text for g in rezono_table.lower_pack(pack.read(pack_dir), meta, pack_dir, errors)] if meta.get("rezono") else []
    assert not errors, errors
    if prog is None:
        return [text for _, text in texts] + tables
    return [view_bound(text, where, prog) for where, text in texts] + tables + lowered(prog)


def source(prog, texts):
    """Rule files as one Soufflé program: declarations and inputs for the tables they read (from the IR, as
    the compiler binds them), the files as written, and an output per derived relation. So the oracle also
    sees what the parser read, not only the IR it made. `texts` is the whole program: for a pack, the rule
    files of its import closure (`closure`, `pack_source`). A relation that an importing pack declares
    again (`// @extend`, with the same columns) is declared once; any other second declaration stays, and
    Soufflé refuses it."""
    lines, columns, kept = [], {}, []
    for text in texts:
        earlier = dict(columns)  # what the files before this one declare

        def once(m):
            name, cols = m.group(1), re.sub(r"\s+", "", m.group(2))
            columns.setdefault(name, cols)
            return "" if earlier.get(name) == cols else m.group(0)
        kept.append(_DECL.sub(once, text))
    declared = set(columns)
    for rel in sorted(prog.relations.values(), key=lambda r: r.name):
        if rel.role in INPUT and rel.name not in declared:
            lines += [_decl(rel), f".input {rel.name}"]
    for text in kept:
        lines.append(re.sub(r"^\s*\.(input|output)\b[^\n]*$", "", text, flags=re.M))
    lines += [f".input {n}" for n in sorted(declared) if prog.relations.get(n) and prog.relations[n].role == "base"]
    lines += [f".output {r.name}" for r in sorted(prog.relations.values(), key=lambda r: r.name) if r.role == "derived"]
    return "\n".join(lines) + "\n"


def pack_source(prog, pack_dir):
    """A pack's rules as written, over its import closure, as one Soufflé program (`closure`, `source`), with
    the rules of a view the pack reads a theory through as the compiler lowers them."""
    return source(prog, closure(pack_dir, prog))


def run(prog, data, workdir=None, program_text=None):
    """Evaluate with Soufflé: {relation: set of tuples of str} for every derived relation."""
    with tempfile.TemporaryDirectory(dir=workdir) as d:
        d = Path(d)
        (d / "facts").mkdir()
        (d / "out").mkdir()
        for name, rel in prog.relations.items():
            if rel.role in INPUT:
                rows = data.get(name, [])
                (d / "facts" / f"{name}.facts").write_text("".join("\t".join(map(str, r)) + "\n" for r in rows))
        (d / "p.dl").write_text(program_text if program_text is not None else program(prog))
        subprocess.run(["souffle", "-j", "1", "-F", str(d / "facts"), "-D", str(d / "out"), str(d / "p.dl")],
                       check=True, capture_output=True, text=True)
        out = {}
        for name, rel in prog.relations.items():
            if rel.role == "derived":
                text = (d / "out" / f"{name}.csv").read_text()
                out[name] = {tuple(line.split("\t")) for line in text.splitlines() if line}
        return out


def version():
    return subprocess.run(["souffle", "--version"], capture_output=True, text=True).stdout.split("\n")[1].strip()
