"""Independently check a signed row transition over two complete, witnessed snapshots."""

import json
from dataclasses import dataclass

from rezono_canon import canonical_bytes, canonical_sha256, sha256_hex

from . import closure
from .canon import INTEGER, calc_value, encode_key
from .check import check_epoch
from .evaluate import BIGINT
from .rules import check_worlds, derived_relations, load_rules

Key = tuple[str, ...]
Snapshot = dict[str, set[Key]]


class Refused(ValueError):
    """An invalid certificate or evidence this checker cannot establish."""


@dataclass(frozen=True)
class Relation:
    role: str
    columns: tuple[str, ...]
    head_columns: tuple[str, ...] = ()
    domain: str | None = None


def _text(value) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _unique_object(pairs):
    obj = dict(pairs)
    if len(obj) != len(pairs):
        raise Refused("ambiguous_observation")
    return obj


def _not_json(_):
    raise Refused("malformed_observation")


def _pin_observation(certificate, context) -> None:
    cut = context["cut"]
    if not all(_text(cut[field]) for field in ("id", "run", "scope")):
        raise Refused("malformed_cut")
    if certificate["cut"] != cut["id"] or certificate["run"] != cut["run"]:
        raise Refused("cut_mismatch")
    observations = context["observations"]
    # This cut carries one file digest. Additional inputs would have no authenticated identity.
    if not isinstance(observations, dict) or len(observations) != 1:
        raise Refused("observation_inventory_mismatch")
    (observation_id, body), = observations.items()
    if not _text(observation_id) or not isinstance(body, bytes):
        raise Refused("malformed_observation")
    if sha256_hex(body) != cut["observation_sha256"]:
        raise Refused("observation_hash_mismatch")
    observation = json.loads(body.decode("utf-8"), object_pairs_hook=_unique_object, parse_constant=_not_json)
    if not isinstance(observation, dict) or any(
        observation.get(name) != expected
        for name, expected in (("id", observation_id), ("run", cut["run"]), ("scope", cut["scope"]))
    ):
        raise Refused("observation_scope_mismatch")


def _catalogue(program) -> dict[str, Relation]:
    fmt = program["format"]
    if fmt not in ("rezono.rules/1", "rezono.rules/2") or not isinstance(program["relations"], list):
        raise Refused("malformed_definition")
    allowed_roles = ("base", "derived", "functional") if fmt == "rezono.rules/2" else ("base", "derived")
    catalogue = {}
    for entry in program["relations"]:
        name, role, key = entry["name"], entry["role"], entry["key"]
        if not _text(name) or name in catalogue:
            raise Refused("malformed_definition")
        if role not in allowed_roles or entry.get("values"):
            # The certificate provides keyed rows and ordinary witnesses, not calculation or value evidence.
            raise Refused("unsupported_snapshot_relation")
        if not isinstance(key, list) or not key:
            raise Refused("malformed_definition")
        names = [column["name"] for column in key]
        types = tuple(column["type"] for column in key)
        if not all(_text(name) for name in names) or len(set(names)) != len(names):
            raise Refused("malformed_definition")
        # decisions/boolean-rule-inputs.md: a boolean rule column holds the canonical text true or false.
        if any(column not in ("string", "integer", "rational", "boolean") for column in types):
            raise Refused("malformed_definition")
        if role == "functional":
            domain = entry.get("domain")
            val = entry.get("value")
            if (not _text(domain) or not isinstance(val, dict) or not _text(val.get("name"))
                    or val.get("type") not in ("string", "integer", "rational", "boolean")):
                raise Refused("malformed_definition")
            catalogue[name] = Relation(role, types + ("string", "string", val["type"]),
                                       types + (val["type"],), domain)
        else:
            catalogue[name] = Relation(role, types, types)
    return catalogue


