"""Property tests on generated worlds: valid proofs are accepted, each fault is rejected with its own reason.

A world is generated as a spec (facts and derivation steps), realized into rows, rules and witnesses,
and serialized into the checker's input: a proof, a manifest with JSON snapshots, and rule definitions.
Every step gets its own rule, generalised from the step's values, so the rules fit the witnesses by
construction. Faults are injected into the realized world. Aggregates are computed here from
formal.md §6, not with the checker's code. Nothing here knows an example.
"""

import copy
import hashlib
import json
from fractions import Fraction

import pytest
from hypothesis import assume, given
from hypothesis import strategies as st

from rezono_checker import check, render
from rezono_checker.rules import load_rules

PRESENT = ["c0", "c1", "c2"]  # may occur in the negated relation
ABSENT = ["c3", "c4", "c5"]  # never occur in it
CONSTANTS = PRESENT + ABSENT
STATES = ["known", "known", "unknown", "not_applicable"]  # invalid input is a fault, see below
FUNCTIONS = ["count", "sum", "min", "max"]
SHAPES = ["value", "amount", "quantity", "ratio"]  # the classes of contracts/value.yaml
SECRET = "s3cret"  # role r never reads a row that contains it


def text(state, v):
    if state != "known":
        return state
    v = Fraction(v)
    return f"known:{v.numerator}" if v.denominator == 1 else f"known:{v.numerator}/{v.denominator}"


def key(parts):
    return json.dumps(list(parts), separators=(",", ":"))


def reference(function, cells):
    """formal.md §6: strict in unknown, blocks on invalid, not_applicable does not count."""
    if function == "count":
        return f"known:{len(cells)}"
    states = {s for s, _ in cells}
    if "invalid" in states:
        return "invalid"
    if "unknown" in states:
        return "unknown"
    known = [v for s, v in cells if s == "known"]
    if function == "sum":
        return text("known", sum(known))
    return text("known", (min if function == "min" else max)(known)) if known else "not_applicable"


def aggregate(weights, x, function):
    members = {k: v for k, v in weights.items() if k[0] == x}
    entries = [[key(k)] if function == "count" else [key(k), text(*v)] for k, v in sorted(members.items())]
    digest = hashlib.sha256(json.dumps(entries, separators=(",", ":"), sort_keys=True).encode()).hexdigest()
    return {"x": x, "function": function, "count": len(members),
            "result": reference(function, list(members.values())), "contributors": digest}


@st.composite
def worlds(draw):
    shape = draw(st.sampled_from(SHAPES))
    facts = {"f0": set(), "f1": set(), "n0": {(c,) for c in draw(st.sets(st.sampled_from(PRESENT)))}}
    weights = {}
    for x in PRESENT:
        for i in range(draw(st.integers(0, 3))):
            n = draw(st.integers(-50, 50))
            weights[(x, f"m{i}")] = (draw(st.sampled_from(STATES)),
                                     Fraction(n, draw(st.integers(1, 6))) if shape == "ratio" else n)
    steps = []
    for j in range(draw(st.integers(1, 5))):
        body = []
        for _ in range(draw(st.integers(1 if j == 0 else 0, 2))):
            rel = draw(st.sampled_from(["f0", "f1"]))
            row = tuple(draw(st.sampled_from(CONSTANTS)) for _ in range(1 if rel == "f0" else 2))
            facts[rel].add(row)
            body.append([rel, row, "positive", 0])
        if j > 0:
            body.append([steps[-1]["rel"], steps[-1]["key"], "positive", 1])
        if j == 0 or draw(st.booleans()):
            body.append(["n0", (draw(st.sampled_from(ABSENT)),), "negative", 0])
        agg = None
        if j == 0 or draw(st.booleans()):
            agg = aggregate(weights, draw(st.sampled_from(PRESENT)), draw(st.sampled_from(FUNCTIONS)))
        pool = sorted({v for _, row, _, _ in body for v in row} | ({agg["x"], agg["result"]} if agg else set()))
        head = draw(st.lists(st.tuples(st.sampled_from(pool), st.booleans()), min_size=1, max_size=3))
        steps.append({"rel": f"d{j}", "key": tuple(v for v, _ in head), "const": [c for _, c in head],
                      "body": body, "agg": agg})
    return {"facts": facts, "weights": weights, "steps": steps,
            "hidden": draw(st.sets(st.integers(0, len(steps) - 2))) if len(steps) > 1 else set(),
            "order": draw(st.permutations(range(len(steps)))), "filtered": draw(st.booleans()), "shape": shape}


