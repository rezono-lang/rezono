"""The checks of docs/formal.md §3 and §6 for one proof against one manifest.

Input is plain data (the contracts' YAML/JSON as dicts), rule definitions from
rules.load_rules, and a function that returns the bytes of a snapshot URI.

The closed world is the complete snapshots: negation and aggregates are checked only
against snapshots marked complete, never against a role-filtered one. A role only filters
the report. Screened steps (`hidden`) are checked like every other witness; screening is a
redaction the explainer applies after a valid check.
"""

import datetime
import json
import re
from graphlib import CycleError, TopologicalSorter

from rezono_canon import canonical_sha256, sha256_hex

from . import calc, closure, metadata
from .canon import INTEGER, encode_key, sha256_json, value_text
from .evaluate import _arith, _fits, _fold, _holds, _value, cells
from .snapshots import read_rows

# A role snapshot never decides validity: a bad one is reported, as a warning.
WARNINGS = {"unreachable_witness", "role_snapshot_hash_mismatch", "role_malformed_snapshot"}  # every other reason blocks
# A role's report keeps only what carries no row data, plus the keys of rows the role can read.
PUBLIC = ("reason", "severity", "witness", "relation")
PUBLIC_DETAIL = {"manifest_mismatch", "manifest_check_red", "unknown_rule", "unknown_variable",
                 "duplicate_binding", "unbound_variable", "aggregate_binding", "assignment_mismatch",
                 "arithmetic_overflow"}
GROUP_KEYS = {"aggregate_mismatch", "aggregate_count", "aggregate_contributors", "aggregate_result", "invalid_value"}


def check(proof: dict, manifest: dict, rules: dict, read_bytes, role: str | None = None) -> dict:
    findings = []
    if proof["manifest_id"] != manifest["id"]:
        findings.append({"reason": "manifest_mismatch", "detail": proof["manifest_id"]})
    for c in manifest.get("checks", []):
        if c["status"] == "red":
            findings.append({"reason": "manifest_check_red", "detail": c["name"]})

    snapshots, readable = _load(manifest, read_bytes, role, findings)
    if snapshots is None:
        return _report(proof, role, readable, findings)  # nothing is checked against unverified data

    rows, groups = _rows(snapshots, findings), {}
    proof = {**proof, "witnesses": _well_formed(proof.get("witnesses", []), findings)}
    for i, w in enumerate(proof["witnesses"]):
        if w is not None:
            _check_witness(i, w, rules, rows, findings, groups)
    _check_graph(proof, rules, findings)
    return _report(proof, role, readable, findings)


