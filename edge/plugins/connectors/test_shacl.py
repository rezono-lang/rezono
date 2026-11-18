"""The SHACL shapes of a publication schema against an independent validator (M08; docs/publication/l0.md §5).

pySHACL is the oracle: it knows SHACL and nothing of the publication. On the conformance fixtures the shapes accept
what the library's reader accepts, and each defect a shape can name is refused by both: by pySHACL through the
shapes, and by the reader (`rdf.from_graph`, or `l0.read_rows` for what RDF cannot hold as a row). A difference
is a defect in one of the two.
"""

import sys
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))  # Shared publication test fixtures.

import pyshacl  # noqa: E402
from rdflib import BNode, Graph, Literal, URIRef  # noqa: E402
from rdflib.namespace import RDF, RDFS, SH, XSD  # noqa: E402

from rezono_publication import l0, rdf  # noqa: E402
from publication.tests.test_l0 import (  # noqa: E402
    FILES, FIXTURE, R01, THING, TREE, TREE_ROWS, TYPES, merge, rows_of, schema_of)
from publication.tests.test_rdf import canon  # noqa: E402

import shacl  # noqa: E402  (this directory)

HERE = Path(__file__).parent
BASE = FIXTURE["base"]
A, B = (URIRef(rdf.element_iri(FIXTURE, "Host", i)) for i in ("host-a", "host-b"))
MEMORY, OWNER, TAGS = (URIRef(rdf.slot_iri(FIXTURE, "Host", s)) for s in ("memory_need", "owner", "tags"))
GIB = URIRef(rdf.schema_iri(FIXTURE) + "types/GiB")

# A schema that declares its reason codes (§2.3), and one with a slot of the core type Integer with bounds.
REASONS = merge(FIXTURE, {"reasons": {"not_assigned": {"label": {"en": "Not assigned"}, "states": ["unknown"]}}})
COUNTED = merge(FIXTURE, {"kinds": {"Team": {"slots": {
    "size": {"card": "1", "type": "Integer", "states": ["known"], "min": "0", "max": "10"}}}}})
TEAM = {"$kind": "Team", "$id": "t1", "size": "5"}  # text: LD2 follows the bounds of a type, not of a slot
THINGS = [dict(THING, hosts=[{"$ref": "host-a"}]), *R01]


def validate(schema: dict, graph: Graph):
    """(conforms, the shapes that reported a violation) from pySHACL; the shapes graph itself is checked too."""
    conforms, report, _ = pyshacl.validate(graph, shacl_graph=shacl.shapes(schema), meta_shacl=True)
    return conforms, {str(s).rsplit("#", 1)[-1] for s in report.objects(None, SH.sourceShape) if isinstance(s, URIRef)}


def reader_refuses(schema: dict, graph: Graph) -> bool:
    try:
        rdf.from_graph(schema, graph)
    except l0.L0Error:
        return True
    return False


def state(g: Graph, term, reason: str = "") -> BNode:
    node = BNode()
    g.add((node, term, Literal(reason)))
    return node


def replace(g: Graph, subject, predicate, *objects):
    g.remove((subject, predicate, None))
    for o in objects:
        g.add((subject, predicate, o))


# ---------------------------------------------------------------------------------------------------------------
# What the reader accepts, the shapes accept


@pytest.mark.parametrize("schema, rows", [(FIXTURE, R01), (TYPES, THINGS), (REASONS, R01), (COUNTED, [TEAM, *R01])],
                         ids=["R01", "every type", "declared reasons", "a bounded integer"])
def test_a_dataset_the_reader_accepts_conforms(schema, rows):
    assert validate(schema, rdf.to_graph(schema, rows)) == (True, set())


SETTLED_ROWS = sorted(cid for cid, case in FILES.items()
                      if case["class"] == "valid" and case["status"] == "settled"
                      and case["form"] in {"row", "rows", "collection"})
# An element with multiple versions has no node mapping. An imported reference carries no target base IRI.
NO_RDF_FORM = {"V02": "Q13", "P01": "Q20"}


def assert_no_rdf_form(schema, rows, question):
    assert l0.read_rows(schema, rows) == rows
    with pytest.raises(rdf.RdfError, match=rf"\({question}\)"):
        rdf.to_graph(schema, rows)
    with pytest.raises(rdf.RdfError, match=rf"\({question}\)"):
        shacl.shapes(schema)


