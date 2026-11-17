"""What one filtered role may read, derived by the checker itself.

The publisher filters a role's rows and names the relations the role reads in full (`full`). If the checker
took both as given, a bug in that filter would go green: the role's proofs would be checked against
whatever it was handed. So the checker derives both here, from the schema (the kind per column and the
parent chain of the kinds), the role, the complete `may_read(role, kind, id)` rows and the read rules of
the rule IR, and shares no code with the publisher's filter (edge/publisher/tests/test_checker_boundary.py):

- A base row is readable if every column that holds an element holds one the role may read; a right on a
  kind holds for its subkinds. The role's snapshot of a base relation is exactly its readable rows: a row
  more is `not_readable`, a row less `readable_missing`. The relations of a seal with parts are readable only
  for a role that reads every part kind in full (`withheld_seals`). A calculated row names its subject, which must be
  readable (`not_readable`); which calculated rows a role sees is the calculation check's.
- A kind is full for the role if a read rule grants it without a condition: with the role as a constant
  and only `K(x)`, or `may_read(r, "K", x) :- role(r), K(x).` for a role the complete `role` rows hold (for
  any other role that rule derives nothing, so nothing in full either; RV-S10), or
  `may_read(r, "K", x) :- role__capability(r, "c"), K(x).` for a role the complete `role__capability` rows map
  to capability `c` (roles in two layers, B19). Subkinds follow. Each such grant is evidence: the rule and the
  row it rests on (`grants`). The evidence must be the one the publisher hands over (`evidence_mismatch`), so
  a total or an absence over a kind is complete for the role only on a row of the complete snapshots.
  Every element of a full kind must be readable (`full_not_readable`). A base relation is full if each of
  its kind columns is; a derived relation if every base relation it reaches through the rules is. A
  calculation view is full if its subject kind is, every relation that a version of its rule reads is, and
  every calculation view a version takes as a premise is (RV-S26); never when the program does not account
  for it or a rule reads it. The set must be the one the publisher marks (`full_mismatch`), and the role's
  proofs are checked against it.
- A derived row is the role's if it is derivable from what the role reads: among all witness instances of
  the engine, those whose positive base premises the role reads and whose negations and aggregates range
  over relations it reads in full, with derived premises derivable in turn (least fixpoint). The proof of
  each is chosen by rank (`select`, R7). The role's snapshot of a derived relation is exactly those rows:
  a row more is `not_derivable`, a row less `derivable_missing`.
- A calculated row is the role's if its subject is an element the role reads, the role reads in full every
  relation the evaluation reads, and every premise is the role's: a derived row it can derive, or a
  calculated row it sees the same way (least fixpoint). The role's calculation views and calculation
  witnesses are exactly those (`calc_not_visible`, `calc_visible_missing`).
- The witnesses are exactly the proofs `select` chooses (`choice_mismatch`): per role among the instances
  it can use, and for the complete snapshots among all instances (`check_choice`).
"""

from __future__ import annotations

import json
from collections import defaultdict
from collections.abc import Set as AbstractSet

from .calc import published_views, subject_of, version_of
from .calc import reads as calc_reads
from .calc import sources as calc_sources
from .canon import INTEGER, encode_key
from .snapshots import read_rows

ACCESS = "may_read"
ROLE = "role"  # the kind of the roles: `role(r)` in a read rule means every role the pack's facts name
# A role's generic capabilities (std-access): `role__capability(r, "c")` in a read rule means every role the
# pack's facts map to capability `c`.
CAPABILITY = "role__capability"


def _chains(kinds, parents: dict) -> dict[str, tuple[str, ...]]:
    out = {}
    for k in kinds:
        chain, cur = [k], parents.get(k)
        while cur is not None and cur not in chain:
            chain.append(cur)
            cur = parents.get(cur)
        out[k] = tuple(chain)
    return out


