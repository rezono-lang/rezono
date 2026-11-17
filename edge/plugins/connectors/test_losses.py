"""Every loss list here is in the contract's form and says what the export does (M01, decision N7).

A loss list is a claim about a mapping, so it is tested against the mapping: the terms outside the standard that
an export writes are exactly the terms its `extension` entries name, and an export writes nothing else that the
list does not account for. The exports are the library's (publication/rezono_publication/rdf.py); nothing is converted here.
"""

import json
import re
import sys
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))  # Shared publication test fixtures.

pytest.importorskip("rdflib")
pytest.importorskip("rezono_canon")
pytest.importorskip("linkml")

from linkml.validator import validate  # noqa: E402
from rdflib import Literal  # noqa: E402
from rdflib.namespace import PROV, RDF  # noqa: E402

from rezono_publication import rdf  # noqa: E402

HERE = Path(__file__).parent
CONTRACT = ROOT / "contracts" / "connector.yaml"
CASES = ROOT / "docs" / "publication" / "cases"
LISTS = sorted(HERE.glob("*.losses.yaml"))


def load(name: str) -> dict:
    return yaml.safe_load((HERE / f"{name}.losses.yaml").read_text(encoding="utf-8"))


def problems(document: dict) -> list[str]:
    return [r.message for r in validate(document, str(CONTRACT), "LossList").results]


def terms(document: dict, fate: str) -> set[str]:
    return {t for loss in document["losses"] if loss["fate"] == fate for t in loss["carried_by"]}


def rd(term) -> str:
    return "rd:" + str(term)[len(str(rdf.RD)):]


def test_there_are_loss_lists():
    assert LISTS


@pytest.mark.parametrize("path", LISTS, ids=lambda p: p.name)
def test_a_loss_list_is_in_the_contracts_form(path):
    document = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert problems(document) == []
    # `<standard>.losses.yaml` for out, `<standard>.in.losses.yaml` for in, when a connector maps both ways
    stem = document["connector"].removesuffix("-" + document["direction"])
    assert path.name == stem + (".in" if document["direction"] == "in" else "") + ".losses.yaml"


def test_the_contract_refuses_what_it_does_not_know():
    """The check above means something only if the validator is closed: an unknown field and a free text fail."""
    document = load("rdf")
    assert problems(dict(document, owner="data-office"))
    assert problems(dict(document, losses=["unknown values are left out"]))
    assert problems(dict(document, losses=[{"subject": "proof", "what": "A witness.", "fate": "extension"}]))


# ---------------------------------------------------------------------------------------------------------------
# The RDF view

SCHEMA = json.loads((CASES / "fixture.schema.json").read_text(encoding="utf-8"))
R01 = yaml.safe_load((CASES / "R01.yaml").read_text(encoding="utf-8"))["input"]["$rows"]
SOURCE = {"kind": "pack", "name": "facts/hosts.yaml", "position": "host-a"}
# R01 has a known quantity, an unknown and a not applicable value, an empty set and a proof; a source is added.
ROWS = [dict(R01[0], **{"$src": {"$id": [SOURCE]}}), *R01[1:]]
REIFICATION = {RDF.type, RDF.subject, RDF.predicate, RDF.object}


def test_the_rdf_view_writes_the_extension_terms_its_list_names_and_no_other():
    g = rdf.to_graph(SCHEMA, ROWS)
    written = {rd(t) for triple in g for t in triple if str(t).startswith(str(rdf.RD))}
    listed = terms(load("rdf"), "extension")
    # R01 has no invalid value; `rd:invalid` is written the same way as the other two states (rdf._STATE_TERMS).
    assert written == listed - {"rd:invalid"}
    assert {rd(t) for t in rdf._STATE_TERMS.values()} <= listed


