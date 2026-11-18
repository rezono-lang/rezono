from copy import deepcopy
import json
from pathlib import Path

from rezono_checker.check import check
from rezono_checker.rules import load_rules
from rezono_compiler import batch, pack, rules, sources
from rules_support import states

from query_fixture import ROOT, check_relation


def _expected_release():
    evidence = json.loads(Path(__file__).with_name("product-evidence.json").read_text())["keycloak"]
    fields = ['release', 'published', 'url', 'sha256']
    return ("keycloak", *(evidence[k] for k in fields))


def _release_slots(relation, key, release):
    fields = ("product", "version", "published", "source_url", "source_sha256")
    return {f"{relation}__{name}": [(key, value)] for name, value in zip(fields, release, strict=True)}


def _outcome(program, rows):
    with batch.connect(program, rows, threads=1) as connection:
        batch.compute(connection, program, relations=["published_release"])
        return batch.read(connection, program, ["published_release"])["published_release"]


def test_keycloak_release():
    check_relation("published_release", [_expected_release()])


def test_announcement_slots_alone_do_not_publish_a_release():
    program = rules.load(pack.read(ROOT).rules)
    announcement = "unregistered-announcement"
    release = ("unregistered-product", "0.0.0", "2030-01-01", "https://example.org/releases/unregistered", "0" * 64)
    rows = _release_slots("product_release_announcement", announcement, release)
    assert _outcome(program, rows) == set()
    rows.update(product=[(release[0],)], product_release_announcement=[(announcement,)])
    assert _outcome(program, rows) == set()


def test_published_release_requires_every_independent_ground():
    model, program, (state,) = states(ROOT)
    release = _expected_release()
    announcement = f"{release[0]}-{release[1]}"
    source = f"{announcement}-release-source"
    rows = {
        "product": [(release[0],)],
        "product_release_announcement": [(announcement,)],
        "product_release_source": [(source,)],
        **_release_slots("product_release_announcement", announcement, release),
        **_release_slots("product_release_source", source, release),
    }
    assert _outcome(program, rows) == {release}
    for relation in rows:
        assert _outcome(program, {name: records for name, records in rows.items() if name != relation}) == set(), relation

    different = ("unregistered-product", "0.0.0", "2030-01-01", "https://example.org/releases/unregistered", "0" * 64)
    for relation, record in _release_slots("product_release_source", source, different).items():
        assert _outcome(program, rows | {relation: record}) == set(), relation

    proof = state.proof("published_release", release)
    manifest, read = state.manifest()
    checker_rules = load_rules(model.rules)
    report = check(proof, manifest, checker_rules, read)
    assert report["valid"] and not report["findings"], report["findings"]
    premises = {(item["row"]["relation"], tuple(json.loads(item["row"]["key"])))
                for witness in proof["witnesses"] for item in witness["premises"]}
    assert premises == {(relation, records[0]) for relation, records in rows.items()}

    damaged = deepcopy(proof)
    for witness in damaged["witnesses"]:
        witness["premises"] = [item for item in witness["premises"]
                              if item["row"]["relation"] != "product_release_source__source_sha256"]
    assert not check(damaged, manifest, checker_rules, read)["valid"]

    entries = sources.file_entries(model, ROOT / "facts/keycloak_release_source.yaml")
    assert len(entries) == 6
    for entry in entries:
        assert entry["sources"] == [{
            "kind": "git",
            "name": "rezono-lang/rezono",
            "revision": "90b056e6ef1d1034bb53ccac8620961150545b0f",
            "position": "examples/platform/acceptance/product-evidence.json#/keycloak",
        }]
