"""Replay the shared expression state projection against an independent archive.

See decisions/scoped-completeness.md and decisions/language-expression-semantics.md.
The source Values, origin paths, expected projection and scope grant are authored
separately from the engine snapshots and witnesses supplied to the checker.
"""

import json
from pathlib import Path

from rezono_canon import sha256_hex
from rezono_checker.access import check_role
from rezono_checker.canon import encode_key
from rezono_checker.check import check_epoch
from rezono_checker.rules import derived_relations, load_rules


CASE = Path(__file__).with_name("fixtures") / "expression-state-projection-coverage.json"
SOURCE = "sensor_values"
PROJECTION = "sensor__estimate_state"
CONCLUSION = "observed_state"
GRANT = "state_read_grant"
ACCESS = "may_read"
METADATA = "ir/state-projections.json"

STATE_TERMS = ("?subject", "?state", "?reason")
GRANT_TERMS = ("?role", "?kind", "?subject")
COLUMNS = {SOURCE: ("sensor",), PROJECTION: ("sensor", None, None), GRANT: (None, None, "sensor")}


def relation(name, role, *columns):
    return {"name": name, "role": role, "key": [{"name": column, "type": "string"} for column in columns]}


def rule(head, premise, terms):
    return {
        "id": head,
        "stratum": "1",
        "head": {"relation": head, "terms": list(terms)},
        "body": [{"relation": premise, "terms": list(terms), "polarity": "positive", "stratum": "0"}],
    }


IR = {
    "format": "rezono.rules/1",
    "pack": "state-projection-coverage",
    "relations": [
        relation(SOURCE, "base", "subject"),
        relation(PROJECTION, "base", "subject", "state", "reason"),
        relation(CONCLUSION, "derived", "subject", "state", "reason"),
        relation(GRANT, "base", "role", "kind", "subject"),
        relation(ACCESS, "derived", "role", "kind", "subject"),
    ],
    "rules": [rule(CONCLUSION, PROJECTION, STATE_TERMS), rule(ACCESS, GRANT, GRANT_TERMS)],
}
DESCRIPTOR = [{
    "relation": PROJECTION,
    "source_relation": SOURCE,
    "value_column": "estimate",
    "origin_column": "origin",
    "required": True,
}]


class UnprovenProjectionAccepted(AssertionError):
    """The checker accepted an incomplete projection against the immutable inputs."""


def as_bytes(document):
    return json.dumps(document, sort_keys=True, ensure_ascii=False).encode("utf-8")


def witness(head, premise, terms, row):
    key = encode_key(row["key"])
    return {
        "rule_id": head,
        "bindings": [{"variable": term, "value": value} for term, value in zip(terms, row["key"], strict=True)],
        "premises": [{"row": {"relation": premise, "key": key}, "polarity": "positive", "stratum": 0}],
        "conclusion": {"relation": head, "key": key},
    }


def evidence(source, projection, grants):
    """The claim's reported downstream rows and proofs agree with its supplied projection."""
    snapshots = {
        SOURCE: as_bytes(source),
        PROJECTION: as_bytes(projection),
        CONCLUSION: as_bytes([{"key": row["key"]} for row in projection]),
        GRANT: as_bytes(grants),
        ACCESS: as_bytes(grants),
    }
    witnesses = [witness(CONCLUSION, PROJECTION, STATE_TERMS, row) for row in projection]
    witnesses.extend(witness(ACCESS, GRANT, GRANT_TERMS, row) for row in grants)
    return snapshots, witnesses


