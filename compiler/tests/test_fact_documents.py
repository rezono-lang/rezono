"""AUD-C5: a fact file states its records explicitly. A null document or a null section is refused rather
than read as "no records": an empty relation is written as [] and a file without records as {} (P4)."""

import pytest

from support import FIXTURE
from rezono_compiler import facts, pack, scenarios


@pytest.fixture(scope="module")
def model():
    return pack.read(FIXTURE)


REFUSED = {
    "empty-file": ("", "null document"),
    "null-document": ("~\n", "null document"),
    "list-document": ("- {id: a, title: t}\n", "mapping of kind to records"),
    "null-section": ("alpha:\n", "section 'alpha' is null"),
    "explicit-null-section": ("alpha: null\n", "section 'alpha' is null"),
    "mapping-section": ("alpha: {id: a, title: t}\n", "section 'alpha' is not a list"),
}


@pytest.mark.parametrize("text, message", REFUSED.values(), ids=REFUSED.keys())
def test_the_loader_refuses_a_null_document_or_section(model, tmp_path, text, message):
    (tmp_path / "facts.yaml").write_text(text, encoding="utf-8")
    with pytest.raises(facts.LoadError, match=message):
        facts.load(model, tmp_path / "facts.yaml")


@pytest.mark.parametrize("text, message", REFUSED.values(), ids=REFUSED.keys())
def test_scenario_records_refuse_a_null_document_or_section(model, tmp_path, text, message):
    (tmp_path / "s1.yaml").write_text(text, encoding="utf-8")
    with pytest.raises(facts.LoadError, match=f"s1.yaml: .*{message}"):
        scenarios.records(model, tmp_path / "s1.yaml")


def test_rows_of_refuses_a_null_section(model):
    with pytest.raises(facts.LoadError, match="section 'alpha' is null"):
        facts.rows_of(model, {"alpha": None})


@pytest.mark.parametrize("text", ["{}\n", "alpha: []\n"], ids=["empty-mapping", "empty-section"])
def test_an_explicit_empty_relation_loads_as_no_rows(model, tmp_path, text):
    (tmp_path / "facts.yaml").write_text(text, encoding="utf-8")
    assert not any(facts.load(model, tmp_path / "facts.yaml").get(t) for t in model.kinds)
    assert scenarios.records(model, tmp_path / "facts.yaml") == []
