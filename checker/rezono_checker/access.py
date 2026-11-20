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
- A program that declares `may_read_full(role, kind)` requires a row of the complete snapshots for this role
  and kind and a valid rule witness for that row. The evidence names the rule and the coverage row.
  A program that predates the relation reads a kind in full if a read rule grants it without a condition:
  with the role as a constant
  and only `K(x)`, or `may_read(r, "K", x) :- role(r), K(x).` for a role the complete `role` rows hold (for
  any other role that rule derives nothing, so nothing in full either), or
  `may_read(r, "K", x) :- role__capability(r, "c"), K(x).` for a role the complete `role__capability` rows map
  to capability `c` (roles in two layers, B19). Subkinds follow. Each such grant is evidence: the rule and the
  row it rests on (`grants`). The evidence must be the one the publisher hands over (`evidence_mismatch`), so
  a total or an absence over a kind is complete for the role only on a row of the complete snapshots.
  Every element of a full kind must be readable (`full_not_readable`). A base relation is full if each of
  its kind columns is; a derived relation if every base relation it reaches through the rules is. A
  calculation view is full if its subject kind is, every relation that a version of its rule reads is, and
  every calculation view a version takes as a premise is; never when the program does not account
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
from .evidence import PROTECTED
from .check import _check_witness, _rows, shaped
from .rules import load_rules
from .snapshots import read_rows
from .variant_access import check_variant_status_readers as check_variant_status_readers

ACCESS = "may_read"
READ_FULL = "may_read_full"
ROLE = "role"  # the kind of the roles: `role(r)` in a read rule means every role the pack's facts name
# A role's generic capabilities (std-access): `role__capability(r, "c")` in a read rule means every role the
# pack's facts map to capability `c`.
CAPABILITY = "role__capability"
SLOT_PARAMETER_SUFFIXES = (
    "minimum",
    "maximum",
    "constant",
    "minimum_cardinality",
    "maximum_cardinality",
)


def _non_empty_str(value, what: str) -> str:
    if not isinstance(value, str) or not value:
        raise ValueError(f"{what} must be a non-empty string")
    return value


def _schema_from_bundle(bundle, doc: dict) -> tuple[frozenset[str], dict[str, str], dict[str, tuple]]:
    """Derive (kinds, parents, columns) independently from the compiled schema bundle and rule IR."""
    if not isinstance(bundle, dict):
        raise ValueError("schema bundle must be a mapping")
    raw_kinds = bundle.get("kinds")
    if not isinstance(raw_kinds, list):
        raise ValueError("schema bundle must list kinds")
    kinds: set[str] = set()
    parents: dict[str, str] = {}
    columns: dict[str, tuple] = {}
    for entry in raw_kinds:
        if not isinstance(entry, dict):
            raise ValueError("kind entry must be a mapping")
        kid = _non_empty_str(entry.get("id"), "kind id")
        if kid in kinds:
            raise ValueError(f"duplicate kind {kid!r}")
        kinds.add(kid)
        columns[kid] = (kid,)
        parent = entry.get("parent")
        if parent is not None:
            parents[kid] = _non_empty_str(parent, f"parent of kind {kid!r}")
    for kid, parent in parents.items():
        if parent not in kinds:
            raise ValueError(f"kind {kid!r} names unknown parent {parent!r}")
    for kid in kinds:
        seen, cur = {kid}, parents.get(kid)
        while cur is not None:
            if cur in seen:
                raise ValueError(f"parent cycle involving kind {kid!r}")
            seen.add(cur)
            cur = parents.get(cur)

    def section(name: str) -> list:
        value = bundle.get(name)
        if value is None:
            return []
        if not isinstance(value, list):
            raise ValueError(f"schema bundle {name} must be a list")
        return value

    slot_tables: list[str] = []
    for entry in section("arrows"):
        if not isinstance(entry, dict):
            raise ValueError("arrow entry must be a mapping")
        table = _non_empty_str(entry.get("table"), "arrow table")
        kind = _non_empty_str(entry.get("kind"), f"arrow {table!r} kind")
        target = _non_empty_str(entry.get("target"), f"arrow {table!r} target")
        if kind not in kinds or target not in kinds:
            raise ValueError(f"arrow {table!r} references unknown kind")
        if table in columns:
            raise ValueError(f"duplicate table {table!r}")
        columns[table] = (kind, target)
        slot_tables.append(table)

    for entry in section("attributes"):
        if not isinstance(entry, dict):
            raise ValueError("attribute entry must be a mapping")
        table = _non_empty_str(entry.get("table"), "attribute table")
        kind = _non_empty_str(entry.get("kind"), f"attribute {table!r} kind")
        if kind not in kinds:
            raise ValueError(f"attribute {table!r} references unknown kind")
        if table in columns:
            raise ValueError(f"duplicate table {table!r}")
        columns[table] = (kind, None)
        slot_tables.append(table)

    for entry in section("enums"):
        if not isinstance(entry, dict):
            raise ValueError("enum entry must be a mapping")
        eid = _non_empty_str(entry.get("id"), "enum id")
        if eid in columns:
            raise ValueError(f"duplicate table {eid!r}")
        columns[eid] = (None,)

    relations = doc.get("relations", ()) if isinstance(doc, dict) else ()
    base_relations = {
        r["name"] for r in relations
        if isinstance(r, dict) and r.get("role") == "base" and isinstance(r.get("name"), str)
    }
    for slot_table in slot_tables:
        for suffix in SLOT_PARAMETER_SUFFIXES:
            param_table = f"{slot_table}__{suffix}"
            if param_table in base_relations and param_table not in columns:
                columns[param_table] = (None,)

    seals = doc.get("seals") if isinstance(doc, dict) else ()
    if seals is None:
        seals = ()
    if not isinstance(seals, (list, tuple)):
        raise ValueError("seals must be a list")
    for seal in seals:
        if not isinstance(seal, dict):
            raise ValueError("seal entry must be a mapping")
        kind = _non_empty_str(seal.get("kind"), "seal kind")
        refused = _non_empty_str(seal.get("refused"), "seal refused")
        accepted = _non_empty_str(seal.get("accepted"), "seal accepted")
        row_sha = _non_empty_str(seal.get("row_sha256"), "seal row_sha256")
        columns[refused] = (kind, "period_close")
        columns[accepted] = (kind,)
        columns[row_sha] = (kind, None)
        parts = seal.get("parts")
        if parts is None:
            parts = ()
        if not isinstance(parts, (list, tuple)):
            raise ValueError("seal parts must be a list")
        for part in parts:
            if not isinstance(part, dict):
                raise ValueError("seal part must be a mapping")
            p_kind = _non_empty_str(part.get("kind"), "seal part kind")
            p_accepted = _non_empty_str(part.get("accepted"), "seal part accepted")
            columns[p_accepted] = (p_kind,)

    return frozenset(kinds), parents, columns


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