def full_kinds(doc: dict, role: str, chains: dict, named: bool,
               capabilities: AbstractSet[str] = frozenset()) -> set[str]:
    """The kinds the read rules give `role` without a condition (`grants`), with their subkinds."""
    granted = {g["kind"] for g in grants(doc, role, chains, named, capabilities)}
    return {k for k, chain in chains.items() if granted.intersection(chain)}


def grants(doc: dict, role: str, chains: dict, named: bool,
           capabilities: AbstractSet[str] = frozenset()) -> list[dict]:
    """Every read rule that gives `role` a kind without a condition, with the row of the complete snapshots it
    rests on: `{"kind", "rule", "ground"}`, sorted. `named`: the complete `role` rows hold this role;
    `capabilities`: the capabilities the complete `role__capability` rows map it to. A rule over every role
    (`role(r)`) derives a row only for a role the pack names, a rule over a capability (`role__capability(r,
    "c")`) only for a role mapped to `c`, so each gives a kind in full only to such a role, on that row; a rule
    with the role as a constant rests on no row (`ground` is empty)."""
    out = []
    for r in doc.get("rules", ()):
        head = r["head"]
        if head["relation"] != ACCESS or len(head["terms"]) != 3:
            continue
        if r.get("aggregates") or r.get("conditions") or r.get("assignments"):
            continue
        if any(b["polarity"] != "positive" for b in r["body"]):
            continue
        who, kind, x = head["terms"]
        if kind.startswith("?") or kind not in chains or not x.startswith("?") or x == who:
            continue
        body = {(b["relation"], tuple(b["terms"])) for b in r["body"]}
        others = body - {(kind, (x,))}
        if (kind, (x,)) not in body or len(others) != (0 if not who.startswith("?") else 1):
            continue
        if not who.startswith("?"):
            if who == role:
                out.append({"kind": kind, "rule": r["id"], "ground": []})
            continue
        (rel, terms), = others
        if rel == ROLE and terms == (who,) and named:
            out.append({"kind": kind, "rule": r["id"], "ground": [ROLE, role]})
        elif (rel == CAPABILITY and len(terms) == 2 and terms[0] == who and not terms[1].startswith("?")
              and terms[1] in capabilities):
            out.append({"kind": kind, "rule": r["id"], "ground": [CAPABILITY, role, terms[1]]})
    return sorted(out, key=lambda g: (g["kind"], g["rule"], g["ground"]))


def check_evidence(claimed, derived: list[dict]) -> list[dict]:
    """The publisher's evidence for a role's full kinds against the checker's own (`grants`)."""
    text = lambda gs: {json.dumps(g, sort_keys=True) for g in gs}  # noqa: E731
    got, want = text(claimed), text(derived)
    return [{"reason": "evidence_mismatch", "relation": ACCESS, "key": key} for key in sorted(got ^ want)]


def withheld_seals(doc: dict, kinds_full: set) -> frozenset[str]:
    """The relations of a seal with parts (docs/compiler.md#parts) a role gets none of: whether an element is
    refused or accepted, and whether each part counts, depends on all its parts, so a role reads them only if
    it reads every part kind in full."""
    out = set()
    for s in doc.get("seals", ()):
        parts = s.get("parts", ())
        if parts and not all(p.get("kind") in kinds_full for p in parts):
            out |= {s["refused"], s["accepted"], s["row_sha256"], *(p["accepted"] for p in parts)}
    return frozenset(out)


