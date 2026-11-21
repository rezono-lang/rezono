"""The publisher on a small synthetic epoch: blocking, the manifest last, filtering per role, no leaks."""

import dataclasses
import hashlib
import json
import shutil
from pathlib import Path

import pytest

from rezono_canon import canonical_json, canonical_sha256
from rezono_checker import access as checker_access
from rezono_checker import metadata
from rezono_publisher import access, pointers, publish, retained_calculation, store
from rezono_publisher.publish import Epoch

SECRET = "zz-secret"  # an element the guest may not read; its id must not reach any guest file


def object_bytes(s, role, name, mid="m-1"):
    return s.get(publish.role_objects(s, "toy", mid, role)[name])


def ref(rel, *key):
    return {"relation": rel, "key": canonical_json(list(key))}


def witness(rel, key, rule, bindings, premises=(), negated=(), aggregates=None):
    """One witness instance; a premise is (relation, key) or (relation, key, stratum)."""
    w = {"conclusion": ref(rel, *key), "rule_id": rule,
         "bindings": [{"variable": f"?{v}", "value": x} for v, x in bindings],
         "premises": [{"row": ref(p[0], *p[1]), "polarity": "positive", "stratum": p[2] if len(p) > 2 else 0}
                      for p in premises]
         + [{"row": ref(r, *k), "polarity": "negative", "stratum": 0} for r, k in negated]}
    if aggregates:
        w["aggregates"] = aggregates
    return w


def lit(rel, *terms, polarity="positive", stratum=0):
    return {"relation": rel, "terms": list(terms), "polarity": polarity, "stratum": stratum}


def rule(rid, head, body, stratum=0, **extra):
    return {"id": rid, "stratum": stratum, "head": {"relation": head[0], "terms": list(head[1:])}, "body": body, **extra}


def relation(name, role, arity):
    return {"name": name, "role": role, "key": [{"name": f"c{i}", "type": "string"} for i in range(arity)]}


# The toy's rule IR (contracts/rules.yaml). The guest's rights come from `grant`; with FULL, every role
# reads every node, by the shape of rule a2.
BASE = [("node", 1), ("role", 1), ("edge", 2), ("salary", 2), ("grant", 2)]
DERIVED = [("may_read", 3), ("path", 2), ("reach", 1), ("touched", 1), ("isolated", 1), ("degree", 2), ("hub", 1),
           ("wage", 1), ("total", 1)]
FUNCTION = "count"  # the aggregate of rule r9


def rules(full=False, function=FUNCTION, role_rule=True):
    return {
        "format": "rezono.rules/1",
        "relations": [relation(n, "base", a) for n, a in BASE] + [relation(n, "derived", a) for n, a in DERIVED],
        "rules": [
            rule("a1", ("may_read", "?r", "node", "?x"), [lit("grant", "?x", "?r")]),
            *([rule("a2", ("may_read", "?r", "node", "?x"), [lit("role", "?r"), lit("node", "?x")])] if full else []),
            *([rule("a3", ("may_read", "?r", "role", "?x"), [lit("role", "?r"), lit("role", "?x")])] if full and role_rule else []),
            rule("r1", ("path", "?x", "?y"), [lit("edge", "?x", "?y")]),
            rule("r2", ("path", "?x", "?z"), [lit("path", "?x", "?y"), lit("edge", "?y", "?z")]),
            rule("r3", ("reach", "?x"), [lit("path", "?x", "?y")]),
            rule("r4", ("degree", "?x", "?n"), [lit("node", "?x")], stratum=1,
                 aggregates=[{"relation": "edge", "terms": ["?x", "_"], "function": "count", "as": "?n", "stratum": 0}]),
            rule("r5", ("wage", "?s"), [lit("salary", "?x", "?s")]),
            rule("r6", ("hub", "?x"), [lit("degree", "?x", "?n", stratum=1)], stratum=1,
                 conditions=[{"op": "gt", "left": "?n", "right": "0"}]),
            rule("r7", ("isolated", "?x"), [lit("node", "?x"), lit("touched", "?x", polarity="negative")], stratum=1),
            rule("r8", ("touched", "?x"), [lit("edge", "?x", "?y")]),
            rule("r9", ("total", "?t"), [], stratum=1,
                 aggregates=[{"relation": "salary", "terms": ["_", "_"], "function": function, "as": "?t", "stratum": 0,
                              **({"over": "c1"} if function != "count" else {})}]),
        ],
    }


def group(rows, function):
    """count, contributors hash and result of one aggregate group (formal.md §6), as the explainer gives them."""
    keys = sorted((canonical_json(list(r)), r) for r in rows)
    if function == "count":
        return len(keys), canonical_sha256([[k] for k, _ in keys]), str(len(keys))
    values = [int(r[1]) for _, r in keys]
    return len(keys), canonical_sha256([[k, f"known:{r[1]}"] for k, r in keys]), str({"sum": sum, "min": min, "max": max}[function](values))


def toy(nodes, edges, salaries, grants, roles=("guest",), full=False, function=FUNCTION, role_rule=True):
    """The rows and every witness instance of the toy rules, as the engine would give them."""
    ws = [witness("may_read", [r, "node", x], "a1", [("r", r), ("x", x)], [("grant", [x, r])]) for r, x in grants]
    if full:
        ws += [witness("may_read", [r, "node", x], "a2", [("r", r), ("x", x)], [("role", [r]), ("node", [x])])
               for r in roles for x in nodes]
        if role_rule:
            ws += [witness("may_read", [r, "role", x], "a3", [("r", r), ("x", x)], [("role", [r]), ("role", [x])])
                   for r in roles for x in roles]
    path = set(edges)
    while True:
        more = {(x, z) for x, y in path for y2, z in edges if y == y2} - path
        if not more:
            break
        path |= more
    ws += [witness("path", [x, y], "r1", [("x", x), ("y", y)], [("edge", [x, y])]) for x, y in edges]
    ws += [witness("path", [x, z], "r2", [("x", x), ("y", y), ("z", z)], [("path", [x, y]), ("edge", [y, z])])
           for x, y in sorted(path) for y2, z in edges if y == y2]
    ws += [witness("reach", [x], "r3", [("x", x), ("y", y)], [("path", [x, y])]) for x, y in sorted(path)]
    ws += [witness("touched", [x], "r8", [("x", x), ("y", y)], [("edge", [x, y])]) for x, y in edges]
    touched = {x for x, _ in edges}
    ws += [witness("isolated", [x], "r7", [("x", x)], [("node", [x])], [("touched", [x])]) for x in nodes if x not in touched]
    for x in nodes:
        count, contributors, n = group([e for e in edges if e[0] == x], "count")
        agg = {"relation": "edge", "position": 0, "group_key": canonical_json([x]), "count": count,
               "contributors_sha256": contributors, "result": f"known:{n}"}
        ws.append(witness("degree", [x, n], "r4", [("x", x), ("n", n)], [("node", [x])], aggregates=[agg]))
        if count:
            ws.append(witness("hub", [x], "r6", [("x", x), ("n", n)], [("degree", [x, n], 1)]))
    ws += [witness("wage", [v], "r5", [("x", x), ("s", v)], [("salary", [x, v])]) for x, v in salaries]
    if salaries or function in ("count", "sum"):
        count, contributors, t = group(salaries, function)
        ws.append(witness("total", [t], "r9", [("t", t)], aggregates=[
            {"relation": "salary", "position": 0, "group_key": "[]", "count": count,
             "contributors_sha256": contributors, "result": f"known:{t}"}]))
    rows = {"node": [(n,) for n in nodes], "role": [(r,) for r in roles], "edge": list(edges),
            "salary": list(salaries), "grant": [(x, r) for r, x in grants]}
    for rel, _ in DERIVED:
        rows[rel] = sorted({tuple(json.loads(w["conclusion"]["key"])) for w in ws if w["conclusion"]["relation"] == rel})
    return rows, ws


HIDDEN = "a0-hidden"  # a second hidden element, sorted before every readable one
NODES, EDGES, SALARIES = ["a", "b", "c", SECRET], [("a", "b"), ("b", SECRET)], [(SECRET, "12345")]
GRANTS = [("guest", "a"), ("guest", "b"), ("guest", "c")]
# The same epoch with more hidden rows: a hidden node, two edges to it (one from a readable node that had
# none, so `isolated(c)` would go; one that gives reach(a) an earlier-ranked hidden proof) and a salary.
MORE = {"nodes": NODES + [HIDDEN], "edges": EDGES + [("a", HIDDEN), ("c", HIDDEN)], "salaries": SALARIES + [(HIDDEN, "7")]}
COLUMNS = {"node": ("node",), "role": ("role",), "edge": ("node", "node"), "salary": ("node", None), "grant": ("node", None)}
TOY_ARROWS = [
    {"id": "node.edge", "kind": "node", "name": "edge", "table": "edge", "target": "node",
     "required": False, "multivalued": True, "world": "closed"},
]
TOY_ATTRIBUTES = [
    {"id": "node.salary", "kind": "node", "name": "salary", "table": "salary", "type": "text",
     "required": False, "multivalued": False, "world": "closed"},
    {"id": "node.grant", "kind": "node", "name": "grant", "table": "grant", "type": "text",
     "required": False, "multivalued": True, "world": "closed"},
]


# The questions of packs/std-explain the gate answers, as the compiler puts them in the bundle.
QUESTIONS = [
    {"term": "grounds", "start": "present", "steps": [{"trace": {"direction": "back", "depth": "all"}}], "answer": "route",
     "limit": 200, "applies_to": {"derivation": "conclusion"}},
    {"term": "reach", "start": "present", "steps": [{"trace": {"direction": "forward", "depth": "3"}}], "answer": "rings",
     "limit": 200},
]


def bundle(kinds, parents=None, arrows=None, attributes=None, enums=None) -> str:
    """A schema bundle with the kinds and the questions: what the gate reads of it (fail closed without kinds).
    Plain sorted JSON, as the compiler writes it: a limit is a number there (canonical JSON writes text)."""
    doc = {"format": "rezono.schema-bundle/1", "questions": QUESTIONS, "checks": [], "kinds": [
        {"id": k, **({"parent": (parents or {})[k]} if k in (parents or {}) else {})} for k in sorted(kinds)]}
    if arrows:
        doc["arrows"] = list(arrows)
    if attributes:
        doc["attributes"] = list(attributes)
    if enums:
        doc["enums"] = [{"id": e} for e in enums]
    return json.dumps(doc, sort_keys=True, separators=(",", ":")) + "\n"


def epoch(full=False, function=FUNCTION, nodes=NODES, edges=EDGES, salaries=SALARIES, grants=GRANTS, roles=("guest",),
          role_rule=True, **changes) -> Epoch:
    rows, ws = toy(nodes, edges, salaries, grants, roles=roles, full=full, function=function, role_rule=role_rule)
    e = Epoch(
        pack="toy", epoch=1, knowledge_time="2026-01-01T00:00:00Z",
        pack_sha256="1" * 64, compiler_sha256="2" * 64, schema_version="0.1.0",
        engine={"name": "test", "version": "0", "sha256": "3" * 64},
        sources=[("rules", "abc")],
        checks=[{"name": "node__unique", "status": "green", "violations": 0}],
        kinds=frozenset({"node", "role"}), rows=rows, witnesses=ws, columns=COLUMNS,
        rules=json.dumps(rules(full, function, role_rule)), definition_sha256="4" * 64,
        bundle=bundle({"node", "role"}, arrows=TOY_ARROWS, attributes=TOY_ATTRIBUTES),
    )
    if "bundle" in changes and "check_metadata" not in changes:
        changes["check_metadata"] = loaded(changes["bundle"])
    return dataclasses.replace(e, **{"check_metadata": loaded(e.bundle)} | changes)