def withheld_admission() -> frozenset[str]:
    """Every protected admission input (decisions/admission-transport.md, section 6), by the checker's own list,
    whatever the rule IR declares and never by the publisher's columns: a role reads none of their rows until a
    decision gives them a read rule or element columns. A rule IR that leaves one out withholds it all the same."""
    return frozenset(PROTECTED)


def full_relations(doc: dict, columns: dict, kinds_full: set, relations: set, withheld=frozenset(),
                   calc: dict | None = None) -> set[str]:
    """Of `relations` and the derived relations, those the role reads in full: every relation a derived
    one reaches through its rules (positive, negative, aggregated) that is not derived must be a base
    relation whose kind columns are all full, and not withheld. `calc` gives per calculation view what it
    rests on (`calc.sources`): such a view is no base relation. It is full if its subject kind is and each
    of its sources is, a premise view by this same rule; without known sources it is not."""
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


def _derived_premises(witness: dict, derived: set) -> set[tuple[str, str]]:
    return {(p["row"]["relation"], p["row"]["key"]) for p in witness.get("premises", ())
            if p["polarity"] == "positive" and p["row"]["relation"] in derived}


def select(instances, derived: set, usable=None) -> dict[tuple[str, str], dict]:
    """For every derivable row its chosen proof, as R7 defines it (docs/formal.md §3), computed here and not
    with the compiler's selector. The rank of a row is the least, over its usable instances whose derived
    positive premises all have a rank, of one more than the highest of those ranks (1 without), found level
    by level in rising rank, each row once. Each row gets the instance of least (rank, rule id, binding values, position)."""
    inst = []
    for i, w in enumerate(instances):
        if usable is not None and not usable(w):
            continue
        needs = _derived_premises(w, derived)
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