@pytest.mark.parametrize("cid", SETTLED_ROWS)
def test_every_valid_case_with_an_rdf_form_conforms(cid):
    case = FILES[cid]
    assert case["expect"]["accept"] is True
    schema, rows = schema_of(case), rows_of(case)
    if cid in NO_RDF_FORM:
        assert_no_rdf_form(schema, rows, NO_RDF_FORM[cid])
        return
    graph = rdf.to_graph(schema, rows)
    assert validate(schema, graph) == (True, set())
    assert canon(rdf.from_graph(schema, graph)) == canon(rows)


def test_public_corpus_has_at_least_three_graph_cases():
    graph_cases = set(SETTLED_ROWS) - NO_RDF_FORM.keys()
    assert len(graph_cases) >= 3, sorted(graph_cases)


def test_public_corpus_has_at_least_five_rdf_comparisons():
    assert len(SETTLED_ROWS) >= 5, SETTLED_ROWS


# ---------------------------------------------------------------------------------------------------------------
# What a shape can name, both refuse

def missing(g):
    g.remove((A, MEMORY, None))


def two_values(g):
    g.add((A, MEMORY, Literal("1 GiB", datatype=GIB)))


def untyped(g):
    replace(g, A, MEMORY, Literal("400 GiB"))


def no_unit(g):
    replace(g, A, MEMORY, Literal("400", datatype=GIB))


def state_not_listed(g):  # memory_need takes `unknown` only
    replace(g, A, MEMORY, state(g, rdf.RD.notApplicable))


def state_with_two_properties(g):
    node = state(g, rdf.RD.unknown)
    g.add((node, rdf.RD.invalid, Literal("")))
    replace(g, A, MEMORY, node)


def reason_not_a_code(g):
    replace(g, A, MEMORY, state(g, rdf.RD.unknown, "Not Assigned"))


def core_code_of_another_state(g):  # `empty` labels not_applicable only
    replace(g, A, MEMORY, state(g, rdf.RD.unknown, "empty"))


def set_mixed_with_the_empty_set(g):
    g.add((A, TAGS, rdf.RD.emptySet))


def set_as_a_state(g):  # tags takes no state
    replace(g, A, TAGS, state(g, rdf.RD.unknown))


def reference_into_another_kind(g):
    replace(g, B, OWNER, B)


def reference_as_text(g):
    replace(g, B, OWNER, Literal("team-1"))


def element_outside_its_kind(g):
    other = URIRef("https://elsewhere.example/host-a")
    for p, o in list(g.predicate_objects(A)):
        g.add((other, p, o))


DEFECTS = [
    (missing, "Host.memory_need"), (two_values, "Host.memory_need"), (untyped, "Host.memory_need"),
    (no_unit, "Host.memory_need"), (state_not_listed, "Host.memory_need"),
    (state_with_two_properties, "Host.memory_need"), (reason_not_a_code, "Host.memory_need"),
    (core_code_of_another_state, "Host.memory_need"), (set_mixed_with_the_empty_set, "Host"),
    (set_as_a_state, "Host"), (reference_into_another_kind, "Host.owner"), (reference_as_text, "Host.owner"),
    (element_outside_its_kind, "Host"),
]


@pytest.mark.parametrize("defect, shape", DEFECTS, ids=lambda v: getattr(v, "__name__", v))
def test_a_defect_is_refused_by_the_shapes_and_by_the_reader(defect, shape):
    g = rdf.to_graph(FIXTURE, R01)
    defect(g)
    conforms, shapes = validate(FIXTURE, g)
    assert not conforms and shape in shapes
    assert reader_refuses(FIXTURE, g)


def test_an_element_lies_in_the_iri_space_of_its_kind():
    """Cases X04 and X05 (§3.4): a kind's own `iri` is where its elements live, and an id is spelled one way."""
    for cid in ("X04", "X05"):
        schema, rows = schema_of(FILES[cid]), FILES[cid]["input"]["$rows"]
        assert validate(schema, rdf.to_graph(schema, rows)) == (True, set())
    schema = schema_of(FILES["X04"])
    team = URIRef(rdf.kind_iri(schema, "Team"))
    for iri in (BASE + "Team/team-platform",  # the document's base, where this kind does not live
                str(team) + "/a%2Fb", str(team) + "/a~2fb", str(team) + "/a b"):
        g = Graph()
        g.add((URIRef(iri), RDF.type, team))
        assert validate(schema, g) == (False, {"Team"})
        assert reader_refuses(schema, g)


