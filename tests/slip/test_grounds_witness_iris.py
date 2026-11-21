"""The witnesses of a `grounds` answer carry their canonical IRIs (decisions/publication-conclusion-addresses.md §2).

The fixture is published by the publisher, with each filtered role's publication form, and asked through the local
reader of edge/gate (`openLocalGate`, reader.mjs). Every expectation comes from the Python side: the witness is the
one the role's published witness set holds, unchanged, and its IRI is what `rdf.canonical_witness_iri` gives under
the role's publication schema. The hash in that IRI is the hash the form's `$why` names for the same row.
"""

import json

from slip_support import FIXTURE, KNOWLEDGE_TIME, PACK, ROLES, ask, row_query

from rezono_compiler import modules
from rezono_publication import publication, rdf
from rezono_publisher import batch, publish, store as stores

QUESTIONS = [
    ("flagged", "item-a", "12"),  # a rule row with a negative premise
    ("busy", "group-a"),  # a conclusion on a conclusion
    ("group_size", "group-a", "2"),  # an aggregate
    ("calc__capped_amount", "item-a", "12", "known", ""),  # a calculated row
]


def publish_with_forms(directory):
    pack = modules.copy_closure(FIXTURE, directory / "closure")
    epoch = batch.epoch(pack, epoch=1, knowledge_time=KNOWLEDGE_TIME, sources=[("rules", "test")])
    target = directory / "store"
    manifest = publish.publish(epoch, stores.FileStore(target), ROLES, forms=True)
    return target, manifest


def test_grounds_witnesses_carry_the_iri_the_publication_side_gives(tmp_path):
    target, manifest = publish_with_forms(tmp_path)
    st = stores.FileStore(target)
    for role in ("reader", "summary"):
        form = f"{PACK}/{manifest['id']}/{role}/publication/"
        schema = json.loads(st.get(form + "schema.json"))
        why = {(row["$kind"], row["$id"]): row["$why"]["$id"]
               for row in json.loads(st.get(form + "rows.json"))["$rows"] if "$why" in row}
        published = json.loads(st.get(publish.role_objects(st, PACK, manifest["id"], role)["witnesses.json"]))
        replies = ask(target, role, *(f"/{PACK}/{manifest['id']}/ask/grounds?{row_query(*q)}" for q in QUESTIONS))
        shown = set()
        for question, reply in zip(QUESTIONS, replies):
            assert reply["status"] == 200, (role, question, reply)
            body = reply["body"]
            for w in body["witnesses"]:
                iri = w.pop("iri")
                assert w in published["witnesses"], (role, w)  # the published witness, unchanged
                assert iri == rdf.canonical_witness_iri(schema, w)
                assert iri.startswith(schema["base"] + "witness/")
                # The form's `$why` names the same witness by the same hash.
                stated = why[publication.pascal(w["conclusion"]["relation"]), w["conclusion"]["key"]]
                assert stated.rsplit("/", 1)[1] == iri.rsplit("/", 1)[1], (stated, iri)
                shown.add(w["conclusion"]["relation"])
            for w in body.get("calc_witnesses", []):
                iri = w.pop("iri")
                assert w in published["calc_witnesses"], (role, w)
                assert iri == rdf.canonical_witness_iri(schema, w)
                shown.add(w["conclusion"]["relation"])
            # Only what the contract names: no reader-made flag beside a step (contracts/explain.yaml, AnswerStep).
            assert all(set(step) <= {"conclusion", "premise", "how", "position", "value"} for step in body["steps"])
        assert shown >= {"flagged", "busy", "group_size", "calc__capped_amount"}, (role, shown)
