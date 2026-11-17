"""A pack's invariants as SHACL-SPARQL against Rede's own result (M08 second half; shacl_sparql.py).

pySHACL is the oracle: it knows SHACL and SPARQL and nothing of Rede. It validates the RDF view of a dataset
through the constraints made from the rule IR, and per invariant it must report exactly the rows that Rede's
batch engine (`rede_compiler.batch`, DuckDB) derives from the same facts. A difference is a defect in one of the
two, and fails the test. The pack is `fixtures/checks`: neutral names, an invariant per construct the
translation knows (an aggregate over an empty group, negation, a division, two rules, a constant in the head, a
repeated variable) and a recursive one it refuses.
"""

import json
import random
import sys
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))  # reckon_data is a directory of the repository, not an installed package

pytest.importorskip("duckdb")
pytest.importorskip("pyshacl")

import pyshacl  # noqa: E402
from rdflib import Graph, Literal  # noqa: E402
from rdflib.namespace import RDF, SH  # noqa: E402
from rede_compiler import batch, emit, facts, pack  # noqa: E402
from rede_compiler import rules as ir  # noqa: E402

from reckon_data import publication, rdf  # noqa: E402

import accept  # noqa: E402  (this directory)
import shacl_sparql  # noqa: E402

PACK = pack.read(Path(__file__).parent / "fixtures" / "checks")
FILES = emit.compile_pack(PACK)
BUNDLE = json.loads(FILES["bundle/schema-bundle.json"])
RULES = json.loads(FILES["ir/rules.json"])
PROG = ir.load(RULES)
CARRIED = ("big", "empty_group", "odd_half", "over_limit", "self_next", "ungrouped")
G1 = "g 1/ü~"  # an id that only its spelling keeps in an IRI (§3.4): a space, a slash, two bytes and a `~`
CRAFTED = {
    "group": [{"id": G1, "title": "a", "limit": 3}, {"id": "g2", "title": "b", "limit": 100},
              {"id": "g3", "title": "c"}],
    "item": [{"id": "i1", "group": G1, "size": 2, "state": "high", "next": ["i1", "i2"]},
             {"id": "i2", "group": G1, "size": 5, "state": "low", "next": ["i1"]},
             {"id": "i3", "size": -4},
             {"id": "i4", "group": "g2", "size": 7, "state": "high"}],
}


def compare(records: dict) -> dict:
    """Rede's invariants and pySHACL's results on the same facts; accept.checks raises on a difference."""
    data = facts.rows_of(PACK, records)
    con = batch.connect(PROG, data)
    batch.compute(con, PROG)
    derived = batch.read(con, PROG)
    doc, plan = publication.schema_document(BUNDLE)
    stored = {t: [tuple(str(v) for v in r) for r in rs] for t, rs in data.items()}  # the store holds text
    rows = publication.row_json(doc, plan, {"rows": stored, "witnesses": [], "sources": []})
    return accept.checks(BUNDLE, RULES, doc, rows, derived)


def test_every_invariant_agrees_with_rede_and_each_has_rows():
    result = compare(CRAFTED)
    assert {n for n, r in result.items() if r["state"] == "carried"} == set(CARRIED)
    assert all(result[n]["rows"] for n in CARRIED), result  # each invariant is broken, so the test means something
    assert "g~201~2F~C3~BC~7E/7" in result["over_limit"]["rows"]
    assert set(result["odd_half"]["rows"]) == {"i1/0", "i3/-8"}  # 2 / 3 truncates to 0; -4 * 2


def test_a_recursive_invariant_is_deactivated_with_its_reason():
    result = compare(CRAFTED)
    assert result["cycle"]["state"] == "deactivated"
    assert "recursive" in result["cycle"]["reason"]


@pytest.mark.parametrize("seed", range(12))
def test_random_datasets_agree(seed):
    r = random.Random(seed)  # a fixed seed: the same datasets on every run
    groups = [G1, "g2", "g3", "g4"][: r.randint(1, 4)]
    items = [f"i{n}" for n in range(r.randint(0, 7))]
    records = {"group": [], "item": []}
    for g in groups:
        record = {"id": g, "title": r.choice("ab")}
        if r.random() < 0.7:
            record["limit"] = r.randint(0, 12)
        records["group"].append(record)
    for i in items:
        record = {"id": i}
        if r.random() < 0.8:
            record["group"] = r.choice(groups)
        if r.random() < 0.8:
            record["size"] = r.randint(-6, 9)
        if r.random() < 0.6:
            record["state"] = r.choice(["low", "high"])
        nxt = sorted({r.choice(items) for _ in range(r.randint(0, 2))})
        if nxt:
            record["next"] = nxt
        records["item"].append(record)
    compare(records)


