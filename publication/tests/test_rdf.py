"""The RDF view (docs/publication/l0.md §5): cases X01, X02, X04, X05 and T03, the converter's rules, and PROV-O
(O12c)."""

import copy
import json

import pytest
from rdflib import BNode, Graph, Literal, URIRef
from rdflib.namespace import PROV, RDF, RDFS, XSD

from rezono_canon import canonical_json

from rezono_publication import l0, rdf
from rezono_publication.hash import hashes
from publication.tests.test_l0 import FILES, FIXTURE, R01, TREE, TREE_ROWS, merge, schema_of


def canon(rows):
    """Rows with their order and member order taken out: what T03 compares."""
    out = []
    for row in rows:
        row = copy.deepcopy(row)
        for k, v in row.items():
            if isinstance(v, list) and not k.startswith("$"):
                row[k] = sorted(v, key=canonical_json)
        out.append(canonical_json(row))
    return sorted(out)


def test_the_context_is_protected_and_kind_scoped():
    ctx = rdf.context(FIXTURE)["@context"]
    assert ctx["@version"] == 1.1 and ctx["@protected"] is True
    assert ctx["$id"] == "@id" and ctx["$kind"] == "@type" and ctx["$rows"] == "@graph"
    assert ctx["$why"] is None and ctx["$src"] is None and ctx["$schema"] is None
    host = ctx["Host"]
    assert host["@id"] == "https://rezono.example/fixture/Host"
    assert host["@context"]["owner"] == {"@id": "https://rezono.example/fixture/Host#owner", "@type": "@id"}
    assert host["@context"]["memory_need"]["@type"] == rdf.schema_iri(FIXTURE) + "types/GiB"
    assert host["@context"]["tags"]["@type"] == "http://www.w3.org/2001/XMLSchema#string"
    assert "owner" not in ctx  # no slot at the top level


def document(schema, rows, extra=()):
    return {"@context": [rdf.schema_iri(schema) + "context.jsonld", *extra], "$rows": rows}


def test_x01_one_slot_name_on_two_kinds_expands_to_two_iris():
    case = FILES["X01"]
    schema = schema_of(case)
    g = rdf.expand(schema, document(schema, case["input"]["$rows"]))
    host = URIRef("https://rezono.example/fixture/Host")
    plan = URIRef("https://rezono.example/fixture/Plan")
    for kind, iri in ((host, case["expect"]["expanded"]["Host.owner"]), (plan, case["expect"]["expanded"]["Plan.owner"])):
        (s,) = g.subjects(RDF.type, kind)
        assert {str(p) for p in g.predicates(s) if str(p).endswith("#owner")} == {iri}


def test_x02_a_protected_term_cannot_be_redefined():
    case = FILES["X02"]
    schema = schema_of(case)
    doc = copy.deepcopy(case["input"])
    doc["@context"][0] = rdf.schema_iri(schema) + "context.jsonld"
    with pytest.raises(l0.L0Error, match="protected term redefinition"):
        rdf.expand(schema, doc)


@pytest.mark.parametrize("extra", [
    {"owner": {"@id": "https://other.example/owner"}},           # a slot term
    {"$id": "https://other.example/id"},                          # a keyword alias
    {"@vocab": "https://other.example/"},                         # a change of how terms read
])
def test_x02_no_embedded_context_redefines_what_the_published_one_defines(extra):
    with pytest.raises(l0.L0Error):
        rdf.expand(FIXTURE, document(FIXTURE, R01, [extra]))
    nested = document(FIXTURE, [dict(R01[0], **{"@context": extra}), R01[1]])
    with pytest.raises(l0.L0Error):
        rdf.expand(FIXTURE, nested)


def test_an_unrelated_term_may_be_added():
    g = rdf.expand(FIXTURE, document(FIXTURE, R01, [{"note": "https://other.example/note"}]))
    assert len(g) > 0


def test_t03_r01_round_trips_through_the_converter():
    for back in (rdf.from_jsonld(FIXTURE, rdf.to_jsonld(FIXTURE, R01)),
                 rdf.from_turtle(FIXTURE, rdf.to_turtle(FIXTURE, R01))):
        assert canon(back) == canon(R01)
        assert hashes(FIXTURE, back) == hashes(FIXTURE, R01)


def test_t03_the_empty_set_is_rd_empty_set():
    g = rdf.to_graph(FIXTURE, R01)
    b = URIRef(rdf.element_iri(FIXTURE, "Host", "host-b"))
    assert list(g.objects(b, URIRef("https://rezono.example/fixture/Host#tags"))) == [rdf.RD.emptySet]
    back = {r["$id"]: r for r in rdf.from_graph(FIXTURE, g)}
    assert back["host-b"]["tags"] == []