def check_epoch(witnesses: list, manifest: dict, rules: dict, read_bytes, *, derived: set, full=None,
                seals=(), calc_witnesses=(), calc_ir=None, bundle=None, check_metadata=None) -> dict:
    """Every chosen witness of an epoch at once, against the complete snapshots, before a publication.

    Each witness is checked as in `check`, the graph of all of them is acyclic and every derived premise
    has a witness, and the set is complete: every row of every declared derived relation (`derived`, the
    relation catalogue: rules.derived_relations) has exactly one witness. A row without one is
    `unproven_row`. A witness that is not shaped as the contract says is `malformed_witness`. There is no
    root, so no reachability.

    For one role the snapshots are that role's, read as its closed world, and `full` names
    the relations it reads in full. A negation or an aggregate over any other relation would tell about
    rows the role cannot read: `outside_full_scope`.

    For the complete epoch (no `full`) the obligations of the rule IR are held against the snapshots
    themselves: every invariant relation is empty (`invariant_violated`), and every outcome gives each
    element of its kind exactly one state (`outcome_total`, `outcome_state`). And the snapshots
    are closed where a missing row is read: every instance of a rule of a relation that is negated, aggregated
    over, an invariant, an outcome or read by the calculation, or that such a relation depends on, has its
    head row (`underived_row`, closure.py). And no counter reached its bound: the rule of a
    counter with an explicit bound would add no row past it on the snapshots (`bound_reached`, closure.py).

    `seals` (rules.load_seals) are recomputed from the complete snapshots: row hashes, refused and accepted
    input of the sealed kind must be exactly what the snapshots give (`seal_mismatch`).

    `calc_witnesses` are recomputed with `calc_ir` (ir/calc.json, calc.check). Every row of a
    calculation view has exactly one (`unproven_row`); a derived premise needs a witness (`unproven_premise`);
    for a role, every relation a version reads, absences included, must be one it reads in full
    (`outside_full_scope`). A result that is `invalid` never publishes, even when proven right (`calc_invalid`).
    For the complete epoch every published calculation view gives every element of the subject kind exactly
    one row (`calc_row_missing`, `calc_row_duplicate`, calc.total).

    With `bundle` (the publication's schema bundle, as a dict), the check metadata the engine loaded
    (`check_metadata`: table -> rows of canonical text) must be exactly what the bundle's schema gives
    (`check_metadata_mismatch`, `malformed_check_metadata`, metadata.check).
    """
    findings = []
    if bundle is not None or check_metadata is not None:  # either alone is refused: nothing to compare
        findings += metadata.check(bundle, check_metadata)
    snapshots, _ = _load(manifest, read_bytes, None, findings)
    witnesses = _well_formed(witnesses if isinstance(witnesses, list) else [witnesses], findings)
    proof = {"manifest_id": manifest["id"], "root": None, "witnesses": witnesses}
    if snapshots is None:
        return _report(proof, None, set(), findings)
    rows, groups = _rows(snapshots, findings), {}
    for s in seals:
        _check_seal(s, rows, findings)
    for i, w in enumerate(witnesses):
        if w is not None:
            _check_witness(i, w, rules, rows, findings, groups)
            if full is not None:
                scoped = [p["row"]["relation"] for p in w.get("premises", []) if p["polarity"] != "positive"]
                for relation in sorted(set(scoped + [a["relation"] for a in w.get("aggregates", [])]) - set(full)):
                    findings.append({"reason": "outside_full_scope", "witness": i, "relation": relation})
    if full is None:  # a role's snapshots are filtered: the obligations hold for the complete epoch
        _check_obligations(rules, rows, findings)
        read = set().union(*(calc.reads(calc_ir, v["id"]) for v in (calc_ir or {}).get("versions", [])))
        findings += closure.check(rules, lambda relation: rows(relation, None), read)
        findings += closure.exhausted(rules, lambda relation: rows(relation, None))
    concluded = {(w["conclusion"]["relation"], w["conclusion"]["key"]) for w in witnesses if w is not None}
    checked_calcs, calc_views, calc_findings = [], set(), []
    if calc_ir is not None or calc_witnesses:
        checked_calcs = _check_calc(list(calc_witnesses), calc_ir, rows, concluded, derived, full, calc_findings)
        if calc_ir is not None:
            calc_views = calc.published_views(calc_ir)
    _check_graph(proof, rules, findings, checked_calcs, calc_views)
    for relation in sorted(derived):
        for key in sorted(rows(relation, None)):
            if (relation, key) not in concluded:
                findings.append({"reason": "unproven_row", "relation": relation, "key": key})
    findings.extend(calc_findings)
    return _report(proof, None, set(), findings)


OUTCOME_STATES = ("known", "unknown", "not_applicable")  # `invalid` comes from the violation views
REASON = re.compile(r"[a-z][a-z0-9_]*")  # a reason is a code, never free text


def _check_obligations(rules, rows, findings) -> None:
    """The obligations of the rule IR, held against the complete snapshots: an invariant relation is empty
    (`invariant_violated`, one per row), and an outcome gives every element of its kind a row and no row to
    anything else (`outcome_total`), with one state: `known` once with reason "", or `unknown` or
    `not_applicable` with one or more reason codes (`outcome_state`)."""
    for relation in sorted(getattr(rules, "invariants", ())):
        for key in sorted(rows(relation, None)):
            findings.append({"reason": "invariant_violated", "relation": relation, "key": key})
    for relation, kind in sorted(getattr(rules, "outcomes", {}).items()):
        elements = {parts[0] for parts, _ in rows(kind, None).values() if len(parts) == 1}
        given = {}
        for key, (parts, _) in sorted(rows(relation, None).items()):
            if len(parts) != 3:  # element, state and reason; checked before any part is read
                findings.append({"reason": "outcome_state", "relation": relation, "key": key})
            elif parts[0] in elements:
                given.setdefault(parts[0], []).append(parts)
            else:
                findings.append({"reason": "outcome_total", "relation": relation, "key": key})
        for element in sorted(elements - set(given)):
            findings.append({"reason": "outcome_total", "relation": relation, "key": encode_key([element])})
        for element, parts in sorted(given.items()):
            states = {p[1] for p in parts}
            (state,) = states if len(states) == 1 else (None,)
            reasons_ok = all(p[2] == "" if state == "known" else bool(REASON.fullmatch(p[2])) for p in parts)
            if state not in OUTCOME_STATES or not reasons_ok:
                findings.append({"reason": "outcome_state", "relation": relation, "key": encode_key([element])})