def test_a_dataset_that_breaks_no_invariant_conforms():
    records = {"group": [{"id": "g2", "title": "b", "limit": 100}],
               "item": [{"id": "i4", "group": "g2", "size": 1, "state": "low"}]}
    result = compare(records)
    assert all(r["rows"] == [] for r in result.values() if r["state"] == "carried")
    data = facts.rows_of(PACK, records)
    doc, plan = publication.schema_document(BUNDLE)
    stored = {t: [tuple(str(v) for v in r) for r in rs] for t, rs in data.items()}
    view = rdf.to_graph(doc, publication.row_json(doc, plan, {"rows": stored, "witnesses": [], "sources": []}))
    conforms, _, text = pyshacl.validate(view, shacl_graph=shacl_sparql.checks(BUNDLE, RULES), advanced=True)
    assert conforms, text


def test_rede_writes_the_report_a_validator_writes():
    """Rede's violations as a SHACL validation report (`report`) hold the results pySHACL reports through the
    constraints: the same focus node, value, shape, constraint, component and severity per result."""
    data = facts.rows_of(PACK, CRAFTED)
    con = batch.connect(PROG, data)
    batch.compute(con, PROG)
    derived = {n: rs for n, rs in batch.read(con, PROG).items() if n in CARRIED}
    doc, plan = publication.schema_document(BUNDLE)
    stored = {t: [tuple(str(v) for v in r) for r in rs] for t, rs in data.items()}
    view = rdf.to_graph(doc, publication.row_json(doc, plan, {"rows": stored, "witnesses": [], "sources": []}))
    _, theirs, _ = pyshacl.validate(view, shacl_graph=shacl_sparql.checks(BUNDLE, RULES), advanced=True)
    ours = shacl_sparql.report(BUNDLE, RULES, derived)
    terms = (SH.focusNode, SH.value, SH.sourceShape, SH.sourceConstraint, SH.sourceConstraintComponent,
             SH.resultSeverity)

    def results(g):
        return {tuple(g.value(r, t) for t in terms) for r in g.subjects(RDF.type, SH.ValidationResult)}

    assert results(ours) == results(theirs) and len(results(ours)) >= len(CARRIED)
    assert set(ours.objects(None, SH.conforms)) == set(theirs.objects(None, SH.conforms)) == {Literal(False)}


def test_a_difference_with_rede_is_not_accepted():
    """The comparison is not vacuous: a row Rede did not derive, or one it did that SHACL misses, fails."""
    doc, plan = publication.schema_document(BUNDLE)
    data = facts.rows_of(PACK, CRAFTED)
    stored = {t: [tuple(str(v) for v in r) for r in rs] for t, rs in data.items()}
    rows = publication.row_json(doc, plan, {"rows": stored, "witnesses": [], "sources": []})
    with pytest.raises(accept.NotAccepted, match="ungrouped"):
        accept.checks(BUNDLE, RULES, doc, rows, {"ungrouped": [("i1",)]})


@pytest.mark.parametrize("value", ["", "plain-._x", ".", "..", "...", "a.b", "~", "a~b", "%", "%7E", "~7E", "g 1/ü", "€",
                                   "a@m-1@d-ff", 'q"\\', "a b\tc", "a%2Fb", "~~", "%~%"])
def test_a_value_is_spelled_in_sparql_as_an_element_iri_spells_an_id(value):
    """A text has one canonical form, the spelling of an id in an IRI (`rdf.spell`, §3.4). A constraint spells a
    slot's value with a SPARQL expression and reads an element's id from its IRI; the two meet only if the
    expression gives what `rdf.spell` gives, for every text: also for `~`, `%`, a dot segment and the empty text."""
    query = f"SELECT ({shacl_sparql._spelled('?o')} AS ?s) WHERE {{ BIND({shacl_sparql._string(value)} AS ?o) }}"
    (row,) = Graph().query(query)
    assert str(row[0]) == rdf.spell(value) == shacl_sparql.text(value)


def test_the_shapes_are_the_same_bytes_and_plain_shacl_sparql():
    text = shacl_sparql.to_turtle(BUNDLE, RULES)
    assert text == shacl_sparql.to_turtle(BUNDLE, RULES)
    shapes = shacl_sparql.checks(BUNDLE, RULES)
    for query in shapes.objects(None, SH.select):
        # SHACL §5.3.1: no MINUS, VALUES or SERVICE in a SPARQL constraint; the rule IR is the only source
        assert not {"MINUS", "VALUES", "SERVICE"} & set(str(query).split()), query
    names = {str(n) for n in shapes.objects(None, SH.name)}
    assert names == {n for n, rel in PROG.relations.items() if rel.invariant}
    assert (None, SH.name, Literal("cycle")) in shapes


def test_the_loss_list_matches_the_shapes():
    """The constraints write SHACL terms only (no extension), and every term a `weakened` entry names is one they
    write, or the result's value."""
    losses = yaml.safe_load((Path(__file__).parent / "shacl-sparql.losses.yaml").read_text(encoding="utf-8"))
    assert not [loss for loss in losses["losses"] if loss["fate"] == "extension"]
    shapes = shacl_sparql.checks(BUNDLE, RULES)
    used = {p for p in shapes.predicates()}
    assert used <= {RDF.type} | {p for p in used if str(p).startswith(str(SH))}
    named = {t for loss in losses["losses"] if loss["fate"] == "weakened" for t in loss["carried_by"]}
    assert {SH[t.removeprefix("sh:")] for t in named} - used == {SH.value}  # sh:value is in the report