def loaded(bundle_text: str) -> dict | None:
    """The check metadata an engine would load for this bundle: what the checker expects."""
    return metadata.expected(json.loads(bundle_text)) if bundle_text else None


def epoch_with_hidden(**changes) -> Epoch:
    """The paired fixture: the same publication with more rows the guest may not read."""
    return epoch(**MORE, **changes)


def epoch_of_roles(*roles) -> Epoch:
    """Every node is granted to the guest (a1), and a2 gives node in full to every role the pack names. The
    guest may not read `role` rows (no a3), so which other roles exist must not change what it gets."""
    return epoch(full=True, role_rule=False, grants=[("guest", n) for n in NODES], roles=roles)


ROLES = {"checker": "complete", "guest": "may_read"}


def role_keys(s, role="guest", mid="m-1"):
    return sorted(set(s.list(f"toy/{mid}/{role}/")) | set(publish.role_objects(s, "toy", mid, role).values()))


def keys(s, role, rel, mid="m-1"):
    return [r["key"] for r in json.loads(object_bytes(s, role, f"relations/{rel}.json", mid))]


def published(e, tmp_path, roles=ROLES):
    s = store.FileStore(tmp_path)
    return s, publish.publish(e, s, roles)


def test_red_check_blocks_and_writes_nothing(tmp_path):
    s = store.FileStore(tmp_path)
    red = epoch(checks=[{"name": "node__unique", "status": "red", "violations": 2}])
    with pytest.raises(publish.Blocked):
        publish.publish(red, s, ROLES)
    assert s.list("") == []


def test_warning_does_not_block(tmp_path):
    warn = epoch(checks=[{"name": "style", "status": "warning", "violations": 3}])
    assert publish.publish(warn, store.FileStore(tmp_path), ROLES)["id"] == "m-1"


def test_checker_passes_the_epoch_and_the_manifest_says_so(tmp_path):
    assert publish.verify(epoch())["findings"] == []
    m = publish.publish(epoch(), store.FileStore(tmp_path), ROLES)
    assert {"name": publish.PROOFS, "status": "green", "violations": 0} in m["checks"]


def blocked(e, tmp_path, reason):
    """The checker refuses the epoch for `reason`, and nothing is written."""
    assert reason in {f["reason"] for f in publish.verify(e)["findings"]}
    s = store.FileStore(tmp_path)
    with pytest.raises(publish.Blocked, match=publish.PROOFS):
        publish.publish(e, s, ROLES)
    assert s.list("") == []


def replaced(match, **fields):
    """The toy with one instance changed: the one that concludes `match` (relation, key)."""
    ws = [dict(w) for w in epoch().witnesses]
    i = next(i for i, w in enumerate(ws) if (w["conclusion"]["relation"], json.loads(w["conclusion"]["key"])) == match)
    ws[i] = {**ws[i], **fields}
    return epoch(witnesses=ws)


def test_a_forged_proof_blocks(tmp_path):
    """path(a, b) by r1 from a premise that is not in the snapshot."""
    forged = replaced(("path", ["a", "b"]), premises=[{"row": ref("edge", "a", "x"), "polarity": "positive", "stratum": 0}],
                      bindings=[{"variable": "?x", "value": "a"}, {"variable": "?y", "value": "x"}])
    blocked(forged, tmp_path, "premise_missing")


def test_a_missing_proof_blocks(tmp_path):
    """reach(a) is published without a witness: completeness."""
    blocked(epoch(witnesses=[w for w in epoch().witnesses if w["conclusion"]["relation"] != "reach"]), tmp_path,
            "unproven_row")


def test_a_wrong_aggregate_hash_blocks(tmp_path):
    w = next(w for w in epoch().witnesses if w["conclusion"] == ref("degree", "b", "1"))
    agg = {**w["aggregates"][0], "contributors_sha256": "4" * 64}
    blocked(replaced(("degree", ["b", "1"]), aggregates=[agg]), tmp_path, "aggregate_contributors")


def test_an_instance_given_twice_changes_nothing(tmp_path):
    """The engine gives instances; one proof per row is chosen, so a repeated instance is no second proof."""
    e = epoch()
    a, _ = published(e, tmp_path / "a")
    b, _ = published(epoch(witnesses=[*e.witnesses, *e.witnesses[:3]]), tmp_path / "b")
    assert a.list("") == b.list("") and all(a.get(k) == b.get(k) for k in a.list(""))


@pytest.mark.parametrize("witnesses", [None, []], ids=["with-witnesses", "without"])
def test_no_rule_definitions_never_give_green(tmp_path, witnesses):
    """Also without witnesses: the derived rows would be published unproven."""
    s = store.FileStore(tmp_path)
    e = epoch(rules="") if witnesses is None else epoch(rules="", witnesses=witnesses)
    with pytest.raises(publish.Blocked, match="no rule definitions"):
        publish.publish(e, s, ROLES)
    assert s.list("") == []


@pytest.mark.parametrize("ir", [json.dumps({**rules(), "format": None}),
                                json.dumps({k: v for k, v in rules().items() if k != "format"}),
                                json.dumps({**rules(), "format": "rezono.rules/0"}), json.dumps(["not", "a", "dict"]),
                                "{not json"],
                         ids=["format-null", "no-format", "other-format", "not-a-dict", "not-json"])
def test_rules_must_be_the_rule_ir(tmp_path, ir):
    """The minimal form has no relation catalogue, so coverage could not be checked: refused."""
    s = store.FileStore(tmp_path)
    with pytest.raises(publish.Blocked, match="rezono.rules/1|not JSON"):
        publish.publish(epoch(rules=ir), s, ROLES)
    assert s.list("") == []


def test_a_sealed_pack_without_its_seal_in_the_rule_ir_is_refused(tmp_path):
    """Review P1: a pack without rules got the empty rule IR, without seals, so forged refused and accepted rows
    were never recomputed. A sealed kind the rule IR does not carry stops the publication."""
    s = store.FileStore(tmp_path)
    with pytest.raises(publish.Blocked, match="no seal for the sealed kind run"):
        publish.publish(epoch(seals=("run",)), s, ROLES)
    assert s.list("") == []


def test_a_declared_derived_relation_is_covered_also_without_its_rule(tmp_path):
    """reach stays declared derived, with a row, but its rule and witness are gone: refused."""
    ir = json.dumps({**rules(), "rules": [r for r in rules()["rules"] if r["id"] != "r3"]})
    e = epoch(rules=ir, witnesses=[w for w in epoch().witnesses if w["rule_id"] != "r3"])
    s = store.FileStore(tmp_path)
    with pytest.raises(publish.Blocked, match="without a rule"):
        publish.publish(e, s, ROLES)
    assert s.list("") == []


@pytest.mark.parametrize("bad", [{}, {"conclusion": {"relation": "path"}, "rule_id": "r1"}, "x",
                                 {**{"conclusion": {"relation": "path", "key": '["a","b"]'}, "rule_id": "r1"},
                                  "premises": [{"row": {"relation": "edge", "key": '["a","b"]'}}]}])
def test_a_malformed_witness_is_a_red_check(tmp_path, bad):
    s = store.FileStore(tmp_path)
    with pytest.raises(publish.Blocked, match=publish.PROOFS):
        publish.publish(epoch(witnesses=[*epoch().witnesses, bad]), s, ROLES)
    assert s.list("") == []


class Mutating(store.FileStore):
    """A store that changes the epoch's rows and instances after the first write."""

    def __init__(self, root, e):
        super().__init__(root)
        self.e, self.writes = e, 0

    def put_new(self, key, data):
        self.writes += 1
        if self.writes == 1:
            self.e.rows["reach"].append(("c",))
            self.e.rows["node"].clear()
            self.e.witnesses.clear()
        super().put_new(key, data)


def test_only_the_checked_bytes_are_written(tmp_path):
    """The publication is planned and checked first; a change to the epoch during writing changes nothing."""
    clean, m = published(epoch(), tmp_path / "clean")
    s = Mutating(tmp_path / "s", epoch())
    assert publish.publish(s.e, s, ROLES) == m
    assert s.list("") == clean.list("") and all(s.get(k) == clean.get(k) for k in clean.list(""))


def test_manifest_lists_every_file_with_its_hash(tmp_path):
    s, m = published(epoch(), tmp_path)
    assert s.list("toy/manifests/") == ["toy/manifests/m-1.json"]
    assert s.list("toy/heads/") == [pointers.head_key("toy", 1)], "its head, right after it"
    assert json.loads(s.get("toy/manifests/m-1.json")) == m
    listed = m["snapshots"] + m["witnesses"]
    for f in listed:
        key = f["uri"].removeprefix("s3://rezono/")
        assert hashlib.sha256(s.get(key)).hexdigest() == f["sha256"]
    assert sorted({f["uri"].removeprefix("s3://rezono/") for f in listed}) == [
        k for k in s.list("toy/") if not k.startswith(("toy/manifests/", "toy/bundles/", "toy/heads/", "toy/epochs/", "toy/bases/"))]
    assert {c["relation"]: c["rows"] for c in m["counts"]}["node"] == 4


def test_the_manifest_names_its_access_semantics_and_a_definition_hash(tmp_path):
    """O8: the gate serves only manifests with access_semantics 2; the bundle path never names the facts."""
    s, m = published(epoch(), tmp_path)
    assert m["access_semantics"] == publish.ACCESS_SEMANTICS == 2
    assert m["definition_sha256"] == "4" * 64
    for c in m["compiled"]:
        assert m["pack_sha256"] not in c["uri"] and m["definition_sha256"] in c["uri"]
    assert [k for k in s.list("") if m["pack_sha256"] in k] == []
    with pytest.raises(ValueError, match="definition_sha256"):
        publish.publish(epoch(definition_sha256=""), store.FileStore(tmp_path / "x"), ROLES)


def test_bundle_is_shared_by_definition_and_compiler(tmp_path):
    s = store.FileStore(tmp_path)
    publish.publish(epoch(), s, ROLES)
    publish.publish(epoch(epoch=2), s, ROLES)
    assert s.list("toy/bundles/") == [f"toy/bundles/{'4' * 64}/{'2' * 64}.json", f"toy/bundles/{'4' * 64}/{'2' * 64}.rules.json"]


def test_bundle_and_rule_ir_are_archived_with_their_hash(tmp_path):
    s, m = published(epoch(), tmp_path)
    assert [c["file"] for c in m["compiled"]] == ["bundle/schema-bundle.json", "ir/rules.json"]
    for c in m["compiled"]:
        assert hashlib.sha256(s.get(c["uri"].removeprefix("s3://rezono/"))).hexdigest() == c["sha256"]
    # The rule IR the proofs were checked against is always archived; the bundle only when there is one.
    assert [c["file"] for c in publish.publish(epoch(epoch=2, bundle=""), s, {"checker": "complete"})["compiled"]] == ["ir/rules.json"]


