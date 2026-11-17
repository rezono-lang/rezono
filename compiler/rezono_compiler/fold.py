"""Fold marks: which relations and kinds a pack may fold in an explanation (RV-C29).

A pack marks mechanics with `// @explain fold` on the line right above a `.decl` and with
`annotations: {explain: fold}` on a class (docs/explain/contract.md). The mark is display only: it goes into
the schema bundle (`fold: true` on the relation and on the kind) and nowhere else, so the rule IR, the engine
files, the witnesses, the rank and the checker are the same bytes with and without it.

Only a helper may be folded. The definition is the one of the explanation lint's class B
(tools/explain-lint), so that a mark the lint asks for always compiles:

- a helper relation is derived, read in the body of a rule, no invariant, and no channel, question or check
  of the bundle names it;
- a helper kind has no name (no name attribute and no name arrows), and no id of it reaches the head of a
  relation that is no helper.

The rules are those of the whole program except the access rules: an imported pack's marks are judged with
the rules that come with it. A kind a view maps is read through the relation that view_rules.bind makes to hold
its table: that relation is the kind under another name, so its pass-through clause is no step an id reaches a
head by, and a rule that reads the relation reads the kind (RV-C49).
"""

from __future__ import annotations

ACCESS = "may_read"  # access rules are never a step of an answer


def strings(value):
    """Every text in a JSON value, keys included."""
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for k, v in value.items():
            yield k
            yield from strings(v)
    elif isinstance(value, (list, tuple)):
        for v in value:
            yield from strings(v)


def var(t) -> str | None:
    return t if isinstance(t, str) and t.startswith("?") else None


def passes_through(r, pack) -> str | None:
    """The kind whose table clause `r` holds, when `bind` lowered it for a kind a view maps: its origin is the
    view source, which no rule file carries, its one body atom is the kind's table, and the head is the relation
    bind made for that table with the same terms. It concludes nothing. The same clause written
    in a rule file is an author's rule and is judged as one (ruling RV-C49, 13-11-2026)."""
    from . import view_rules  # view_rules imports pack, which imports this module, so it is imported here
    body = r["body"]
    if (r.get("origin") or {}).get("file") != view_rules.SOURCE or len(body) != 1 \
            or r.get("assignments") or r.get("conditions") or r.get("aggregates"):
        return None
    kind = body[0]["relation"]
    if kind in pack.kinds and body[0].get("polarity", "positive") == "positive" \
            and body[0]["terms"] == r["head"]["terms"] \
            and r["head"]["relation"] == view_rules.table_relation(r["module"], kind):
        return kind
    return None


def helpers(pack) -> tuple[set[str], set[str]]:
    """The helper relations of a pack, and the kinds an id of which reaches the head of a relation that is none."""
    from . import emit  # emit reads this module's Pack, so it is imported here
    doc = pack.rules or {"relations": [], "rules": []}
    shown = set(strings([pack.channels, pack.questions, emit.bundle_checks(emit.integrity(pack))]))
    clauses = [r for r in doc["rules"] if r["head"]["relation"] != ACCESS]
    read = {a["relation"] for r in clauses for a in r["body"]}
    relations = {r["name"] for r in doc["relations"] if r["role"] == "derived" and not r.get("invariant")
                 and r["name"] in read and r["name"] not in shown}

    by_head: dict[str, list] = {}
    for r in doc["rules"]:
        by_head.setdefault(r["head"]["relation"], []).append(r)

    def made(r) -> set:
        """The variables a clause computes: a value, never an id."""
        return ({a["var"] for a in r.get("assignments") or []} | {a["as"] for a in r.get("aggregates") or []}
                | {t for a in r["body"] for i, t in enumerate(a["terms"]) if (a["relation"], i) in computed})

    computed: set[tuple[str, int]] = set()  # head positions that every clause computes, to a fixed point
    changed = True
    while changed:
        changed = False
        for head, rs in sorted(by_head.items()):
            for i, _ in enumerate(rs[0]["head"]["terms"]):
                if (head, i) not in computed and all(var(r["head"]["terms"][i]) in made(r) for r in rs):
                    computed.add((head, i))
                    changed = True

    slots = {s.table: (k, s) for k, kind in pack.kinds.items() for s in kind.slots.values()}
    held = {id(r): (r["head"]["relation"], k) for r in clauses if (k := passes_through(r, pack))}
    tables = dict(held.values())  # a mapped kind's table under the name bind gave it -> the kind
    reaches = set()
    for r in clauses:
        if r["head"]["relation"] in relations or id(r) in held:
            continue
        ids = {}  # variable -> the kind it holds an id of
        for a in r["body"]:
            t, terms = a["relation"], a["terms"]
            if (t in pack.kinds or t in tables) and var(terms[0]):
                ids[terms[0]] = tables.get(t, t)
            elif t in slots and len(terms) == 2:
                if var(terms[0]):
                    ids[terms[0]] = slots[t][0]
                if var(terms[1]) and slots[t][1].arrow:
                    ids[terms[1]] = slots[t][1].range
        reaches |= {ids[t] for t in set(r["head"]["terms"]) - made(r) if t in ids}
    return relations, reaches


def check(pack, errors: list[str]) -> None:
    """A fold mark on anything but a helper is an error. A pack without marks is not looked at."""
    kinds = sorted(k for k, kind in pack.kinds.items() if kind.fold)
    if not kinds and not pack.folds:
        return
    relations, reaches = helpers(pack)
    for name, where in sorted(pack.folds.items()):
        if name not in relations:
            errors.append(f"{where}: @explain fold is for a helper relation, and {name} is none: a helper is read by "
                          "a rule, is no invariant, and no channel, question or check names it")
    for k in kinds:
        if pack.name(k) or pack.name_arrows(k) or k in reaches:
            errors.append(f"class {pack.kinds[k].cls}: explain: fold is for a helper kind, and {k} is none: a helper "
                          "has no name, and no id of it reaches the head of a relation that is no helper")
