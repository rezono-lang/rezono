"""Contract tests for reader-served seal fields (decisions/reader-served-seal-fields.md, #1451).

Verifies that contracts/explain.yaml accepts valid ReaderHead (including compiled, snapshots,
trust_tier, may_propose) and Answer.reader_hashes (ReaderHashCheck / WitnessHashCheck), and
tracks the atomic contracts/source.yaml + checker/rezono_checker/sources.py origin_sign addition.
"""

import pytest
from contracts.validate import validator

HEX64 = "0123456789abcdef" * 4


def _errors(schema: str, doc: dict, target: str) -> list[str]:
    return [r.message for r in validator(schema).validate(doc, target).results]


def test_reader_head_contract_accepts_trust_tier_and_may_propose():
    head = {
        "id": "m-1",
        "epoch": 1,
        "knowledge_time": "2026-01-01T00:00:00Z",
        "access_semantics": 2,
        "definition_sha256": HEX64,
        "manifest_sha256": HEX64,
        "witness_check": "green",
        "trust_tier": "sealed",
        "may_propose": False,
        "compiled": [{"file": "schema/bundle.json", "sha256": HEX64}],
        "snapshots": [
            {"relation": "flagged", "role": "reader", "complete": True, "full": True, "format": "rezono.snapshot/1"}
        ],
    }
    assert _errors("explain.yaml", head, "ReaderHead") == []
    assert _errors("explain.yaml", head | {"trust_tier": "provisional_checked", "may_propose": True}, "ReaderHead") == []
    assert _errors("explain.yaml", head | {"trust_tier": "provisional_engine"}, "ReaderHead") == []
    assert _errors("explain.yaml", head | {"trust_tier": "guessed_tier"}, "ReaderHead")
    assert _errors("explain.yaml", {k: v for k, v in head.items() if k != "may_propose"}, "ReaderHead")


def test_answer_contract_accepts_reader_hashes_and_rejects_bad_digest():
    answer = {
        "format": "rezono.answer/1",
        "question": "grounds",
        "manifest_id": "m-1",
        "nodes": [{"relation": "flagged", "key": '["item-a","12"]', "distance": 0}],
        "reader_hashes": {
            "status": "green",
            "checked_witnesses": [
                {
                    "conclusion": {"relation": "flagged", "key": '["item-a","12"]'},
                    "status": "green",
                    "piece_sha256": HEX64,
                }
            ],
        },
    }
    assert _errors("explain.yaml", answer, "Answer") == []
    bad_hash = {
        **answer,
        "reader_hashes": {
            "status": "green",
            "checked_witnesses": [
                {
                    "conclusion": {"relation": "flagged", "key": '["item-a","12"]'},
                    "status": "green",
                    "piece_sha256": "not-a-sha256",
                }
            ],
        },
    }
    assert _errors("explain.yaml", bad_hash, "Answer")


def test_source_contract_accepts_origin_sign_and_rejects_unknown_sign():
    base = {"kind": "synthetic", "name": "example-generator", "position": "seed:1"}
    assert _errors("source.yaml", base, "Source") == []
    for sign in ("origin_decision", "origin_vendor", "origin_design", "origin_observation"):
        assert _errors("source.yaml", base | {"origin_sign": sign}, "Source") == []
    assert _errors("source.yaml", base | {"origin_sign": "law"}, "Source")