def _check_calc(witnesses, ir, rows, concluded, derived, full, findings):
    """The calculation witnesses of an epoch: each recomputed, the set complete."""
    if ir is None:
        findings.append({"reason": "malformed_witness", "detail": "calculation witnesses without ir/calc.json"})
        return []
    good = []
    for i, w in enumerate(witnesses):
        if calc.shaped(w):
            good.append(w)
        else:
            findings.append({"reason": "malformed_witness", "witness": i, "detail": "calculation"})
    for f in calc.check(good, ir, lambda relation: rows(relation, None)):
        findings.append(f)
    # calc.check says whether each result is computed right; whether it may publish is decided here. An
    # `invalid` result never does: the model contradicts itself, which is ours to fix. A witness that records another state than the checker computes is already calc_result.
    for i, w in enumerate(good):
        if w["state"] == "invalid":
            findings.append({"reason": "calc_invalid", "witness": i, "relation": w["conclusion"]["relation"],
                             "key": w["conclusion"]["key"], "detail": w.get("reason", "")})
    views = {r["view"] for r in ir.get("rules", [])} | {v["view"] for v in ir.get("versions", [])}
    proven = {(w["conclusion"]["relation"], w["conclusion"]["key"]) for w in good}
    for i, w in enumerate(good):
        for p in w.get("premises", []):
            ref = (p["relation"], p["key"])
            if (p["relation"] in derived and ref not in concluded) or (p["relation"] in views and ref not in proven):
                findings.append({"reason": "unproven_premise", "witness": i, "relation": ref[0], "key": ref[1]})
        if full is not None:
            for relation in sorted(calc.reads(ir, calc.version_of(ir, w)) - set(full)):
                findings.append({"reason": "outside_full_scope", "witness": i, "relation": relation})
    for relation in sorted(calc.published_views(ir)):
        for key in sorted(rows(relation, None)):
            if (relation, key) not in proven:
                findings.append({"reason": "unproven_row", "relation": relation, "key": key})
    if full is None:  # a role's snapshots are filtered: it may read a subject and not see its row
        findings.extend(calc.total(ir, lambda relation: rows(relation, None)))
    return good


