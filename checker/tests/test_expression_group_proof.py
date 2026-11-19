"""expression-group-proof: the checker verifies a filtered count group over the rule IR.

decisions/language-expression-semantics.md, sections 1 and 6. The rule counts the `precedes`
edges of each stage, so the fixed `kind` term is part of the group. The expected counts are
worked out by hand from three edges: a has two, b and c have none (b's only edge is a
`blocks` edge). Hand-written, so it does not depend on the compiler.
"""

import copy
import hashlib
import json

from rezono_checker.canon import encode_key, sha256_json
from rezono_checker.check import check_epoch
from rezono_checker.rules import derived_relations, load_rules

IR = {
    "format": "rezono.rules/1", "pack": "example",
    "relations": [
        {"name": "stage", "role": "base", "key": [{"name": "id", "type": "string"}]},
        {"name": "edge", "role": "base", "key": [{"name": "pred", "type": "string"}, {"name": "succ", "type": "string"},
                                                  {"name": "kind", "type": "string"}]},
        {"name": "successors", "role": "derived", "module": "m", "explain": "materialize",
         "key": [{"name": "x", "type": "string"}, {"name": "n", "type": "integer"}]},
    ],
    "rules": [
        {"id": "successors", "module": "m", "stratum": "1", "head": {"relation": "successors", "terms": ["?x", "?n"]},
         "body": [{"relation": "stage", "terms": ["?x"], "polarity": "positive", "stratum": "0"}],
         "aggregates": [{"relation": "edge", "terms": ["?x", "_", "precedes"], "function": "count", "as": "?n",
                         "stratum": "0"}],
         "witness": {"relation": "successors__witness", "variables": ["?x", "?n"]},
         "origin": {"file": "r.dl", "line": "1"}},
    ],
}
EDGES = [["a", "b", "precedes"], ["a", "c", "precedes"], ["b", "c", "blocks"]]
COUNTS = [["a", "2"], ["b", "0"], ["c", "0"]]


def world(counts=COUNTS, *, edges_complete=True):
    rows = {"stage": [["a"], ["b"], ["c"]], "edge": EDGES, "successors": counts}
    snaps = {name: json.dumps([{"key": key} for key in keys]).encode() for name, keys in rows.items()}
    manifest = {"id": "m-1", "snapshots": [
        {"relation": name, "role": "all", "complete": edges_complete or name != "edge", "uri": name, "format": "json",
         "sha256": hashlib.sha256(data).hexdigest()} for name, data in snaps.items()]}
    return manifest, snaps.__getitem__


def witness(stage, members, *, kind="precedes"):
    count = str(len(members))
    keys = sorted(encode_key(edge) for edge in members)
    return {"conclusion": {"relation": "successors", "key": encode_key([stage, count])}, "rule_id": "successors",
            "bindings": [{"variable": "?x", "value": stage}, {"variable": "?n", "value": count}],
            "premises": [{"row": {"relation": "stage", "key": encode_key([stage])}, "polarity": "positive",
                          "stratum": 0}],
            "aggregates": [{"relation": "edge", "group_key": encode_key([stage, kind]), "count": len(members),
                            "contributors_sha256": sha256_json([[key] for key in keys]),
                            "result": f"known:{count}"}]}


VALID = [witness("a", EDGES[:2]), witness("b", []), witness("c", [])]


def errors(witnesses, counts=COUNTS, **options):
    manifest, read = world(counts, edges_complete=options.pop("edges_complete", True))
    rules = load_rules(IR)
    report = check_epoch(witnesses, manifest, rules, read, derived=derived_relations(IR, rules), **options)
    return report["valid"], {f["reason"] for f in report["findings"] if f["severity"] == "error"}


def test_expression_group_proof():
    assert errors(VALID) == (True, set())

    # Counting b's blocks edge ignores the fixed filter term of the group.
    unfiltered = [VALID[0], witness("b", [EDGES[2]]), VALID[2]]
    valid, reasons = errors(unfiltered, [["a", "2"], ["b", "1"], ["c", "0"]])
    assert not valid and {"aggregate_count", "aggregate_contributors"} <= reasons

    # The same count under a group key whose filter differs from the rule's.
    rekeyed = [VALID[0], witness("b", [EDGES[2]], kind="blocks"), VALID[2]]
    valid, reasons = errors(rekeyed, [["a", "2"], ["b", "1"], ["c", "0"]])
    assert not valid and "aggregate_mismatch" in reasons

    # Omitting the a -> c contributor.
    omitted = [witness("a", EDGES[:1]), *VALID[1:]]
    valid, reasons = errors(omitted, [["a", "1"], ["b", "0"], ["c", "0"]])
    assert not valid and {"aggregate_count", "aggregate_contributors"} <= reasons

    # A forged empty group for a, which has two contributors.
    forged = [witness("a", []), *VALID[1:]]
    valid, reasons = errors(forged, [["a", "0"], ["b", "0"], ["c", "0"]])
    assert not valid and {"aggregate_count", "aggregate_contributors"} <= reasons

    # An empty group needs full scope evidence: an incomplete edge snapshot or a role
    # without the full edge relation proves no zero.
    assert not errors(VALID, edges_complete=False)[0]
    valid, reasons = errors(VALID, full={"stage", "successors"})
    assert not valid and reasons == {"outside_full_scope"}
    assert errors(copy.deepcopy(VALID), full={"stage", "edge", "successors"}) == (True, set())