def realize(spec):
    rows = {rel: set(r) for rel, r in spec["facts"].items()}
    rules, witnesses = [], []
    for j, s in enumerate(spec["steps"]):
        rows.setdefault(s["rel"], set()).add(s["key"])
        agg = s["agg"]
        # Range restriction: what a negation reads, the group of an aggregate and the head are bound by a positive
        # premise (the head also by the aggregate's result). Where the step has none for a value, it gets a fact
        # of its own.
        body = list(s["body"])
        positive = {v for _, row, pol, _ in body if pol == "positive" for v in row}
        read = {v for _, row, pol, _ in body if pol == "negative" for v in row} | set(s["key"])
        read = (read | {agg["x"]}) - {agg["result"]} if agg else read
        for v in sorted(read - positive):
            rows.setdefault("dom", set()).add((v,))
            body.append(["dom", (v,), "positive", 0])
        values = sorted({v for _, row, _, _ in body for v in row} | set(s["key"]))
        var = {v: f"?v{i}" for i, v in enumerate(values)}
        if agg:
            var[agg["result"]] = "?agg"
        rule = {"id": f"r{j}", "stratum": 1,
                "head": {"relation": s["rel"], "terms": [v if c else var[v] for v, c in zip(s["key"], s["const"])]},
                "body": [{"relation": rel, "terms": [var[v] for v in row], "polarity": pol, "stratum": stratum}
                         for rel, row, pol, stratum in body]}
        used = {t for atom in [rule["head"], *rule["body"]] for t in atom["terms"]} | ({var[agg["x"]], "?agg"} if agg else set())
        witness = {"conclusion": {"relation": s["rel"], "key": key(s["key"])}, "rule_id": f"r{j}",
                   "bindings": [{"variable": n, "value": v} for v, n in sorted(var.items()) if n in used],
                   "premises": [{"row": {"relation": rel, "key": key(row)}, "polarity": pol, "stratum": stratum}
                                for rel, row, pol, stratum in body]}
        if agg:
            rule["aggregates"] = [{"relation": "g0", "terms": [var[agg["x"]], "_"], "function": agg["function"],
                                   "over": "v", "as": "?agg", "stratum": 0}]
            witness["aggregates"] = [{"relation": "g0", "group_key": key([agg["x"]]), "count": agg["count"],
                                      "contributors_sha256": agg["contributors"], "result": agg["result"]}]
        rules.append(rule)
        witnesses.append(witness)
    root = spec["steps"][-1]
    return {"rows": rows, "weights": dict(spec["weights"]), "extra_g0": [], "rules": rules, "witnesses": witnesses,
            "root": {"relation": root["rel"], "key": key(root["key"])}, "order": list(spec["order"]),
            "hidden": [witnesses[j]["conclusion"] for j in sorted(spec["hidden"])], "filtered": spec["filtered"],
            "shape": spec["shape"], "measure": {}}


def serialize(world):
    tables = {rel: [{"key": list(r), "values": {}} for r in sorted(rs)] for rel, rs in world["rows"].items()}
    tables["g0"] = [{"key": list(k), "values": {"v": cell(world, k, s, v)}}
                    for k, (s, v) in sorted(world["weights"].items())] + world["extra_g0"]
    files, snapshots = {}, []

    def publish(rel, role, complete, rows):
        uri = f"{role}/{rel}.json"
        files[uri] = json.dumps(rows).encode()
        snapshots.append({"relation": rel, "role": role, "complete": complete, "uri": uri,
                          "sha256": hashlib.sha256(files[uri]).hexdigest(), "format": "json"})

    for rel, rows in sorted(tables.items()):
        publish(rel, "all", True, rows)
        if world["filtered"] and rel != "n0":  # role r sees half of each relation, none of n0, no secret
            publish(rel, "r", False, [r for r in rows[::2] if SECRET not in json.dumps(r)])
    manifest = {"id": "m", "snapshots": snapshots, "checks": [{"name": "integrity", "status": "green"}]}
    present = [i for i, w in enumerate(world["witnesses"]) if w is not None]
    order = [i for i in world["order"] if i in present] + [i for i in present if i not in world["order"]]
    proof = {"root": world["root"], "manifest_id": "m", "witnesses": [world["witnesses"][i] for i in order],
             "hidden": world["hidden"]}
    return proof, manifest, {"rules": world["rules"]}, files