def _check_seal(seal: dict, rows, findings) -> None:
    """The row hashes and the refused and accepted input of the sealed kind, recomputed from the
    snapshots. A row hash is the canonical JSON of {table: sorted values} over the seal's tables; a
    subkind's table has no values, so membership is the empty list. A close applies to an element when the
    element's period lies before its boundary or the close covers it, and refuses it unless it covers it with
    its recomputed hash; each close on its own. A row too many or too few is `seal_mismatch`; a date that is not
    ISO is `seal_bad_date`."""
    def all_rows(relation):
        return [parts for parts, _ in rows(relation, None).values()]

    def pairs(relation):
        return [parts for parts in all_rows(relation) if len(parts) == 2]

    def dated(relation):
        out = []
        for parts in all_rows(relation):
            try:
                out.append((parts[0], datetime.date.fromisoformat(parts[1])))
            except (IndexError, ValueError):
                findings.append({"reason": "seal_bad_date", "relation": relation, "key": encode_key(list(parts))})
        return out

    elements = {parts[0] for parts in all_rows(seal["kind"])}
    values = {}
    for table in seal["tables"]:
        for parts in all_rows(table):
            values.setdefault(parts[0], {}).setdefault(table, []).extend(parts[1:])
    # A part's rows belong to the row of the element it reaches through its arrow (and its owner's, for a part
    # of a part); each row as a list [id, values...].
    owner_of = {}
    for part in seal.get("parts", []):
        up = owner_of.get(part["owner"])
        owner_of[part["kind"]] = {p[0]: (p[1] if up is None else up[p[1]]) for p in pairs(part["arrow"])
                                  if (p[1] in elements if up is None else p[1] in up)}
        for table in part["tables"]:
            for parts in all_rows(table):
                if parts[0] in owner_of[part["kind"]]:
                    values.setdefault(owner_of[part["kind"]][parts[0]], {}).setdefault(table, []).append(list(parts))
    hashes = {i: canonical_sha256({t: sorted(vs) for t, vs in values.get(i, {}).items()}) for i in elements}
    until = dated(seal["closed_until"])
    closes_of = {}
    for v, c in pairs(seal["covers"]):
        closes_of.setdefault(c, set()).add(v)
    sha = {}
    for c, h in pairs(seal["sha256"]):
        sha.setdefault(c, set()).add(h)
    applies = {(i, v) for i, p in dated(seal["period"]) for v, u in until if p < u}
    held = set()
    for c, e in pairs(seal["element"]):
        for v in closes_of.get(c, ()):
            if e in elements:
                applies.add((e, v))
            if hashes.get(e) in sha.get(c, ()):
                held.add((e, v))
    refused = applies - held
    accepted = {(i,) for i in elements - {i for i, _ in refused}}
    expected = [(seal["row_sha256"], {(i, h) for i, h in hashes.items()}), (seal["refused"], refused),
                (seal["accepted"], accepted)]
    ok = {seal["kind"]: {i for (i,) in accepted}}
    for part in seal.get("parts", []):  # a part counts when the element it is part of does
        ok[part["kind"]] = {p[0] for p in pairs(part["arrow"]) if p[1] in ok[part["owner"]]}
        expected.append((part["accepted"], {(i,) for i in ok[part["kind"]]}))
    for relation, want in expected:
        got = {tuple(parts) for parts in all_rows(relation)}
        for key in sorted(got ^ want):
            findings.append({"reason": "seal_mismatch", "relation": relation, "key": encode_key(list(key))})


def _text(v) -> bool:
    return isinstance(v, str)


def _ref(r) -> bool:
    return isinstance(r, dict) and _text(r.get("relation")) and _text(r.get("key"))


def shaped(w) -> bool:
    """A witness as contracts/proof.yaml has it: the fields the checks read, with their types."""
    if not (isinstance(w, dict) and _ref(w.get("conclusion")) and _text(w.get("rule_id"))):
        return False
    lists = [w.get(f, []) for f in ("bindings", "premises", "aggregates")]
    if not all(isinstance(x, list) for x in lists):
        return False
    bindings, premises, aggregates = lists
    return (all(isinstance(b, dict) and _text(b.get("variable")) and _text(b.get("value")) for b in bindings)
            and all(isinstance(p, dict) and _ref(p.get("row")) and _text(p.get("polarity"))
                    and type(p.get("stratum")) is int for p in premises)
            and all(isinstance(a, dict) and _text(a.get("relation")) and _text(a.get("group_key"))
                    and type(a.get("count")) is int and _text(a.get("contributors_sha256")) and _text(a.get("result"))
                    and type(a.get("position", 0)) is int for a in aggregates))


def _well_formed(witnesses, findings) -> list:
    """The witnesses, with None for each that is malformed (and a finding for it)."""
    out = []
    for i, w in enumerate(witnesses):
        if shaped(w):
            out.append(w)
        else:
            findings.append({"reason": "malformed_witness", "witness": i})
            out.append(None)
    return out


def _rows(snapshots, findings):
    """The rows of a relation from the complete snapshots; a missing snapshot is a finding."""

    def rows(relation, witness):
        if relation not in snapshots:
            finding = {"reason": "snapshot_missing", "relation": relation}
            findings.append(finding if witness is None else {**finding, "witness": witness})
            snapshots[relation] = {}
        return snapshots[relation]

    return rows