def test_a_slot_the_schema_does_not_have_is_refused():
    """A closed shape. An RDF graph may hold more than a dataset, so `from_graph` reads past it; the reader of
    rows refuses the same member (§3.1), and that is what the shape follows."""
    g = rdf.to_graph(FIXTURE, R01)
    g.add((A, URIRef(BASE + "Host#colour"), Literal("red")))
    conforms, shapes = validate(FIXTURE, g)
    assert not conforms and shapes == {"Host"}
    with pytest.raises(l0.L0Error):
        l0.read_rows(FIXTURE, [dict(R01[0], colour="red"), R01[1]])


@pytest.mark.parametrize("reason, term, slot", [("other_code", rdf.RD.unknown, MEMORY),   # not declared
                                                ("not_assigned", rdf.RD.notApplicable, OWNER)],  # not for this state
                         ids=["undeclared", "declared for another state"])
def test_declared_reasons_close_the_codes(reason, term, slot):
    for schema, refused in ((REASONS, True), (FIXTURE, False)):  # without `reasons` any code is one
        g = rdf.to_graph(schema, R01)
        replace(g, B, slot, state(g, term, reason))
        assert validate(schema, g)[0] is not refused and reader_refuses(schema, g) is refused


def thing(slot: str) -> URIRef:
    return URIRef(rdf.slot_iri(TYPES, "Thing", slot))


T = URIRef(rdf.element_iri(TYPES, "Thing", "t"))


@pytest.mark.parametrize("slot, value", [
    ("size", Literal("xl", datatype=URIRef(rdf.schema_iri(TYPES) + "types/Size"))),   # not in the closed enum
    ("code", Literal("abcd", datatype=URIRef(rdf.schema_iri(TYPES) + "types/Code"))),  # not the pattern
    ("seen", Literal("yesterday", datatype=XSD.dateTime, normalize=False)),            # not a dateTime
    ("on", Literal("yes", datatype=XSD.boolean, normalize=False)),                     # not a boolean
    ("hosts", rdf.RD.emptySet),                                                        # `+` has a member
], ids=["enum", "pattern", "dateTime", "boolean", "empty +"])
def test_a_value_out_of_its_type_is_refused(slot, value):
    g = rdf.to_graph(TYPES, THINGS)
    replace(g, T, thing(slot), value)
    conforms, shapes = validate(TYPES, g)
    assert not conforms and f"Thing.{slot}" in shapes
    assert reader_refuses(TYPES, g)


@pytest.mark.parametrize("text", ["11", "-1"])
def test_the_bounds_of_a_core_integer_are_in_the_shape(text):
    g = rdf.to_graph(COUNTED, [TEAM, *R01])
    team = URIRef(rdf.element_iri(COUNTED, "Team", "t1"))
    replace(g, team, URIRef(rdf.slot_iri(COUNTED, "Team", "size")), Literal(text, datatype=XSD.integer))
    assert validate(COUNTED, g)[0] is False and reader_refuses(COUNTED, g)


# ---------------------------------------------------------------------------------------------------------------
# The document

def test_the_turtle_is_the_same_bytes_and_names_every_shape():
    text = shacl.to_turtle(TYPES)
    assert text == shacl.to_turtle(TYPES)
    g = Graph().parse(data=text, format="turtle")
    document = shacl.document_iri(TYPES)
    assert document == rdf.schema_iri(TYPES) + "shapes.ttl"
    named = {s for s in g.subjects(RDF.type, None)}
    assert named and all(isinstance(s, URIRef) and str(s).startswith(document + "#") for s in named)
    assert {str(o) for o in g.objects(None, SH.targetClass)} == {rdf.kind_iri(TYPES, k) for k in TYPES["kinds"]}


def test_another_schema_is_another_document():
    assert shacl.document_iri(FIXTURE) != shacl.document_iri(TYPES)


def test_reader_refuses_an_rdf_subject_of_the_versioned_kind():
    schema = schema_of(FILES["V02"])
    graph = Graph()
    graph.add((URIRef(BASE + "Plan/example"), RDF.type, URIRef(BASE + "Plan")))
    with pytest.raises(rdf.RdfError, match=r"\(Q13\)"):
        rdf.from_graph(schema, graph)


def test_an_imported_reference_without_a_target_base_has_no_rdf_form():
    elsewhere = merge(FIXTURE, {"imports": {"org": {"pack": "org", "schema": "s-" + "0" * 64}},
                                "kinds": {"Host": {"slots": {"site": {"card": "?", "ref": "org.Site",
                                                                      "states": ["known", "not_applicable"]}}}}})
    row = dict(R01[0], site={"$ref": "org@s-" + "0" * 64 + ":Site/annex"})
    assert_no_rdf_form(elsewhere, [row], "Q20")