def test_the_rdf_view_writes_nothing_its_list_calls_dropped():
    """Elements, their kinds, their values and the annotations: no schema, rule, role or pin is in the graph."""
    g = rdf.to_graph(SCHEMA, ROWS)
    slots = {rdf.slot_iri(SCHEMA, kind, slot) for kind, k in SCHEMA["kinds"].items() for slot in k["slots"]}
    for _, p, _ in g:
        assert p in REIFICATION or str(p) in slots or str(p).startswith(str(rdf.RD)), p
    text = g.serialize(format="nt")
    assert rdf.schema_iri(SCHEMA) + "types/" in text  # a datatype of the schema names the schema id, and only that
    assert "d-" + "0" * 8 not in text and "role" not in text.lower()
    assert {loss["subject"] for loss in load("rdf")["losses"] if loss["fate"] == "dropped"} == {
        "structure", "rule", "access", "identity"}


def test_a_quantity_is_a_literal_with_a_datatype_of_the_schema():
    """`weakened`: the unit is text in the literal; the datatype is the schema's own, not a unit vocabulary's."""
    g = rdf.to_graph(SCHEMA, ROWS)
    quantities = [o for _, _, o in g if isinstance(o, Literal) and str(o) == "400 GiB"]  # the value and its proof
    assert {str(q.datatype) for q in quantities} == {rdf.schema_iri(SCHEMA) + "types/GiB"}
    assert terms(load("rdf"), "weakened") == {"<schema>/types/<Type>"}


# ---------------------------------------------------------------------------------------------------------------
# PROV-O

WITNESS = {
    "conclusion": {"relation": "host_fits", "key": '["host-a","zone 1"]'},
    "rule_id": "rule.fits",
    "bindings": [{"variable": "H", "value": "host-a"}, {"variable": "Z", "value": "zone 1"}],
    "premises": [
        {"row": {"relation": "host", "key": '["host-a"]'}, "polarity": "positive", "stratum": 0},
        {"row": {"relation": "blocked", "key": '["host-a"]'}, "polarity": "negative", "stratum": 1},
    ],
    "aggregates": [{"relation": "disk", "group_key": '["host-a"]', "count": 2,
                    "contributors_sha256": "a" * 64, "result": "known:2"}],
}
EPOCH = ("m-12", "d-" + "b" * 64)


def prov_graph():
    return rdf.witness_to_prov(WITNESS, *EPOCH, sources={("host", '["host-a"]'): [SOURCE]})


def test_the_prov_export_writes_the_extension_terms_its_list_names_and_no_other():
    g = prov_graph()
    written = {rd(t) for triple in g for t in triple if str(t).startswith(str(rdf.RD))}
    assert written == terms(load("prov-o"), "extension")
    for _, p, _ in g:  # everything else is PROV-O itself, or rdf:type
        assert p == RDF.type or str(p).startswith((str(PROV), str(rdf.RD))), p


def test_the_prov_list_names_every_term_the_library_says_is_lost():
    named = {t for line in rdf.PROV_LOSS for t in re.findall(r"rd:[A-Za-z]+", line)}
    assert named and named <= terms(load("prov-o"), "extension")


def test_a_reader_of_prov_o_alone_keeps_the_positive_route_and_loses_the_rest():
    g = prov_graph()
    alone = [t for t in g if not any(str(x).startswith(str(rdf.RD)) for x in t)]
    conclusion, host, blocked = (rdf.row_iri(r) for r in (
        WITNESS["conclusion"], WITNESS["premises"][0]["row"], WITNESS["premises"][1]["row"]))
    activity = rdf.witness_iri(WITNESS)
    assert (conclusion, PROV.wasGeneratedBy, activity) in alone
    assert (activity, PROV.used, host) in alone and (conclusion, PROV.wasDerivedFrom, host) in alone
    assert not [t for t in alone if t[0] == activity and t[2] == blocked]  # the negative premise is not used
    assert not [t for t in alone if isinstance(t[2], Literal) and str(t[2]) == WITNESS["rule_id"]]  # nor the rule


def test_a_source_is_a_literal_on_was_derived_from():
    """`weakened`: the reader sees that the base row was derived from something, as JSON text."""
    g = prov_graph()
    sources = [o for _, p, o in g if p == PROV.wasDerivedFrom and isinstance(o, Literal)]
    assert [json.loads(str(s)) for s in sources] == [SOURCE] and sources[0].datatype == RDF.JSON
    assert terms(load("prov-o"), "weakened") == {"prov:wasDerivedFrom"}