def _witnessed_grants(doc: dict, role: str, chains: dict, every: dict, instances, derived: set,
                      findings: list[dict]) -> list[dict]:
    """Check coverage witnesses and their positive rule premises against the complete snapshots."""
    coverage = {}
    for key, (parts, _) in every.get(READ_FULL, {}).items():
        if parts[:1] == (role,):
            if len(parts) != 2 or parts[1] not in chains:
                findings.append({"reason": "evidence_mismatch", "relation": READ_FULL, "key": key})
            else:
                coverage[(READ_FULL, key)] = parts[1]
    if not coverage:
        return []

    by_row = defaultdict(list)
    for index, witness in enumerate(instances):
        conclusion = witness["conclusion"]
        by_row[conclusion["relation"], conclusion["key"]].append((index, witness))
    rules, groups = load_rules(doc), {}
    checked = []
    seen, pending = set(), set(coverage)
    while pending:
        ref = pending.pop()
        seen.add(ref)
        for index, witness in by_row[ref]:
            problems: list[dict] = []
            _check_witness(index, witness, rules, _rows(dict(every), problems), problems, groups)
            if not problems:
                checked.append(witness)
                pending.update(_derived_premises(witness, derived) - seen)

    supported = set(select(checked, derived))
    proofs = defaultdict(set)
    for witness in checked:
        conclusion = witness["conclusion"]
        ref = (conclusion["relation"], conclusion["key"])
        if ref in coverage and _derived_premises(witness, derived) <= supported:
            proofs[ref].add(witness["rule_id"])
    out = []
    for ref, kind in sorted(coverage.items()):
        if not proofs[ref]:
            findings.append({"reason": "evidence_mismatch", "relation": READ_FULL, "key": ref[1]})
        out.extend({"kind": kind, "rule": rule, "ground": [READ_FULL, role, kind]} for rule in sorted(proofs[ref]))
    return out


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


def check_role(role: str, complete: dict, snapshots: dict, claimed_full, bundle: dict,
               doc: dict, calc_ir: dict | None = None, instances=(), calc_all=(),
               calc_witnesses=(), witnesses=(), claimed_evidence=None) -> tuple[frozenset, list[dict]]:
    """(the relations `role` reads in full, findings) for one filtered role.

    `complete` and `snapshots` are {relation: snapshot bytes}: every row, and the role's. `bundle` is the
    compiled schema bundle (`schema-bundle.json`), from which the checker derives kinds, parents and per-column
    kinds itself; `doc` is the rule IR; `claimed_full` the publisher's `full` for the role; `instances` every
    witness instance of the engine; `calc_all` every calculation witness and `calc_witnesses` the role's;
    `witnesses` the role's chosen proofs; `claimed_evidence` the publisher's evidence for the role's full kinds
    (`grants`), compared when given."""
    try:
        kinds, parents, columns = _schema_from_bundle(bundle, doc)
    except ValueError as err:
        return frozenset(), [{"reason": "malformed_bundle", "detail": str(err), "severity": "error"}]
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

    every = rows(complete, "complete")
    complete_valid = not findings
    mine = rows(snapshots, role)
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

    relations = doc.get("relations", ())
    derived = {r["name"] for r in relations if r.get("role") == "derived"}
    explicit = any(r["name"] == READ_FULL for r in relations)
    if explicit:
        instances = list(instances)
        valid = [w for w in instances if shaped(w)]
        if len(valid) != len(instances):
            findings.append({"reason": "evidence_mismatch", "relation": READ_FULL, "detail": "malformed rule instances"})
        evidence = _witnessed_grants(doc, role, chains, every, valid, derived, findings) if complete_valid else []
        instances = valid
    else:
        named = any(p[:1] == (role,) for p, _ in every.get(ROLE, {}).values())
        capabilities = frozenset(p[1] for p, _ in every.get(CAPABILITY, {}).values() if len(p) == 2 and p[0] == role)
        evidence = grants(doc, role, chains, named, capabilities)
    granted = {g["kind"] for g in evidence}
    kinds_full = {k for k, chain in chains.items() if granted.intersection(chain)}
    unreadable = {k for k in kinds_full if any(not reads(k, p[0]) for p, _ in every.get(k, {}).values())}
    findings += [{"reason": "full_not_readable", "relation": k} for k in sorted(unreadable)]
    if explicit and unreadable:
        rejected = {ancestor for k in unreadable for ancestor in chains[k]}
        evidence = [g for g in evidence if g["kind"] not in rejected]
        kinds_full = {k for k, chain in chains.items() if (granted - rejected).intersection(chain)}
    if claimed_evidence is not None:
        findings += check_evidence(claimed_evidence, evidence)
    withheld = withheld_seals(doc, kinds_full) | withheld_admission()
    for rel in sorted((set(every) | set(mine)) - derived):
        if rel in withheld:
            got = set(mine.get(rel, {}))
            findings += [{"reason": "not_readable", "relation": rel, "key": key} for key in sorted(got)]
            continue
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