def cell(world, k, state, v):
    """One weight in the world's shape; integers as decimal strings."""
    shape, known = world["shape"], state == "known"
    if shape == "amount":
        return {"state": state, "currency": world["measure"].get(k, "EUR"), **({"minor_units": str(v)} if known else {})}
    if shape == "quantity":
        return {"state": state, "unit": world["measure"].get(k, "g"), "scale": 3, **({"minor_units": str(v)} if known else {})}
    if shape == "ratio" and known:
        v = Fraction(v)
        return {"state": state, "numerator": str(v.numerator), "denominator": str(v.denominator)}
    return {"state": state, "value": text(state, v).removeprefix("known:")} if known else {"state": state}


def outcome(world, role=None, mutate=None):
    proof, manifest, rules_doc, files = serialize(world)
    if mutate:
        mutate(proof, manifest, files)
    rules = load_rules(rules_doc)
    report = check(proof, manifest, rules, files.__getitem__, role)
    assert render(report) == render(check(proof, manifest, rules, files.__getitem__, role))
    by = lambda sev: {f["reason"] for f in report["findings"] if f["severity"] == sev}
    return by("error"), by("warning"), report


def errors(world, **kw):
    return outcome(world, **kw)[0]


def spec_world(spec, change):
    spec = copy.deepcopy(spec)
    change(spec)
    return realize(spec)


def world_with(spec, change):
    world = realize(spec)
    change(world)
    return world


# Valid worlds.

@given(worlds())
def test_valid_proofs_are_accepted(spec):
    found, warnings, report = outcome(realize(spec))
    assert (found, warnings, report["valid"]) == (set(), set(), True)


@given(worlds())
def test_filtered_snapshots_do_not_decide(spec):
    """Closed world: only complete snapshots count. A role only filters the report."""
    world = realize(spec)
    world["filtered"] = True
    assert errors(world) == errors(world, role="r") == set()


# The faults of the task.

@given(worlds())
def test_missing_premise(spec):
    def change(w):
        p = w["witnesses"][0]["premises"][0]["row"]
        w["rows"][p["relation"]].discard(tuple(json.loads(p["key"])))
    assert errors(world_with(spec, change)) == {"premise_missing"}


@given(worlds(), st.sampled_from([None, "r"]))
def test_negative_premise_present(spec, role):
    def change(w):
        w["filtered"] = True
        p = next(p for p in w["witnesses"][0]["premises"] if p["polarity"] == "negative")
        w["rows"]["n0"].add(tuple(json.loads(p["row"]["key"])))
    found, _, report = outcome(world_with(spec, change), role=role)
    assert found == {"negative_premise_present"}
    if role:  # n0 is not visible to r: the report names the relation, not the row
        assert all(f.get("screened") and "key" not in f for f in report["findings"])


@given(worlds())
def test_wrong_count(spec):
    assert errors(world_with(spec, lambda w: w["witnesses"][0]["aggregates"][0].update(
        count=w["witnesses"][0]["aggregates"][0]["count"] + 1))) == {"aggregate_count"}


@given(worlds(), st.data())
def test_cycle(spec, data):
    def change(w):
        j = data.draw(st.integers(0, len(w["witnesses"]) - 1))
        root_row = json.loads(w["root"]["key"])
        w["rules"][j]["body"].append({"relation": w["root"]["relation"], "terms": root_row,
                                      "polarity": "positive", "stratum": 1})
        w["witnesses"][j]["premises"].append({"row": dict(w["root"]), "polarity": "positive", "stratum": 1})
    assert errors(world_with(spec, change)) == {"cycle"}


