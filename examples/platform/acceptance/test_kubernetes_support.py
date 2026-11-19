from copy import deepcopy
import json
from pathlib import Path

from rezono_checker.check import check
from rezono_checker.rules import load_rules
from rezono_compiler import batch, pack, rules, sources
from rules_support import states

from query_fixture import ROOT, check_relation


FIELDS = ("product", "series", "latest_patch", "support_end", "source_url", "source_sha256")
PUBLISHED = "published_series_support"
ORACLE = Path(__file__).with_name("product-evidence.json")


def _published_support():
    evidence = json.loads(ORACLE.read_text(encoding="utf-8"))["kubernetes"]
    fields = ['series', 'latestPatch', 'end', 'url', 'sha256']
    return ("kubernetes", *(evidence[k] for k in fields))


def _slots(relation, record, support):
    return {f"{relation}__{name}": [(record, value)] for name, value in zip(FIELDS, support, strict=True)}


def _supported(program, rows):
    with batch.connect(program, rows, threads=1) as connection:
        batch.compute(connection, program, relations=[PUBLISHED])
        return batch.read(connection, program, [PUBLISHED])[PUBLISHED]


def test_kubernetes_support():
    check_relation(PUBLISHED, [_published_support()])


def test_orphaned_support_slots_do_not_assert_support():
    _, *support = _published_support()
    rows = _slots("series_support_evidence", "unregistered-announcement", ("unregistered-product", *support))
    program = rules.load(pack.read(ROOT).rules)
    assert _supported(program, rows) == set()


def test_support_requires_each_independent_ground():
    model, program, (state,) = states(ROOT)
    support = _published_support()
    product, series, *_ = support
    evidence = f"{product}-{series}"
    source = f"{evidence}-source"
    required = {
        "product": [(product,)],
        "series_support_evidence": [(evidence,)],
        "series_support_source": [(source,)],
        **_slots("series_support_evidence", evidence, support),
        **_slots("series_support_source", source, support),
    }
    assert _supported(program, required) == {support}
    for relation in required:
        without = {name: records for name, records in required.items() if name != relation}
        assert _supported(program, without) == set(), relation

    other_source = json.loads(ORACLE.read_text(encoding="utf-8"))["keycloak"]
    other = ("keycloak", "26.0", other_source["release"], other_source["published"], other_source["url"], other_source["sha256"])
    for relation, row in _slots("series_support_source", source, other).items():
        assert _supported(program, required | {relation: row}) == set(), relation

    proof = state.proof(PUBLISHED, support)
    manifest, read = state.manifest()
    checker_rules = load_rules(model.rules)
    report = check(proof, manifest, checker_rules, read)
    assert report["valid"] and not report["findings"], report["findings"]
    premises = {(item["row"]["relation"], tuple(json.loads(item["row"]["key"])))
                for witness in proof["witnesses"] for item in witness["premises"]}
    assert premises == {(relation, row) for relation, records in required.items() for row in records}

    for relation in ("product", "series_support_evidence", "series_support_source", "series_support_source__source_sha256"):
        damaged = deepcopy(proof)
        for witness in damaged["witnesses"]:
            witness["premises"] = [item for item in witness["premises"] if item["row"]["relation"] != relation]
        report = check(damaged, manifest, checker_rules, read)
        assert not report["valid"] and any(f["reason"] == "premise_mismatch" for f in report["findings"]), relation

    entries = sources.file_entries(model, ROOT / "facts/kubernetes_support_source.yaml")
    assert len(entries) == 7
    assert all(entry["sources"] == [{
        "kind": "git",
        "name": "rezono-lang/rezono",
        "revision": "90b056e6ef1d1034bb53ccac8620961150545b0f",
        "position": "examples/platform/acceptance/product-evidence.json#/kubernetes",
    }] for entry in entries)
