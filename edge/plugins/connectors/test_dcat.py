"""The DCAT entry of a published epoch (M10, decision O12a): what it says, back and forth, and what it leaves out.

There is no validator of plain DCAT to hold it against, and the DCAT-AP shapes are not in the repository, so
the entry is checked four ways: the exact triples for one input; a round trip through Turtle that gives the
input back; the names it shares with the other exports (the PROV-O bundle of the epoch, the shapes document,
the media types of docs/publication/l0.md §7); and its terms against the vocabularies rdflib ships, which know
DCAT and Dublin Core and nothing of this entry.
"""

import json
import re
import sys
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))  # Shared publication test fixtures.

from linkml.validator import validate as linkml_validate  # noqa: E402
from rdflib import BNode, Graph, Literal, URIRef  # noqa: E402
from rdflib.namespace import DCTERMS, RDF  # noqa: E402

from rezono_publication import l0, rdf  # noqa: E402
from publication.tests.test_l0 import FIXTURE, TYPES, merge  # noqa: E402

import dcat  # noqa: E402  (this directory)
import shacl  # noqa: E402

HERE = Path(__file__).parent
LOSSES = yaml.safe_load((HERE / "dcat.losses.yaml").read_text(encoding="utf-8"))
PIN = {"manifest": "m-12", "dataset": "d-" + "b" * 64}
AT = "https://data.example/fixture/m-12/reader/"
FILES = {"row-json": AT + "rows.json", "json-ld": AT + "rows.jsonld", "turtle": AT + "rows.ttl",
         "parquet": AT + "parquet/"}
SID = l0.schema_id(FIXTURE)
SPACE = f"https://rezono.example/fixture/{SID}/"
EPOCH = URIRef(f"rezono:m/m-12@{PIN['dataset']}")
IANA = "https://www.iana.org/assignments/media-types/"


def test_the_entry_of_an_epoch_is_these_triples_and_no_other():
    d, c = dcat.DCAT, DCTERMS.conformsTo
    profile = URIRef("https://rezono.org/publication/1.0")
    context, shapes, contract = (URIRef(SPACE + name) for name in ("context.jsonld", "shapes.ttl", "contract.odcs.yaml"))
    row, ld, ttl, parquet = (URIRef(f"{EPOCH}#{form}") for form in ("row-json", "json-ld", "turtle", "parquet"))
    expected = {
        (EPOCH, RDF.type, d.Dataset),
        (EPOCH, DCTERMS.identifier, Literal(f"fixture@{SID}@m-12@{PIN['dataset']}")),
        (EPOCH, d.version, Literal("m-12")),
        (EPOCH, c, URIRef(SPACE)),
        *((EPOCH, d.distribution, x) for x in (row, ld, ttl, parquet)),
        *((x, RDF.type, d.Distribution) for x in (row, ld, ttl, parquet)),
        (row, d.accessURL, URIRef(AT + "rows.json")), (row, d.mediaType, URIRef(IANA + "application/json")),
        (row, c, profile),
        (ld, d.accessURL, URIRef(AT + "rows.jsonld")), (ld, d.mediaType, URIRef(IANA + "application/ld+json")),
        (ld, c, profile), (ld, c, context), (ld, c, shapes),
        (ttl, d.accessURL, URIRef(AT + "rows.ttl")), (ttl, d.mediaType, URIRef(IANA + "text/turtle")),
        (ttl, c, shapes),
        (parquet, d.accessURL, URIRef(AT + "parquet/")),
        (parquet, d.mediaType, URIRef(IANA + "application/vnd.apache.parquet")),
        (parquet, c, contract),
    }
    assert set(dcat.entry(FIXTURE, PIN, FILES)) == expected