def _load(manifest, read_bytes, role, findings):
    """The complete snapshots of a manifest, and the rows the role can read. None if one is untrustworthy."""
    snapshots, readable = {}, set()
    for s in manifest.get("snapshots", []):
        prefix = "" if s["complete"] else "role_"  # "_owner": only that role may read the detail
        data = read_bytes(s["uri"])
        if sha256_hex(data) != s["sha256"]:
            findings.append({"reason": prefix + "snapshot_hash_mismatch", "relation": s["relation"],
                             "detail": s["uri"], "_owner": s["role"]})
            continue
        if not (s["complete"] or s["role"] == role):
            continue
        try:
            relation_rows = read_rows(data, s["format"])
        except ValueError as e:
            findings.append({"reason": prefix + "malformed_snapshot", "relation": s["relation"],
                             "detail": str(e), "_owner": s["role"]})
            continue
        if s["complete"]:
            snapshots[s["relation"]] = relation_rows
        if s["role"] == role:
            readable |= {(s["relation"], k) for k in relation_rows}
    if any(f["reason"] in ("snapshot_hash_mismatch", "malformed_snapshot") for f in findings):
        return None, readable
    return snapshots, readable


def _check_witness(i, w, rules, rows, findings, groups=None):
    def find(reason, **kw):
        findings.append({"reason": reason, "witness": i, **kw})

    rule = rules.get(w["rule_id"])
    if rule is None:
        return find("unknown_rule", detail=w["rule_id"])
    theta = {}
    for b in w.get("bindings", []):
        if b["variable"] not in rule.variables:
            find("unknown_variable", detail=b["variable"])
        elif b["variable"] in theta:
            find("duplicate_binding", detail=b["variable"])
        else:
            theta[b["variable"]] = b["value"]
    # Every variable of the rule is bound: a missing binding never lets a check be skipped.
    for v in sorted(rule.variables - set(theta)):
        find("unbound_variable", detail=v)

    def subst(atom):
        """Replace variables by their binding; constants and '_' stay as they are."""
        out = []
        for t in atom.terms:
            if t.startswith("?") and t not in theta:
                find("unbound_variable", detail=t)
            out.append(theta.get(t, t) if t.startswith("?") else t)
        return tuple(out)

    c = w["conclusion"]
    if (rule.head.relation, encode_key(subst(rule.head))) != (c["relation"], c["key"]):
        find("head_mismatch", relation=c["relation"], key=c["key"])
    if c["key"] not in rows(c["relation"], i):
        find("conclusion_missing", relation=c["relation"], key=c["key"])

    expected = sorted((b.atom.relation, encode_key(subst(b.atom)), b.polarity, b.stratum) for b in rule.body)
    given = sorted((p["row"]["relation"], p["row"]["key"], p["polarity"], p["stratum"]) for p in w.get("premises", []))
    if expected != given:
        find("premise_mismatch", expected=[list(e) for e in expected], given=[list(g) for g in given])
    for relation, key, polarity, stratum in given:
        present = key in rows(relation, i)
        if polarity == "positive" and not present:
            find("premise_missing", relation=relation, key=key)
        elif polarity == "negative":
            if stratum >= rule.stratum:
                find("stratum_violation", relation=relation, key=key)
            if present:
                find("negative_premise_present", relation=relation, key=key)

    # An aggregate premise is known by its position in the rule; without a position (optional in the
    # contract, as in the first, minimal form) by relation and group, which two aggregates over one
    # group would share. A proof may mix both.
    given = w.get("aggregates", [])
    positioned = {a["position"]: a for a in given if "position" in a}
    keyed = {(a["relation"], a["group_key"]): a for a in given if "position" not in a}
    if (len(positioned) + len(keyed) != len(given) or len(given) != len(rule.aggregates)
            or not set(positioned) <= set(range(len(rule.aggregates)))):
        find("aggregate_mismatch", detail=f"{len(given)} given, {len(rule.aggregates)} expected")
    for index, spec in enumerate(rule.aggregates):
        values = subst(spec.atom)
        fixed = [(pos, v) for pos, (t, v) in enumerate(zip(spec.atom.terms, values)) if t != "_"]
        group = encode_key(v for _, v in fixed)
        a = positioned[index] if index in positioned else keyed.get((spec.atom.relation, group))
        if a is None or (a["relation"], a["group_key"]) != (spec.atom.relation, group):
            find("aggregate_mismatch", relation=spec.atom.relation, key=group)
            continue
        count, contributors, result, invalid = recompute(spec, fixed, rows(spec.atom.relation, i), groups)
        if invalid:
            find("invalid_value", relation=spec.atom.relation, key=group)
        for field, value in (("count", count), ("contributors_sha256", contributors), ("result", result)):
            if a[field] != value:
                find(f"aggregate_{field.removesuffix('_sha256')}", relation=a["relation"], key=group,
                     detail=f"{a[field]} != {value}")
        if rule.bare_values and result.startswith("known:") and not _fits(result.removeprefix("known:")):
            find("arithmetic_overflow", relation=spec.atom.relation, detail=spec.var)  # before any use of it
        bound = theta.get(spec.var)
        if spec.var and (f"known:{bound}" if rule.bare_values and bound is not None else bound) != result:
            find("aggregate_binding", detail=spec.var)
    for c in rule.assignments:
        if not all(t in theta for t in (c.var, c.left, c.right) if t.startswith("?")):
            continue  # reported as unbound_variable
        got = _arith(c.op, _value(c.left, theta), _value(c.right, theta))
        if not all(_fits(v) for v in (_value(c.left, theta), _value(c.right, theta), got) if v is not None):
            find("arithmetic_overflow", detail=c.var)  # every engine stops there, so no proof can pass it
        elif got is None or got != _value(c.var, theta):
            find("assignment_mismatch", detail=c.var)
    for c in rule.conditions:
        if not all(t in theta for t in (c.left, c.right) if t.startswith("?")):
            continue
        if not _holds(c.op, _value(c.left, theta), _value(c.right, theta)):
            find("condition_false", detail=f"{c.left} {c.op} {c.right}")