@given(worlds(), st.data())
def test_hash_mismatch(spec, data):
    """A tampered complete snapshot blocks; a tampered role snapshot is a warning (see below)."""
    tampered = []

    def mutate(proof, manifest, files):
        tampered.append(data.draw(st.sampled_from(manifest["snapshots"])))
        tampered[0]["sha256"] = hashlib.sha256(b"tampered").hexdigest()
    found, warnings, _ = outcome(realize(spec), mutate=mutate)
    if tampered[0]["complete"]:
        assert (found, warnings) == ({"snapshot_hash_mismatch"}, set())
    else:
        assert (found, warnings) == (set(), {"role_snapshot_hash_mismatch"})


# Review findings: each test fails without its fix.

@given(worlds())
def test_constants_are_not_variables(spec):
    """Rule p("v") :- f("v") with a binding v -> z must not accept p("z") from f("z")."""
    world = realize(spec)
    j = len(world["witnesses"]) - 1
    rule, w = world["rules"][j], world["witnesses"][j]
    theta = {b["variable"]: b["value"] for b in w["bindings"]}
    derived = {v for p in w["premises"] if p["stratum"] == 1 for v in json.loads(p["row"]["key"])}
    candidates = [v for v in json.loads(w["conclusion"]["key"]) if v not in derived]
    assume(candidates)
    v = candidates[0]
    for atom in [rule["head"], *rule["body"], *rule.get("aggregates", [])]:
        atom["terms"] = [theta[t] if t.startswith("?") else t for t in atom["terms"]]
    rename = lambda k: key(["z" if x == v else x for x in json.loads(k)])
    for ref in [w["conclusion"], world["root"]] + [p["row"] for p in w["premises"] if p["stratum"] == 0]:
        old, ref["key"] = ref["key"], rename(ref["key"])
        if ref["relation"] != "n0":
            world["rows"][ref["relation"]].discard(tuple(json.loads(old)))
            world["rows"][ref["relation"]].add(tuple(json.loads(ref["key"])))
    for p in w["premises"]:  # other witnesses may share the fact rows: keep the originals too
        if p["stratum"] == 0 and p["polarity"] == "positive":
            world["rows"][p["row"]["relation"]].update(
                tuple(json.loads(x["row"]["key"])) for ww in world["witnesses"] for x in ww["premises"]
                if x["row"]["relation"] == p["row"]["relation"])
    w["bindings"].append({"variable": v, "value": "z"})
    assert "unknown_variable" in errors(world)


@given(worlds(), st.data())
def test_screened_step_needs_its_witness(spec, data):
    """A hidden step is a redaction, not a proof: dropping its witness is rejected."""
    assume(len(spec["steps"]) > 1)
    def change(w):
        j = data.draw(st.integers(0, len(w["witnesses"]) - 2))
        w["hidden"].append(w["witnesses"][j]["conclusion"])
        w["witnesses"][j] = None
    assert errors(world_with(spec, change)) == {"unproven_premise", "hidden_without_witness"}


@given(worlds(), st.sampled_from(["negative", "aggregate", "declared", "two_strata"]), st.data())
def test_strata_are_derived(spec, attack, data):
    """Declared strata are checked against the rules; negation and aggregation through recursion fail."""
    rules = realize(spec)["rules"]
    j = data.draw(st.integers(0, len(rules) - 1))
    head = rules[j]["head"]
    if attack == "negative":
        rules[j]["body"].append({"relation": head["relation"], "terms": head["terms"], "polarity": "negative", "stratum": 0})
    elif attack == "aggregate":
        rules[j].setdefault("aggregates", []).append(
            {"relation": head["relation"], "terms": head["terms"], "function": "count", "stratum": 0})
    elif attack == "declared":
        assume(j > 0)
        next(b for b in rules[j]["body"] if b["stratum"] == 1)["stratum"] = 0
    else:
        rules.append({**copy.deepcopy(rules[j]), "id": "again", "stratum": 2})
    with pytest.raises(ValueError):
        load_rules({"rules": rules})


@given(worlds(), st.sampled_from(FUNCTIONS))
def test_bound_underscore_is_not_a_wildcard(spec, function):
    """A value '_' is a value. Wildcard positions come from the rule, not from the bindings."""
    def change(s):
        s["weights"][("_", "m9")] = ("known", 1)
        s["steps"][0]["agg"] = aggregate(s["weights"], "_", function)
        s["steps"][0]["const"] = [c and v != "_" for v, c in zip(s["steps"][0]["key"], s["steps"][0]["const"])]
    world = spec_world(spec, change)
    assert errors(world) == set()


