"""Facts versus derivations: checker warns without blocking on an uncited stored fact equal to a derivable conclusion."""
import hashlib
import json

import pytest

from rezono_checker.canon import encode_key
from rezono_checker.check import check_epoch
from rezono_checker.rules import derived_relations, load_rules

DATASET_HASH = "a" * 64


def _rel(name: str, role: str, *columns: str) -> dict:
    return {"name": name, "role": role, "key": [{"name": c, "type": "string"} for c in columns]}


def _run_epoch(fact_sources: list[dict]) -> dict:
    relations = [
        _rel("service", "base", "id"),
        _rel("vendor_default", "base", "service", "port"),
        _rel("stored_port", "base", "service", "port"),
        _rel("derived_port", "derived", "service", "port"),
    ]
    rules = [
        {
            "id": "derive_port_from_vendor",
            "stratum": "0",
            "head": {"relation": "derived_port", "terms": ["?s", "?p"]},
            "body": [
                {"relation": "service", "terms": ["?s"], "polarity": "positive", "stratum": "0"},
                {"relation": "vendor_default", "terms": ["?s", "?p"], "polarity": "positive", "stratum": "0"},
            ],
        },
    ]
    doc = {"format": "rezono.rules/1", "relations": relations, "rules": rules}
    loaded = load_rules(doc)
    rows = {
        "service": [["idp"]],
        "vendor_default": [["idp", "8443"]],
        "stored_port": [["idp", "8443"]],
        "derived_port": [["idp", "8443"]],
    }
    snaps = {r: json.dumps([{"key": k} for k in rs]).encode("utf-8") for r, rs in rows.items()}
    manifest = {
        "id": "m-1",
        "snapshots": [
            {
                "relation": r,
                "role": "all",
                "complete": True,
                "uri": r,
                "format": "json",
                "sha256": hashlib.sha256(b).hexdigest(),
            }
            for r, b in snaps.items()
        ],
    }
    witnesses = [
        {
            "conclusion": {"relation": "derived_port", "key": encode_key(["idp", "8443"])},
            "rule_id": "derive_port_from_vendor",
            "bindings": [
                {"variable": "?s", "value": "idp"},
                {"variable": "?p", "value": "8443"},
            ],
            "premises": [
                {"row": {"relation": "service", "key": encode_key(["idp"])}, "polarity": "positive", "stratum": 0},
                {
                    "row": {"relation": "vendor_default", "key": encode_key(["idp", "8443"])},
                    "polarity": "positive",
                    "stratum": 0,
                },
            ],
        },
    ]
    return check_epoch(
        witnesses,
        manifest,
        loaded,
        snaps.__getitem__,
        derived=derived_relations(doc, loaded),
        fact_sources=fact_sources,
    )


def _base_sources(stored_port_sources: list[dict]) -> list[dict]:
    return [
        {
            "row": {"relation": "service", "key": encode_key(["idp"])},
            "sources": [{"kind": "git", "name": "pack", "revision": "b" * 40, "position": "decisions/core.md#1"}],
        },
        {
            "row": {"relation": "vendor_default", "key": encode_key(["idp", "8443"])},
            "sources": [
                {
                    "kind": "document",
                    "name": "vendor-manual",
                    "revision": "26.0",
                    "position": "ports#default",
                    "url": "https://vendor.example.org/docs/ports",
                    "fragment_sha256": "c" * 64,
                    "licence": "Apache-2.0",
                    "attribution": "Vendor Docs",
                },
            ],
        },
        {
            "row": {"relation": "stored_port", "key": encode_key(["idp", "8443"])},
            "sources": stored_port_sources,
        },
    ]


@pytest.mark.xfail(
    strict=True,
    reason=(
        "extra: decisions/facts-versus-derivations.md: accept fact_sources in checker/rezono_checker/check.py "
        "check_epoch and emit non-blocking warning stored_derivable_fact when a stored base fact (arity >= 2) "
        "equals an independently derivable conclusion without a pinned conclusion citation or observation origin "
        "(checker/ requires independent pre-land review via p1-read-<sha>)."
    ),
)
def test_checker_warns_without_blocking_on_uncited_stored_derivable_fact() -> None:
    expected_warning = {
        "reason": "stored_derivable_fact",
        "severity": "warning",
        "relation": "stored_port",
        "key": encode_key(["idp", "8443"]),
        "detail": "derived_port",
    }

    # 1. An uncited stored fact repeating an independently derivable conclusion emits a non-blocking warning,
    #    while vendor_default (a premise of derived_port) does not warn.
    uncited = _run_epoch(_base_sources([{"kind": "pack", "name": "facts/ports.yaml", "position": "2"}]))
    assert uncited["valid"] is True
    assert uncited["findings"] == [expected_warning]

    # 2. An unpinned epoch reference (?pin=m-1 without @d-<64 hex>) is not a valid pinned citation and still warns.
    unpinned = _run_epoch(
        _base_sources([
            {
                "kind": "proposal",
                "name": "prop-1",
                "revision": "m-1",
                "position": "step-1",
                "url": "https://pack.example.org/DerivedPort/idp?pin=m-1",
            },
        ]),
    )
    assert unpinned["valid"] is True
    assert unpinned["findings"] == [expected_warning]

    # 3. An explicit decision citing the pinned canonical conclusion address (?pin=m-1@d-<64 hex>) suppresses the warning.
    cited_decision = _run_epoch(
        _base_sources([
            {
                "kind": "proposal",
                "name": "prop-2",
                "revision": "m-1",
                "position": "step-1",
                "url": f"https://pack.example.org/DerivedPort/idp?pin=m-1@d-{DATASET_HASH}",
            },
        ]),
    )
    assert cited_decision["valid"] is True
    assert cited_decision["findings"] == []

    # 4. An independent external observation (origin: observation) suppresses the warning.
    observed = _run_epoch(
        _base_sources([{"kind": "tool", "name": "port-probe", "position": "scan-1"}]),
    )
    assert observed["valid"] is True
    assert observed["findings"] == []