def test_the_build_record_holds_the_profile_and_names_the_build(tmp_path):
    s = store.FileStore(tmp_path)
    build = {"compiler_sha256": "2" * 64, "python": {"implementation": "cpython", "version": "3.13.18"}}
    m = publish.publish(epoch(build=build), s, ROLES)
    record = s.get(m["build"]["uri"].removeprefix("s3://rezono/"))
    assert hashlib.sha256(record).hexdigest() == m["build"]["sha256"]
    assert json.loads(record) == build | {"profile": {"roles": dict(sorted(ROLES.items()))}}
    other = publish.publish(epoch(epoch=2, build=build), s, {"checker": "complete"})
    assert other["build"]["sha256"] != m["build"]["sha256"], "another profile is another build"


def test_complete_role_reads_everything(tmp_path):
    s, m = published(epoch(), tmp_path)
    mine = [x for x in m["snapshots"] if x["role"] == "checker"]
    assert all(x["complete"] and x["full"] for x in mine)
    assert keys(s, "checker", "node") == [["a"], ["b"], ["c"], [SECRET]]
    assert keys(s, "checker", "isolated") == [["c"], [SECRET]]


def test_filtered_role_sees_what_it_can_derive_from_what_it_reads(tmp_path):
    """reach(a) and touched(a) have a proof from readable rows; what counts or negates over edge, or
    rests on a hidden row, is gone."""
    s, m = published(epoch(), tmp_path)
    assert not any(x["complete"] for x in m["snapshots"] if x["role"] == "guest")
    assert keys(s, "guest", "node") == [["a"], ["b"], ["c"]]
    assert keys(s, "guest", "edge") == [["a", "b"]]
    assert keys(s, "guest", "path") == [["a", "b"]]
    assert keys(s, "guest", "reach") == [["a"]]
    assert keys(s, "guest", "touched") == [["a"]]
    for rel in ("isolated", "degree", "hub", "wage", "total", "salary", "role"):
        assert keys(s, "guest", rel) == [], rel
    seen = json.loads(object_bytes(s, "guest", "witnesses.json"))
    assert seen["hidden"] == []
    for key in role_keys(s):
        assert SECRET.encode() not in s.get(key) and b"12345" not in s.get(key), key


def test_the_proof_is_chosen_per_role_among_readable_proofs(tmp_path):
    """With a hidden edge(a, a0-hidden), the earliest proof of reach(a) is hidden; the guest gets the
    readable one, the checker the earliest."""
    s, _ = published(epoch_with_hidden(), tmp_path)
    proofs = lambda role: {(w["conclusion"]["relation"], w["conclusion"]["key"]): w
                           for w in reversed(json.loads(object_bytes(s, role, "witnesses.json"))["witnesses"])}
    assert proofs("checker")[("reach", '["a"]')]["premises"][0]["row"] == ref("path", "a", HIDDEN)
    assert proofs("guest")[("reach", '["a"]')]["premises"][0]["row"] == ref("path", "a", "b")


def test_non_interference_hidden_rows_change_no_byte_of_the_guest(tmp_path):
    """The paired fixture: the same publication with and without more hidden rows, also rows that would
    change a negation (isolated(c)), a count (degree(a)), a sum and the earliest proof (reach(a))."""
    for function in ("count", "sum", "min", "max"):
        a, ma = published(epoch(function=function), tmp_path / function / "a")
        b, mb = published(epoch_with_hidden(function=function), tmp_path / function / "b")
        assert keys(a, "checker", "isolated") != keys(b, "checker", "isolated")
        assert function == "max" or keys(a, "checker", "total") != keys(b, "checker", "total")
        guest = role_keys(a)
        assert guest == role_keys(b)
        assert [k for k in guest if a.get(k) != b.get(k)] == [], function
        view = lambda m: [x for x in m["snapshots"] + m["witnesses"] if x["role"] == "guest"]
        assert view(ma) == view(mb)
        for key in role_keys(b):
            assert HIDDEN.encode() not in b.get(key)


@pytest.mark.parametrize("function", ["count", "sum", "min", "max"])
def test_negation_and_aggregates_over_relations_read_in_full(tmp_path, function):
    """With a2, every role reads every node in full, so also edge and salary: the guest gets what the
    checker gets, counts, sums, minimums, maximums and negation included."""
    s, m = published(epoch(full=True, function=function), tmp_path)
    for x in m["snapshots"]:
        if x["role"] == "guest":
            assert x["full"], x["relation"]
            assert keys(s, "guest", x["relation"]) == keys(s, "checker", x["relation"]), x["relation"]
    assert keys(s, "guest", "total") == [[group(SALARIES, function)[2]]]
    assert keys(s, "guest", "isolated") == [["c"], [SECRET]]
    assert object_bytes(s, "guest", "witnesses.json") == object_bytes(s, "checker", "witnesses.json")


def test_full_scope_comes_from_the_rules_not_from_the_data(tmp_path):
    """Without a2 the guest reads every node too (all granted), yet edge is not read in full: no count."""
    s, m = published(epoch(grants=[("guest", n) for n in NODES]), tmp_path)
    assert keys(s, "guest", "node") == keys(s, "checker", "node")
    assert keys(s, "guest", "degree") == [] and keys(s, "guest", "isolated") == []
    assert [x["relation"] for x in m["snapshots"] if x["role"] == "guest" and x["full"]] == []


@pytest.mark.parametrize("named, worlds", [(True, [("guest",), ("guest", "other")]), (False, [(), ("other",)])],
                         ids=["named", "not-named"])
def test_role_rows_the_guest_cannot_read_change_no_byte(tmp_path, named, worlds):
    """A rule over every role (a2) gives node in full to a role the pack names, and nothing to one it does
    not name: the guest then reads the nodes it was granted, none of them in full. Either way the
    guest may not read `role` rows, and which other roles exist changes no byte of what it gets."""
    stores = []
    for i, roles in enumerate(worlds):
        s, m = published(epoch_of_roles(*roles), tmp_path / str(i))
        assert keys(s, "guest", "role") == [] and keys(s, "guest", "node") == keys(s, "checker", "node")
        assert (keys(s, "guest", "degree") != []) is named
        assert any(x["full"] for x in m["snapshots"] if x["role"] == "guest") is named
        stores.append((s, [x for x in m["snapshots"] + m["witnesses"] if x["role"] == "guest"]))
    (a, ma), *rest = stores
    for b, mb in rest:
        assert mb == ma
        assert [k for k in role_keys(a) if a.get(k) != b.get(k)] == []
        assert all(b"other" not in b.get(k) for k in role_keys(b))


def test_a_configured_role_the_pack_does_not_name_reads_nothing(tmp_path):
    """A2 and a3 are rules over every role, and derive rows only for a role the pack's facts name. A
    role of the profile that the pack does not name gets an empty projection and no witness, nothing in full.
    Read by its shape alone, a2 gave such a role node in full, and the publication went red on `rezono:access`."""
    s, m = published(epoch(full=True), tmp_path / "a", ROLES | {"stranger": "may_read"})
    mine = [x for x in m["snapshots"] if x["role"] == "stranger"]
    assert {x["relation"] for x in mine} == {x["relation"] for x in m["snapshots"] if x["role"] == "checker"}
    assert not any(x["full"] or x["complete"] for x in mine)
    assert all(keys(s, "stranger", x["relation"]) == [] for x in mine)
    assert json.loads(object_bytes(s, "stranger", "witnesses.json")) == {"hidden": [], "witnesses": []}
    assert access.without_rights(epoch(full=True).rows, ROLES | {"stranger": "may_read"}) == ["stranger"]
    # The role the pack names reads what it read without the stranger in the profile.
    alone, _ = published(epoch(full=True), tmp_path / "b")
    assert role_keys(alone) and all(alone.get(k) == s.get(k) for k in role_keys(alone))


def test_a_full_kind_with_an_unreadable_element_is_refused():
    """The read rules give node in full, but may_read misses an element: the data disagrees (a red check
    `rezono:access` in a publication)."""
    e = epoch(full=True)
    rows = {**e.rows, "may_read": [r for r in e.rows["may_read"] if r[2] != SECRET]}
    with pytest.raises(access.Uncovered, match="kind node in full"):
        guest(dataclasses.replace(e, rows=rows))


def test_the_checker_checks_every_role_against_its_own_snapshots(tmp_path, monkeypatch):
    """R7 per role: a role's witness that negates a relation it does not read in full is red. The checker's
    own derivation finds the row first (`not_derivable`); the proof check finds it too (`outside_full_scope`)."""
    real = access.for_role

    def leaky(*args):
        readable, sees, full = real(*args)
        extra = witness("isolated", ["c"], "r7", [("x", "c")], [("node", ["c"])], [("touched", ["c"])])
        readable = {**readable, "isolated": [("c",)]}
        return readable, {"witnesses": [*sees["witnesses"], extra], "hidden": []}, full

    monkeypatch.setattr(access, "for_role", leaky)
    s = store.FileStore(tmp_path)
    with pytest.raises(publish.Blocked, match=r"role guest: .*not_derivable isolated.*outside_full_scope"):
        publish.publish(epoch(), s, ROLES)
    assert s.list("") == []


def _leak(readable, full):
    return {**readable, "node": [*readable["node"], (SECRET,)]}, full


def _drop(readable, full):
    return {**readable, "node": readable["node"][1:]}, full


def _widen(readable, full):
    return readable, full | {"node"}


@pytest.mark.parametrize("bug, reason", [(_leak, "not_readable"), (_drop, "readable_missing"),
                                         (_widen, "full_mismatch")])
def test_a_filter_bug_is_red_because_the_checker_derives_access_itself(tmp_path, monkeypatch, bug, reason):
    """Audit 07-11 (O8, R7): the checker derives a role's readable rows and its full relations from the
    schema, the role and may_read, so a filter that leaks a row, drops one or widens `full` is red."""
    real = access.for_role

    def buggy(*args):
        readable, sees, full = real(*args)
        readable, full = bug(readable, full)
        return readable, sees, full

    monkeypatch.setattr(access, "for_role", buggy)
    s = store.FileStore(tmp_path)
    with pytest.raises(publish.Blocked, match=f"role guest: .*{reason}"):
        publish.publish(epoch(), s, ROLES)
    assert s.list("") == []


def test_a_filter_that_drops_a_derivable_row_is_red(tmp_path, monkeypatch):
    """A filter that chose the proof over all data first would lose reach(a), which
    the guest can derive from path(a, b). Its snapshot is a closed world, so the row would read as false;
    the checker derives the role's derived rows itself and finds it missing."""
    real = access.for_role
    gone = ("a",)

    def lossy(*args):
        readable, sees, full = real(*args)
        readable = {**readable, "reach": [r for r in readable["reach"] if tuple(r) != gone]}
        kept = [w for w in sees["witnesses"] if access.ref(w) != ("reach", canonical_json(list(gone)))]
        return readable, {**sees, "witnesses": kept}, full

    monkeypatch.setattr(access, "for_role", lossy)
    s = store.FileStore(tmp_path)
    with pytest.raises(publish.Blocked, match="role guest: .*derivable_missing"):
        publish.publish(epoch(), s, ROLES)
    assert s.list("") == []