@pytest.mark.parametrize("schema", [FIXTURE, TYPES], ids=["the fixture", "every type"])
@pytest.mark.parametrize("forms", [list(FILES), ["parquet"], ["turtle", "row-json"]], ids=lambda f: "+".join(f))
def test_out_and_back_through_turtle_gives_the_input(schema, forms):
    files = {form: FILES[form] for form in forms}
    back = dcat.read(Graph().parse(data=dcat.to_turtle(schema, PIN, files), format="turtle"))
    held = dcat.descriptors(schema)
    assert back == {
        "identifier": f"{schema['pack']}@{l0.schema_id(schema)}@{PIN['manifest']}@{PIN['dataset']}",
        "version": PIN["manifest"], "pin": PIN, "schema": rdf.schema_iri(schema), "files": files,
        "conforms": {form: sorted(held[document] for document in dcat.FORMS[form][1]) for form in forms}}


def test_a_relative_address_is_read_against_the_entry_s_own_address():
    """As the publisher writes it beside a role's form (RV-K20): no host in the bytes, the reader's site resolves."""
    files = {"row-json": "rows.json", "turtle": "view.ttl"}
    text = dcat.to_turtle(FIXTURE, PIN, files)
    assert "https://data.example" not in text and "<rows.json>" in text
    back = dcat.read(Graph().parse(data=text, format="turtle", publicID=AT + "dcat.ttl"))
    assert back["files"] == {form: AT + name for form, name in files.items()}


def test_the_dataset_has_the_name_of_the_prov_bundle_of_its_epoch():
    witness = {"conclusion": {"relation": "host", "key": '["host-a"]'}, "rule_id": "rule.host", "bindings": [],
               "premises": [], "aggregates": []}
    bundle = rdf.witness_to_prov(witness, PIN["manifest"], PIN["dataset"]).identifier
    assert dcat.dataset_iri(PIN) == bundle == EPOCH


def test_the_documents_a_form_holds_to_are_beside_the_schema_id():
    held = dcat.descriptors(FIXTURE)
    assert held["shapes"] == shacl.document_iri(FIXTURE)
    assert held["context"] == rdf.schema_iri(FIXTURE) + "context.jsonld"  # §5
    assert held["profile"] + "#" == str(rdf.RD)
    assert all(held[d].startswith(rdf.schema_iri(FIXTURE)) for d in ("context", "shapes", "contract"))


@pytest.mark.xfail(strict=True, reason="docs/publication/l0.md is not in the standalone repository yet")
def test_the_media_types_are_those_of_the_specification():
    """§7 of docs/publication/l0.md is the one place that names them."""
    text = (ROOT / "docs" / "publication" / "l0.md").read_text(encoding="utf-8")
    table = dict(re.findall(r"^\| ([A-Za-z -]+?) (?:view )?\| `([a-z.+/-]+)`", text, flags=re.M))
    named = {"row-json": "Row JSON", "json-ld": "JSON-LD", "turtle": "Turtle", "parquet": "Parquet"}
    assert {form: table[row] for form, row in named.items()} == {form: media for form, (media, _) in dcat.FORMS.items()}


def test_every_term_is_one_dcat_or_dublin_core_has():
    """rdflib's vocabularies are closed: a misspelt term is not in them. `dcat:version` is new in DCAT 3."""
    from rdflib.namespace import DCAT as DCAT2  # here: pytest's collection trips over a closed namespace
    g = dcat.entry(FIXTURE, PIN, FILES)
    terms = {p for _, p, _ in g} | {o for _, p, o in g if p == RDF.type}
    assert not [t for triple in g for t in triple if isinstance(t, BNode)]
    known = set(dir(DCAT2)) | set(dir(DCTERMS)) | {dcat.DCAT.version}  # `dir` of a closed namespace: its terms
    assert terms - {RDF.type} <= known
    assert sorted(o for _, _, o in g if isinstance(o, Literal)) == sorted(
        [Literal("m-12"), Literal(dcat.identifier(FIXTURE, PIN))])  # no other text, so no clock and no label


