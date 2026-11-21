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
from operator import itemgetter

from rezono_canon import canonical_bytes, canonical_sha256, sha256_hex

from . import calc, closure, completeness, metadata
from . import evidence as admission
from .canon import INTEGER, calc_value, encode_key, sha256_json, strict_json_loads, value_text
from .evaluate import _arith, _fits, _fold, _holds, _value, cells
from .refusals import RefusalError
from .rules import check_calc_personal_slots, check_personal_slots
from .snapshots import read_rows
from .state_projections import check as check_state_projections

# A role snapshot never decides validity: a bad one is reported, as a warning.
# Every other reason blocks; an unadmitted receipt or round only leaves coverage unknown.
WARNINGS = {"unreachable_witness", "role_snapshot_hash_mismatch", "role_malformed_snapshot",
            "receipt_unverified", "round_unverified"}
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
    domains = set()
    functionals = getattr(rules, "functionals", {})
    for i, w in enumerate(proof["witnesses"]):
        if w is not None:
            _check_witness(i, w, rules, rows, findings, groups)
            if (rule := rules.get(w["rule_id"])) is not None:
                domains.update(aggregate.atom.relation for aggregate in rule.aggregates)
                if functionals:
                    domains.update(b.atom.relation for b in rule.body if b.polarity != "positive")
                if (func := functionals.get(rule.head.relation)) is not None:
                    domains.add(rule.head.relation)
                    domains.add(func.domain)
                    for r_item in rules.values():
                        if r_item.head.relation == func.name:
                            domains.update(b.atom.relation for b in r_item.body)
                            domains.update(a.atom.relation for a in r_item.aggregates)
    _check_graph(proof, rules, findings)
    if domains and not any(f["reason"] not in WARNINGS for f in findings):
        scope = closure.dependencies(rules, domains)
        findings.extend(closure.check(rules, lambda relation: rows(relation, None), domains=domains))
        for relation in sorted(scope & functionals.keys()):
            _check_functional_relation(relation, functionals[relation], rules, rows, findings, groups)
    return _report(proof, role, readable, findings)