def recompute(spec, fixed, relation_rows, groups=None):
    """Count, contributors hash, result and 'reads invalid input' for one aggregate (formal.md §6).

    The group is every row of the right arity that matches the fixed (non-'_') positions of the rule.
    `groups` caches an index per (relation, arity, fixed positions), so each relation is scanned once.
    """
    arity, positions = len(spec.atom.terms), tuple(pos for pos, _ in fixed)
    index_key = (spec.atom.relation, id(relation_rows), arity, positions)
    if groups is None or index_key not in groups:
        index = {}
        for k, (parts, values) in relation_rows.items():
            if len(parts) == arity:
                index.setdefault(tuple(parts[pos] for pos in positions), []).append((k, values))
        for members in index.values():
            members.sort(key=lambda m: m[0])
        if groups is None:
            groups = {}
        groups[index_key] = index
    members = groups[index_key].get(tuple(v for _, v in fixed), [])
    if spec.function == "count":
        return len(members), sha256_json([[k] for k, _ in members]), f"known:{len(members)}", False
    read = cells(spec, [(json.loads(k), values) for k, values in members])
    contributors = sha256_json([[k, value_text(v)] for (k, _), v in zip(members, read)])
    result = _fold(spec.function, read)
    return len(members), contributors, result, result == "invalid"


