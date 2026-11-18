"""Project a step from matching run evidence."""

import json
from pathlib import Path
from runpy import run_path

import pytest


def test_status_projection():
    project = run_path(str(Path(__file__).resolve().parents[1] / "status_projection.py"))["project"]
    step = {"tenant": "elm", "delivery": "elm-1", "step": "database", "run": "new"}
    old = {**step, "run": "old", "relation": "done", "reason": "old-observation"}
    applied = {**step, "relation": "applied", "reason": "dispatch"}
    other = {**step, "tenant": "reed", "relation": "done", "reason": "other-owner"}
    assert project(step, [old, applied, other]) == "pending"
    assert project(step, [{**step, "relation": "done", "reason": "observed"}]) == "success"
    assert project(step, [{**step, "relation": "stuck", "reason": "expired"}]) == "failure"


def status_observations():
    step = {"tenant": "elm", "delivery": "elm-1", "step": "database", "run": "current"}
    stuck = {**step, "id": "stuck", "relation": "stuck", "reason": "https://example.org/stuck",
             "at": "2026-01-01T00:00:00.123456789Z"}
    done = {**step, "id": "done", "relation": "done", "reason": "https://example.org/done",
            "at": "2026-01-01T01:00:00.123456790+01:00"}
    return step, stuck, done


def test_current_status_carries_the_latest_scoped_witness():
    from loop.status_projection import project_status

    step, stuck, done = status_observations()
    other_rows = [{**stuck, key: "outside", "id": "other-" + key, "at": "2026-01-02T00:00:00Z"}
                  for key in step]
    readings = [stuck, done, *other_rows]
    projection = project_status(step, readings)
    assert projection.state == "success"
    assert projection.reasons == {done["reason"]}
    assert projection == project_status(step, reversed(readings))
    assert {reading["id"] for reading in projection.observations} == {"stuck", "done"}
    proof, = projection.proofs
    grounds = [(p["row"]["relation"], json.loads(p["row"]["key"]))
               for witness in proof["witnesses"] for p in witness["premises"] if p["polarity"] == "positive"]
    assert ("loop_status_observation__at", ["done", done["at"]]) in grounds
    assert ("loop_status_observation__reason", ["done", done["reason"]]) in grounds
    assert json.loads(proof["root"]["key"])[-2:] == ["success", done["reason"]]
    assert [a["count"] for w in proof["witnesses"] for a in w.get("aggregates", [])] == [2]

    later_refusal = {**stuck, "at": "2026-01-01T00:01:00Z"}
    failure = project_status(step, [later_refusal, done])
    assert (failure.state, failure.reasons) == ("failure", {later_refusal["reason"]})


@pytest.mark.parametrize("time", ["2026-01-01T00:00:00.123456790Z", ""])
def test_current_status_stays_pending_when_evidence_cannot_choose(time):
    from loop.status_projection import project_status

    step, stuck, done = status_observations()
    conflicting = {**stuck, "at": time}
    projection = project_status(step, [conflicting, done])
    assert projection.state == "pending"
    assert projection.reasons == {stuck["reason"], done["reason"]}
    assert projection == project_status(step, [done, conflicting])
    for proof in projection.proofs:
        grounded_ids = {json.loads(p["row"]["key"])[0] for w in proof["witnesses"] for p in w["premises"]
                        if p["polarity"] == "positive" and p["row"]["relation"] == "loop_status_observation__reason"}
        assert grounded_ids == {"done", "stuck"}


def test_independent_checker_validates_the_delivered_proof():
    from rezono_canon import sha256_hex
    from rezono_checker import check, rules as checker_rules
    from rezono_compiler import explain, pack

    from loop.status_projection import project_status
    from pack_records import LOOP, evaluate

    step, stuck, done = status_observations()
    projection = project_status(step, [stuck, done])
    proof, = projection.proofs
    theory = pack.read(LOOP)
    _, _, explainer = evaluate(theory, {"loop_status_observation": list(projection.observations)})
    snapshots = {relation: explainer.snapshot(relation).encode() for relation in explain.relations_of(proof)}
    manifest = {"id": proof["manifest_id"], "snapshots": [
        {"relation": relation, "role": "all", "complete": True, "uri": relation, "format": "json",
         "sha256": sha256_hex(content)} for relation, content in sorted(snapshots.items())
    ]}
    rules = checker_rules.load_rules(theory.rules)
    assert check(proof, manifest, rules, snapshots.__getitem__)["findings"] == []

    # Remove the winning source while retaining the original proof and recorded hash.
    snapshots["loop_status_observation__reason"] = b"[]"
    damaged = check(proof, manifest, rules, snapshots.__getitem__)
    assert any(finding["reason"] == "snapshot_hash_mismatch" for finding in damaged["findings"])