def full_relations(doc: dict, columns: dict, kinds_full: set, relations: set, withheld=frozenset(),
                   calc: dict | None = None) -> set[str]:
    """Of `relations` and the derived relations, those the role reads in full: every relation a derived
    one reaches through its rules (positive, negative, aggregated) that is not derived must be a base
    relation whose kind columns are all full, and not withheld. `calc` gives per calculation view what it
    rests on (`calc.sources`): such a view is no base relation. It is full if its subject kind is and each
    of its sources is, a premise view by this same rule; without known sources it is not (RV-S26)."""
    calc = calc or {}
    derived = {r["name"] for r in doc.get("relations", ()) if r.get("role") == "derived"}
    calc_inputs = {r["name"] for r in doc.get("relations", ()) if r.get("role") == "calc"}
    deps: dict[str, set[str]] = {}
    for r in doc.get("rules", ()):
        reads = deps.setdefault(r["head"]["relation"], set())
        reads.update(b["relation"] for b in r["body"])
        reads.update(a["relation"] for a in r.get("aggregates", ()))
    by_kinds = {rel for rel, cols in columns.items() if rel not in withheld and rel not in calc_inputs
                and all(k is None or k in kinds_full for k in cols)}
    base = {rel for rel in by_kinds if rel not in calc}

    def plain(rel: str) -> bool:
        reached, todo = set(), [rel]
        while todo:
            x = todo.pop()
            if x not in reached:
                reached.add(x)
                if x in derived:
                    todo.extend(deps.get(x, ()))
        return all(x in derived or x in base for x in reached)

    verdict: dict[str, bool] = {}

    def view(rel: str, above: tuple = ()) -> bool:
        """A calculation view; `above` are the views that rest on it here, so a circle is never full."""
        if rel not in verdict:
            if rel in above or calc[rel] is None or rel not in by_kinds:
                return False
            verdict[rel] = all(view(s, (*above, rel)) if s in calc else plain(s) for s in sorted(calc[rel]))
        return verdict[rel]

    return {rel for rel in relations | derived if (view(rel) if rel in calc else plain(rel))}


def select(instances, derived: set, usable=None) -> dict[tuple[str, str], dict]:
    """For every derivable row its chosen proof, as R7 defines it (docs/formal.md §3), computed here and not
    with the compiler's selector. The rank of a row is the least, over its usable instances whose derived
    positive premises all have a rank, of one more than the highest of those ranks (1 without), found level
    by level in rising rank, each row once. Each row gets the instance of least (rank, rule id, binding values, position)."""
    inst = []
    for i, w in enumerate(instances):
        if usable is not None and not usable(w):
            continue
        needs = {(p["row"]["relation"], p["row"]["key"]) for p in w.get("premises", ())
                 if p["polarity"] == "positive" and p["row"]["relation"] in derived}
        tie = (w["rule_id"], json.dumps([b["value"] for b in w.get("bindings", ())]))
        inst.append(((w["conclusion"]["relation"], w["conclusion"]["key"]), needs, tie, i, w))
    users = defaultdict(list)
    left = []
    for j, (_, needs, _, _, _) in enumerate(inst):
        left.append(len(needs))
        for n in needs:
            users[n].append(j)
    # In rising rank, one list per rank: a row is ranked once, by the first list that reaches it. An instance
    # waits until its last premise is ranked; that premise has the highest rank, so the instance has one more.
    rank: dict = {}
    level, r = [j for j, x in enumerate(inst) if not x[1]], 1
    while level:
        later = []
        for j in level:
            head = inst[j][0]
            if head in rank:
                continue
            rank[head] = r
            for k in users[head]:
                left[k] -= 1
                if left[k] == 0:
                    later.append(k)
        level, r = later, r + 1

    def of(needs) -> int | None:
        return 1 + max((rank[n] for n in needs), default=0) if all(n in rank for n in needs) else None

    best: dict = {}
    for head, needs, tie, i, w in inst:
        r = of(needs)
        if r is not None and (head not in best or (r, tie, i) < best[head][0]):
            best[head] = ((r, tie, i), w)
    return {h: w for h, (_, w) in best.items()}


def check_choice(witnesses, chosen: dict) -> list[dict]:
    """The given witnesses against the chosen proofs (`select`): the same set, or `choice_mismatch`."""
    text = lambda ws: {json.dumps(w, sort_keys=True) for w in ws}  # noqa: E731
    got, want = text(witnesses), text(chosen.values())
    out = []
    if got - want:
        out.append({"reason": "choice_mismatch", "detail": f"{len(got - want)} witnesses that are no chosen proof"})
    if want - got:
        out.append({"reason": "choice_mismatch", "detail": f"{len(want - got)} chosen proofs missing"})
    for f in out:
        f["severity"] = "error"
    return out


