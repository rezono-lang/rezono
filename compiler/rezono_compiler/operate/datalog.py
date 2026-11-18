# --- Rules ---------------------------------------------------------------------------------------------------

from __future__ import annotations

from collections import Counter

from .. import rules_dl
from ..plan import V, Var, X, definition
from .. import pack as packs
from ..pack import ACCESS

from .spec import PARAMETERS, OUTCOME, OperationError
from .model import Model, rule_files, rule_tokens
from .text import Edits, read_text, line_start, line_end
from .rename import descendants
from .maps import Maps
from .state import text_of


def quote_dl(value: str) -> str:
    return '"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"'


def statements(toks: list) -> list[tuple[str, int, int]]:
    """('decl' | 'io' | 'rule', first token, last token) of one file's tokens, which already parsed."""
    out, i = [], 0
    while toks[i].kind != "end":
        t = toks[i]
        if t.kind == "directive":
            j = i + 1
            if t.text == ".decl":
                while toks[j].text != ")":
                    j += 1
            else:
                while toks[j + 1].text == ",":
                    j += 2
            out.append(("decl" if t.text == ".decl" else "io", i, j))
            i = j + 1
            continue
        j, depth = i, 0
        while not (toks[j].text == "." and toks[j].kind == "op" and depth == 0):
            depth += {"(": 1, ")": -1, "{": 1, "}": -1}.get(toks[j].text, 0) if toks[j].kind == "op" else 0
            j += 1
        out.append(("rule", i, j))
        i = j + 1
    return out


def remove_statement(rel: str, text: str, first, last, edits: Edits):
    """Remove a directive; its whole line when nothing else is on it."""
    a, b = first.start, last.start + len(last.text)
    s, e = line_start(text, a), line_end(text, b)
    if not text[s:a].strip() and not text[b:e].strip():
        a, b = s, e
    edits.add(rel, a, b, "")


def args_of(toks: list, i: int) -> list[list]:
    """The arguments of the atom whose name is toks[i], as lists of tokens."""
    args, j, depth, cur = [], i + 2, 0, []
    while depth > 0 or toks[j].text != ")":
        if toks[j].text == "," and depth == 0:
            args.append(cur)
            cur = []
        else:
            depth += {"(": 1, ")": -1}.get(toks[j].text, 0) if toks[j].kind == "op" else 0
            cur.append(toks[j])
        j += 1
    args.append(cur)
    return args if any(args) else []


def atom_close(toks: list, i: int):
    """The closing parenthesis of the atom whose name is toks[i]."""
    j, depth = i + 1, 0
    while True:
        if toks[j].kind == "op" and toks[j].text in "()":
            depth += 1 if toks[j].text == "(" else -1
            if depth == 0:
                return toks[j]
        j += 1


def changed_kinds(p: packs.Pack, mp: Maps) -> set[str]:
    """The kinds whose element ids change: inlined kinds without an identifier, held by a slot whose element
    id changes or by an owner whose ids change."""
    out: set[str] = set()
    grow = True
    while grow:
        grow = False
        for kind in p.kinds.values():
            for s in kind.slots.values():
                if not (s.arrow and s.inlined) or p.kinds[p.root(s.range)].identifier is not None:
                    continue
                if s.element in mp.elements or any(d in out for d in descendants(p, s.kind)):
                    for d in descendants(p, s.range):
                        if d not in out:
                            out.add(d)
                            grow = True
    return out