@given(worlds(), st.sampled_from(["sum", "min", "max"]))
def test_invalid_contributor_blocks(spec, function):
    def change(s):  # a fresh group, so no other step aggregates over it
        s["weights"][("c9", "m9")] = ("invalid", 0)
        s["steps"][0]["agg"] = aggregate(s["weights"], "c9", function)
    assert errors(spec_world(spec, change)) == {"invalid_value"}


@given(worlds(), st.sampled_from(["state", "payload", "unit-number", "unit-list", "empty-payload", "reason-prose",
                                  "known-reason"]))
def test_malformed_values_are_rejected(spec, attack):
    bad = {"payload": {"state": "known", "value": 5},
           "unit-number": {"state": "known", "unit": 7, "minor_units": "5"},
           "unit-list": {"state": "known", "unit": [], "minor_units": "5"},
           "empty-payload": {"state": "unknown", "value": ""},
           "reason-prose": {"state": "unknown", "reason": "fact is missing"},
           "known-reason": {"state": "known", "value": "5", "reason": "empty"}}

    def change(w):
        if attack == "state":
            w["weights"][("c0", "m9")] = ("bogus", 0)
        else:
            w["extra_g0"].append({"key": ["c0", "m9"], "values": {"v": bad[attack]}})
    assert errors(world_with(spec, change)) == {"malformed_snapshot"}


@given(worlds())
def test_wrong_result(spec):
    def change(w):
        a = w["witnesses"][0]["aggregates"][0]
        a["result"] = "unknown" if a["result"] != "unknown" else "not_applicable"
    assert errors(world_with(spec, change)) == {"aggregate_result"}


@given(worlds())
def test_wrong_binding(spec):
    world = realize(spec)
    assume("?agg" not in world["rules"][0]["head"]["terms"])
    b = next(b for b in world["witnesses"][0]["bindings"] if b["variable"] == "?agg")
    b["value"] = "unknown" if b["value"] != "unknown" else "not_applicable"
    assert errors(world) == {"aggregate_binding"}


@given(worlds())
def test_unreachable_witness_warns(spec):
    def change(w):
        w["rows"]["f0"].add(("c0",))
        w["rows"]["dx"] = {("c0",)}
        w["rules"].append({"id": "rx", "stratum": 1, "head": {"relation": "dx", "terms": ["?a"]},
                           "body": [{"relation": "f0", "terms": ["?a"], "polarity": "positive", "stratum": 0}]})
        w["witnesses"].append({"conclusion": {"relation": "dx", "key": key(["c0"])}, "rule_id": "rx",
                               "bindings": [{"variable": "?a", "value": "c0"}],
                               "premises": [{"row": {"relation": "f0", "key": key(["c0"])},
                                             "polarity": "positive", "stratum": 0}]})
    found, warnings, report = outcome(world_with(spec, change))
    assert (found, warnings, report["valid"]) == (set(), {"unreachable_witness"}, True)


@given(worlds())
def test_head_mismatch(spec):
    def change(w):
        other = json.loads(w["root"]["key"]) + ["zz"]
        w["rows"][w["root"]["relation"]].add(tuple(other))
        w["root"]["key"] = w["witnesses"][-1]["conclusion"]["key"] = key(other)
    assert errors(world_with(spec, change)) == {"head_mismatch"}


@given(worlds(), st.sampled_from(["red", "other"]))
def test_manifest(spec, attack):
    def mutate(proof, manifest, files):
        if attack == "red":
            manifest["checks"][0]["status"] = "red"
        else:
            proof["manifest_id"] = "other"
    expected = {"manifest_check_red"} if attack == "red" else {"manifest_mismatch"}
    assert errors(realize(spec), mutate=mutate) == expected


