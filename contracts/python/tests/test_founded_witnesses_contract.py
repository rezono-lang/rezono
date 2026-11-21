"""Contract test for founded witnesses and load-bearing steps (decisions/publish-founded-witnesses.md, #1445).

Verifies that contracts/explain.yaml validates an Answer carrying multiple founded AnswerWitness records
for one conclusion (each with its canonical <base>witness/<64 hex> IRI), AnswerNode.witnesses_truncated,
and AnswerStep.load_bearing, while refusing a malformed witness IRI.
"""

from pathlib import Path

from linkml.validator import validate

ROOT = Path(__file__).resolve().parents[3]
EXPLAIN = str(ROOT / "contracts" / "explain.yaml")

HASH_A = "a" * 64
HASH_B = "b" * 64


def _sample_answer(*, iri_a=f"https://example.org/p/witness/{HASH_A}", iri_b=f"https://example.org/p/witness/{HASH_B}"):
    return {
        "format": "rezono.answer/1",
        "question": "grounds",
        "manifest_id": "m-1",
        "start": {"relation": "near", "key": '["a","b"]'},
        "nodes": [
            {"relation": "near", "key": '["a","b"]', "distance": 0, "witnesses_truncated": False},
            {"relation": "edge", "key": '["b","a"]', "distance": 1},
            {"relation": "edge", "key": '["a","b"]', "distance": 1},
        ],
        "steps": [
            {
                "conclusion": {"relation": "near", "key": '["a","b"]'},
                "premise": {"relation": "edge", "key": '["b","a"]'},
                "how": "positive",
                "position": 0,
                "load_bearing": False,
            },
            {
                "conclusion": {"relation": "near", "key": '["a","b"]'},
                "premise": {"relation": "edge", "key": '["a","b"]'},
                "how": "positive",
                "position": 0,
                "load_bearing": False,
            },
        ],
        "witnesses": [
            {
                "conclusion": {"relation": "near", "key": '["a","b"]'},
                "rule_id": "near_in",
                "bindings": [{"variable": "?a", "value": "a"}, {"variable": "?b", "value": "b"}],
                "premises": [
                    {"row": {"relation": "edge", "key": '["b","a"]'}, "polarity": "positive", "stratum": 0}
                ],
                "iri": iri_a,
            },
            {
                "conclusion": {"relation": "near", "key": '["a","b"]'},
                "rule_id": "near_out",
                "bindings": [{"variable": "?a", "value": "a"}, {"variable": "?b", "value": "b"}],
                "premises": [
                    {"row": {"relation": "edge", "key": '["a","b"]'}, "polarity": "positive", "stratum": 0}
                ],
                "iri": iri_b,
            },
        ],
    }


def test_explain_contract_accepts_multiple_founded_witnesses_with_iri_and_load_bearing():
    report = validate(_sample_answer(), EXPLAIN, "Answer")
    assert [r.message for r in report.results] == []


def test_explain_contract_rejects_malformed_witness_iri():
    bad = _sample_answer(iri_a="https://example.org/p/witness/not-64-hex")
    report = validate(bad, EXPLAIN, "Answer")
    assert report.results, "malformed AnswerWitness.iri must be rejected by contracts/explain.yaml"
