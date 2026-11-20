"""Independent checker decision on whether a delta may change read access.

A proposal, local supposition or sweep variant delta may change what a filtered
role reads if any modified kind, ancestor kind, slot table or seal input lies in
the dependency closure of `may_read` or `may_read_full` (decisions/central-read-access.md,
section 3). Decided solely from the rule IR, schema bundle and delta, never from
data (avoiding existence leaks), and sharing no code with `rezono_publisher.difference`.
"""

from __future__ import annotations

from collections import defaultdict

from .rules import load_seals

ACCESS = "may_read"
READ_FULL = "may_read_full"
ACCESS_ROOTS = (ACCESS, READ_FULL)
DELTA_OPS = frozenset({"insert", "delete", "set", "unset"})
MEMBERSHIP_OPS = frozenset({"insert", "delete"})


def _parse_bundle_parents(bundle: object) -> dict[str, str | None] | None:
    """Return {kind_id: parent_id | None} from a schema bundle, or None if malformed."""
    if not isinstance(bundle, dict):
        return None
    raw_kinds = bundle.get("kinds")
    if not isinstance(raw_kinds, list):
        return None
    parents: dict[str, str | None] = {}
    for entry in raw_kinds:
        if not isinstance(entry, dict):
            return None
        kid = entry.get("id")
        if not isinstance(kid, str) or not kid or kid in parents:
            return None
        parent = entry.get("parent")
        if parent is not None and (not isinstance(parent, str) or not parent):
            return None
        parents[kid] = parent
    return parents


def _parse_delta_changes(delta: object) -> list[tuple[str, str]] | None:
    """Return [(op, kind), ...] from a delta, or None if malformed."""
    if not isinstance(delta, dict):
        return None
    raw_changes = delta.get("changes")
    if not isinstance(raw_changes, list):
        return None
    parsed: list[tuple[str, str]] = []
    for change in raw_changes:
        if not isinstance(change, dict):
            return None
        op = change.get("op")
        kind = change.get("kind")
        if not isinstance(op, str) or op not in DELTA_OPS:
            return None
        if not isinstance(kind, str) or not kind:
            return None
        parsed.append((op, kind))
    return parsed


def _parse_rules(rules_doc: object) -> tuple[dict[str, list[dict]], set[str], list[dict]] | None:
    """Validate rules_doc and return (rules_by_head, calc_relations, seals), or None if malformed."""
    if rules_doc is None:
        return {}, set(), []
    if not isinstance(rules_doc, dict):
        return None
    if "seals" in rules_doc and not isinstance(rules_doc["seals"], list):
        return None
    try:
        seals = load_seals(rules_doc)
    except (ValueError, TypeError, AttributeError, KeyError):
        return None

    if "relations" in rules_doc and not isinstance(rules_doc["relations"], list):
        return None
    calc_relations: set[str] = set()
    for rel_decl in rules_doc.get("relations", ()):
        if not isinstance(rel_decl, dict):
            return None
        if rel_decl.get("role") == "calc":
            name = rel_decl.get("name")
            if not isinstance(name, str) or not name:
                return None
            calc_relations.add(name)

    if "rules" in rules_doc and not isinstance(rules_doc["rules"], list):
        return None
    rules_by_head: dict[str, list[dict]] = defaultdict(list)
    for rule in rules_doc.get("rules", ()):
        if not isinstance(rule, dict):
            return None
        head = rule.get("head")
        if not isinstance(head, dict):
            return None
        head_rel = head.get("relation")
        head_terms = head.get("terms")
        if (not isinstance(head_rel, str) or not head_rel
                or not isinstance(head_terms, list) or not all(isinstance(t, str) for t in head_terms)):
            return None
        if "body" in rule and not isinstance(rule["body"], list):
            return None
        if "aggregates" in rule and not isinstance(rule["aggregates"], list):
            return None
        for atom in rule.get("body", ()):
            if not isinstance(atom, dict):
                return None
            rel = atom.get("relation")
            terms = atom.get("terms")
            polarity = atom.get("polarity")
            if (not isinstance(rel, str) or not rel
                    or not isinstance(terms, list) or not all(isinstance(t, str) for t in terms)
                    or (polarity is not None and not isinstance(polarity, str))):
                return None
        for agg in rule.get("aggregates", ()):
            if not isinstance(agg, dict):
                return None
            rel = agg.get("relation")
            if not isinstance(rel, str) or not rel:
                return None
        rules_by_head[head_rel].append(rule)

    return rules_by_head, calc_relations, seals