def test_a_state_is_a_blank_node_with_its_reason():
    g = rdf.to_graph(FIXTURE, R01)
    a = URIRef(rdf.element_iri(FIXTURE, "Host", "host-a"))
    (node,) = g.objects(a, URIRef("https://rezono.example/fixture/Host#owner"))
    assert isinstance(node, BNode)
    assert list(g.predicate_objects(node)) == [(rdf.RD.unknown, Literal("not_assigned"))]


def test_a_closed_kind_says_so():
    g = rdf.to_graph(FIXTURE, R01)
    assert (URIRef("https://rezono.example/fixture/Host"), rdf.RD.world, rdf.RD.closed) in g
    assert not list(g.objects(URIRef("https://rezono.example/fixture/Team"), rdf.RD.world))  # Team is open


def test_a_known_value_is_a_typed_literal_of_its_row_json_text():
    g = rdf.to_graph(FIXTURE, R01)
    a = URIRef(rdf.element_iri(FIXTURE, "Host", "host-a"))
    (v,) = g.objects(a, URIRef("https://rezono.example/fixture/Host#memory_need"))
    assert v == Literal("400 GiB", datatype=URIRef(rdf.schema_iri(FIXTURE) + "types/GiB"))


def test_an_element_iri_spells_its_id():
    assert rdf.element_iri(FIXTURE, "Host", "a/b c") == "https://rezono.example/fixture/Host/a~2Fb~20c"
    rows = [dict(R01[1], **{"$id": "a/b c"})]
    assert canon(rdf.from_turtle(FIXTURE, rdf.to_turtle(FIXTURE, rows))) == canon(rows)


def test_x04_an_element_lives_in_the_namespace_of_its_kind():
    case = FILES["X04"]
    schema, rows = schema_of(case), case["input"]["$rows"]
    for e in case["expect"]["iris"]:
        assert rdf.element_iri(schema, e["kind"], e["id"]) == e["iri"]
    g = rdf.to_graph(schema, rows)
    host, team = (URIRef(e["iri"]) for e in case["expect"]["iris"])
    assert (team, RDF.type, URIRef("https://rezono.example/people/Team")) in g
    assert list(g.objects(host, URIRef("https://rezono.example/fixture/Host#owner"))) == [team]
    for back in (rdf.from_graph(schema, g), rdf.from_jsonld(schema, rdf.to_jsonld(schema, rows))):
        assert canon(back) == canon(rows)


def test_x05_every_id_has_one_iri_and_reads_back():
    case = FILES["X05"]
    schema, rows = schema_of(case), case["input"]["$rows"]
    assert [r["$id"] for r in rows] == [e["id"] for e in case["expect"]["iris"]]
    for e in case["expect"]["iris"]:
        assert rdf.element_iri(schema, e["kind"], e["id"]) == e["iri"]
        segment = e["iri"].rsplit("/", 1)[1]
        assert set(segment) <= set("ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-._~")
        assert rdf.unspell(segment) == e["id"]
    for back in (rdf.from_turtle(schema, rdf.to_turtle(schema, rows)),
                 rdf.from_jsonld(schema, rdf.to_jsonld(schema, rows))):
        assert canon(back) == canon(rows)


@pytest.mark.parametrize("segment", [
    "a%2Fb",  # percent-encoding: a resolver decodes or refuses it (docs/ring2/iris.md §4.1)
    "a~2fb",  # lower-case hex
    "~41",  # `A` is written as itself
    "a~",  # a lone `~`
    "a~2",
    "~G1",
    "a b",  # a character that is not written as itself
    "a/b",
    "~FF",  # not UTF-8
    ".",  # a dot segment
    "..",
], ids=["percent", "lower hex", "plain as hex", "lone ~", "one digit", "no hex", "space", "slash", "not utf-8",
        "dot", "dots"])
def test_a_segment_that_is_not_the_spelling_of_its_id_is_refused(segment):
    with pytest.raises(l0.L0Error, match="§3.4"):
        rdf.unspell(segment)
    g = Graph()
    g.add((URIRef("https://rezono.example/fixture/Team/" + segment), RDF.type, URIRef("https://rezono.example/fixture/Team")))
    with pytest.raises(l0.L0Error):
        rdf.from_graph(FIXTURE, g)