@given(worlds(), st.sampled_from(["amount", "quantity", "ratio-numerator", "ratio-denominator"]))
def test_integers_are_decimal_strings(spec, field):
    """minor_units, numerator and denominator travel as decimal strings; a JSON number is rejected."""
    bad = {"amount": {"state": "known", "currency": "EUR", "minor_units": 5},
           "quantity": {"state": "known", "unit": "g", "scale": 3, "minor_units": 5},
           "ratio-numerator": {"state": "known", "numerator": 1, "denominator": "3"},
           "ratio-denominator": {"state": "known", "numerator": "1", "denominator": 3}}[field]
    found, _, report = outcome(world_with(spec, lambda w: w["extra_g0"].append(
        {"key": ["c0", "m9"], "values": {"v": bad}})))
    assert found == {"malformed_snapshot"}
    assert "decimal string" in report["findings"][0]["detail"]


@given(worlds(), st.sampled_from([("amount", "USD"), ("quantity", "kg")]), st.sampled_from(["sum", "min", "max"]),
       st.booleans())
def test_mixed_measures_do_not_add_up(spec, measure, function, with_unknown):
    """Two currencies or two units are invalid input, also when an unknown contributor would make the result unknown."""
    assume(spec["shape"] != "ratio")  # ratios have no minor units
    shape, other = measure

    def change(s):  # a fresh group with one value in another currency or unit
        s["shape"] = shape
        s["weights"][("c9", "m8")], s["weights"][("c9", "m9")] = ("known", 1), ("known", 2)
        if with_unknown:
            s["weights"][("c9", "m7")] = ("unknown", 0)
        s["steps"][0]["agg"] = {**aggregate(s["weights"], "c9", function), "result": "invalid"}
    world = spec_world(spec, change)
    world["measure"][("c9", "m9")] = other
    assert errors(world) == {"invalid_value"}


@given(worlds(), st.sampled_from(["result", "count", "malformed", "premise"]))
def test_role_report_shows_nothing_the_role_cannot_read(spec, fault):
    """A role's report carries the same verdict but no key or value from rows the role cannot read."""
    def change(s):
        s["weights"][(SECRET, "m0")] = ("known", 12345)
        s["steps"][0]["agg"] = aggregate(s["weights"], SECRET, "sum")
        s["filtered"] = True
    world = spec_world(spec, change)
    w = world["witnesses"][0]
    if fault == "result":
        w["aggregates"][0]["result"] = "unknown"
    elif fault == "count":
        w["aggregates"][0]["count"] += 1
    elif fault == "malformed":
        world["extra_g0"].append({"key": [SECRET, "m1"], "values": {"v": {"state": "known", "value": 12345}}})
    else:
        w["premises"][0]["row"]["key"] = key([SECRET])
    full, role_r = outcome(world), outcome(world, role="r")
    assert SECRET in render(full[2]) or "12345" in render(full[2])  # the unfiltered report does show it
    assert role_r[0] == full[0] != set()
    assert SECRET not in render(role_r[2]) and "12345" not in render(role_r[2])


# Snapshot files that are broken in their structure, not only in a value.
BROKEN = {"value": json.dumps([{"key": ["c0"], "values": {"v": {"state": "bogus"}}}]).encode(),
          "empty-row": b"[{}]", "null-row": b"[null]", "not-a-list": b"{}", "not-json": b"[{",
          "not-utf8": b"\xff", "key-not-list": b'[{"key": "c0"}]', "extra-field": b'[{"key": [], "x": 1}]'}


@given(worlds(), st.sampled_from(["hash", *BROKEN]), st.data())
def test_bad_role_snapshot_does_not_change_validity(spec, fault, data):
    """Validity depends only on complete snapshots. A bad role snapshot is a warning in the report."""
    world = realize(spec)
    world["filtered"] = True

    def mutate(proof, manifest, files):
        s = data.draw(st.sampled_from([s for s in manifest["snapshots"] if not s["complete"]]))
        if fault == "hash":
            s["sha256"] = hashlib.sha256(b"tampered").hexdigest()
        else:
            files[s["uri"]] = BROKEN[fault]
            s["sha256"] = hashlib.sha256(files[s["uri"]]).hexdigest()
    plain, role_r = outcome(world, mutate=mutate), outcome(world, role="r", mutate=mutate)
    assert plain[2]["valid"] and role_r[2]["valid"]
    assert plain[0] == role_r[0] == set()
    assert role_r[1] == {"role_snapshot_hash_mismatch" if fault == "hash" else "role_malformed_snapshot"}