def _check_graph(proof, rules, findings, calc_witnesses=(), calc_views=frozenset()):
    """A well-founded graph of the rule and calculation witnesses in the same manifest."""
    calc_views = set(calc_views)
    for rule in rules.values():
        calc_views.update(rule.calc_inputs)
    by_conclusion = {}
    for i, w in enumerate(proof.get("witnesses", [])):
        if w is None:
            continue
        ref = (w["conclusion"]["relation"], w["conclusion"]["key"])
        if ref in by_conclusion:
            findings.append({"reason": "duplicate_witness", "witness": i, "relation": ref[0], "key": ref[1]})
        by_conclusion.setdefault(ref, i)
    calculated = {}
    for i, w in enumerate(calc_witnesses):
        ref = (w["conclusion"]["relation"], w["conclusion"]["key"])
        if ref in calculated or ref in by_conclusion:
            findings.append({"reason": "duplicate_witness", "witness": i, "relation": ref[0], "key": ref[1]})
        calculated.setdefault(ref, w)
    root = (proof["root"]["relation"], proof["root"]["key"]) if proof["root"] else None
    if root and root not in by_conclusion:
        findings.append({"reason": "root_not_derived", "relation": root[0], "key": root[1]})
    for h in proof.get("hidden", []):
        if (h["relation"], h["key"]) not in by_conclusion:
            findings.append({"reason": "hidden_without_witness", "relation": h["relation"], "key": h["key"]})

    derived = {r.head.relation for r in rules.values()}
    proved = by_conclusion.keys() | calculated.keys()
    graph = {ref: {(p["relation"], p["key"]) for p in w.get("premises", ())
                   if (p["relation"], p["key"]) in proved} for ref, w in calculated.items()}
    for i, w in enumerate(proof.get("witnesses", [])):
        if w is None:
            continue
        ref = (w["conclusion"]["relation"], w["conclusion"]["key"])
        graph.setdefault(ref, set())
        for p in w.get("premises", []):
            row = (p["row"]["relation"], p["row"]["key"])
            if p["polarity"] != "positive":
                continue
            if row in calculated:
                calc_witness = calculated[row]
                value = calc_witness.get("value", "")
                if (calc_witness["state"] != "known" or calc_witness.get("reason", "")
                        or not INTEGER.fullmatch(value)):
                    findings.append({"reason": "bad_calc_premise", "witness": i, "relation": row[0], "key": row[1]})
            if row[0] in calc_views and row not in calculated:
                findings.append({"reason": "unproven_premise", "witness": i, "relation": row[0], "key": row[1]})
            elif row in proved:
                graph[ref].add(row)
            elif row[0] in derived:
                findings.append({"reason": "unproven_premise", "witness": i, "relation": row[0], "key": row[1]})
    try:
        TopologicalSorter({k: sorted(v) for k, v in sorted(graph.items())}).prepare()
    except CycleError as e:
        rows = sorted(set(e.args[1]))
        findings.append({"reason": "cycle", "rows": [{"relation": r, "key": k} for r, k in rows]})

    if root is None:
        return  # an epoch's witness set: no root to reach from
    reached, todo = set(), [root] if root in graph else []
    while todo:
        ref = todo.pop()
        if ref not in reached:
            reached.add(ref)
            todo.extend(graph[ref])
    for ref in sorted(set(graph) - reached):
        findings.append({"reason": "unreachable_witness", "witness": by_conclusion[ref],
                         "relation": ref[0], "key": ref[1]})


def _redact(finding, role, readable):
    """The finding as a role may see it: no values, and only keys of rows the role can read."""
    out = {k: v for k, v in finding.items() if k in PUBLIC}
    if "detail" in finding and (finding["reason"] in PUBLIC_DETAIL or finding.get("_owner") == role):
        out["detail"] = finding["detail"]
    if "key" in finding:
        if finding["reason"] not in GROUP_KEYS and (finding["relation"], finding["key"]) in readable:
            out["key"] = finding["key"]
        else:
            out["screened"] = True
    if "rows" in finding:
        out["rows"] = [r if (r["relation"], r["key"]) in readable else {"relation": r["relation"], "screened": True}
                       for r in finding["rows"]]
    for field in ("expected", "given"):
        if field in finding:
            out[field] = [[rel, key if (rel, key) in readable else "screened", *rest] for rel, key, *rest in finding[field]]
    return out


def _report(proof, role, readable, findings):
    for f in findings:
        f["severity"] = "warning" if f["reason"] in WARNINGS else "error"
    if role is not None:
        findings = [_redact(f, role, readable) for f in findings]
    findings = [{k: v for k, v in f.items() if k != "_owner"} for f in findings]
    unique = {json.dumps(f, sort_keys=True): f for f in findings}
    ordered = sorted(unique.values(), key=lambda f: (f.get("witness", -1), f["reason"], json.dumps(f, sort_keys=True)))
    report = {
        "manifest_id": proof["manifest_id"],
        "witnesses": len(proof.get("witnesses", [])),
        "valid": not any(f["severity"] == "error" for f in ordered),
        "findings": ordered,
    }
    if proof["root"]:
        root = {"relation": proof["root"]["relation"], "key": proof["root"]["key"]}
        if role is not None and (root["relation"], root["key"]) not in readable:
            root = {"relation": root["relation"], "screened": True}
        report["root"] = root
    if role is not None:
        report["role"] = role
    return report


def render(report: dict) -> str:
    """Deterministic bytes: sorted keys, fixed separators, trailing newline."""
    return json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