# ---------------------------------------------------------------------------------------------------------------
# The loss list (contracts/connector.yaml, M01)

LOSSES = yaml.safe_load((HERE / "shacl.losses.yaml").read_text(encoding="utf-8"))


def carried(fate: str) -> set[str]:
    return {t for loss in LOSSES["losses"] if loss["fate"] == fate for t in loss["carried_by"]}


def test_the_shapes_are_plain_shacl():
    """No extension: every property of a shape is SHACL's own (or rdf:type). `rd:` terms occur as paths and
    values only, which any validator follows."""
    assert not [loss for loss in LOSSES["losses"] if loss["fate"] == "extension"]
    for schema in (FIXTURE, TYPES, REASONS):
        for _, p, _ in shacl.shapes(schema):
            assert p in (RDF.type, RDF.first, RDF.rest) or str(p).startswith(str(SH)), p


def test_what_the_list_calls_weakened_is_all_a_value_shape_says():
    """`share` (a Ratio between 0 and 1), `big` (a local Integer with bounds), `price` and `window` keep their
    datatype and nothing else: the bounds and the normal form are not in the shape."""
    assert carried("weakened") == {"sh:datatype", "sh:pattern"}
    g = shacl.shapes(TYPES)
    ns = shacl.document_iri(TYPES) + "#"
    for slot in ("share", "big", "price", "rate", "window"):
        value = URIRef(f"{ns}Thing.{slot}.value")
        assert {p for p, _ in g.predicate_objects(value)} == {RDF.type, SH.datatype}, slot


def test_what_the_list_calls_dropped_is_not_in_the_shapes():
    """No shape targets an annotation, says that a kind is closed, or names a role, a rule or a label."""
    assert {loss["subject"] for loss in LOSSES["losses"] if loss["fate"] == "dropped"} == {
        "world", "proof", "source", "check", "rule", "text", "access"}
    for schema in (FIXTURE, TYPES, REASONS):
        g = shacl.shapes(schema)
        assert not list(g.subject_objects(SH.targetSubjectsOf)) and not list(g.subject_objects(SH.targetObjectsOf))
        assert not list(g.subject_objects(SH.sparql)) and not list(g.subject_objects(SH.description))
        text = g.serialize(format="nt")
        assert str(rdf.RD.world) not in text and str(rdf.RD.why) not in text and str(rdf.RD.source) not in text
    assert "Not assigned" not in shacl.to_turtle(REASONS)


# (§2.1 `parent`): a kind tree
def test_a_dataset_with_a_subkind_conforms_also_closed_under_subclass():
    """The view says `rdfs:subClassOf`, so a validator holds an element of the subkind to its parent's shape too:
    the slots it restates are the same properties, and the parent's closed shape lets the subkind's own pass."""
    g = rdf.to_graph(TREE, TREE_ROWS)
    assert (URIRef(BASE + "Server"), RDFS.subClassOf, URIRef(BASE + "Host")) in g
    assert validate(TREE, g) == (True, set())
    g.add((URIRef(BASE + "Host/srv-1"), RDF.type, URIRef(BASE + "Host")))
    assert validate(TREE, g) == (True, set())


def test_a_subkind_s_own_slot_on_an_element_of_its_parent_is_refused():
    g = rdf.to_graph(TREE, TREE_ROWS)
    g.add((URIRef(BASE + "Host/host-a"), URIRef(BASE + "Server#rack"), Literal("r2")))
    conforms, shapes = validate(TREE, g)
    assert not conforms and shapes == {"Host"}  # host-a is no server: only an element of a kind below may hold it
    with pytest.raises(l0.L0Error):
        l0.read_rows(TREE, [dict(TREE_ROWS[0], rack="r2"), *TREE_ROWS[1:]])


def test_a_restated_slot_is_held_on_an_element_of_the_subkind():
    g = rdf.to_graph(TREE, TREE_ROWS)
    g.remove((URIRef(BASE + "Host/srv-1"), URIRef(BASE + "Host#memory_need"), None))
    conforms, shapes = validate(TREE, g)
    assert not conforms and {"Server.memory_need"} <= shapes
    assert reader_refuses(TREE, g)


def test_a_reference_to_the_parent_kind_takes_an_element_of_the_subkind_and_no_other():
    g = rdf.to_graph(TREE, TREE_ROWS)
    g.add((URIRef(BASE + "Team/ops"), URIRef(BASE + "Team#runs"), URIRef(BASE + "Server/srv-1")))
    assert validate(TREE, g)[0] is False  # the subkind's elements live in the root kind's space (§3.4)
    assert reader_refuses(TREE, g)
