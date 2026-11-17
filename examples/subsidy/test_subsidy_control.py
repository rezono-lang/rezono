"""DV1 on subsidy: the scheme's parameters are decided values (`plane: control` on SchemeParameter). A planted
direct delta on them is refused with its reason, the same way in batch (the compiler's loader) and in the step
the live service admits through (rede_admission against the archived schema bundle). A reviewed batch whose rows
name their decision is admitted, and a delta on a data-plane kind needs no review."""

import json
from pathlib import Path

import pytest

from rede_admission import Admission, Schema

pytest.importorskip("rede_compiler")

from rede_compiler import facts, pack  # noqa: E402

HERE = Path(__file__).parent
BUNDLE = HERE / "expected" / "compiled" / "bundle" / "schema-bundle.json"
PLANTED = {"id": "par-99", "name": "maximum_award", "value": 900000, "unit": "cents", "valid_from": "2026-01-01",
           "valid_until": "2027-01-01", "article": "art-7"}


def test_a_scheme_parameter_without_its_decision_is_refused_in_batch():
    model = pack.read(HERE)
    with pytest.raises(facts.LoadError, match=r"scheme_parameter\[1\]\.decision: a decided value names its decision"):
        facts.rows_of(model, {"scheme_parameter": [PLANTED]})
    assert facts.rows_of(model, {"scheme_parameter": [PLANTED | {"decision": "2025-112"}]})


def test_a_direct_delta_on_the_scheme_parameters_is_refused_by_the_service_s_admission():
    schema = Schema(json.loads(BUNDLE.read_text(encoding="utf-8")))
    assert schema.control("scheme_parameter") and not schema.control("application")
    step = Admission(schema)
    direct = step.admit({"scheme_parameter": [PLANTED | {"decision": "2025-112"}]}, source="in-port", event="e1")
    assert [(r.code, r.where) for r in direct.refusals] == [("control_unreviewed", "scheme_parameter")]
    assert direct.refusals[0].schema == schema.sha256
    unnamed = step.admit({"scheme_parameter": [PLANTED]}, source="git", event="e2", reviewed="proposal")
    assert [(r.code, r.where) for r in unnamed.refusals] == [("decision_missing", "scheme_parameter[1].decision")]
    assert step.admit({"scheme_parameter": [PLANTED | {"decision": "2025-112"}]}, source="git", event="e3",
                      reviewed="proposal").admitted
    data = {"household": [{"id": "h-99", "persons": 2}]}
    assert step.admit(data, source="in-port", event="e4").admitted, "a data-plane delta needs no review"