def _rule_scope(rules, catalogue, invariants, worlds) -> None:
    safety = closure.dependencies(rules, invariants)
    required = set(invariants)
    for rule in rules.values():
        head_rel = catalogue.get(rule.head.relation)
        if head_rel is None or len(head_rel.head_columns) != len(rule.head.terms):
            raise Refused("malformed_definition")
        for item in (*rule.body, *rule.aggregates):
            relation = catalogue.get(item.atom.relation)
            if relation is None or len(relation.columns) != len(item.atom.terms):
                raise Refused("malformed_definition")
        required.update(item.atom.relation for item in rule.body if item.polarity == "negative")
        required.update(item.atom.relation for item in rule.aggregates)
        if head_rel.role == "functional":
            if head_rel.domain is not None:
                required.add(head_rel.domain)
            required.update(item.atom.relation for item in (*rule.body, *rule.aggregates))
        if rule.head.relation in safety:
            required.add(rule.head.relation)
            required.update(item.atom.relation for item in (*rule.body, *rule.aggregates))
    # A closed modeled table is sufficient here. This cut carries no coverage receipt for open reads.
    if any(worlds[name] == "open" for name in required):
        raise Refused("missing_scope_coverage")


def _typed_part(part, column: str) -> None:
    if not isinstance(part, str):
        raise Refused("malformed_row_key")
    if column == "integer" and (not INTEGER.fullmatch(part) or not BIGINT[0] <= int(part) <= BIGINT[1]):
        raise Refused("malformed_row_key")
    if column == "rational" and not calc_value(part, "rational"):
        raise Refused("malformed_row_key")
    if column == "boolean" and part not in ("true", "false"):
        raise Refused("malformed_row_key")


def _key(value, relation: Relation) -> Key:
    if not isinstance(value, (list, tuple)) or len(value) != len(relation.columns):
        raise Refused("malformed_row_key")
    if relation.role == "functional":
        n = len(relation.columns) - 3
        for part, column in zip(value[:n], relation.columns[:n], strict=True):
            _typed_part(part, column)
        state, reason, val = value[n:]
        if state not in ("known", "unknown", "not_applicable", "invalid") or not isinstance(reason, str):
            raise Refused("malformed_row_key")
        if state == "known":
            _typed_part(val, relation.columns[-1])
        elif val != "":
            raise Refused("malformed_row_key")
        return tuple(value)
    for part, column in zip(value, relation.columns, strict=True):
        _typed_part(part, column)
    return tuple(value)


def _snapshot(state, catalogue: dict[str, Relation]) -> Snapshot:
    if set(state) != {"id", "rows", "witnesses"} or not _text(state["id"]) or not isinstance(state["witnesses"], list):
        raise Refused("malformed_snapshot")
    if not isinstance(state["rows"], dict) or state["rows"].keys() != catalogue.keys():
        raise Refused("snapshot_inventory_mismatch")
    tables = {}
    for name, rows in state["rows"].items():
        if not isinstance(rows, (list, tuple)):
            raise Refused("malformed_snapshot")
        keys = {_key(row, catalogue[name]) for row in rows}
        if len(keys) != len(rows):
            raise Refused("duplicate_snapshot_row")
        tables[name] = keys
    return tables


def _reapply(certificate, base: Snapshot, variant: Snapshot, catalogue: dict[str, Relation]) -> None:
    delta, asserted = certificate["delta"], certificate["expected_old"]
    if not isinstance(delta, (list, tuple)) or not isinstance(asserted, list):
        raise Refused("malformed_delta")
    applied = {name: rows.copy() for name, rows in base.items() if catalogue[name].role == "base"}
    seen: set[tuple[str, Key]] = set()
    removed = set()
    for change in delta:
        if not isinstance(change, (list, tuple)) or len(change) != 3:
            raise Refused("malformed_delta")
        name, parts, weight = change
        if not isinstance(name, str) or name not in applied or type(weight) is not int or weight not in (-1, 1):
            raise Refused("malformed_delta")
        key = _key(parts, catalogue[name])
        if (name, key) in seen:
            raise Refused("conflicting_delta")
        seen.add((name, key))
        rows = applied[name]
        if weight == 1:
            if key in rows:
                raise Refused("delta_row_already_present")
            rows.add(key)
        else:
            if key not in rows:
                raise Refused("delta_old_row_missing")
            rows.remove(key)
            removed.add((name, encode_key(key)))
    expected_old = set()
    for ref in asserted:
        if not isinstance(ref, dict) or set(ref) != {"relation", "key"} or not all(map(_text, ref.values())):
            raise Refused("malformed_expected_old")
        expected_old.add((ref["relation"], ref["key"]))
    if len(expected_old) != len(asserted) or removed != expected_old:
        raise Refused("expected_old_mismatch")
    if any(keys != variant[name] for name, keys in applied.items()):
        raise Refused("delta_variant_mismatch")