@given(worlds(), st.data())
def test_role_report_hides_other_snapshot_uris(spec, data):
    """A snapshot URI can carry an id. A role's report names only the URIs of its own snapshots."""
    def mutate(proof, manifest, files):
        s = data.draw(st.sampled_from([s for s in manifest["snapshots"] if s["complete"]]))
        files[f"all/{SECRET}.json"] = files[s["uri"]]
        s["uri"], s["sha256"] = f"all/{SECRET}.json", hashlib.sha256(b"tampered").hexdigest()
    world = realize(spec)
    world["filtered"] = True
    plain, role_r = outcome(world, mutate=mutate), outcome(world, role="r", mutate=mutate)
    assert SECRET in render(plain[2]) and SECRET not in render(role_r[2])
    assert plain[0] == role_r[0] == {"snapshot_hash_mismatch"}


@given(worlds(), st.sampled_from(sorted(BROKEN)), st.data())
def test_broken_complete_snapshot_is_a_finding(spec, fault, data):
    """A structurally broken complete snapshot is malformed_snapshot, never a crash without a verdict."""
    def mutate(proof, manifest, files):
        s = data.draw(st.sampled_from([s for s in manifest["snapshots"] if s["complete"]]))
        files[s["uri"]] = BROKEN[fault]
        s["sha256"] = hashlib.sha256(files[s["uri"]]).hexdigest()
    assert errors(realize(spec), mutate=mutate) == {"malformed_snapshot"}


# Closure (RV-K01): an engine that never derives one row leaves snapshots in which every proof is valid.

NODES = ["c0", "c1", "c2", "c3"]
LITERAL = lambda relation, terms, polarity="positive", stratum=0: {
    "relation": relation, "terms": terms, "polarity": polarity, "stratum": stratum}
# blocked is negated and reach is aggregated over; both read mid, which is recursive. allowed and fan are read by
# nothing, so nothing reads the absence of a row of theirs.
PROGRAM = [
    {"id": "mid_flag", "stratum": 1, "head": {"relation": "mid", "terms": ["?x"]}, "body": [LITERAL("flag", ["?x"])]},
    {"id": "mid_step", "stratum": 1, "head": {"relation": "mid", "terms": ["?y"]},
     "body": [LITERAL("mid", ["?x"], stratum=1), LITERAL("link", ["?x", "?y"])]},
    {"id": "blocked", "stratum": 1, "head": {"relation": "blocked", "terms": ["?x"]},
     "body": [LITERAL("mid", ["?x"], stratum=1), LITERAL("request", ["?x"])]},
    {"id": "reach", "stratum": 1, "head": {"relation": "reach", "terms": ["?x", "?y"]},
     "body": [LITERAL("link", ["?x", "?y"]), LITERAL("mid", ["?y"], stratum=1)]},
    {"id": "allowed", "stratum": 2, "head": {"relation": "allowed", "terms": ["?x"]},
     "body": [LITERAL("request", ["?x"]), LITERAL("blocked", ["?x"], "negative", 1)]},
    {"id": "fan", "stratum": 2, "head": {"relation": "fan", "terms": ["?x", "?n"]}, "body": [LITERAL("request", ["?x"])],
     "aggregates": [{"relation": "reach", "terms": ["?x", "_"], "function": "count", "as": "?n", "stratum": 1}]},
]
COVERED = ("mid", "blocked", "reach")