def test_a_row_iri_spells_its_relation_and_key():
    ref = {"relation": "host_fits", "key": '["host-a","zone 1"]'}
    iri = rdf.row_iri(ref)
    assert str(iri) == "rezono:r/host_fits/~5B~22host-a~22~2C~22zone~201~22~5D"
    assert rdf._row_ref(iri) == ref
    with pytest.raises(l0.L0Error):
        rdf._row_ref("rezono:r/host_fits/%5B%22host-a%22%5D")


@pytest.mark.parametrize("iri", ["https://rezono.example/people/Team#x", "https://rezono.example/people/Team?x",
                                 "https://rezono.example/people/Team/"])
def test_a_kind_iri_ends_in_no_fragment_query_or_slash(iri):
    schema = merge(FIXTURE, {"kinds": {"Team": {"iri": iri}}})
    with pytest.raises(l0.L0Error, match="`iri` has no `#`"):
        l0.check_schema(schema)


SOURCE = {"kind": "pack", "name": "facts/hosts.yaml", "position": "host-a"}


def test_why_and_src_are_statement_annotations_and_round_trip():
    rows = [dict(R01[0], **{"$why": {"memory_need": "rezono:w/91c2", "tags": {"gpu": "rezono:w/1"}, "$id": "rezono:w/2"},
                            "$src": {"$id": [SOURCE], "tags": [SOURCE]}}), R01[1]]
    g = rdf.to_graph(FIXTURE, rows)
    statements = list(g.subjects(RDF.type, RDF.Statement))
    assert len(statements) == 5  # three proofs; the `tags` source on each of its two member triples
    back = rdf.from_turtle(FIXTURE, g.serialize(format="turtle"))
    assert canon(back) == canon(rows)
    assert hashes(FIXTURE, back) == hashes(FIXTURE, rows)  # side tables too


def test_every_type_and_state_round_trips():
    from publication.tests.test_l0 import THING, TYPES
    rows = [dict(THING, hosts=[{"$ref": "host-a"}]), *R01]
    assert canon(rdf.from_turtle(TYPES, rdf.to_turtle(TYPES, rows))) == canon(rows)


def test_an_ld2_integer_comes_back_as_a_number():
    case = FILES["R04"]
    schema = schema_of(case)
    rows = [case["input"]]
    back = rdf.from_turtle(schema, rdf.to_turtle(schema, rows))
    assert canon(back) == canon(rows)
    assert any(isinstance(v, int) and not isinstance(v, bool) for v in back[0].values())


def test_the_converter_refuses_what_it_cannot_write():
    schema = schema_of(FILES["V02"])
    with pytest.raises(l0.L0Error, match="Q13"):
        rdf.to_graph(schema, FILES["V02"]["input"])
    with pytest.raises(l0.L0Error, match="undefined"):
        rdf.to_graph(FIXTURE, [dict(R01[0], **{"$version": "1"})])  # rows are read first


def test_from_graph_refuses_a_graph_that_is_no_dataset():
    g = rdf.to_graph(FIXTURE, R01)
    a = URIRef(rdf.element_iri(FIXTURE, "Host", "host-a"))
    g.add((a, URIRef("https://rezono.example/fixture/Host#memory_need"), Literal("2 GiB")))
    with pytest.raises(l0.L0Error, match="one object"):
        rdf.from_graph(FIXTURE, g)
    g = rdf.to_graph(FIXTURE, R01)
    b = URIRef(rdf.element_iri(FIXTURE, "Host", "host-b"))
    g.add((b, URIRef("https://rezono.example/fixture/Host#tags"), Literal("gpu")))
    with pytest.raises(l0.L0Error, match="rd:emptySet alone"):
        rdf.from_graph(FIXTURE, g)


# O12c: a witness as PROV-O
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


def test_a_witness_becomes_prov_o_and_comes_back():
    g = rdf.witness_to_prov(WITNESS, "m-12", "d-" + "b" * 64,
                            {("host", '["host-a"]'): [SOURCE]})
    a = rdf.witness_iri(WITNESS)
    conclusion = rdf.row_iri(WITNESS["conclusion"])
    host = rdf.row_iri(WITNESS["premises"][0]["row"])
    blocked = rdf.row_iri(WITNESS["premises"][1]["row"])
    assert (a, RDF.type, PROV.Activity) in g
    assert (conclusion, RDF.type, PROV.Entity) in g and (conclusion, PROV.wasGeneratedBy, a) in g
    assert (a, PROV.used, host) in g and (a, PROV.used, blocked) not in g  # an absence is not a use
    assert (a, rdf.RD.absent, blocked) in g
    assert (conclusion, PROV.wasDerivedFrom, host) in g
    assert (host, PROV.wasDerivedFrom, Literal(canonical_json(SOURCE), datatype=RDF.JSON)) in g
    assert (g.identifier, RDF.type, PROV.Bundle) in g
    assert str(g.identifier) == "rezono:m/m-12@d-" + "b" * 64
    back = rdf._parse(g.serialize(format="turtle"), "turtle")
    assert rdf.prov_to_witness(back) == WITNESS