def _inventory(certificate, context, declared) -> None:
    named, evidence = context["invariants"], certificate["invariants"]
    if not isinstance(named, (list, tuple)) or not all(map(_text, named)):
        raise Refused("malformed_invariant_inventory")
    if (len(named) != len(declared) or set(named) != declared
            or not isinstance(evidence, dict) or evidence.keys() != declared):
        raise Refused("invariant_inventory_mismatch")
    if any(result != {"rows": [], "count": "0"} for result in evidence.values()):
        raise Refused("nonzero_or_missing_invariant_evidence")


def _proof(state, rows: Snapshot, rules, derived, label: str) -> list[dict]:
    objects = {name: canonical_bytes([{"key": key} for key in sorted(keys)]) for name, keys in sorted(rows.items())}
    manifest = {"id": state["id"], "snapshots": [
        {"relation": name, "role": "all", "format": "json", "uri": name, "complete": True, "sha256": sha256_hex(body)}
        for name, body in objects.items()
    ]}
    report = check_epoch(state["witnesses"], manifest, rules, objects.__getitem__, derived=derived)
    findings = report["findings"]
    if report["valid"]:
        # A transition binds the entire variant, including derived rows with no consumer of absence.
        decoded = {name: {encode_key(key): (key, {}) for key in keys} for name, keys in rows.items()}
        findings += closure.check(rules, decoded.__getitem__, domains=derived - closure.covered(rules))
    return [{"snapshot": label, **finding} for finding in findings]


def check_transition_certificate(certificate: dict, context: dict, base: dict, variant: dict) -> dict:
    """Check the declared row changes, cut, and all obligations independently of the engine."""
    try:
        if not _text(context["manifest"]) or certificate["manifest"] != context["manifest"]:
            raise Refused("manifest_mismatch")
        _pin_observation(certificate, context)
        program = context["program"]
        definition = canonical_sha256(program)
        if definition != context["definition_sha256"] or certificate["definition_sha256"] != definition:
            raise Refused("definition_mismatch")
        if certificate["base"] != canonical_sha256(base) or certificate["variant"] != canonical_sha256(variant):
            raise Refused("snapshot_hash_mismatch")
        bindings = certificate["bindings"]
        if (not _text(certificate["rule"]) or not _text(certificate["effect"]) or not isinstance(bindings, dict)
                or any(not _text(name) or not isinstance(value, str) for name, value in bindings.items())):
            raise Refused("malformed_effect_identity")

        catalogue = _catalogue(program)
        rules = load_rules(program)
        derived = derived_relations(program, rules)
        invariants = getattr(rules, "invariants", frozenset())
        _inventory(certificate, context, invariants)
        _rule_scope(rules, catalogue, invariants, check_worlds(program, rules))
        before, after = _snapshot(base, catalogue), _snapshot(variant, catalogue)
        _reapply(certificate, before, after, catalogue)
        findings = _proof(base, before, rules, derived, "base") + _proof(variant, after, rules, derived, "variant")
    except Refused as error:
        findings = [{"reason": str(error)}]
    except (AttributeError, LookupError, OverflowError, RecursionError, TypeError, ValueError):
        findings = [{"reason": "malformed_transition_evidence"}]
    return {"valid": not findings, "findings": findings}