def rule_edits(m: Model, mp: Maps, ids: dict[str, int], changed_ids: dict, edits: Edits,
               gone: set = frozenset(), new_kinds: set = frozenset(), back: dict | None = None,
               keep: set = frozenset()) -> list[dict]:
    """Rename predicates, the enum values they read and @outcome kinds. A constant is rewritten only where it
    provably is what changed: a renamed enum value in the value column of a literal over a slot table of that
    enum, or a kind in the `kind` column of an access relation (`may_read(role, kind, id)`, O7). Any other
    constant equal to a changed name, value or id blocks, in access rules too: a constant has no type, so
    "placement" in the role column may be a role as well as a kind, and rewriting it could widen access.
    A head that carries an id the operation changes blocks as well. The author changes the rule first.

    A literal over a table the plan's backward queries (`back`) define is replaced by its definition over the
    new tables: atoms with fresh variables, or the atom of the case its constant selects. Under a negation or
    in an aggregate, or when no one case is selected, it reads a helper relation `was_<k>_<a>` with that
    definition instead; reloading the pack checks strata and worlds again. With access rules (may_read), a
    definition across an arrow blocks: what a role sees of the conclusion would then depend on another kind.
    A split's definitions stay within the kind's own subkinds, which its rights cover. `keep`: parameter
    predicates of tables in `gone` that stay, renamed (an absorbed slot's minimum)."""
    p = m.pack
    gone_preds = ({t for t in gone} | {f"{t}__{b}" for t in gone for b in PARAMETERS}) - set(keep)
    defs = {t: definition(q, mp.tables) for t, q in (back or {}).items()}
    consumed = {t for t in defs if t not in mp.predicates}  # its table goes: its directives go with it
    taken = {x.text for _, f in rule_files(m) for x in rule_tokens(read_text(f), f.name)
             if x.kind == "ident"}
    helpers: dict[str, str] = {}  # old table -> the helper relation that defines it
    enum_tables = {s.table: s.enum for k in p.kinds.values() for s in k.slots.values() if s.enum in mp.values}
    changed = changed_kinds(p, mp)
    touches = {k for k in p.kinds if any(d in changed for d in descendants(p, k))}
    id_cols: dict[str, set[int]] = {}
    for k, kind in p.kinds.items():
        if k in touches:
            id_cols.setdefault(k, set()).add(0)
        for s in kind.slots.values():
            if k in touches:
                id_cols.setdefault(s.table, set()).add(0)
            if s.arrow and s.range in touches:
                id_cols.setdefault(s.table, set()).add(1)
    old_ids = {text_of(x) for x in changed_ids}
    changes, errors = [], []
    kind_col = access_kind_columns(m)
    kinds_change = bool(mp.kinds) or bool(new_kinds) or bool(set(gone) & set(p.kinds))
    if kinds_change:
        errors += [f"rules: {r} is declared without the access relation signature (role, kind, id); an operation that changes "
                   f"kind names cannot tell its kind column, so it blocks" for r, c in sorted(kind_col.items()) if c is None]
    fresh_names = set(mp.elements.values()) | set(mp.kinds.values()) | set(new_kinds)
    fresh_names |= {v for vm in mp.values.values() for v in vm.values()} | {text_of(v) for v in changed_ids.values()}
    seen: Counter = Counter()
    for rel, f in rule_files(m):
        text = read_text(f)
        toks = rule_tokens(text, rel)
        made = []  # the helper relations this file declares
        for what, a, b in statements(toks):
            named = [t.text for t in toks[a + 1:b + 1] if t.kind == "ident"][:1 if what == "decl" else None]
            if what in ("decl", "io") and set(named) & consumed:
                if not set(named) <= consumed:
                    errors.append(f"{rel}:{toks[a].line}: {toks[a].text} names {', '.join(sorted(named))}; the "
                                  f"table of the split slot goes, so give it a directive of its own first")
                else:  # the table goes, and the subkinds are base relations the rules need not declare
                    remove_statement(rel, text, toks[a], toks[b], edits)
                continue
            if what in ("decl", "io"):
                for t in toks[a + 1:b + 1]:
                    if t.kind == "ident" and (what == "io" or t is toks[a + 1]) and t.text in gone_preds:
                        errors.append(f"{rel}:{t.line}: {toks[a].text} {t.text}: the table goes; change the rules "
                                      f"first")
                    elif t.kind == "ident" and t.text in mp.predicates and (what == "io" or t is toks[a + 1]):
                        edits.add(rel, t.start, t.start + len(t.text), mp.predicates[t.text])
                continue
            head = toks[a].text
            seen[head] += 1
            rid = head if ids[head] == 1 else f"{head}_{seen[head]}"
            count, handled, carriers = 0, set(), set()
            names = {x.text for x in toks[a:b] if x.kind == "ident"}
            depth = 0
            for i in range(a, b):
                t = toks[i]
                if t.kind == "op" and t.text in "{}":
                    depth += 1 if t.text == "{" else -1
                if not (t.kind == "ident" and toks[i + 1].text == "("):
                    continue
                if t.text in defs:  # an old predicate, defined over the new tables
                    args = args_of(toks, i)
                    alts = defs[t.text]
                    if len(args) != len(alts[0][0]):
                        errors.append(f"{rel}:{t.line}: rule {rid}: {t.text} takes {len(alts[0][0])} arguments")
                        continue
                    x, v = [text[g[0].start:g[-1].start + len(g[-1].text)] for g in args] + [None] * (2 - len(args))
                    c = args[1][0] if len(args) == 2 and len(args[1]) == 1 and args[1][0].kind in ("string", "number") \
                        else None
                    value = None if c is None else rules_dl.unescape(c.text[1:-1]) if c.kind == "string" else c.text
                    if "may_read" in kind_col and any(len(atoms) > 1 for _, atoms in alts):
                        errors.append(f"{rel}:{t.line}: rule {rid}: {t.text} becomes atoms across an arrow; under "
                                      f"O8 a role that reads {t.text} but not the kind at the other end would no "
                                      f"longer see what the rule concludes, so change the rule first")
                        continue
                    cases = {text_of(h[1]): atoms for h, atoms in alts if len(h) == 2 and not isinstance(h[1], Var)}
                    under = (toks[i - 1].kind == "op" and toks[i - 1].text == "!") or depth > 0
                    if cases and value is not None:  # cases: the constant selects one, k__d(x, "v") -> s(x)
                        if value not in cases:
                            errors.append(f"{rel}:{t.line}: rule {rid}: {t.text} goes; only a literal with a case "
                                          f"value becomes the subkind ({', '.join(sorted(cases))}); change the rule "
                                          f"first")
                            continue
                        handled.add(id(c))
                        (pred, _), = cases[value]
                        edits.add(rel, t.start, atom_close(toks, i).start + 1, f"{pred}({x})")
                    elif not cases and not under:  # a conjunction, in place, with fresh variables
                        sub = {X: x, V: v} if v is not None else {X: x}
                        out = []
                        for pred, terms in alts[0][1]:
                            for term in terms:
                                if term not in sub:
                                    sub[term] = next(f"mv{n}" for n in range(len(names) + 1) if f"mv{n}" not in names)
                                    names.add(sub[term])
                            out.append(f"{pred}({', '.join(sub[term] for term in terms)})")
                        edits.add(rel, t.start, atom_close(toks, i).start + 1, ", ".join(out))
                    else:  # under a negation or in an aggregate, or a case value as a variable: a helper relation
                        if t.text not in helpers:
                            stem = "was_" + t.text.replace("__", "_")
                            helpers[t.text] = next(h for h in (f"{stem}{n or ''}" for n in range(len(taken) + 1))
                                                   if h not in taken)
                            taken.add(helpers[t.text])
                            made.append(helper(p, t.text, helpers[t.text], alts))
                        edits.add(rel, t.start, t.start + len(t.text), helpers[t.text])
                    count += 1
                    continue
                if t.text in gone_preds:
                    errors.append(f"{rel}:{t.line}: rule {rid}: it reads {t.text}, a table that goes; change the "
                                  f"rule first")
                if t.text in mp.predicates:
                    edits.add(rel, t.start, t.start + len(t.text), mp.predicates[t.text])
                    count += 1
                args = args_of(toks, i)
                for c in id_cols.get(t.text, ()):
                    if i != a and c < len(args) and len(args[c]) == 1 and args[c][0].kind == "ident":
                        carriers.add(args[c][0].text)
                c = kind_col.get(t.text)
                if c is not None and kinds_change and not (c < len(args) and len(args[c]) == 1
                                                           and args[c][0].kind == "string"):
                    errors.append(f"{rel}:{t.line}: rule {rid}: the kind column of {t.text} is not a constant, so a "
                                  f"change of kind names cannot be followed through it; change the rule first")
                elif c is not None and c < len(args) and len(args[c]) == 1 and args[c][0].kind == "string":
                    k = args[c][0]
                    v = rules_dl.unescape(k.text[1:-1])
                    handled.add(id(k))
                    if v in fresh_names:
                        errors.append(f"{rel}:{k.line}: rule {rid}: it names the kind {v}, which this operation brings "
                                      f"in; the grant would start to hold, so change the rule first")
                    elif v in gone:
                        errors.append(f"{rel}:{k.line}: rule {rid}: it names the kind {v}, which goes; change the "
                                      f"rule first")
                    elif v in mp.kinds:
                        edits.add(rel, k.start, k.start + len(k.text), quote_dl(mp.kinds[v]))
                        count += 1
                if t.text in enum_tables:
                    vmap = mp.values[enum_tables[t.text]]
                    if len(args) == 2 and len(args[1]) == 1 and args[1][0].kind == "string":
                        c = args[1][0]
                        v = rules_dl.unescape(c.text[1:-1])
                        handled.add(id(c))
                        if v in vmap:
                            edits.add(rel, c.start, c.start + len(c.text), quote_dl(vmap[v]))
                            count += 1
            renamed_values = {v for vm in mp.values.values() for v in vm}
            for t in toks[a:b]:
                if t.kind != "string" or id(t) in handled:
                    continue
                v = rules_dl.unescape(t.text[1:-1])
                if v in fresh_names:
                    errors.append(f"{rel}:{t.line}: rule {rid}: the constant {t.text} equals a name this operation "
                                  f"brings in; after it, the constant would name that element (and could widen "
                                  f"access), so change the rule first")
                elif v in gone:
                    errors.append(f"{rel}:{t.line}: rule {rid}: the constant {t.text} equals the name of a kind or "
                                  f"table that goes; it may reach an access relation through another relation, so "
                                  f"change the rule first")
                elif v in mp.elements or v in renamed_values or v in old_ids:
                    errors.append(f"{rel}:{t.line}: rule {rid}: the constant {t.text} equals an element, value or "
                                  f"id this operation changes, in a place that is not a column of that enum; it "
                                  f"may as well be a role or an element (renaming it could widen access), so "
                                  f"change the rule first")
            head_vars = {x[0].text for x in args_of(toks, a) if len(x) == 1 and x[0].kind == "ident"}
            if head_vars & carriers:
                errors.append(f"{rel}:{toks[a].line}: rule {rid}: its head carries the id of an element this "
                              f"rename gives a new id ({', '.join(sorted(head_vars & carriers))}); change the rule first")
            if count:
                changes.append({"rule": rid, "file": rel, "literals": count})
        if made:
            edits.add(rel, len(text), len(text), ("" if text.endswith("\n") or not text else "\n") + "".join(made))
        for mo in OUTCOME.finditer(text):
            if mo.group(2) in gone:
                errors.append(f"{rel}: @outcome {mo.group(2)}: the kind goes; change the outcome first")
            elif mo.group(2) in mp.kinds:
                edits.add(rel, mo.start(2), mo.end(2), mp.kinds[mo.group(2)])
    if errors:
        raise OperationError("\n".join(errors))
    return sorted(changes, key=lambda c: (c["rule"], c["file"]))