def test_a_proof_that_is_not_the_ranked_choice_is_red(tmp_path, monkeypatch):
    """reach(a) has a proof of rank 2 (through path(a, b)) and one of rank 3 (through
    path(a, secret)). Both are valid, so only an independent choice finds that the publisher took the worse."""
    real = access.choose
    head = ("reach", canonical_json(["a"]))

    def worse(instances, derived):
        chosen = real(instances, derived)
        other = [w for w in instances if access.ref(w) == head and w != chosen.get(head)
                 and all((p["row"]["relation"], p["row"]["key"]) in chosen for p in w["premises"])]
        return {**chosen, head: other[0]} if other else chosen

    monkeypatch.setattr(access, "choose", worse)
    s = store.FileStore(tmp_path)
    with pytest.raises(publish.Blocked, match=r"role \(complete\): .*choice_mismatch"):
        publish.publish(epoch(), s, ROLES)
    assert s.list("") == []


def test_an_element_is_typed():
    """The same id in two kinds is two elements: a right on node(a) is no right on team(a)."""
    e = epoch(kinds=frozenset({"node", "role", "team"}), columns={**COLUMNS, "team": ("team",)})
    rows = {**e.rows, "team": [("a",), ("b",)], "may_read": [*e.rows["may_read"], ("guest", "team", "b")]}
    readable, _, _ = guest(dataclasses.replace(e, rows=rows))
    assert readable["team"] == [("b",)]
    assert readable["node"] == [("a",), ("b",), ("c",)]


def test_a_rule_reads_only_the_calculation_the_role_can_prove():
    selection = "calc__amount"
    doc = {"relations": [relation(selection, "calc", 4), relation("notice", "derived", 2),
                         relation("may_read", "derived", 3)],
           "rules": [
               rule("public_node", ("may_read", "?r", "node", "?x"), [lit("role", "?r"), lit("node", "?x")]),
               rule("private_entry", ("may_read", "finance", "entry", "?x"), [lit("entry", "?x")]),
           ]}
    calc_ir = {
        "subject": "node", "as_of": "calc__as_of", "rules": [{"view": selection}],
        "versions": [{"id": "amount@v", "view": "calc__amount__v", "definitions": [
            {"when": {"boolean": True}, "value": {"fact": "private_amount"}}
        ]}],
        "facts": [{"id": "private_amount", "reads": "attribute", "table": "entry__amount"}],
    }
    columns = {"node": ("node",), "entry": ("entry",), "entry__amount": ("entry", None),
               "role": (None,)}
    schema_bundle = {
        "kinds": [{"id": "node"}, {"id": "entry"}],
        "attributes": [{"table": "entry__amount", "kind": "entry"}],
        "enums": [{"id": "role"}],
    }

    def visible(role, amount, forge_notice=False):
        calc_row = ("n", amount, "known", "")
        rows = {"node": [("n",)], "entry": [("e",)], "entry__amount": [("e", amount)],
                "role": [("guest",), ("finance",)], "calc__as_of": [], selection: [calc_row],
                "may_read": [("guest", "node", "n"), ("finance", "node", "n"), ("finance", "entry", "e")],
                "notice": [("n", amount)]}
        proof = {"conclusion": ref(selection, *calc_row), "rule": "amount", "version": "v"}
        may_read_witnesses = [
            witness("may_read", ("guest", "node", "n"), "public_node", [("r", "guest"), ("x", "n")],
                    premises=[("role", ("guest",)), ("node", ("n",))]),
            witness("may_read", ("finance", "node", "n"), "public_node", [("r", "finance"), ("x", "n")],
                    premises=[("role", ("finance",)), ("node", ("n",))]),
            witness("may_read", ("finance", "entry", "e"), "private_entry", [("x", "e")],
                    premises=[("entry", ("e",))]),
        ]
        notice = witness("notice", ("n", amount), "notice", [], premises=[(selection, calc_row)])
        instances = [*may_read_witnesses, notice]
        kinds = {"node", "entry"}
        readable, proofs, full = access.for_role(rows, kinds, {}, columns, doc, instances, role, calc_ir, [proof])
        snapshots = {name: publish.snapshot(rs) for name, rs in readable.items()}
        if forge_notice:
            snapshots["notice"] = publish.snapshot(rows["notice"])
        _, findings = checker_access.check_role(
            role, {name: publish.snapshot(rs) for name, rs in rows.items()}, snapshots, full, schema_bundle,
            doc, calc_ir, instances, [proof], proofs["calc_witnesses"],
            [*proofs["witnesses"], notice] if forge_notice else proofs["witnesses"]
        )
        if forge_notice:
            assert any(f["reason"] == "not_derivable" and f["relation"] == "notice" for f in findings)
        else:
            assert not findings
        return readable, proofs, full

    guest_rows, guest_proofs, guest_full = visible("guest", "12")
    assert (guest_rows, guest_proofs, guest_full) == visible("guest", "31")
    assert guest_rows["node"] == [("n",)]
    assert guest_rows[selection] == guest_rows["notice"] == []
    assert [w for w in guest_proofs["witnesses"] if w["conclusion"]["relation"] == "notice"] == []
    assert guest_proofs["calc_witnesses"] == []
    assert selection not in guest_full
    finance_rows, finance_proofs, _ = visible("finance", "12")
    assert finance_rows[selection] == [("n", "12", "known", "")]
    assert finance_rows["notice"] == [("n", "12")]
    assert len([w for w in finance_proofs["witnesses"] if w["conclusion"]["relation"] == "notice"]) == 1
    assert len(finance_proofs["calc_witnesses"]) == 1
    visible("guest", "12", forge_notice=True)


def calculated(role, publisher_sources=None, checker_sources=None):
    """A calculation per node that no rule reads: `amount` reads an attribute of `entry`, `twice` takes `amount`
    as a premise. Every role reads every node; only `finance` reads the entries. Gives the role's rows, its
    full relations, every row, and the findings of the checker's own derivation."""
    amount, twice = "calc__amount", "calc__twice"
    doc = {"relations": [relation("may_read", "derived", 3)],
           "rules": [rule("public_node", ("may_read", "?r", "node", "?x"), [lit("role", "?r"), lit("node", "?x")]),
                     rule("private_entry", ("may_read", "finance", "entry", "?x"), [lit("entry", "?x")])]}
    one = {"when": {"boolean": True}}
    calc_ir = {"subject": "node", "as_of": "calc__as_of",
               "rules": [{"rule": "amount", "view": amount, "versions": ["amount@v"]},
                         {"rule": "twice", "view": twice, "versions": ["twice@v"]}],
               "versions": [{"id": "amount@v", "view": "calc__amount__v", "definitions": [one | {"value": {"fact": "held"}}]},
                            {"id": "twice@v", "view": "calc__twice__v", "definitions": [one | {"value": {"rule": "amount"}}]}],
               "facts": [{"id": "held", "reads": "attribute", "table": "entry__amount"}]}
    columns = {"node": ("node",), "entry": ("entry",), "entry__amount": ("entry", None), "role": (None,)}
    schema_bundle = {
        "kinds": [{"id": "node"}, {"id": "entry"}],
        "attributes": [{"table": "entry__amount", "kind": "entry"}],
        "enums": [{"id": "role"}],
    }
    kinds = {"node", "entry"}
    held, doubled = [(n, "12", "known", "") for n in ("n", "m")], [(n, "24", "known", "") for n in ("n", "m")]
    rows = {"node": [("n",), ("m",)], "entry": [("e",)], "entry__amount": [("e", "12")],
            "role": [("guest",), ("finance",)], "calc__as_of": [], amount: held, twice: doubled,
            "may_read": [(r, "node", n) for r in ("guest", "finance") for n in ("n", "m")] + [("finance", "entry", "e")]}
    instances = [
        witness("may_read", (r, "node", n), "public_node", [("r", r), ("x", n)],
                premises=[("role", (r,)), ("node", (n,))])
        for r in ("guest", "finance") for n in ("n", "m")
    ] + [
        witness("may_read", ("finance", "entry", "e"), "private_entry", [("x", "e")],
                premises=[("entry", ("e",))])
    ]
    proofs = [{"conclusion": ref(amount, *r), "rule": "amount", "version": "v"} for r in held]
    proofs += [{"conclusion": ref(twice, *r), "rule": "twice", "version": "v", "premises": [ref(amount, *h)]}
               for r, h in zip(doubled, held)]
    with pytest.MonkeyPatch.context() as patch:
        if publisher_sources:
            patch.setattr(access.calc_scope, "view_sources", publisher_sources)
        if checker_sources:
            patch.setattr(checker_access, "calc_sources", checker_sources)
        readable, sees, full = access.for_role(rows, kinds, {}, columns, doc, instances, role, calc_ir, proofs)
        _, findings = checker_access.check_role(
            role, {name: publish.snapshot(rs) for name, rs in rows.items()},
            {name: publish.snapshot(rs) for name, rs in readable.items()}, full, schema_bundle, doc, calc_ir,
            instances, proofs, sees["calc_witnesses"], sees["witnesses"])
    return readable, full, rows, {(f["reason"], f.get("relation")) for f in findings}


def test_a_calculation_view_is_full_only_for_a_role_that_reads_all_its_sources():
    """Full means a missing row is "none". The guest reads the subject kind in full and not the
    relation the calculation reads: it gets no calculated row, so the view is not full for it, and neither is
    the view that takes it as a premise. A role that reads every source has both in full, row for row."""
    views = {"calc__amount", "calc__twice"}
    readable, full, rows, findings = calculated("guest")
    assert {"node", "calc__as_of"} <= full and "entry__amount" not in full
    assert [readable[v] for v in sorted(views)] == [[], []]
    assert not views & full
    assert findings == set()
    readable, full, rows, findings = calculated("finance")
    assert views <= full
    assert all(publish.snapshot(readable[v]) == publish.snapshot(rows[v]) and rows[v] for v in views)
    assert findings == set()


@pytest.mark.parametrize("side", ["publisher_sources", "checker_sources"])
def test_the_rule_for_a_full_calculation_view_changed_on_one_side_is_red(side):
    """The publisher and the checker each read the sources of a view themselves. With the rule of
    before on one side only (a view full by its subject kind alone), the two sets differ: `full_mismatch`."""
    by_subject = lambda ir: {}  # noqa: E731
    _, _, _, findings = calculated("guest", **{side: by_subject})
    assert findings == {("full_mismatch", "calc__amount, calc__twice")}
    assert calculated("finance", **{side: by_subject})[3] == set()