def check_epoch(witnesses: list, manifest: dict, rules: dict, read_bytes, *, derived: set, full=None,
                seals=(), calc_witnesses=(), calc_ir=None, bundle=None, check_metadata=None,
                completeness_authority=(), evidence=None) -> dict:
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

    For the complete epoch every row of the protected relation `verified_receipt` must be supplied by a
    candidate of the manifest's `completeness_receipts` that completeness.verify admits against the trusted
    contexts in `completeness_authority` (from the verified definition or the protected caller, never from the
    manifest): `receipt_not_admitted`. A candidate that is not admitted is `receipt_unverified`, a warning.
    With `evidence` (rezono_checker.evidence.Evidence, the one the epoch was admitted with) the checker admits
    again instead, and every protected snapshot must be exactly its admitted rows (evidence.check). Without it,
    no row of `verified_member`, `verified_round` or `verified_round_member` was admitted.
    """
    findings = []
    if bundle is not None or check_metadata is not None:  # either alone is refused: nothing to compare
        findings += metadata.check(bundle, check_metadata)
    if bundle is not None:
        try:
            check_personal_slots(rules, bundle)
            if calc_ir is not None:
                check_calc_personal_slots(calc_ir, bundle)
        except RefusalError as err:
            findings.append({"reason": err.refusal.code, **err.refusal.arguments})
    snapshots, _ = _load(manifest, read_bytes, None, findings)
    witnesses = _well_formed(witnesses if isinstance(witnesses, list) else [witnesses], findings)
    proof = {"manifest_id": manifest["id"], "root": None, "witnesses": witnesses}
    if snapshots is None:
        return _report(proof, None, set(), findings)
    findings.extend(check_state_projections(manifest, read_bytes, snapshots, full=full))
    if full is None:  # admission is on the complete side; a role's proof only shows what it may read
        if evidence is None:
            findings += completeness.check(manifest, read_bytes, completeness_authority,
                                           snapshots.get(completeness.RELATION))
            findings += admission.check(None, snapshots, admission.PROTECTED[1:])
        else:
            findings += admission.check(evidence, snapshots)
    rows, groups = _rows(snapshots, findings), {}
    for s in seals:
        _check_seal(s, rows, findings)
    for i, w in enumerate(witnesses):
        if w is not None:
            _check_witness(i, w, rules, rows, findings, groups)
            if full is not None:
                scoped = [p["row"]["relation"] for p in w.get("premises", []) if p["polarity"] != "positive"]
                if (rule := rules.get(w["rule_id"])) is not None and (
                        func := getattr(rules, "functionals", {}).get(rule.head.relation)) is not None:
                    scoped.append(func.domain)
                    for r_item in rules.values():
                        if r_item.head.relation == func.name:
                            scoped.extend(b.atom.relation for b in r_item.body)
                            scoped.extend(a.atom.relation for a in r_item.aggregates)
                for relation in sorted(set(scoped + [a["relation"] for a in w.get("aggregates", [])]) - set(full)):
                    findings.append({"reason": "outside_full_scope", "witness": i, "relation": relation})
    if full is None:  # a role's snapshots are filtered: the obligations hold for the complete epoch
        _check_obligations(rules, rows, findings, groups)
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
FUNCTIONAL_STATES = ("known", "unknown", "not_applicable", "invalid")
REASON = re.compile(r"[a-z][a-z0-9_]*")  # a reason is a code, never free text


def _functional_value_ok(value: str, value_type: str) -> bool:
    if value_type == "integer":
        return bool(INTEGER.fullmatch(value)) and _fits(value)
    if value_type == "rational":
        return calc_value(value, "rational")
    if value_type == "boolean":
        return value in ("true", "false")
    return isinstance(value, str)


def _functional_state_ok(func, all_vals: set[str], state: str, reason: str, val: str,
                         prop_states: set[str] | frozenset[str] = frozenset()) -> bool:
    if state not in FUNCTIONAL_STATES:
        return False
    if "invalid" in prop_states or len(all_vals) > 1:
        return state == "invalid" and val == "" and bool(REASON.fullmatch(reason))
    if "unknown" in prop_states:
        return state == "unknown" and val == "" and bool(REASON.fullmatch(reason))
    if "not_applicable" in prop_states:
        return state == "not_applicable" and val == "" and bool(REASON.fullmatch(reason))
    if len(all_vals) == 1:
        return state == "known" and reason == "" and val in all_vals and _functional_value_ok(val, func.value_type)
    return (state == func.empty_state and val == "" and bool(REASON.fullmatch(reason))
            and (func.empty_reason is None or reason == func.empty_reason))


def _functional_candidates(rules, func, rows, witness=None, groups=None):
    """Evaluate all rules of a functional relation against the snapshots.

    Returns (values_by_key, states_by_key, rule_instances, state_instances), cached in `groups` when provided:
    - values_by_key: {domain_key_tuple: set[str]} of all distinct known candidate values across all rules of `func`.
    - states_by_key: {domain_key_tuple: set[str]} of propagated non-known aggregate states per domain key.
    - rule_instances: {rule_id: {domain_key_tuple: list[dict[str, str]]}} of known firing variable substitutions.
    - state_instances: {rule_id: {domain_key_tuple: list[tuple[dict[str, str], str]]}} of non-known firing substitutions.
    """
    cache_key = ("__functional__", func.name)
    if groups is not None and cache_key in groups:
        return groups[cache_key]
    ordered = {}

    def table(relation):
        if relation not in ordered:
            ordered[relation] = sorted(rows(relation, witness).values(), key=itemgetter(0))
        return ordered[relation]

    values_by_key: dict[tuple, set[str]] = {}
    states_by_key: dict[tuple, set[str]] = {}
    rule_instances: dict[str, dict[tuple, list[dict[str, str]]]] = {}
    state_instances: dict[str, dict[tuple, list[tuple[dict[str, str], str]]]] = {}
    n = func.key_arity
    for r in sorted(rules.values(), key=lambda x: x.id):
        if r.head.relation != func.name:
            continue
        by_key: dict[tuple, list[dict[str, str]]] = {}
        by_key_state: dict[tuple, list[tuple[dict[str, str], str]]] = {}
        variables, found = closure.functional_instances(r, table)
        for row, row_state in found:
            theta = {v: x for v, x in zip(variables, row) if x is not None}
            key_terms = r.head.terms[:n]
            if any(t.startswith("?") and t not in theta for t in key_terms):
                continue
            dom_key = tuple(theta[t] if t.startswith("?") else t for t in key_terms)
            if row_state == "known":
                val_term = r.head.terms[n]
                cand_val = theta[val_term] if val_term.startswith("?") else val_term
                values_by_key.setdefault(dom_key, set()).add(cand_val)
                by_key.setdefault(dom_key, []).append(theta)
            else:
                states_by_key.setdefault(dom_key, set()).add(row_state)
                by_key_state.setdefault(dom_key, []).append((theta, row_state))
        rule_instances[r.id] = by_key
        state_instances[r.id] = by_key_state
    result = (values_by_key, states_by_key, rule_instances, state_instances)
    if groups is not None:
        groups[cache_key] = result
    return result


def _check_functional_relation(relation, func, rules, rows, findings, groups=None) -> None:
    """Verify totality, uniqueness, state/value accuracy, and conflict_policy for one functional relation."""
    n = func.key_arity
    domain_keys = {parts for parts, _ in rows(func.domain, None).values() if len(parts) == n}
    values_by_key, states_by_key, _, _ = _functional_candidates(rules, func, rows, None, groups)
    given = {}
    for key, (parts, _) in sorted(rows(relation, None).items()):
        if len(parts) != n + 3:  # key..., state, reason, value; checked before any part is read
            findings.append({"reason": "outcome_state", "relation": relation, "key": key})
        else:
            dom_key = parts[:n]
            if dom_key in domain_keys:
                given.setdefault(dom_key, []).append(parts)
            else:
                findings.append({"reason": "outcome_total", "relation": relation, "key": key})
    for dom_key in sorted(domain_keys - set(given)):
        findings.append({"reason": "outcome_total", "relation": relation, "key": encode_key(dom_key)})
    for dom_key, row_list in sorted(given.items()):
        if len(row_list) != 1:
            findings.append({"reason": "outcome_state", "relation": relation, "key": encode_key(dom_key)})
            continue
        (parts,) = row_list
        state, reason, val = parts[n:]
        if not _functional_state_ok(func, values_by_key.get(dom_key, set()), state, reason, val,
                                    states_by_key.get(dom_key, frozenset())):
            findings.append({"reason": "outcome_state", "relation": relation, "key": encode_key(dom_key)})
        elif state == "invalid" and func.conflict_policy == "block":
            findings.append({"reason": "functional_invalid", "relation": relation,
                             "key": encode_key(parts), "detail": reason})


def _check_obligations(rules, rows, findings, groups=None) -> None:
    """The obligations of the rule IR, held against the complete snapshots: an invariant relation is empty
    (`invariant_violated`, one per row), an outcome gives every element of its kind a row and no row to
    anything else (`outcome_total`), with one state (`outcome_state`), and a rezono.rules/2 functional
    relation gives every key of its closed domain exactly one row whose state matches the candidate set,
    rejecting `invalid` rows under conflict_policy=block (`functional_invalid`)."""
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
    for relation, func in sorted(getattr(rules, "functionals", {}).items()):
        _check_functional_relation(relation, func, rules, rows, findings, groups)


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


def _check_functional_witness(i, w, rule, func, rules, rows, findings, groups=None):
    """Verify one witness of a rezono.rules/2 functional derivation against the snapshots."""
    def find(reason, **kw):
        findings.append({"reason": reason, "witness": i, **kw})

    n = func.key_arity
    c = w["conclusion"]
    try:
        c_parts = strict_json_loads(c["key"])
    except ValueError:
        c_parts = None
    if (c["relation"] != rule.head.relation or not isinstance(c_parts, list)
            or len(c_parts) != n + 3 or not all(isinstance(p, str) for p in c_parts)):
        return find("head_mismatch", relation=c["relation"], key=c["key"])
    if c["key"] not in rows(c["relation"], i):
        find("conclusion_missing", relation=c["relation"], key=c["key"])

    key_parts = tuple(c_parts[:n])
    state, reason, val = c_parts[n:]

    theta = {}
    for b in w.get("bindings", []):
        if b["variable"] not in rule.variables:
            find("unknown_variable", detail=b["variable"])
        elif b["variable"] in theta:
            find("duplicate_binding", detail=b["variable"])
        else:
            theta[b["variable"]] = b["value"]

    key_terms = rule.head.terms[:n]
    key_vars = {t for t in key_terms if t.startswith("?")}
    for v in sorted(key_vars - set(theta)):
        find("unbound_variable", detail=v)
    val_term = rule.head.terms[n]
    if tuple(theta.get(t, t) if t.startswith("?") else t for t in key_terms) != key_parts:
        find("head_mismatch", relation=c["relation"], key=c["key"])
    if state == "known":
        if val_term.startswith("?"):
            if val_term in theta and theta[val_term] != val:
                find("head_mismatch", relation=c["relation"], key=c["key"])
        elif val_term != val:
            find("head_mismatch", relation=c["relation"], key=c["key"])

    dom_key_enc = encode_key(key_parts)
    if dom_key_enc not in rows(func.domain, i):
        find("premise_missing", relation=func.domain, key=dom_key_enc)

    values_by_key, states_by_key, rule_instances, state_instances = _functional_candidates(rules, func, rows, i, groups)
    all_vals = values_by_key.get(key_parts, set())
    prop_states = states_by_key.get(key_parts, frozenset())
    insts = rule_instances.get(rule.id, {}).get(key_parts, [])
    prop_insts = state_instances.get(rule.id, {}).get(key_parts, [])
    matching_insts = [
        inst_theta for inst_theta in insts
        if (inst_theta[val_term] if val_term.startswith("?") else val_term) == val
    ]

    if not _functional_state_ok(func, all_vals, state, reason, val, prop_states):
        find("outcome_state", relation=c["relation"], key=dom_key_enc)
    elif state == "invalid" and func.conflict_policy == "block":
        find("functional_invalid", relation=c["relation"], key=c["key"], detail=reason)
    if state == "known" and not matching_insts:
        find("premise_mismatch", relation=c["relation"], key=c["key"])

    expected_premises = set()
    for b in rule.body:
        if b.polarity == "positive" and b.atom.relation == func.domain:
            b_vars = {t for t in b.atom.terms if t.startswith("?")}
            if b_vars <= set(theta):
                dom_terms = tuple(theta[t] if t.startswith("?") else t for t in b.atom.terms)
                if dom_terms == key_parts:
                    expected_premises.add((b.atom.relation, dom_key_enc, b.polarity, b.stratum))
    if state == "invalid":
        premise_rules = [
            (r, [
                *rule_instances.get(r.id, {}).get(key_parts, []),
                *(t for t, st in state_instances.get(r.id, {}).get(key_parts, []) if st == "invalid"),
            ])
            for r in sorted(rules.values(), key=lambda x: x.id) if r.head.relation == func.name
        ]
        active_insts = [*insts, *(t for t, st in prop_insts if st == "invalid")]
    elif state == "known":
        premise_rules = [(rule, matching_insts)]
        active_insts = matching_insts
    elif state in prop_states:
        state_matching = [t for t, st in prop_insts if st == state]
        if not state_matching:
            find("premise_mismatch", relation=c["relation"], key=c["key"])
        premise_rules = [(rule, state_matching)]
        active_insts = state_matching
    else:
        premise_rules = [(rule, [])]
        active_insts = []
    for r_item, r_insts in premise_rules:
        for inst_theta in r_insts:
            for b in r_item.body:
                b_vars = {t for t in b.atom.terms if t.startswith("?")}
                if b_vars <= set(inst_theta):
                    row_key = encode_key(tuple(inst_theta[t] if t.startswith("?") else t for t in b.atom.terms))
                    expected_premises.add((b.atom.relation, row_key, b.polarity, b.stratum))

    matched_envs = [inst for inst in active_insts if all(inst.get(k) == v for k, v in theta.items())]
    if active_insts:
        if not matched_envs:
            find("premise_mismatch", relation=c["relation"], key=c["key"])
    elif set(theta) - key_vars:
        find("premise_mismatch", relation=c["relation"], key=c["key"])

    expected = sorted(expected_premises)
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

    given_aggs = w.get("aggregates", [])
    if rule.aggregates:
        positioned = {a["position"]: a for a in given_aggs if "position" in a}
        keyed = {(a["relation"], a["group_key"]): a for a in given_aggs if "position" not in a}
        if (active_insts or given_aggs) and (
                len(positioned) + len(keyed) != len(given_aggs) or len(given_aggs) != len(rule.aggregates)
                or not set(positioned) <= set(range(len(rule.aggregates)))):
            find("aggregate_mismatch", detail=f"{len(given_aggs)} given, {len(rule.aggregates)} expected")
        for index, spec in enumerate(rule.aggregates):
            spec_vars = {t for t in spec.atom.terms if t.startswith("?")}
            if matched_envs:
                envs = matched_envs
            elif active_insts:
                envs = active_insts
            elif given_aggs and spec_vars <= set(theta) and set(theta) <= key_vars:
                envs = [theta]
            elif not active_insts and not given_aggs and state != "known":
                continue
            else:
                for v in sorted(spec_vars - set(theta)):
                    find("unbound_variable", detail=v)
                continue
            for env in envs:
                values = tuple(env[t] if t.startswith("?") else t for t in spec.atom.terms)
                fixed = [(pos, v) for pos, (t, v) in enumerate(zip(spec.atom.terms, values)) if t != "_"]
                group = encode_key(v for _, v in fixed)
                a = positioned[index] if index in positioned else keyed.get((spec.atom.relation, group))
                if a is None or (a["relation"], a["group_key"]) != (spec.atom.relation, group):
                    find("aggregate_mismatch", relation=spec.atom.relation, key=group)
                    continue
                count, contributors, result, invalid = recompute(spec, fixed, rows(spec.atom.relation, i), groups)
                if invalid and state != "invalid":
                    find("invalid_value", relation=spec.atom.relation, key=group)
                for field, value in (("count", count), ("contributors_sha256", contributors), ("result", result)):
                    if a[field] != value:
                        find(f"aggregate_{field.removesuffix('_sha256')}", relation=a["relation"], key=group,
                             detail=f"{a[field]} != {value}")
                if rule.bare_values and result.startswith("known:") and not _fits(result.removeprefix("known:")):
                    find("arithmetic_overflow", relation=spec.atom.relation, detail=spec.var)
                bound = env.get(spec.var) if spec.var else None
                if bound is None and state == "known" and spec.var and spec.var == val_term:
                    bound = val
                if spec.var and bound is not None and (f"known:{bound}" if rule.bare_values else bound) != result:
                    find("aggregate_binding", detail=spec.var)
    else:
        for a in given_aggs:
            rel = a["relation"]
            if a["group_key"] != dom_key_enc:
                find("aggregate_mismatch", relation=rel, key=a["group_key"])
                continue
            cand_rows_set = set()
            matched_any = False
            for r_item, r_insts in premise_rules:
                body_matches = [b for b in r_item.body if b.polarity == "positive" and b.atom.relation == rel]
                if body_matches:
                    matched_any = True
                    for inst_theta in r_insts:
                        for b in body_matches:
                            cand_rows_set.add(tuple(inst_theta[t] if t.startswith("?") else t for t in b.atom.terms))
            if not matched_any:
                find("aggregate_mismatch", relation=rel, key=dom_key_enc)
                continue
            cand_rows = sorted(cand_rows_set)
            expected_count = len(cand_rows)
            expected_digest = sha256_hex(canonical_bytes([{"key": list(r)} for r in cand_rows]))
            expected_result = f"known:{val}" if state == "known" else f"{state}:{reason}"
            for field, value in (("count", expected_count), ("contributors_sha256", expected_digest),
                                 ("result", expected_result)):
                if a[field] != value:
                    find(f"aggregate_{field.removesuffix('_sha256')}", relation=rel, key=dom_key_enc,
                         detail=f"{a[field]} != {value}")


def _check_witness(i, w, rules, rows, findings, groups=None):
    def find(reason, **kw):
        findings.append({"reason": reason, "witness": i, **kw})

    rule = rules.get(w["rule_id"])
    if rule is None:
        return find("unknown_rule", detail=w["rule_id"])
    if (func := getattr(rules, "functionals", {}).get(rule.head.relation)) is not None:
        return _check_functional_witness(i, w, rule, func, rules, rows, findings, groups)
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
        if not _holds(c.op, _value(c.left, theta), _value(c.right, theta), c.compare_as):
            find("condition_false", detail=f"{c.left} {c.op} {c.right}")


def recompute(spec, fixed, relation_rows, groups=None, fmt=None):
    """Count, contributors hash, result and 'reads invalid input' for one aggregate.

    The group is every row of the right arity that matches the fixed (non-'_') positions of the rule.
    `groups` caches an index per (relation, arity, fixed positions), so each relation is scanned once.
    """
    members = aggregate_members(spec, fixed, relation_rows, groups)
    effective_fmt = spec.format if fmt is None else fmt
    if spec.function == "count" and (effective_fmt == "rezono.rules/1"
                                     or (spec.over is None and getattr(spec, "state_key", None) is None)):
        return len(members), sha256_json([[k] for k, _ in members]), f"known:{len(members)}", False
    read = cells(spec, [(strict_json_loads(k), values) for k, values in members])
    contributors = sha256_json([[k, value_text(v)] for (k, _), v in zip(members, read)])
    result = _fold(spec.function, read, effective_fmt)
    return len(members), contributors, result, result == "invalid"


def aggregate_members(spec, fixed, relation_rows, groups=None):
    """The exact group whose members the checker uses to verify an aggregate."""
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
    return groups[index_key].get(tuple(v for _, v in fixed), [])


def _calc_premise_problem(row, rule, calculated, calc_views):
    if row in calculated:
        witness = calculated[row]
        column_type = (rule.calc_input_type(row[0]) if rule else None) or "integer"
        if (witness["state"] != "known" or witness.get("reason", "")
                or not calc_value(witness.get("value", ""), column_type)):
            return "bad_calc_premise"
    elif row[0] in calc_views:
        return "unproven_premise"
    return None


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
        rule = rules.get(w["rule_id"])
        graph.setdefault(ref, set())
        for p in w.get("premises", []):
            row = (p["row"]["relation"], p["row"]["key"])
            if p["polarity"] != "positive":
                continue
            problem = _calc_premise_problem(row, rule, calculated, calc_views)
            if problem:
                findings.append({"reason": problem, "witness": i, "relation": row[0], "key": row[1]})
            if problem == "unproven_premise":
                continue
            if row in proved:
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