def test_a_witness_without_bindings_or_aggregates_round_trips():
    w = {k: v for k, v in WITNESS.items() if k not in ("bindings", "aggregates")}
    g = rdf.witness_to_prov(w, "m-1", "d-" + "c" * 64)
    assert rdf.prov_to_witness(g) == w


def test_the_epoch_of_a_bundle_carries_its_hash_pin():
    with pytest.raises(l0.L0Error, match="hash pin"):
        rdf.witness_to_prov(WITNESS, "m-12", "")


def test_a_changed_prov_graph_is_refused():
    g = rdf.witness_to_prov(WITNESS, "m-12", "d-" + "b" * 64)
    a = rdf.witness_iri(WITNESS)
    g.set((a, rdf.RD.rule, Literal("rule.other")))
    with pytest.raises(l0.L0Error, match="not the hash of the witness"):
        rdf.prov_to_witness(g)


def test_the_loss_list_names_every_rd_term_prov_o_lacks():
    g = rdf.witness_to_prov(WITNESS, "m-12", "d-" + "b" * 64)
    used = {str(p).split("#")[1] for p in g.predicates() if str(p).startswith(str(rdf.RD))}
    named = {line.split(":")[1].split(" ")[0].split(",")[0] for line in rdf.PROV_LOSS}
    named |= {"polarity", "stratum", "position", "variable", "value"}
    assert used <= named, used - named


def test_no_json_number_or_float_reaches_a_literal():
    text = rdf.to_turtle(FIXTURE, R01)
    assert "double" not in text and "decimal" not in text
    assert json.loads(rdf.to_jsonld(FIXTURE, R01))


# The same rows give the same Turtle bytes in every process (rule 3; the publisher writes the view, RV-K20).

_SEEDED = r'''
import hashlib, json, sys
from rdflib import Graph
from rezono_publication import rdf
kinds = {k: {"world": "closed", "id": {"type": "Text"},
             "slots": {"tags": {"type": "Text", "card": "*", "states": ["known"]},
                       "note": {"type": "Text", "card": "?", "states": ["known", "not_applicable"]}}}
         for k in ("Delta", "Alpha", "Gamma", "Beta")}
schema = {"rezono": "1.0", "pack": "seeded", "base": "https://rezono.example/seeded/", "kinds": kinds}
rows = [{"$kind": k, "$id": f"{k}-{i}", "tags": ["a", "b"], "note": {"$na": ""},
         "$why": {"tags": {"a": "rezono:w/" + format(i, "064x")}}} for k in kinds for i in range(3)]
witnesses = [{"conclusion": {"relation": "r", "key": json.dumps([str(i)])}, "rule_id": "rule",
              "premises": [{"row": {"relation": "s", "key": json.dumps([str(j)])}, "polarity": "positive", "stratum": 0}
                           for j in range(2)], "bindings": [{"variable": "x", "value": str(i)}]} for i in range(3)]
prov = Graph()
for w in witnesses:
    prov += rdf.witness_to_prov(w, "m-1", "d-" + "a" * 64)
for text in (rdf.to_turtle(schema, rows), rdf.bind_namespaces(prov).serialize(format="turtle")):
    print(hashlib.sha256(text.encode()).hexdigest())
'''


def test_the_view_and_prov_are_the_same_bytes_under_every_hash_seed():
    """rdflib names an unbound namespace in the order it meets triples, which follows string hashing: four kinds
    with slots and three witnesses, made in processes with other seeds, must give one text each."""
    import os
    import subprocess
    import sys

    out = set()
    for seed in ("0", "1", "2", "3", "4"):
        env = {**os.environ, "PYTHONHASHSEED": seed}
        run = subprocess.run([sys.executable, "-c", _SEEDED], env=env, capture_output=True, text=True, check=True)
        out.add(run.stdout)
    assert len(out) == 1, out


