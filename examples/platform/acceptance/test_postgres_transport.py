from copy import deepcopy
import json
from pathlib import Path

from rezono_checker.check import check
from rezono_checker.rules import load_rules
from rezono_compiler import batch, pack, rules, sources
from rules_support import states

from query_fixture import ROOT
from transport_support import published_for

RELATION = "published_default_transport"
SOURCE = "vendor_default_transport_source"
FIELDS = ("product", "series", "protocol", "port", "source_url", "source_sha256")
UNVERIFIED = ("unregistered-product", "0", "UDP", 1234, "https://example.org/transport", "0" * 64)


def _expected_transport():
    evidence = json.loads(Path(__file__).with_name("product-evidence.json").read_text(encoding="utf-8"))["postgresql"]
    return ("postgresql", *(evidence[key] for key in ("series", "protocol", "port", "url", "sha256")))


def _slots(relation, identifier, values):
    return {
        f"{relation}__{field}": [(identifier, value)]
        for field, value in zip(FIELDS, values, strict=True)
    }


def _published(program, rows):
    with batch.connect(program, rows, threads=1) as connection:
        batch.compute(connection, program, relations=[RELATION])
        return batch.read(connection, program, [RELATION])[RELATION]


def test_postgres_transport():
    # Other products publish their own defaults; PostgreSQL publishes exactly its pinned one.
    assert published_for("postgresql") == {tuple(map(str, _expected_transport()))}


def test_unverified_transport_does_not_publish():
    program = rules.load(pack.read(ROOT).rules)
    source_id = "unregistered-source"
    rows = _slots(SOURCE, source_id, UNVERIFIED)
    assert _published(program, rows) == set()
    rows[SOURCE] = [(source_id,)]
    assert _published(program, rows) == set()


def test_published_transport_requires_the_product_and_pinned_source():
    model, program, (state,) = states(ROOT)
    expected = _expected_transport()
    source_id = "postgresql-17-connection-settings"
    rows = {
        "product": [(expected[0],)],
        SOURCE: [(source_id,)],
        **_slots(SOURCE, source_id, expected),
    }
    conclusion = tuple(map(str, expected))
    assert _published(program, rows) == {conclusion}
    for relation in rows:
        incomplete = {name: records for name, records in rows.items() if name != relation}
        assert _published(program, incomplete) == set(), relation
    # One pinned statement: a changed value changes the published row, and the acceptance pin catches it.
    forged_slots = _slots(SOURCE, source_id, UNVERIFIED)
    for relation, forged in forged_slots.items():
        assert conclusion not in _published(program, rows | {relation: forged}), relation

    proof = state.proof(RELATION, conclusion)
    manifest, read = state.manifest()
    checker_rules = load_rules(model.rules)
    report = check(proof, manifest, checker_rules, read)
    assert report["valid"] and not report["findings"], report["findings"]
    witness, = proof["witnesses"]
    premises = {(item["row"]["relation"], tuple(json.loads(item["row"]["key"]))) for item in witness["premises"]}
    assert premises == {(relation, tuple(map(str, records[0]))) for relation, records in rows.items()}

    for relation in (SOURCE, *forged_slots):
        damaged = deepcopy(proof)
        altered, = damaged["witnesses"]
        altered["premises"] = [item for item in altered["premises"] if item["row"]["relation"] != relation]
        assert not check(damaged, manifest, checker_rules, read)["valid"], relation
    for relation, (forged,) in forged_slots.items():
        damaged = deepcopy(proof)
        altered, = damaged["witnesses"]
        row, = [item["row"] for item in altered["premises"] if item["row"]["relation"] == relation]
        row["key"] = json.dumps(list(map(str, forged)), separators=(",", ":"))
        assert not check(damaged, manifest, checker_rules, read)["valid"], relation

    entries = sources.file_entries(model, ROOT / "facts/postgres_transport_source.yaml")
    assert len(entries) == 1 + len(FIELDS)
    for entry in entries:
        assert entry["sources"] == [{
            "kind": "git",
            "name": "rezono-lang/rezono",
            "revision": "90b056e6ef1d1034bb53ccac8620961150545b0f",
            "position": "examples/platform/acceptance/product-evidence.json#/postgresql",
        }]