def test_a_view_the_program_does_not_account_for_is_not_full():
    """A rule without its versions, or a premise the program does not hold, says nothing of what the
    view rests on. Both readings then call it not full, also for a role that reads everything else."""
    ir = {"subject": "node", "as_of": "calc__as_of", "facts": [],
          "rules": [{"rule": "bare", "view": "calc__bare"}, {"rule": "lost", "view": "calc__lost", "versions": ["lost@v"]}],
          "versions": [{"id": "lost@v", "view": "calc__lost__v",
                        "definitions": [{"when": {"boolean": True}, "value": {"rule": "nowhere"}}]}]}
    assert access.calc_scope.view_sources(ir) == checker_access.calc_sources(ir) == {"calc__bare": None, "calc__lost": None}
    columns = access.with_calc({"node": ("node",), "role": (None,), "may_read": (None, None, None)}, ir)
    doc = {"rules": [rule("all", ("may_read", "?r", "node", "?x"), [lit("role", "?r"), lit("node", "?x")])]}
    rows = {"node": [("n",)], "role": [("guest",)], "may_read": [("guest", "node", "n")], "calc__as_of": [],
            "calc__bare": [], "calc__lost": []}
    scope = access.Scope(rows, {"node"}, {}, columns, doc, "guest")
    assert scope.full == {"node", "role", "may_read", "calc__as_of"}


def test_a_batch_publication_checks_a_rule_reading_a_calculation(tmp_path):
    from rezono_publisher import batch

    fixture = Path(__file__).resolve().parents[3] / "compiler" / "tests" / "fixtures" / "calc"
    pack = tmp_path / "calc"
    shutil.copytree(fixture, pack)
    (pack / "rules" / "budget.dl").write_text(
        '.decl budget_value(item: symbol, cents: number)\n'
        'budget_value(x, cents) :- calc__total(x, cents, "known", "").\n',
        encoding="utf-8",
    )
    (pack / "facts").mkdir()
    (pack / "facts" / "inputs.yaml").write_text(
        "item:\n  - {id: i0, amount: 7, flag: true}\n  - {id: i1, amount: 0, flag: false}\n"
        "entry:\n  - {id: e0, item: i0, name: first}\n  - {id: e1, item: i0, name: second}\n"
        "setting:\n  - {id: s0, value: 3}\n",
        encoding="utf-8",
    )
    e = batch.epoch(pack, epoch=1, knowledge_time="2026-11-01T00:00:00Z", sources=[("facts", "test")])
    assert e.rows["budget_value"] == [("i0", "12"), ("i1", "0")]
    st = store.FileStore(tmp_path / "store")
    files, m = publish.plan(e, st, {"checker": access.COMPLETE})
    [entry] = m["witnesses"]
    proofs = json.loads(dict(files)[entry["uri"].removeprefix(st.uri(""))])
    result = next(w for w in proofs["witnesses"] if w["conclusion"] == ref("budget_value", "i0", "12"))
    selection = ref("calc__total", "i0", "12", "known", "")
    assert [p["row"] for p in result["premises"]] == [selection]
    calc_proof = next(w for w in proofs["calc_witnesses"] if w["conclusion"] == selection)
    assert {p["relation"] for p in calc_proof["premises"]} == {"entry_total", "has_entry"}


@pytest.fixture
def retained_epoch():
    return retained_publication("toy", "total", {})


@pytest.fixture
def retained_native_cost():
    archive, pin, manifest = retained_publication("pricing-fixture", "native_amount", {
        "item_merchant": [("i0", "shop")],
        "merchant_currency": [("shop", "EUR"), ("another", "EUR")],
    })
    compiled = {entry["file"]: entry["sha256"] for entry in manifest["compiled"]}
    definition = retained_calculation.NativeCostDefinition(
        pin.pack, pin.relation, compiled["ir/rules.json"], compiled["ir/calc.json"],
        "item_merchant", "merchant_currency",
    )
    return archive, pin, manifest, definition


def retained_publication(pack, calc_rule, extra_rows, admitted=False):
    """One calculation reads a derived input. Use the real publisher without an engine. `admitted`: the epoch
    also admitted a completeness receipt, in the archive layout of test_evidence_batch."""

    class MemoryStore:
        def __init__(self):
            self.objects = {}

        def uri(self, key):
            return f"s3://test/{key}"

        def get(self, key):
            return self.objects.get(key)

        def put_new(self, key, data):
            assert self.objects.setdefault(key, data) == data

    archive = MemoryStore()
    evidence, protected = None, {}
    if admitted:
        from rezono_checker.evidence import Evidence, admit
        from test_evidence_batch import layout, reader

        context, index, _, _ = layout(archive)
        evidence = Evidence(context, index, reader(archive))
        protected = {relation: rows for relation, rows in admit(evidence).rows.items() if rows}
    name = f"calc__{calc_rule}"
    date = "2026-11-01"
    row = ref(name, "i0", "0", "known", "")
    early = witness("early", ["i0", "0"], "copy", [("x", "i0"), ("v", "0")], [("amount", ["i0", "0"])])
    rules_doc = {"format": "rezono.rules/1", "pack": pack,
                 "relations": [relation("amount", "base", 2), relation("early", "derived", 2),
                               *(relation(extra, "base", 2) for extra in extra_rows),
                               *(relation(extra, "base", len(rows[0])) for extra, rows in protected.items())],
                 "rules": [rule("copy", ("early", "?x", "?v"), [lit("amount", "?x", "?v")])]}
    calculation = {
        "format": "rezono.calc-ir/1", "pack": pack, "subject": "item", "subject_table": "item", "as_of": "calc__as_of",
        "facts": [{"id": "input", "type": "number", "reads": "column", "table": "early", "index": 1}],
        "rules": [{"rule": calc_rule, "view": name, "type": "number", "versions": [f"{calc_rule}@1"]}],
        "versions": [{"id": f"{calc_rule}@1", "rule": calc_rule, "version": "1", "view": f"{name}__1",
                      "valid_from": date, "valid_until": "2026-12-01", "known_from": date,
                      "definitions": [{"name": "result", "when": {"boolean": True}, "value": {"fact": "input"}}]}],
    }
    calculated = {"conclusion": row, "rule": calc_rule, "version": "1", "definition": "result",
                  "valid_at": date, "known_at": date, "state": "known", "value": "0", "reason": "",
                  "reads": ["calc__as_of", "early"], "premises": [early["conclusion"]],
                  "steps": [{"path": "result/value", "op": "fact", "ref": "input", "relation": "early",
                             "state": "known", "value": "0"}]}
    e = epoch(pack=pack, bundle="", rows={"item": [("i0",)], "amount": [("i0", "0")], "early": [("i0", "0")],
                                         name: [("i0", "0", "known", "")], "calc__as_of": [("as_of", date, date)],
                                         **extra_rows, **protected},
              columns={"item": ("item",), "amount": ("item", None),
                       **dict.fromkeys(extra_rows, ("item", None)),
                       **{extra: (None,) * len(rows[0]) for extra, rows in protected.items()}}, witnesses=[early],
              rules=json.dumps(rules_doc), calc=json.dumps(calculation), calc_witnesses=[calculated],
              evidence=evidence)
    main =publish.publish(e, archive, {"checker": access.COMPLETE})
    publish.publish(dataclasses.replace(e, epoch=3), archive, {"checker": access.COMPLETE})
    old = archive.get(f"{pack}/manifests/m-1.json")
    pin = retained_calculation.PinnedSelection(pack, 1, publish.sha256(old), **row)
    return archive, pin, main


def test_retained_calculation_reads_the_pinned_epoch_and_keeps_known_zero(retained_epoch):
    archive, pin, _ = retained_epoch
    assert retained_calculation.resolve(archive, pin) == 0
    later = dataclasses.replace(pin, epoch=3)
    with pytest.raises(ValueError, match="manifest digest mismatch"):
        retained_calculation.resolve(archive, later)
    same_selection = dataclasses.replace(later, manifest_sha256=publish.sha256(archive.get("toy/manifests/m-3.json")))
    assert retained_calculation.resolve(archive, same_selection) == 0
    with pytest.raises(ValueError):
        retained_calculation.resolve(archive, dataclasses.replace(pin, key=ref(pin.relation, "i1", "0", "known", "")["key"]))


def retained_admitted():
    """A retained publication whose epoch admitted a receipt, and the context hash its protected caller pinned:
    the hash of the context the epoch was admitted with (test_evidence_batch.layout), never read from the
    manifest."""
    archive, pin, manifest = retained_publication("toy", "total", {}, admitted=True)
    trusted = hashlib.sha256(archive.get("observations/retained/context.json")).hexdigest()
    return archive, pin, manifest, trusted


def test_retained_calculation_admits_the_epoch_evidence_again():
    """An epoch that admitted a receipt is verified again from its retained publication: the complete manifest
    names the trusted context and the submitted index, the protected caller pins the context hash, and the
    replay rebuilds the Evidence and admits again. Without the caller's pin, without the manifest naming the
    context, or without the context, the replay fails closed."""
    archive, pin, manifest, trusted = retained_admitted()
    assert retained_calculation.resolve(archive, pin, context_sha256=trusted) == 0
    with pytest.raises(ValueError, match="the caller did not pin"):
        retained_calculation.resolve(archive, pin)

    context = manifest["evidence"]["context"]
    assert context["file"] == "observations/retained/context.json"
    kept = archive.objects.pop(context["uri"].removeprefix("s3://test/"))
    with pytest.raises(ValueError, match="evidence_refused"):
        retained_calculation.resolve(archive, pin, context_sha256=trusted)

    archive.objects[context["uri"].removeprefix("s3://test/")] = kept
    unnamed = repin_retained_manifest(archive, pin, {key: value for key, value in manifest.items() if key != "evidence"})
    with pytest.raises(ValueError, match="names no evidence context"):
        retained_calculation.resolve(archive, unnamed, context_sha256=trusted)
    with pytest.raises(ValueError, match="receipt_not_admitted"):
        retained_calculation.resolve(archive, unnamed)


def test_retained_calculation_refuses_a_context_the_caller_did_not_pin():
    """The manifest names a context; it confers no authority. A context with other bytes, named by a manifest
    that a trusted plan pins, is refused against the caller's own pin, and is not a retained observation."""
    archive, pin, manifest, trusted = retained_admitted()
    forged = json.loads(archive.get("observations/retained/context.json"))
    authorization = forged["completeness"][0]["issuer"]["authorization"]
    forged["completeness"][0]["issuer"]["authorization"] = replaced = dict(authorization, file="toy/objects/a.json",
                                                                           uri=archive.uri("toy/objects/a.json"))
    archive.objects["toy/objects/a.json"] = archive.get(authorization["file"])
    context = {"file": "toy/objects/forged-context.json", "uri": archive.uri("toy/objects/forged-context.json")}
    replace_retained_object(archive, context, forged)
    assert context["sha256"] != trusted and replaced["sha256"] == authorization["sha256"]
    named = repin_retained_manifest(archive, pin, manifest | {"evidence": manifest["evidence"] | {"context": context}})
    with pytest.raises(ValueError, match="does not match the caller's pin"):
        retained_calculation.resolve(archive, named, context_sha256=trusted)
    with pytest.raises(ValueError, match="leaves the retained observations"):
        retained_calculation.resolve(archive, named, context_sha256=context["sha256"])


def test_retained_calculation_reads_evidence_only_from_the_retained_observations():
    """The same context bytes stored outside observations/retained/, under another pack, are refused."""
    archive, pin, manifest, trusted = retained_admitted()
    archive.objects["otherpack/x/context.json"] = archive.get("observations/retained/context.json")
    context = manifest["evidence"]["context"] | {"file": "otherpack/x/context.json",
                                                 "uri": archive.uri("otherpack/x/context.json")}
    named = repin_retained_manifest(archive, pin, manifest | {"evidence": manifest["evidence"] | {"context": context}})
    with pytest.raises(ValueError, match="leaves the retained observations"):
        retained_calculation.resolve(archive, named, context_sha256=trusted)