def helper(p: packs.Pack, table: str, name: str, alts: list) -> str:
    """The declaration and the rules of a helper relation that defines an old predicate over the new tables."""
    cols = rules_dl.base_tables(p)[table]
    if any(t is None for _, t in cols):
        raise OperationError(f"rules: {table} has a column rules cannot read")
    dl = {"string": "symbol", "integer": "number"}
    out = f".decl {name}({', '.join(f'{c}: {dl[t]}' for c, t in zip(('x', 'v'), (t for _, t in cols)))})\n"
    for h, atoms in alts:
        value = h[1] if len(h) == 2 else None
        head = "x" if len(h) == 1 else "x, v" if isinstance(value, Var) else \
            f"x, {quote_dl(value) if isinstance(value, str) else text_of(value)}"
        sub = {X: "x", V: "v"} if len(h) == 2 else {X: "x"}
        body = []
        for pred, terms in atoms:
            for term in terms:
                sub.setdefault(term, f"mv{sum(1 for k in sub if k not in (X, V))}")
            body.append(f"{pred}({', '.join(sub[term] for term in terms)})")
        out += f"{name}({head}) :- {', '.join(body)}.\n"
    return out


def access_kind_columns(m: Model) -> dict[str, int | None]:
    """Per access relation the pack's rules declare: 1, the kind column of the fixed O7 signature
    (role, kind, id), when the declaration has exactly that signature; None when it does not."""
    out = {}
    for _, f in rule_files(m):
        toks = rule_tokens(read_text(f), f.name)
        for what, a, b in statements(toks):
            if what == "decl" and toks[a + 1].text in ACCESS:
                names = [toks[i].text for i in range(a + 3, b) if toks[i].kind == "ident" and toks[i + 1].text == ":"]
                out[toks[a + 1].text] = 1 if len(names) == 3 and names[:2] == ["role", "kind"] else None
    return out


def rule_counts(m: Model) -> dict[str, int]:
    out: Counter = Counter()
    for _, f in rule_files(m):
        toks = rule_tokens(read_text(f), f.name)
        for what, a, _ in statements(toks):
            if what == "rule":
                out[toks[a].text] += 1
    return dict(out)
