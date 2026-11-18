from copy import deepcopy
import json

from rezono_checker.check import check
from rezono_checker.rules import load_rules
from rezono_compiler import batch, calc, pack, rules, scenarios, sources
from rules_support import State, states

from query_fixture import ROOT, check_relation


EXPECTED_RELEASE = (
    "keycloak", "26.0.0", "2024-10-04",
    "https://www.keycloak.org/2024/10/keycloak-2600-released",
    "d5550883927968586033693bd391179dd441d4fd852ad8c55d535c0b8b593b82",
)
SOURCE = "keycloak-26.0.0-release-source"
REFERENCE = "keycloak-26.0.0-register"


def _release_slots(relation, key, release):
    fields = ("product", "version", "published", "source_url", "source_sha256")
    return {f"{relation}__{name}": [(key, value)] for name, value in zip(fields, release, strict=True)}


def _outcomes(program, rows):
    relations = ["published_release", "product_release_date_drift"]
    with batch.connect(program, rows, threads=1) as connection:
        batch.compute(connection, program, relations=["product_release_observed", *relations])
        return batch.read(connection, program, relations)


def test_keycloak_release():
    check_relation("published_release", [EXPECTED_RELEASE])


def test_observation_slots_alone_do_not_publish_a_release():
    program = rules.load(pack.read(ROOT).rules)
    source = "unregistered-announcement"
    release = ("unregistered-product", "0.0.0", "2030-01-01", "https://example.org/releases/unregistered", "0" * 64)
    rows = _release_slots("product_release_source", source, release)
    assert _outcomes(program, rows)["published_release"] == set()
    assert _outcomes(program, rows | {"product": [(release[0],)]})["published_release"] == set()
    assert _outcomes(program, rows | {"product_release_source": [(source,)]})["published_release"] == set()


def test_published_release_requires_every_independent_ground():
    model, program, (state,) = states(ROOT)
    release = EXPECTED_RELEASE
    rows = {
        "product": [(release[0],)],
        "product_release_source": [(SOURCE,)],
        **_release_slots("product_release_source", SOURCE, release),
    }
    assert _outcomes(program, rows)["published_release"] == {release}
    for relation in rows:
        missing = {name: records for name, records in rows.items() if name != relation}
        assert _outcomes(program, missing)["published_release"] == set(), relation

    proof = state.proof("published_release", release)
    manifest, read = state.manifest()
    checker_rules = load_rules(model.rules)
    report = check(proof, manifest, checker_rules, read)
    assert report["valid"] and not report["findings"], report["findings"]
    premises = {(item["row"]["relation"], tuple(json.loads(item["row"]["key"])))
                for witness in proof["witnesses"] for item in witness["premises"]}
    assert premises == {(relation, records[0]) for relation, records in rows.items()} | {
        ("product_release_observed", (SOURCE, *release))
    }

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


def test_register_date_is_only_used_for_drift():
    model, program, (state,) = states(ROOT)
    assert state.derived["product_release_date_drift"] == set()
    published = {EXPECTED_RELEASE}
    assert state.derived["published_release"] == published

    for missing in ("product_release_reference", "product_release_reference__published", "product_release_source"):
        rows = {relation: values for relation, values in state.base.items() if relation != missing}
        assert _outcomes(program, rows) == {
            "published_release": set() if missing == "product_release_source" else published,
            "product_release_date_drift": set(),
        }

    (_, rows), = scenarios.states(model, ROOT)
    changed = rows | {"product_release_reference__published": [(REFERENCE, "2024-10-05")]}
    calculation = calc.build(model, model.calc) if program.calc_inputs() else None
    drift = State(model, program, "changed-release-register", changed, calculation)
    finding = (REFERENCE, SOURCE, "keycloak", "26.0.0", "2024-10-05", "2024-10-04")
    assert drift.derived["published_release"] == published
    assert drift.derived["product_release_date_drift"] == {finding}

    proof = drift.proof("product_release_date_drift", finding)
    manifest, read = drift.manifest()
    report = check(proof, manifest, load_rules(model.rules), read)
    assert report["valid"] and not report["findings"], report["findings"]
    premises = {item["row"]["relation"] for witness in proof["witnesses"] for item in witness["premises"]}
    assert {"product_release_reference__published", "product_release_source__published"} <= premises

    entries = sources.file_entries(model, ROOT / "facts/keycloak_release.yaml")
    assert len(entries) == 4
    assert all(source["kind"] == "pack" and source["name"] == "facts/keycloak_release.yaml"
               for entry in entries for source in entry["sources"])