# RV-K26 (§2.1 `parent`, §3.4, §5): a subkind in the RDF view
def test_an_element_of_a_subkind_has_one_iri_in_the_space_of_its_root_kind():
    base = TREE["base"]
    g = rdf.to_graph(TREE, TREE_ROWS)
    host, server = URIRef(base + "Host"), URIRef(base + "Server")
    srv = URIRef(base + "Host/srv-1")
    assert (server, RDFS.subClassOf, host) in g
    assert set(g.objects(srv, RDF.type)) == {server}  # typed once, at its most specific kind
    assert not list(g.predicate_objects(URIRef(base + "Server/srv-1")))
    # A slot the subkind restates is its parent's property; its own slot is its own.
    assert g.value(srv, URIRef(base + "Host#memory_need")) is not None
    assert g.value(srv, URIRef(base + "Server#rack")) == Literal("r1", datatype=XSD.string)
    assert not list(g.objects(srv, URIRef(base + "Server#memory_need")))
    # A reference to the parent kind names the element by the same IRI.
    assert set(g.objects(URIRef(base + "Team/ops"), URIRef(base + "Team#runs"))) == {URIRef(base + "Host/host-a"), srv}
    ctx = rdf.context(TREE)["@context"]
    assert ctx["Server"]["@id"] == base + "Server"
    assert ctx["Server"]["@context"]["tags"] == ctx["Host"]["@context"]["tags"]
    assert ctx["Server"]["@context"]["rack"]["@id"] == base + "Server#rack"


def test_a_dataset_with_a_subkind_round_trips_through_the_converter():
    for back in (rdf.from_jsonld(TREE, rdf.to_jsonld(TREE, TREE_ROWS)),
                 rdf.from_turtle(TREE, rdf.to_turtle(TREE, TREE_ROWS))):
        assert canon(back) == canon(TREE_ROWS)
        assert hashes(TREE, back) == hashes(TREE, TREE_ROWS)


def test_a_graph_closed_under_subclass_reads_each_element_once():
    """An RDFS reasoner types a server as a host too; the element is still one row, at its most specific kind."""
    g = rdf.to_graph(TREE, TREE_ROWS)
    g.add((URIRef(TREE["base"] + "Host/srv-1"), RDF.type, URIRef(TREE["base"] + "Host")))
    assert canon(rdf.from_graph(TREE, g)) == canon(TREE_ROWS)


def test_a_schema_without_a_subkind_has_no_subclass_triple():
    assert not list(rdf.to_graph(FIXTURE, R01).triples((None, RDFS.subClassOf, None)))


def _awkward(n: int) -> Graph:
    """IRIs rdflib files as namespaces of their own (a spelled `~`, a hash that starts with a digit), beside
    bound ones, a bound namespace as an object, a predicate it makes a prefix for, and a predicate on `.` in an
    unbound namespace: rdflib binds a prefix for it, gives it no name, and names later IRIs with that prefix."""
    g = Graph()
    g.bind("ex", "https://e.example/")
    g.bind("k", "https://e.example/Kind/")
    g.bind("kx", "https://e.example/Kind/xy")  # longer than the split of .../Kind/xyz…: rdflib takes the longest
    for i in range(n):
        for local in (f"xyz{i}", f"a(b){i}", f"end{i}.", f"p%2{i}q", f"r%zz{i}"):
            g.add((URIRef(f"https://e.example/Kind/k{i}"), RDFS.seeAlso, URIRef(f"https://e.example/Kind/{local}")))
        s = URIRef(f"https://e.example/Kind/~5B{i}~5D")
        g.add((s, RDF.type, URIRef("https://e.example/Kind")))
        g.add((s, URIRef("https://e.example/Kind#slot"), URIRef(f"https://e.example/Kind/k{i}")))
        g.add((s, URIRef("https://other.example/p"), URIRef(f"rezono:w/{i}abc")))
        g.add((s, RDFS.seeAlso, URIRef("https://e.example/Kind/")))
        g.add((s, RDFS.label, Literal(f"{i}", datatype=URIRef("https://e.example/types/T"))))
        g.add((s, URIRef("https://u.example/ns/end."), URIRef(f"https://u.example/ns/x{i}")))
    return g


def test_turtle_writes_rdflibs_own_bytes():
    assert rdf.turtle(_awkward(300)) == _awkward(300).serialize(format="turtle")
    based = _awkward(300)
    based.base = "https://e.example/"
    assert rdf.turtle(based) == based.serialize(format="turtle")


def test_turtle_files_no_namespace_per_subject_or_object():
    """rdflib's time per IRI grows with the namespaces filed in its trie; `turtle` files only the predicates',
    so their number does not grow with the graph, while rdflib's own writer files one more per subject."""

    def filed(g: Graph, write) -> int:
        write(g)
        return len(g.namespace_manager._NamespaceManager__strie)

    assert filed(_awkward(50), rdf.turtle) == filed(_awkward(400), rdf.turtle)
    assert filed(_awkward(400), lambda g: g.serialize(format="turtle")) > filed(_awkward(50), rdf.turtle) + 350