@pytest.mark.parametrize("pin, files, fragment", [
    ({"dataset": PIN["dataset"]}, FILES, "pinned by `manifest` and `dataset`"),
    ({**PIN, "role": "reader"}, FILES, "and nothing else"),
    ({"manifest": "12", "dataset": PIN["dataset"]}, FILES, "m-<epoch>"),
    ({"manifest": "m-12", "dataset": "d-4be1"}, FILES, "hash pin"),
    (PIN, {}, "at least one form"),
    (PIN, {"csv": AT + "rows.csv"}, "not a form this entry knows"),
    (PIN, {"turtle": "/rows.ttl"}, "an absolute IRI"),
    (PIN, {"turtle": "../rows.ttl"}, "an absolute IRI"),
    (PIN, {"turtle": "a/./rows.ttl"}, "an absolute IRI"),
    (PIN, {"turtle": "//host/rows.ttl"}, "an absolute IRI"),
], ids=["no epoch pin", "a role in the pin", "not a manifest id", "a short hash", "no form", "an unknown form",
        "a path from the root", "a dot segment up", "a dot segment", "a host without a scheme"])
def test_what_has_no_entry_is_refused(pin, files, fragment):
    with pytest.raises(dcat.DcatError, match=re.escape(fragment)):
        dcat.entry(FIXTURE, pin, files)


def test_a_schema_document_the_library_refuses_has_no_entry():
    with pytest.raises(l0.L0Error):
        dcat.entry(merge(FIXTURE, {"kinds": {"Host": {"world": None}}}), PIN, FILES)


def test_a_graph_that_is_not_an_entry_is_not_read():
    g = dcat.entry(FIXTURE, PIN, FILES)
    with pytest.raises(dcat.DcatError, match="exactly one dataset"):
        dcat.read(Graph())
    other = URIRef("https://data.example/elsewhere")
    g.add((dcat.dataset_iri(PIN), dcat.DCAT.distribution, other))
    with pytest.raises(dcat.DcatError, match="not a distribution of this entry"):
        dcat.read(g)


def test_the_turtle_is_the_same_text_each_time():
    text = dcat.to_turtle(FIXTURE, PIN, FILES)
    assert text == dcat.to_turtle(json.loads(json.dumps(FIXTURE)), dict(PIN), dict(reversed(FILES.items())))
    assert "_:" not in text and "[" not in text


def test_the_command_prints_the_entry(tmp_path, capsys):
    path = tmp_path / "schema.json"
    path.write_text(json.dumps(FIXTURE), encoding="utf-8")
    assert dcat.main([str(path), PIN["manifest"], PIN["dataset"], f"turtle={FILES['turtle']}"]) == 0
    printed = Graph().parse(data=capsys.readouterr().out, format="turtle")
    assert set(printed) == set(dcat.entry(FIXTURE, PIN, {"turtle": FILES["turtle"]}))
    assert dcat.main([str(path), PIN["manifest"], PIN["dataset"]]) == 2


# ---------------------------------------------------------------------------------------------------------------
# The loss list


def short(term) -> str:
    for prefix, space in (("dcat", dcat.DCAT), ("dct", DCTERMS)):
        if str(term).startswith(str(space)):
            return f"{prefix}:{str(term)[len(str(space)):]}"
    return str(term)


def test_the_loss_list_is_in_the_contracts_form():
    report = linkml_validate(LOSSES, str(ROOT / "contracts" / "connector.yaml"), "LossList")
    assert [r.message for r in report.results] == []


def test_the_entry_is_plain_dcat_and_keeps_what_is_weakened_where_the_list_says():
    written = {short(p) for _, p, _ in dcat.entry(FIXTURE, PIN, FILES)}
    by_fate = {fate: {t for loss in LOSSES["losses"] if loss["fate"] == fate for t in loss.get("carried_by", [])}
               for fate in ("extension", "weakened")}
    assert by_fate["extension"] == set()
    assert by_fate["weakened"] == {"dct:identifier", "dct:conformsTo", "dcat:version"} <= written


def test_the_entry_writes_nothing_its_list_calls_dropped():
    written = {short(p) for _, p, _ in dcat.entry(FIXTURE, PIN, FILES)}
    assert not written & {"dct:title", "dct:description", "dct:publisher", "dct:license", "dct:issued",
                          "dct:accessRights", "dct:audience"}
    assert "reader" not in dcat.to_turtle(FIXTURE, PIN, {"parquet": "https://data.example/p/"})  # nor the role
    assert {loss["subject"] for loss in LOSSES["losses"] if loss["fate"] == "dropped"} == {
        "text", "access", "proof", "rule"}