def _calc(ir: dict, views: set, every_witness, role_witnesses, derivable: set, full, every: dict, mine: dict,
          reads_subject) -> tuple[dict[tuple[str, str], dict], list[dict]]:
    """The calculated rows and witnesses the role may see, derived here and compared with what it got."""
    # A work list: a witness is looked at again only when a calculated premise of it becomes visible.
    visible: dict[tuple[str, str], dict] = {}
    users = defaultdict(list)
    for i, w in enumerate(every_witness):
        for p in w.get("premises", ()):
            if p["relation"] in views:
                users[(p["relation"], p["key"])].append(i)

    def sees(w: dict) -> bool:
        subject = subject_of(w["conclusion"]["key"])
        return (subject is not None and reads_subject(subject) and calc_reads(ir, version_of(ir, w)) <= full
                and all((p["relation"], p["key"]) in (visible if p["relation"] in views else derivable)
                        for p in w.get("premises", ())))

    todo = list(range(len(every_witness)))[::-1]
    while todo:
        w = every_witness[todo.pop()]
        r = (w["conclusion"]["relation"], w["conclusion"]["key"])
        if r not in visible and sees(w):
            visible[r] = w
            todo.extend(users[r])
    out = []
    for rel in sorted(views):
        want = {key for key in every.get(rel, {}) if (rel, key) in visible}
        got = set(mine.get(rel, {}))
        out += [{"reason": "calc_not_visible", "relation": rel, "key": key} for key in sorted(got - want)]
        out += [{"reason": "calc_visible_missing", "relation": rel, "key": key} for key in sorted(want - got)]
    text = lambda ws: {json.dumps(w, sort_keys=True) for w in ws}  # noqa: E731
    got, want = text(role_witnesses), text(visible.values())
    if got - want:
        out.append({"reason": "calc_not_visible", "detail": f"{len(got - want)} calculation witnesses"})
    if want - got:
        out.append({"reason": "calc_visible_missing", "detail": f"{len(want - got)} calculation witnesses"})
    return visible, out