def replay(directory, snapshots, witnesses, *, full=None, missing_descriptor=False):
    directory.mkdir()
    descriptor = as_bytes(DESCRIPTOR)
    compiled = directory / METADATA
    compiled.parent.mkdir()
    if not missing_descriptor:
        compiled.write_bytes(descriptor)
    manifest = {
        "id": "m-1",
        "compiled": [{"file": METADATA, "sha256": sha256_hex(descriptor), "uri": METADATA}],
        "snapshots": [],
    }
    for relation_name, contents in snapshots.items():
        uri = f"{relation_name}.json"
        (directory / uri).write_bytes(contents)
        manifest["snapshots"].append({
            "relation": relation_name, "role": "all", "complete": True,
            "uri": uri, "format": "json", "sha256": sha256_hex(contents),
        })

    rules = load_rules(IR)
    return check_epoch(witnesses, manifest, rules, lambda uri: (directory / uri).read_bytes(),
                       derived=derived_relations(IR, rules), full=full)


def check_scope(whole, partial):
    complete, instances = whole
    claimed, witnesses = partial
    return check_role("guest", complete, claimed, None, COLUMNS, ["sensor"], {}, IR,
                      instances=instances, witnesses=witnesses)


def test_state_projection_rejects_omitted_row(tmp_path):
    case = json.loads(CASE.read_bytes())
    source = case["source"]
    projected = case["projection"]
    grants = [case["read_grant"]]
    complete = evidence(source, projected, grants)
    valid = replay(tmp_path / "complete", *complete)
    assert valid["valid"], valid["findings"]
    empty = replay(tmp_path / "empty", *evidence([], [], []))
    assert empty["valid"], empty["findings"]

    # The same role sees the same Value and grounds whether a hidden Value exists or is absent.
    limited = evidence(source[:1], projected[:1], grants)
    without_hidden = evidence([*source[:2], source[3]], projected[:2], grants)
    other = replay(tmp_path / "without-hidden", *without_hidden)
    assert other["valid"], other["findings"]
    full, findings = check_scope(complete, limited)
    assert SOURCE not in full and PROJECTION not in full and not findings, findings
    other_full, other_findings = check_scope(without_hidden, limited)
    assert full == other_full and not other_findings, other_findings
    visible = replay(tmp_path / "limited", *limited, full=full)
    other_visible = replay(tmp_path / "other-limited", *limited, full=other_full)
    assert visible["valid"] and visible == other_visible, visible
    assert b"restricted_detail" not in as_bytes(visible)

    substituted = {"key": ["visible", "unknown", "restricted_detail"], "values": projected[0]["values"]}
    injected = evidence(source[:1], [substituted], grants)
    _, findings = check_scope(complete, injected)
    assert {"not_readable", "readable_missing"} <= {finding["reason"] for finding in findings}
    forbidden = replay(tmp_path / "injected", *injected, full=full)
    assert not forbidden["valid"] and b"restricted_detail" not in as_bytes(forbidden), forbidden

    limited_omission = evidence(source[:1], [], grants)
    _, findings = check_scope(complete, limited_omission)
    assert any(f["reason"] == "readable_missing" and f["relation"] == PROJECTION for f in findings), findings

    # Removing the real projection and all of its downstream traces preserves engine-side consistency.
    omitted = replay(tmp_path / "omitted", *evidence(source, projected[1:], grants))
    no_source, no_source_witnesses = evidence(source, [], grants)
    del no_source[SOURCE]
    no_target, no_target_witnesses = evidence([], [], [])
    del no_target[PROJECTION]
    fabricated = {"key": ["omitted-slot", "unknown", "not_measured"],
                  "values": {"origin": source[3]["values"]["origin"]}}
    invalid = {
        "projection and downstream witness omitted": omitted,
        "source snapshot missing": replay(tmp_path / "no-source", no_source, no_source_witnesses),
        "projection snapshot missing": replay(tmp_path / "no-target", no_target, no_target_witnesses),
        "pinned descriptor missing": replay(tmp_path / "no-descriptor", *complete, missing_descriptor=True),
        "required slot without a Value or absence witness": replay(
            tmp_path / "fabricated", *evidence(source, [*projected, fabricated], grants)
        ),
    }
    accepted = [name for name, report in invalid.items() if report["valid"]]
    if accepted:
        raise UnprovenProjectionAccepted(", ".join(accepted))