def engine(flag, link, request, skip=None):
    """The model of PROGRAM computed here, stratum by stratum, by an engine that never derives the row `skip`:
    every row with one witness, found in rounds, so the proofs are well-founded. Returns {relation: {row: witness}}."""
    out = {name: {} for name in ("mid", "blocked", "reach", "allowed", "fan")}

    def derive(rule_id, relation, row, theta, premises, aggregates=()):
        if (relation, row) == skip or row in out[relation]:
            return False
        out[relation][row] = {
            "conclusion": {"relation": relation, "key": key(row)}, "rule_id": rule_id,
            "bindings": [{"variable": v, "value": x} for v, x in sorted(theta.items())],
            "premises": [{"row": {"relation": r, "key": key(k)}, "polarity": pol, "stratum": s} for r, k, pol, s in premises],
            **({"aggregates": list(aggregates)} if aggregates else {})}
        return True

    changed = True
    while changed:
        changed = False
        for (x,) in sorted(flag):
            changed |= derive("mid_flag", "mid", (x,), {"?x": x}, [("flag", (x,), "positive", 0)])
        for (x,) in sorted(out["mid"]):
            for a, y in sorted(link):
                if a == x:
                    changed |= derive("mid_step", "mid", (y,), {"?x": x, "?y": y},
                                      [("mid", (x,), "positive", 1), ("link", (x, y), "positive", 0)])
    for (x,) in sorted(out["mid"]):
        if (x,) in request:
            derive("blocked", "blocked", (x,), {"?x": x}, [("mid", (x,), "positive", 1), ("request", (x,), "positive", 0)])
    for x, y in sorted(link):
        if (y,) in out["mid"]:
            derive("reach", "reach", (x, y), {"?x": x, "?y": y}, [("link", (x, y), "positive", 0), ("mid", (y,), "positive", 1)])
    for (x,) in sorted(request):
        if (x,) not in out["blocked"]:
            derive("allowed", "allowed", (x,), {"?x": x},
                   [("request", (x,), "positive", 0), ("blocked", (x,), "negative", 1)])
        members = sorted(key(r) for r in out["reach"] if r[0] == x)
        digest = hashlib.sha256(json.dumps([[k] for k in members], separators=(",", ":")).encode()).hexdigest()
        n = f"known:{len(members)}"
        derive("fan", "fan", (x, n), {"?x": x, "?n": n}, [("request", (x,), "positive", 0)],
               [{"relation": "reach", "group_key": key([x]), "count": len(members), "contributors_sha256": digest, "result": n}])
    return out


def epoch_report(flag, link, request, model):
    from rezono_checker.check import check_epoch
    tables = {"flag": flag, "link": link, "request": request, **{name: set(rows) for name, rows in model.items()}}
    files = {name: json.dumps([{"key": list(r)} for r in sorted(rows)]).encode() for name, rows in tables.items()}
    manifest = {"id": "m", "snapshots": [{"relation": name, "role": "all", "complete": True, "uri": name, "format": "json",
                                          "sha256": hashlib.sha256(data).hexdigest()} for name, data in sorted(files.items())]}
    witnesses = [w for _, rows in sorted(model.items()) for _, w in sorted(rows.items())]
    return check_epoch(witnesses, manifest, load_rules({"rules": PROGRAM}), files.__getitem__, derived=set(model))


FACTS = (st.sets(st.tuples(st.sampled_from(NODES))), st.sets(st.tuples(st.sampled_from(NODES), st.sampled_from(NODES))),
         st.sets(st.tuples(st.sampled_from(NODES))))


@given(*FACTS)
def test_the_model_is_closed(flag, link, request):
    report = epoch_report(flag, link, request, engine(flag, link, request))
    assert report["valid"] and not report["findings"], report["findings"]


@given(*FACTS, st.data())
def test_an_underived_row_is_found_where_its_absence_is_read(flag, link, request, data):
    """Delete one derived row together with its witness, and let the engine go on consistently from there: what
    depended on the row is gone too, and what its absence allows is derived, with a correct proof. Every other
    check passes. Only closure tells this epoch from the model."""
    model = engine(flag, link, request)
    rows = [(name, row) for name in COVERED for row in sorted(model[name])]
    assume(rows)
    skip = data.draw(st.sampled_from(rows))
    report = epoch_report(flag, link, request, engine(flag, link, request, skip))
    assert {f["reason"] for f in report["findings"]} == {"underived_row"}
    assert {(f["relation"], f["key"]) for f in report["findings"]} == {(skip[0], key(skip[1]))}
    assert not report["valid"]


@given(*FACTS, st.data())
def test_closure_stops_where_no_absence_is_read(flag, link, request, data):
    """The scope limit: a missing row of a relation that nothing negates or aggregates over hides a conclusion and
    makes no other one false, so the pass does not recompute it."""
    model = engine(flag, link, request)
    rows = [(name, row) for name in ("allowed", "fan") for row in sorted(model[name])]
    assume(rows)
    report = epoch_report(flag, link, request, engine(flag, link, request, data.draw(st.sampled_from(rows))))
    assert report["valid"] and not report["findings"]