def test_retained_calculation_rejects_damaged_evidence(retained_epoch):
    archive, pin, manifest = retained_epoch
    [rule_ir] = [entry for entry in manifest["compiled"] if entry["file"] == "ir/rules.json"]
    key = rule_ir["uri"].removeprefix("s3://test/")
    archive.objects[key] += b" "
    with pytest.raises(ValueError, match="evidence digest mismatch"):
        retained_calculation.resolve(archive, pin)


def repin_retained_manifest(archive, pin, manifest):
    body = publish.canonical(manifest)
    archive.objects[f"{pin.pack}/manifests/{manifest['id']}.json"] = body
    head_key, head = pointers.head(pin.pack, body)
    archive.objects[head_key] = head
    return dataclasses.replace(pin, manifest_sha256=publish.sha256(body))


def replace_retained_object(archive, entry, doc):
    body = publish.canonical(doc)
    archive.objects[entry["uri"].removeprefix("s3://test/")] = body
    entry["sha256"] = publish.sha256(body)


def test_retained_native_cost_keeps_zero_and_checks_the_unit(retained_native_cost):
    archive, pin, _, definition = retained_native_cost
    resolve = retained_calculation.resolve_native_cost
    assert resolve(archive, pin, definition=definition, provider="shop", currency="EUR") == 0
    with pytest.raises(ValueError, match="historical item_merchant"):
        resolve(archive, pin, definition=definition, provider="another", currency="EUR")
    with pytest.raises(ValueError, match="historical merchant_currency"):
        resolve(archive, pin, definition=definition, provider="shop", currency="USD")


@pytest.mark.parametrize("pack,relation", [
    ("toy", "calc__native_amount"), ("pricing-fixture", "calc__converted_amount"),
])
def test_retained_native_cost_rejects_another_calculation(pack, relation, retained_native_cost):
    _, _, _, definition = retained_native_cost
    pin = retained_calculation.PinnedSelection(pack, 1, "1" * 64, relation, "[]")
    with pytest.raises(ValueError, match="selection does not match the native cost definition"):
        retained_calculation.resolve_native_cost(None, pin, definition=definition, provider="shop", currency="EUR")


@pytest.mark.parametrize("file", ["ir/rules.json", "ir/calc.json"])
def test_retained_native_cost_rejects_changed_ir(retained_native_cost, file):
    archive, pin, manifest, definition = retained_native_cost
    [entry] = [entry for entry in manifest["compiled"] if entry["file"] == file]
    key = entry["uri"].removeprefix("s3://test/")
    archive.objects[key] += b" "
    # A trusted new manifest can still carry an unreviewed definition.
    entry["sha256"] = publish.sha256(archive.objects[key])
    pin = repin_retained_manifest(archive, pin, manifest)
    assert retained_calculation.resolve(archive, pin) == 0
    with pytest.raises(ValueError, match="unreviewed native cost definition"):
        retained_calculation.resolve_native_cost(archive, pin, definition=definition, provider="shop", currency="EUR")


@pytest.mark.parametrize("relation,rows,reason", [
    ("item_merchant", None, "missing complete historical item_merchant"),
    ("item_merchant", [], "historical item_merchant does not match"),
    ("item_merchant", [["i0", "shop"], ["i0", "another"]], "historical item_merchant does not match"),
    ("merchant_currency", None, "missing complete historical merchant_currency"),
    ("merchant_currency", [], "historical merchant_currency does not match"),
    ("merchant_currency", [["shop", "USD"]], "historical merchant_currency does not match"),
    ("merchant_currency", [["shop", "EUR", "extra"]], "historical merchant_currency does not match"),
    ("merchant_currency", [["shop", "EUR"], ["shop", "USD"]], "historical merchant_currency does not match"),
    ("merchant_currency", [["shop", "EUR"], ["shop", "EUR"]], "malformed_snapshot"),
])
def test_retained_native_cost_rejects_unproven_unit(retained_native_cost, relation, rows, reason):
    archive, pin, manifest, definition = retained_native_cost
    [entry] = [entry for entry in manifest["snapshots"] if entry["relation"] == relation]
    if rows is None:
        manifest["snapshots"].remove(entry)
    else:
        replace_retained_object(archive, entry, [{"key": row} for row in rows])
    pin = repin_retained_manifest(archive, pin, manifest)
    with pytest.raises(ValueError, match=reason):
        retained_calculation.resolve_native_cost(archive, pin, definition=definition, provider="shop", currency="EUR")


def test_retained_calculation_replays_the_derived_input_witness(retained_epoch):
    archive, pin, manifest = retained_epoch
    [entry] = manifest["witnesses"]
    key = entry["uri"].removeprefix("s3://test/")
    replace_retained_object(archive, entry, {**json.loads(archive.get(key)), "witnesses": []})
    with pytest.raises(ValueError, match="unproven_premise"):
        retained_calculation.resolve(archive, repin_retained_manifest(archive, pin, manifest))


def test_retained_calculation_rechecks_sealed_inputs(retained_epoch):
    archive, pin, manifest = retained_epoch
    [entry] = [e for e in manifest["compiled"] if e["file"] == "ir/rules.json"]
    rules_doc = json.loads(archive.get(entry["uri"].removeprefix("s3://test/")))
    rules_doc["seals"] = [
        {"kind": "run", "period": "run__month", "tables": ["run__month"], "row_sha256": "run__row_sha256",
         "closed_until": "period_close__closed_until", "covers": "period_close__covers",
         "element": "closed_run__element", "sha256": "closed_run__sha256",
         "refused": "run__refused", "accepted": "run__accepted"},
    ]
    tables = [
        ("run", 1, [("i0",)]),
        ("run__month", 2, [("i0", "2026-10-01")]),
        ("run__row_sha256", 2, [("i0", canonical_sha256({"run__month": ["2026-10-01"]}))]),
        ("period_close__closed_until", 2, [("close", "2026-11-01")]),
        ("period_close__covers", 2, []),
        ("closed_run__element", 2, []),
        ("closed_run__sha256", 2, []),
        ("run__refused", 2, []),
        ("run__accepted", 1, [("i0",)]),
    ]
    for name, arity, rows in tables:
        rules_doc["relations"].append(relation(name, "base", arity))
        snapshot = {"relation": name, "role": "checker", "complete": True, "format": "json",
                    "uri": archive.uri(f"toy/m-1/checker/relations/{name}.json")}
        replace_retained_object(archive, snapshot, [{"key": list(row)} for row in rows])
        manifest["snapshots"].append(snapshot)
    rules_doc["rules"][0]["body"].append(lit("run__accepted", "?x"))
    [proof_entry] = manifest["witnesses"]
    proof = json.loads(archive.get(proof_entry["uri"].removeprefix("s3://test/")))
    proof["witnesses"][0]["premises"].append({"row": ref("run__accepted", "i0"), "polarity": "positive", "stratum": 0})
    replace_retained_object(archive, entry, rules_doc)
    replace_retained_object(archive, proof_entry, proof)

    with pytest.raises(ValueError, match="seal_mismatch"):
        retained_calculation.resolve(archive, repin_retained_manifest(archive, pin, manifest))


def test_retained_calculation_rechecks_calc_bindings(retained_epoch):
    archive, pin, manifest = retained_epoch
    [entry] = [e for e in manifest["compiled"] if e["file"] == "ir/rules.json"]
    rules_doc = json.loads(archive.get(entry["uri"].removeprefix("s3://test/")))
    rules_doc["relations"].append(relation(pin.relation, "calc", 4))
    replace_retained_object(archive, entry, rules_doc)

    with pytest.raises(ValueError, match="expected one open, typed input"):
        retained_calculation.resolve(archive, repin_retained_manifest(archive, pin, manifest))


def test_retained_calculation_needs_the_exact_immutable_head(retained_epoch):
    archive, pin, _ = retained_epoch
    old_head = pointers.head_key(pin.pack, pin.epoch)
    archive.objects[old_head] = archive.objects[pointers.head_key(pin.pack, 3)]
    with pytest.raises(ValueError, match="retained head does not match"):
        retained_calculation.resolve(archive, pin)
    del archive.objects[old_head]
    with pytest.raises(ValueError, match="retained object missing"):
        retained_calculation.resolve(archive, pin)


@pytest.mark.parametrize("uri,error", [
    ("s3://elsewhere/toy/bundles/rules.json", "leaves the pinned store"),
    ("s3://test/other/bundles/rules.json", "leaves the pinned store"),
    ("s3://test/toy/../other/bundles/rules.json", "invalid retained object key"),
])
def test_retained_calculation_rejects_out_of_scope_uris(retained_epoch, uri, error):
    archive, pin, manifest = retained_epoch
    [rule_ir] = [entry for entry in manifest["compiled"] if entry["file"] == "ir/rules.json"]
    rule_ir["uri"] = uri
    with pytest.raises(ValueError, match=error):
        retained_calculation.resolve(archive, repin_retained_manifest(archive, pin, manifest))


def test_untyped_may_read_and_untyped_relations_are_refused(tmp_path):
    with pytest.raises(ValueError, match="three columns"):
        guest(epoch(rows={**epoch().rows, "may_read": [("guest", "a")]}))
    with pytest.raises(ValueError, match="no kind per column"):
        guest(epoch(rows={**epoch().rows, "extra": [("a",)]}))
    # A relation that no table, rule or calculation accounts for is never published, for no role.
    with pytest.raises(publish.Blocked, match="no definition accounts for: extra"):
        publish.publish(epoch(rows={**epoch().rows, "extra": [("a",)]}), store.FileStore(tmp_path / "x"), ROLES)


def test_a_release_is_refused_until_it_is_built():
    """O8 stays the default: a rule IR with a delimited release is refused, not published."""
    e = epoch(full=True)
    rules = json.loads(e.rules)
    next(r for r in rules["relations"] if r["role"] == "derived")["release"] = [{"role": "guest"}]
    with pytest.raises(ValueError, match="release is not supported yet"):
        guest(dataclasses.replace(e, rules=json.dumps(rules)))


def guest(e):
    """The guest's rows, witness set and full relations, without publishing (the checker is not asked)."""
    rows, instances = publish.frozen(e)
    return access.for_role(rows, e.kinds, e.parents, e.columns, json.loads(e.rules), instances, "guest")


TREE = {
    "format": "rezono.rules/1",
    "relations": [relation(n, "base", 1) for n in ("top", "mid", "leaf", "role")]
    + [relation("top_grant", "base", 2), relation("leaf_grant", "base", 2), relation("may_read", "derived", 3)],
    "rules": [
        rule("gt", ("may_read", "?r", "top", "?x"), [lit("top_grant", "?x", "?r")]),
        rule("gl", ("may_read", "?r", "leaf", "?x"), [lit("leaf_grant", "?x", "?r")]),
    ],
}