def _access_closure(rules_by_head: dict[str, list[dict]]) -> tuple[set[str], list[dict]]:
    """Compute all relations depended on by `may_read` or `may_read_full` and the rules in that closure."""
    closure: set[str] = set()
    visited_heads: set[str] = set(ACCESS_ROOTS)
    pending: list[str] = list(ACCESS_ROOTS)
    active_rules: list[dict] = []
    while pending:
        head_rel = pending.pop()
        for rule in rules_by_head.get(head_rel, ()):
            active_rules.append(rule)
            for atom in (*rule.get("body", ()), *rule.get("aggregates", ())):
                dep = atom["relation"]
                closure.add(dep)
                if dep not in visited_heads:
                    visited_heads.add(dep)
                    pending.append(dep)
    return closure, active_rules


def _seal_inputs_for_closure(seals: list[dict], closure: set[str]) -> set[str]:
    """Every base table feeding a seal whose output relations intersect `closure`."""
    tables: set[str] = set()
    for seal in seals:
        parts = seal.get("parts", ())
        outputs = {seal["refused"], seal["accepted"], seal["row_sha256"], *(p["accepted"] for p in parts)}
        if closure & outputs:
            tables |= {
                seal["kind"], seal["period"], *seal["tables"],
                seal["closed_until"], seal["covers"], seal["element"], seal["sha256"],
            }
            for part in parts:
                tables |= {part["kind"], part["arrow"], *part["tables"]}
    return tables


def _only_grants_inserted_element(kind: str, active_rules: list[dict], closure: set[str]) -> bool:
    """True iff every use of `kind` in the access closure is a positive `K(?x)` premise of
    `may_read(?r, "K", ?x)` and `may_read` itself does not feed further access rules."""
    if ACCESS in closure:
        return False
    found_use = False
    for rule in active_rules:
        if any(agg["relation"] == kind for agg in rule.get("aggregates", ())):
            return False
        head_rel = rule["head"]["relation"]
        head_terms = rule["head"]["terms"]
        for atom in rule.get("body", ()):
            if atom["relation"] != kind:
                continue
            found_use = True
            if (head_rel != ACCESS or atom.get("polarity") != "positive"
                    or len(atom["terms"]) != 1 or not atom["terms"][0].startswith("?")
                    or len(head_terms) != 3 or head_terms[1] != kind or head_terms[2] != atom["terms"][0]):
                return False
    return found_use


def _ancestor_chain(kind: str, parents: dict[str, str | None]) -> list[str] | None:
    """Return [kind, parent, ...] up the bundle inheritance chain, or None on a cycle."""
    chain: list[str] = []
    seen: set[str] = set()
    current: str | None = kind
    while current is not None:
        if current in seen:
            return None
        seen.add(current)
        chain.append(current)
        current = parents.get(current)
    return chain


def may_change_access(rules_doc: dict | None, bundle: dict | None, delta: dict | None) -> bool:
    """Return True if `delta` may change `may_read` or `may_read_full` for any role (fail closed)."""
    parents = _parse_bundle_parents(bundle)
    changes = _parse_delta_changes(delta)
    parsed_rules = _parse_rules(rules_doc)
    if parents is None or changes is None or parsed_rules is None:
        return True

    rules_by_head, calc_relations, seals = parsed_rules
    closure, active_rules = _access_closure(rules_by_head)
    if calc_relations & closure:
        return True

    seal_inputs = _seal_inputs_for_closure(seals, closure)
    for op, kind in changes:
        chain = _ancestor_chain(kind, parents)
        if chain is None:
            return True
        prefixes = tuple(f"{ancestor}__" for ancestor in chain)
        chain_set = set(chain)
        if any(table in chain_set or table.startswith(prefixes) for table in seal_inputs):
            return True
        for rel in closure:
            if rel.startswith(prefixes):
                return True
            if rel in chain_set and op in MEMBERSHIP_OPS:
                if not (op == "insert" and _only_grants_inserted_element(rel, active_rules, closure)):
                    return True
    return False
