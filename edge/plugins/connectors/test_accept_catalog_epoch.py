"""A DCAT version literal must agree with the epoch identified by its dataset."""

import pytest
from rdflib import Graph, Literal
from rdflib.namespace import RDF

import accept
import dcat
from acceptance_sample import AT, objects


def test_catalog_version_must_identify_the_same_epoch_as_its_dataset():
    sample = objects()
    graph = Graph().parse(data=sample["dcat.ttl"], format="turtle", publicID=AT + "dcat.ttl")
    dataset, = graph.subjects(RDF.type, dcat.DCAT.Dataset)
    assert str(graph.value(dataset, dcat.DCAT.version)) == "m-7"
    graph.set((dataset, dcat.DCAT.version, Literal("m-8")))
    sample["dcat.ttl"] = graph.serialize(format="turtle").encode()
    assert accept.published(sample, AT)["dcat.ttl"]["state"] == "failed"