def inheritance_epoch() -> Epoch:
    """O7: top > mid > leaf, with a right on top(x) and one on leaf(y). Also published for the gate's tests."""
    tree_bundle = bundle(
        {"top", "mid", "leaf", "role"}, {"mid": "top", "leaf": "mid"},
        attributes=[
            {"id": "top.top_grant", "kind": "top", "name": "top_grant", "table": "top_grant"},
            {"id": "leaf.leaf_grant", "kind": "leaf", "name": "leaf_grant", "table": "leaf_grant"},
        ],
    )
    return dataclasses.replace(
        epoch(), kinds=frozenset({"top", "mid", "leaf", "role"}), parents={"mid": "top", "leaf": "mid"},
        columns={"top": ("top",), "mid": ("mid",), "leaf": ("leaf",), "role": ("role",),
                 "top_grant": ("top", None), "leaf_grant": ("leaf", None)},
        rows={"top": [("x",), ("y",)], "mid": [("x",), ("y",)], "leaf": [("x",), ("y",)], "role": [],
              "top_grant": [("x", "guest")], "leaf_grant": [("y", "guest")],
              "may_read": [("guest", "top", "x"), ("guest", "leaf", "y")]},
        witnesses=[
            witness("may_read", ("guest", "top", "x"), "gt", [("r", "guest"), ("x", "x")],
                    premises=[("top_grant", ("x", "guest"))]),
            witness("may_read", ("guest", "leaf", "y"), "gl", [("r", "guest"), ("x", "y")],
                    premises=[("leaf_grant", ("y", "guest"))]),
        ],
        rules=json.dumps(TREE),
        bundle=tree_bundle,
        check_metadata=loaded(tree_bundle))


def test_a_right_on_a_kind_holds_for_its_subkinds_on_every_level(tmp_path):
    """O7 through the publisher: top > mid > leaf. A right on top(x) reads leaf(x); a right on leaf(y)
    does not read top(y). A full right on top makes leaf full."""
    ir = TREE
    e = inheritance_epoch()
    s, _ = published(e, tmp_path)
    assert keys(s, "guest", "top") == [["x"]] and keys(s, "guest", "mid") == [["x"]]
    assert keys(s, "guest", "leaf") == [["x"], ["y"]]
    full = {**ir, "rules": [
        rule("g", ("may_read", "?r", "top", "?x"), [lit("role", "?r"), lit("top", "?x")])]}
    e = dataclasses.replace(e, rows={**e.rows, "role": [("guest",)], "may_read": [("guest", "top", "x"), ("guest", "top", "y")]},
                            rules=json.dumps(full))
    _, _, scope = guest(e)
    assert {"top", "mid", "leaf"} <= scope


@pytest.mark.parametrize("parents", [{"mid": "nowhere"}, {"top": "mid", "mid": "top"}])
def test_a_broken_parent_chain_is_refused(parents):
    with pytest.raises(ValueError, match="parent|cycle"):
        access.ancestors(frozenset({"top", "mid"}), parents)


def test_relation_named_like_the_witness_file_does_not_collide(tmp_path):
    e = epoch()
    doc = json.loads(e.bundle)
    doc["attributes"] = [*doc.get("attributes", []), {"id": "node.witnesses", "kind": "node", "name": "witnesses", "table": "witnesses"}]
    updated = json.dumps(doc, sort_keys=True, separators=(",", ":")) + "\n"
    _, m = published(dataclasses.replace(e, rows={**e.rows, "witnesses": [("a", "v")]},
                                         columns={**COLUMNS, "witnesses": ("node", None)},
                                         bundle=updated, check_metadata=metadata.expected(doc)), tmp_path)
    # An object's key is the hash of its bytes, so a name cannot collide; one uri, one content.
    named = {(x["uri"], x["sha256"]) for x in m["snapshots"] + m["witnesses"]}
    assert len(named) == len({u for u, _ in named})
    assert all(u.endswith(f"/toy/objects/{h}.json") for u, h in named)


class Interrupted(Exception):
    pass


class Flaky:
    """A store that fails after n writes: a crash or a lost connection in the middle of a publication."""

    def __init__(self, inner, n):
        self.inner, self.n = inner, n

    def __getattr__(self, name):
        return getattr(self.inner, name)

    def put_new(self, key, data):
        if self.n == 0:
            raise Interrupted(key)
        self.n -= 1
        self.inner.put_new(key, data)


@pytest.mark.parametrize("n", [0, 1, 5, 12])
def test_interrupted_publication_shows_nothing_and_resumes(tmp_path, n):
    clean = store.FileStore(tmp_path / "clean")
    publish.publish(epoch(), clean, ROLES)
    s = store.FileStore(tmp_path / "s")
    with pytest.raises(Interrupted):
        publish.publish(epoch(), Flaky(s, n), ROLES)
    assert s.list("toy/manifests/") == [], "no manifest before every file is written"
    publish.publish(epoch(), s, ROLES)
    assert s.list("") == clean.list("") and all(s.get(k) == clean.get(k) for k in clean.list(""))


class Slow:
    """A store whose put waits, as a put to R2 waits on its round trip; it counts the puts in flight."""

    def __init__(self, inner, wait=0.02):
        import threading

        self.inner, self.wait, self.lock = inner, wait, threading.Lock()
        self.flight = self.most = 0
        self.uri, self.get, self.list = inner.uri, inner.get, inner.list

    def put_new(self, key, data):
        import time

        with self.lock:
            if "/manifests/" in key:
                assert self.flight == 0, "the manifest goes after every file"
            self.flight += 1
            self.most = max(self.most, self.flight)
        time.sleep(self.wait)
        self.inner.put_new(key, data)
        with self.lock:
            self.flight -= 1


def test_the_files_are_written_concurrently_and_the_manifest_after_them(tmp_path):
    """Promote 07-11: a put to R2 takes ~0.2 s, so one after the other the lab's 526 took most of the job."""
    clean = store.FileStore(tmp_path / "clean")
    publish.publish(epoch(), clean, ROLES)
    s = Slow(store.FileStore(tmp_path / "s"))
    publish.publish(epoch(), s, ROLES)
    assert s.most > 1
    assert s.list("") == clean.list("") and all(s.get(k) == clean.get(k) for k in clean.list(""))


