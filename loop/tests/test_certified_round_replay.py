"""Replay certified round evidence, durable attempts and dated observations at the normal command."""
from copy import deepcopy
import json

import pytest

from loop.recording_cli import main
from rezono_canon import canonical_bytes, canonical_json, canonical_sha256, sha256_hex
from rezono_checker.evidence import admit
from rezono_checker.transition import check_transition_certificate
from rezono_publisher import store
from round_visibility_publication import observation_reference, pinned_evidence, round_claim, round_context
from test_recorded_correction import observation
from test_replay_fixed_point import boundary, execute, setup_recording

MANIFEST = "desired-delivery"
INVARIANTS = ("missing_delivery",)


def _relation(name, role, columns, *, invariant=False):
    signature = {"name": name, "role": role, "key": [{"name": column, "type": "string"} for column in columns]}
    return {**signature, "invariant": True} if invariant else signature


def _literal(relation, *terms, negative=False):
    return {"relation": relation, "terms": list(terms),
            "polarity": "negative" if negative else "positive", "stratum": "0"}


def _rule(name, head, body, *, stratum="0"):
    return {"id": name, "stratum": stratum, "head": {"relation": name, "terms": list(head)}, "body": body}


def _row(relation, cells):
    return {"relation": relation, "key": canonical_json(list(cells))}


PROGRAM = {
    "format": "rezono.rules/1",
    "relations": [
        _relation("delivery__status", "base", ("item", "status")),
        _relation("expected_delivery", "base", ("item",)),
        _relation("delivery_present", "derived", ("item",)),
        _relation("missing_delivery", "derived", ("item",), invariant=True),
    ],
    "rules": [
        _rule("delivery_present", ("?item",), [_literal("delivery__status", "?item", "?status")]),
        _rule("missing_delivery", ("?item",), [_literal("expected_delivery", "?item"),
                                               _literal("delivery_present", "?item", negative=True)], stratum="1"),
    ],
}


def _snapshot(label, status):
    return {
        "id": label,
        "rows": {
            "delivery__status": [("ship", status)],
            "expected_delivery": [("ship",)],
            "delivery_present": [("ship",)],
            "missing_delivery": [],
        },
        "witnesses": [{
            "rule_id": "delivery_present",
            "conclusion": _row("delivery_present", ("ship",)),
            "bindings": [{"variable": "?item", "value": "ship"}, {"variable": "?status", "value": status}],
            "premises": [{"row": _row("delivery__status", ("ship", status)), "polarity": "positive", "stratum": 0}],
        }],
    }


def _write_round_evidence(root, *, include_trusted_context=True):
    """Write a real archived Evidence bundle for the opening cut and verify it with the checker."""
    delta = [("delivery__status", ("ship", "pending"), -1), ("delivery__status", ("ship", "shipped"), 1)]
    plan_hash = canonical_sha256({"step": "ship", "target": "ship", "expected_old": ("ship", "pending"), "delta": delta})
    inspect_hash = canonical_sha256({"step": "inspect", "target": "inspect"})
    observed = canonical_bytes(
        {"id": "read-opening", "run": "active", "scope": "delivery", "cut": "opening", "event_time": 8}
    )
    base, variant = _snapshot("base", "pending"), _snapshot("variant", "shipped")
    cut = {"id": "opening", "run": "active", "scope": "delivery", "observation_sha256": sha256_hex(observed)}
    certificate = {
        "manifest": MANIFEST,
        "definition_sha256": canonical_sha256(PROGRAM),
        "run": "active",
        "cut": "opening",
        "base": canonical_sha256(base),
        "variant": canonical_sha256(variant),
        "rule": "ship-delivery",
        "bindings": {"item": "ship"},
        "effect": canonical_sha256([plan_hash]),
        "expected_old": [_row("delivery__status", ("ship", "pending"))],
        "delta": delta,
        "invariants": {"missing_delivery": {"rows": [], "count": "0"}},
    }
    certificate_context = {
        "manifest": MANIFEST,
        "definition_sha256": canonical_sha256(PROGRAM),
        "program": PROGRAM,
        "invariants": INVARIANTS,
        "cut": cut,
        "observations": {"read-opening": observed},
    }
    assert check_transition_certificate(certificate, certificate_context, base, variant) == {
        "valid": True,
        "findings": [],
    }

    retained = {
        "definition": canonical_bytes(PROGRAM),
        "observed-opening": observed,
        "base": canonical_bytes(base),
        "round-domain": canonical_bytes({
            "width": 1,
            "steps": [
                {"step": "ship", "priority": 0, "effects": [plan_hash]},
                {"step": "inspect", "priority": 1, "effects": [inspect_hash]},
            ],
        }),
    }
    submitted = {
        "variant-ship": canonical_bytes(variant),
        "certificate-ship": canonical_bytes(certificate),
    }
    submitted["claim-ship"] = canonical_bytes(round_claim(
        submitted,
        run="active",
        cut="opening",
        batch="batch-ship",
        members=["ship"],
        subsets=[(["ship"], [plan_hash], "variant-ship", "certificate-ship")],
    ))
    claim_ref = observation_reference("submitted", "claim-ship", submitted["claim-ship"])
    context = {"rounds": [round_context(
        retained,
        run="active",
        cut=cut,
        manifest=MANIFEST,
        invariants=INVARIANTS,
        program="definition",
        observations={"read-opening": "observed-opening"},
        base="base",
        domain="round-domain",
    )]} if include_trusted_context else {}
    index = {"rounds": [claim_ref]}

    archive = store.FileStore(root / "archive")
    for group, objects in (("retained", retained), ("submitted", submitted)):
        for name, body in objects.items():
            archive.put_new(observation_reference(group, name, body)["file"], body)
    evidence = pinned_evidence(archive, context, index)
    admitted = admit(evidence)
    if include_trusted_context:
        assert admitted.findings == []
        assert admitted.rows["verified_round"] == [(claim_ref["sha256"], "active", "opening", "batch-ship")]
        assert admitted.rows["verified_round_member"] == [(claim_ref["sha256"], "ship")]
    else:
        assert admitted.rows["verified_round"] == []
        assert admitted.rows["verified_round_member"] == []
    return plan_hash, {"archive": "archive", "context": evidence.context, "index": evidence.candidates}