def check_role(role: str, complete: dict, snapshots: dict, claimed_full, columns: dict, kinds, parents: dict,
               doc: dict, calc_ir: dict | None = None, instances=(), calc_all=(),
               calc_witnesses=(), witnesses=(), claimed_evidence=None) -> tuple[frozenset, list[dict]]:
    """(the relations `role` reads in full, findings) for one filtered role.

    `complete` and `snapshots` are {relation: snapshot bytes}: every row, and the role's. `columns` is the
    kind per column of each base relation (None for a value), `kinds` the kinds and `parents` their parent,
    all from the schema; `doc` is the rule IR; `claimed_full` the publisher's `full` for the role;
    `instances` every witness instance of the engine; `calc_all` every calculation witness and
    `calc_witnesses` the role's; `witnesses` the role's chosen proofs; `claimed_evidence` the publisher's
    evidence for the role's full kinds (`grants`), compared when given."""
    findings: list[dict] = []

    def rows(snaps: dict, whose: str) -> dict:
        out = {}
        for rel, data in snaps.items():
            try:
                out[rel] = read_rows(data, "json")
            except ValueError as err:
                findings.append({"reason": "malformed_snapshot", "relation": rel, "detail": f"{whose}: {err}"})
                out[rel] = {}
        return out

    every, mine = rows(complete, "complete"), rows(snapshots, role)
    columns = dict(columns)
    views = set()
    if calc_ir is not None:  # a calculated row names its subject; the evaluation date names no element
        views = published_views(calc_ir)
        columns |= {v: (calc_ir["subject"], None, None, None) for v in views}
        columns[calc_ir["as_of"]] = (None, None, None)
    chains = _chains(kinds, parents)
    allowed = {(p[1], p[2]) for p, _ in every.get(ACCESS, {}).values() if len(p) == 3 and p[0] == role}

    def reads(kind: str, id_: str) -> bool:
        return any((k, id_) in allowed for k in chains.get(kind, (kind,)))

    def readable(rel: str, parts) -> bool:
        return rel not in withheld and all(k is None or reads(k, v) for k, v in zip(columns[rel], parts))

    named = any(p[:1] == (role,) for p, _ in every.get(ROLE, {}).values())
    capabilities = frozenset(p[1] for p, _ in every.get(CAPABILITY, {}).values() if len(p) == 2 and p[0] == role)
    evidence = grants(doc, role, chains, named, capabilities)
    if claimed_evidence is not None:
        findings += check_evidence(claimed_evidence, evidence)
    kinds_full = {k for k, chain in chains.items() if {g["kind"] for g in evidence}.intersection(chain)}
    withheld = withheld_seals(doc, kinds_full)
    for k in sorted(kinds_full):
        if any(not reads(k, p[0]) for p, _ in every.get(k, {}).values()):
            findings.append({"reason": "full_not_readable", "relation": k})
    derived = {r["name"] for r in doc.get("relations", ()) if r.get("role") == "derived"}
    for rel in sorted((set(every) | set(mine)) - derived):
        if rel not in columns:
            findings.append({"reason": "no_columns", "relation": rel})
            continue
        want = {key for key, (p, _) in every.get(rel, {}).items() if readable(rel, p)}
        got = set(mine.get(rel, {}))
        findings += [{"reason": "not_readable", "relation": rel, "key": key} for key in sorted(got - want)]
        if rel not in views:
            findings += [{"reason": "readable_missing", "relation": rel, "key": key} for key in sorted(want - got)]
    full = frozenset(full_relations(doc, columns, kinds_full, set(every), withheld,
                                    calc_sources(calc_ir) if calc_ir is not None else None))
    if claimed_full is not None and set(claimed_full) != full:
        findings.append({"reason": "full_mismatch", "relation": ", ".join(sorted(set(claimed_full) ^ full))})
    width = {r["name"]: len(r["key"]) for r in doc.get("relations", ())}
    calc_inputs = {r["name"] for r in doc.get("relations", ()) if r.get("role") == "calc"}
    reads_rows = {rel: {encode_key(p[:width.get(rel, len(p))]) for p, _ in rs.values() if readable(rel, p)}
                  for rel, rs in every.items() if rel not in derived and rel not in calc_inputs and rel in columns}

    def usable(w: dict) -> bool:
        for p in w.get("premises", ()):
            rel = p["row"]["relation"]
            if p["polarity"] != "positive":
                if rel not in full:
                    return False
            elif rel not in derived and p["row"]["key"] not in reads_rows.get(rel, ()):
                return False
        return all(a["relation"] in full for a in w.get("aggregates", ()))

    chosen = select(instances, derived, usable)
    calc_findings = []
    if calc_ir is not None:
        visible, calc_findings = _calc(calc_ir, views, calc_all, calc_witnesses, set(chosen), full, every, mine,
                                       lambda x: reads(calc_ir["subject"], x))
        if calc_inputs:
            # Only the checker's own visibility result can make a calculation a rule premise.
            for rel in calc_inputs:
                reads_rows[rel] = {key for key, (p, _) in every.get(rel, {}).items()
                                   if (rel, key) in visible and len(p) == 4 and p[2:] == ("known", "")
                                   and INTEGER.fullmatch(p[1])}
            chosen = select(instances, derived, usable)
    findings += check_choice(witnesses, chosen)
    for rel in sorted(derived & (set(every) | set(mine))):
        want = {key for key in every.get(rel, {}) if (rel, key) in chosen}
        got = set(mine.get(rel, {}))
        findings += [{"reason": "not_derivable", "relation": rel, "key": key} for key in sorted(got - want)]
        findings += [{"reason": "derivable_missing", "relation": rel, "key": key} for key in sorted(want - got)]
    findings += calc_findings
    for f in findings:
        f["severity"] = "error"
    return full, findings