def test_a_conflict_among_concurrent_writes_stops_before_the_manifest(tmp_path):
    s = store.FileStore(tmp_path)
    changed = epoch(salaries=[(SECRET, "999")])
    files, _ = publish.plan(changed, s, ROLES)
    s.put_new(files[len(files) // 2][0], b"other bytes")  # a key that holds other bytes than its hash names
    with pytest.raises(store.Conflict):
        publish.publish(changed, s, ROLES)
    assert s.list("toy/manifests/") == []


def test_publishing_again_is_a_no_op_and_a_change_conflicts(tmp_path):
    s = store.FileStore(tmp_path)
    first = publish.publish(epoch(), s, ROLES)
    assert publish.publish(epoch(), s, ROLES) == first
    changed = epoch(salaries=[(SECRET, "999")])
    with pytest.raises(store.Conflict):
        publish.publish(changed, s, ROLES)


def test_same_epoch_gives_same_bytes(tmp_path):
    a, b = store.FileStore(tmp_path / "a"), store.FileStore(tmp_path / "b")
    publish.publish(epoch(), a, ROLES)
    shuffled = epoch(rows={k: list(reversed(v)) for k, v in epoch().rows.items()},
                     witnesses=list(reversed(epoch().witnesses)))
    publish.publish(shuffled, b, ROLES)
    assert a.list("") == b.list("")
    assert all(a.get(k) == b.get(k) for k in a.list(""))


def test_proposal_has_its_own_id_and_base(tmp_path):
    m = publish.publish(epoch(proposal="42", base_manifest="m-1"), store.FileStore(tmp_path), ROLES)
    assert (m["id"], m["proposal"], m["base_manifest"]) == ("p-42-1", "42", "m-1")


def test_unknown_access_mode_is_refused(tmp_path):
    with pytest.raises(ValueError):
        publish.publish(epoch(), store.FileStore(tmp_path), {"guest": "everything"})


# Images: the bundle binds node.image (table node__image) as the node's image.
def svg(name):
    return f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1 1"><title>{name}</title></svg>'.encode()


def with_images(e, named, objects=None):
    """The epoch with an image cell per node in `named` (node -> file) and every file listed in assets/."""
    data = {f: svg(f) for f in sorted(set(named.values()))} | (objects or {})
    assets = {f: {"sha256": hashlib.sha256(b).hexdigest(), "media_type": "image/svg+xml",
                  "source": f"example/x@0123abc:{f}", "licence": "CC0-1.0", "bytes": b} for f, b in data.items()}
    doc = json.loads(e.bundle)
    doc = doc | {"attributes": [*doc.get("attributes", []), {"id": "node.image", "kind": "node", "name": "image", "table": "node__image"}],
                 "channels": {"images": [{"kind": "node", "slot": "node.image"}]}}
    return dataclasses.replace(e, rows=dict(e.rows, node__image=sorted(named.items())),
                               columns=dict(e.columns, node__image=("node", None)), assets=assets,
                               bundle=json.dumps(doc, sort_keys=True, separators=(",", ":")) + "\n",
                               check_metadata=metadata.expected(doc))


def index(s, role, mid="m-1"):
    return json.loads(object_bytes(s, role, "assets.json", mid))


def test_a_role_gets_only_the_images_its_rows_name(tmp_path):
    s, m = published(with_images(epoch(), {"a": "images/a.svg", SECRET: "images/secret.svg"}), tmp_path)
    assert [x["file"] for x in index(s, "guest")] == ["images/a.svg"]
    assert [x["file"] for x in index(s, "checker")] == ["images/a.svg", "images/secret.svg"]
    for x in index(s, "checker"):
        assert s.get(f"toy/assets/{x['sha256']}") == svg(x["file"])
        assert x["source"] and x["licence"] == "CC0-1.0"
    assert [a["role"] for a in m["assets"]] == ["checker", "guest"]
    assert {"name": publish.ASSETS, "status": "green", "violations": 0} in m["checks"]
    assert SECRET.encode() not in object_bytes(s, "guest", "assets.json")


def test_without_an_image_binding_the_manifest_has_no_assets(tmp_path):
    _, m = published(epoch(), tmp_path)
    assert "assets" not in m and publish.ASSETS not in {c["name"] for c in m["checks"]}


def test_non_interference_hidden_images_change_no_byte_of_the_guest(tmp_path):
    """The paired fixture: more hidden nodes with images give the guest the same bytes."""
    a, ma = published(with_images(epoch(), {"a": "images/a.svg"}), tmp_path / "a")
    b, mb = published(with_images(epoch_with_hidden(), {"a": "images/a.svg", HIDDEN: "images/hidden.svg"}), tmp_path / "b")
    guest = role_keys(a)
    assert guest == role_keys(b)
    assert [k for k in guest if a.get(k) != b.get(k)] == []
    assert [x for x in ma["assets"] if x["role"] == "guest"] == [x for x in mb["assets"] if x["role"] == "guest"]


@pytest.mark.parametrize("named, objects, reason", [
    ({"a": "images/unlisted.svg"}, {"images/other.svg": svg("other")}, "does not list"),
    ({"a": "images/a.svg"}, {"images/a.svg": b'<svg xmlns="http://www.w3.org/2000/svg"><script>x</script></svg>'}, "asset_unsafe"),
    ({"a": "images/a.svg"}, {"images/a.svg": b'<svg xmlns="http://www.w3.org/2000/svg"><use href="https://x/y.svg#a"/></svg>'}, "asset_unsafe"),
])
def test_an_unlisted_or_unsafe_image_blocks_and_writes_nothing(tmp_path, named, objects, reason):
    e = with_images(epoch(), named, objects)
    if reason == "does not list":
        e = dataclasses.replace(e, assets={k: v for k, v in e.assets.items() if k != "images/unlisted.svg"})
    s = store.FileStore(tmp_path)
    with pytest.raises(publish.Blocked, match=f"{publish.ASSETS}.*{reason}"):
        publish.publish(e, s, ROLES)
    assert s.list("") == []


def test_an_index_from_rows_the_role_does_not_get_blocks(tmp_path, monkeypatch):
    """Fault injection (P1 review of B10): the publisher builds the guest's index from the complete rows, so it
    lists the hidden node's image beside a guest snapshot without that row. The checker derives the named
    files from the guest's published snapshot bytes itself, so it refuses, and nothing is written."""
    original = publish.assets_of

    def injected(e, store_, role, rows, data, *rest):
        return original(e, store_, role, e.rows, data, *rest)

    monkeypatch.setattr(publish, "assets_of", injected)
    e = with_images(epoch(), {"a": "images/a.svg", SECRET: "images/secret.svg"})
    s = store.FileStore(tmp_path)
    with pytest.raises(publish.Blocked, match=f"{publish.ASSETS}: role guest: .*asset_not_named images/secret.svg"):
        publish.publish(e, s, ROLES)
    assert s.list("") == []


def test_a_role_that_reads_a_part_not_in_full_gets_no_seal_status():
    """O8 for a seal with parts (docs/compiler.md#parts): whether a run is refused or accepted, and so whether
    each of its steps counts, depends on all its steps. A role reads that status, and what rests on it, only if
    it reads every part kind in full by the read rules; otherwise it gets none of it, whatever the data."""
    seal = {"kind": "run", "period": "run__month", "row_sha256": "run__row_sha256", "tables": ["run__month"],
            "closed_until": "period_close__closed_until", "covers": "period_close__covers",
            "element": "closed_run__element", "sha256": "closed_run__sha256", "refused": "run__refused",
            "accepted": "run__accepted",
            "parts": [{"kind": "step", "arrow": "step__run", "owner": "run", "tables": ["step__run"],
                       "accepted": "step__accepted"}]}
    full = lambda kind: rule(f"r-{kind}", ("may_read", "?r", kind, "?x"), [lit("role", "?r"), lit(kind, "?x")])
    doc = {"format": "rezono.rules/1", "pack": "toy", "seals": [seal],
           "relations": [relation(n, "base", a) for n, a in (("run", 1), ("step", 1), ("role", 1), ("run__month", 2),
                                                               ("step__run", 2), ("step__label", 2), ("run__row_sha256", 2),
                                                               ("run__refused", 2), ("run__accepted", 1),
                                                               ("step__accepted", 1))]
           + [relation("may_read", "derived", 3), relation("counted", "derived", 1)],
           "rules": [full("run"), full("role"),
                     # guest reads a step only on a condition (its label): not in full, and s2 is hidden from it
                     rule("r-step-guest", ("may_read", "guest", "step", "?x"), [lit("step__label", "?x", "open")]),
                     rule("r-step-host", ("may_read", "host", "step", "?x"), [lit("step", "?x")]),
                     rule("c", ("counted", "?x"), [lit("step__accepted", "?x"), lit("step__run", "?x", "?y")])]}
    grants = [(r, k, x) for r in ("guest", "host") for k, x in (("run", "r1"), ("role", "guest"), ("role", "host"),
                                                               ("step", "s1"))] + [("host", "step", "s2")]
    rows = {"run": [("r1",)], "step": [("s1",), ("s2",)], "role": [("guest",), ("host",)],
            "run__month": [("r1", "2026-10-01")], "step__run": [("s1", "r1"), ("s2", "r1")],
            "step__label": [("s1", "open"), ("s2", "hidden")], "run__row_sha256": [("r1", "h")], "run__refused": [],
            "run__accepted": [("r1",)], "step__accepted": [("s1",), ("s2",)], "may_read": grants, "counted": [("s1",)]}
    columns = {"run": ("run",), "step": ("step",), "role": ("role",), "run__month": ("run", None),
               "step__run": ("step", "run"), "step__label": ("step", None), "run__row_sha256": ("run", None),
               "run__refused": ("run", "period_close"), "run__accepted": ("run",), "step__accepted": ("step",)}
    kinds, parents = ["run", "step", "role", "period_close"], {}
    instances = [witness("counted", ["s1"], "c", [("x", "s1"), ("y", "r1")],
                         premises=[("step__accepted", ["s1"]), ("step__run", ["s1", "r1"])]),
                 *[witness("may_read", list(g), "r-x", []) for g in grants]]
    for role, sees in (("host", True), ("guest", False)):
        readable, _, in_full = access.for_role(rows, kinds, parents, columns, doc, instances, role)
        for rel in ("run__accepted", "step__accepted", "run__row_sha256"):
            assert bool(readable[rel]) == sees, (role, rel)
            assert (rel in in_full) == sees, (role, rel)
        assert readable["counted"] == ([("s1",)] if sees else []), role
        # The parts themselves stay as their read rules say: the guest reads s1, never the hidden s2.
        assert readable["step__run"] == ([("s1", "r1"), ("s2", "r1")] if sees else [("s1", "r1")]), role


# Against a base (a variant or a proposal): only what differs from the base manifest is written.
def resolved(s, m):
    """Every file a manifest names, by what it is for, as the gate reads it: by its uri, checked by its hash."""
    out = {}
    for what, xs in (("relations", m["snapshots"]), ("witnesses", m["witnesses"]), ("assets", m.get("assets", [])),
                     ("compiled", m.get("compiled", [])), ("build", [m["build"]] if "build" in m else [])):
        for x in xs:
            data = s.get(x["uri"].removeprefix("s3://rezono/"))
            assert publish.sha256(data) == x["sha256"], x["uri"]
            out[(what, x.get("role"), x.get("relation") or x.get("file"))] = data
    return out


def without_uris(m):
    return json.loads(json.dumps(m, sort_keys=True).replace("p-42-2/", "X/").replace("m-1/", "X/"))


@pytest.mark.parametrize("named", [{"a": "images/a.svg"}, {"a": "images/b.svg"}])
def test_against_its_base_only_what_differs_is_written_and_a_role_reads_the_same_bytes(tmp_path, named):
    s, base = published(with_images(epoch(), {"a": "images/a.svg"}), tmp_path / "s")
    before = set(s.list(""))
    e = dataclasses.replace(with_images(epoch(), named), epoch=2, proposal="42", base_manifest="m-1")
    files, planned = publish.plan(e, s, ROLES, base=base)
    m = publish.publish(e, s, ROLES, base=base)
    assert m == planned
    # The same manifest and the same bytes per role as a publication without a base, in another store.
    alone = store.FileStore(tmp_path / "alone")
    publish.publish(with_images(epoch(), {"a": "images/a.svg"}), alone, ROLES)
    m_alone = publish.publish(e, alone, ROLES)
    assert without_uris(m) == without_uris(m_alone)
    assert resolved(s, m) == resolved(alone, m_alone)
    # Written: the manifest and its pointer, and per role only what the change touched.
    new = sorted(set(s.list("")) - before)
    changed = {"toy/assets/" + hashlib.sha256(svg("images/b.svg")).hexdigest()} if named["a"] != "images/a.svg" else set()
    if changed:
        changed |= {x["uri"].removeprefix(s.uri("")) for x in m["snapshots"] + m["assets"]
                    if x.get("relation") == "node__image" or x in m["assets"]}
    assert [k for k in new if "/manifests/" not in k and "/bases/" not in k and "/epochs/" not in k] == sorted(changed)
    unchanged = []
    for section in ("snapshots", "witnesses", "assets"):
        old = {(x["role"], x.get("relation")): x for x in base[section]}
        for x in m[section]:
            previous = old[(x["role"], x.get("relation"))]
            key = x["uri"].removeprefix(s.uri(""))
            if x["sha256"] == previous["sha256"]:
                assert x["uri"] == previous["uri"] and key not in dict(files)
                unchanged.append(x["uri"])
            else:
                assert x["uri"] != previous["uri"] and key in dict(files)
    assert unchanged


def test_the_base_must_be_the_epochs_base_manifest(tmp_path):
    s, base = published(epoch(), tmp_path)
    e = dataclasses.replace(epoch(), epoch=2, proposal="42", base_manifest="m-0")
    with pytest.raises(ValueError, match="not the epoch's base manifest"):
        publish.publish(e, s, ROLES, base=base)


def test_a_diagnosis_needs_the_bundles_check_metadata(tmp_path):
    """A red variant read with switched-off checks would under-report; it is refused too."""
    e = dataclasses.replace(epoch(), variant={"sweep": "s", "index": 1}, base_manifest="m-1",
                            checks=[{"name": "node__unique", "status": "red", "violations": 1}])
    meta = {t: rs for t, rs in e.check_metadata.items() if t != "rezono__required"}
    s = store.FileStore(tmp_path)
    with pytest.raises(publish.Blocked, match="check_metadata"):
        publish.diagnose(dataclasses.replace(e, check_metadata=meta), s)
    assert s.list("") == []
    publish.diagnose(e, s)  # the bundle's own metadata: written


@pytest.mark.parametrize("entry", ["plan", "publish", "diagnose"])
@pytest.mark.parametrize("flag", [True, "false", None, 0, 1])
def test_theory_or_untyped_epoch_cannot_reach_any_store_method(entry, flag):
    class NoStore:
        def __getattr__(self, name):
            pytest.fail(f"publication touched the store before refusing the theory: {name}")

    e = epoch(theory=flag)
    with pytest.raises(publish.Blocked, match="theory"):
        if entry == "diagnose":
            publish.diagnose(e, NoStore())
        else:
            getattr(publish, entry)(e, NoStore(), ROLES)


def test_internal_theory_default_preserves_ordinary_publication(tmp_path):
    e = epoch()
    assert e.theory is False
    s, m = published(e, tmp_path)
    assert "theory" not in m
    assert s.list("")


def test_batch_refuses_theory_before_compilation_or_engine_work(tmp_path, monkeypatch):
    import shutil
    from pathlib import Path
    import duckdb
    import yaml
    from rezono_compiler import emit
    from rezono_publisher import batch

    source = Path(__file__).resolve().parents[3] / "compiler/tests/fixtures/minimal"
    target = Path(shutil.copytree(source, tmp_path / "theory"))
    meta = yaml.safe_load((target / "pack.yaml").read_text(encoding="utf-8"))
    (target / "pack.yaml").write_text(yaml.safe_dump(meta | {"theory": True}), encoding="utf-8")

    def forbidden(*args, **kwargs):
        pytest.fail("theory publication reached compilation or the engine")

    monkeypatch.setattr(emit, "compile_pack", forbidden)
    monkeypatch.setattr(duckdb, "connect", forbidden)
    with pytest.raises(publish.Blocked, match="theory"):
        batch.epoch(target, epoch=1, knowledge_time="2026-01-01T00:00:00Z", sources=[])