def _recording(root, *, include_trusted_context=True):
    root.mkdir()
    data = setup_recording(root)
    data["records"]["loop_step"].append({"id": "inspect"})
    data["records"]["loop_completion"].append(
        {"id": "inspection", "step": "inspect", "run": "active", "token": "inspected", "reason": "inspection"}
    )
    data["records"]["loop_expectation"].append({"id": "inspected", "value": "yes"})
    data["initial"] = boundary("opening", at=8, observations=[
        observation("active", "opening", "seed", "permit-readback", 8, "yes"),
    ])
    data["sweeps"] = [
        boundary("lost", at=10),
        boundary("confirmed", at=11, observations=[
            observation("active", "confirmed", "ship", "shipment-readback", 11, "yes"),
        ]),
        boundary("corrected", at=12, observations=[
            observation("active", "corrected", "ship", "changed-readback", 12, "no"),
        ]),
    ]
    plan_hash, evidence = _write_round_evidence(root, include_trusted_context=include_trusted_context)
    data["evidence"] = evidence
    if include_trusted_context:
        data["certified_rounds"] = [
            {"run": "active", "cut": "opening",
             "attempts": [{"step": "ship", "plan_hash": plan_hash, "state": "unknown"}]},
            {"run": "active", "cut": "lost",
             "attempts": [{"step": "ship", "plan_hash": plan_hash, "state": "unknown"}]},
            {"run": "active", "cut": "confirmed",
             "attempts": [{"step": "ship", "plan_hash": plan_hash, "state": "applied"}]},
            {"run": "active", "cut": "corrected", "attempts": []},
        ]
    else:
        data["certified_rounds"] = [
            {"run": "active", "cut": cut, "attempts": []}
            for cut in ("opening", "lost", "confirmed", "corrected")
        ]
    return plan_hash, data


def test_certified_round_replay(tmp_path, capsys):
    certified_dir = tmp_path / "certified"
    plan_hash, data = _recording(certified_dir)

    status, report = execute(certified_dir, capsys, data)
    assert (status, report["outcome"], report["plans"]) == (1, "failure", [["ship"], [], []])
    assert report["submissions"] == [{"step": "ship", "plan_hash": plan_hash}]
    assert [round_["done"] for round_ in report["certified_rounds"]] == [[], [], ["ship"], []]
    assert report["certified_rounds"][1]["reserved"] == [plan_hash]
    assert report["certified_rounds"][2]["reserved"] == []

    # Counterexample: the same submitted round claim without a trusted round context authorizes nothing.
    untrusted_dir = tmp_path / "untrusted"
    _, untrusted = _recording(untrusted_dir, include_trusted_context=False)
    status, report = execute(untrusted_dir, capsys, untrusted)
    assert (status, report["outcome"], report["plans"]) == (1, "failure", [[], [], []])
    assert report["submissions"] == []
    assert [round_["done"] for round_ in report["certified_rounds"]] == [[], [], ["ship"], []]

    # Counterexample: a certified round bound to a stale cut is refused.
    stale = deepcopy(data)
    stale["certified_rounds"][0]["cut"] = "prior"
    recording = certified_dir / "stale-recording.json"
    recording.write_text(json.dumps(stale), encoding="utf-8")
    assert main([str(recording)]) == 1
    refused = capsys.readouterr()
    assert not refused.out and "cut" in refused.err.lower()
