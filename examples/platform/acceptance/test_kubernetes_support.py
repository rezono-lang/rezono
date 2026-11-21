from copy import deepcopy
import json
from pathlib import Path

import pytest

from rezono_checker.check import check
from rezono_checker.rules import load_rules
from rezono_compiler import batch, calc, pack, rules, scenarios, sources
from rules_support import State, states

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
    rows = _slots("series_support_source", "unregistered-announcement", ("unregistered-product", *support))
    program = rules.load(pack.read(ROOT).rules)
    assert _supported(program, rows) == set()


class SupportStatementRecordedTwice(AssertionError):
    pass


def test_support_requires_each_independent_ground():
    model, program, (state,) = states(ROOT)
    support = _published_support()
    product, series, *_ = support
    source = f"{product}-{series}-source"
    required = {
        "product": [(product,)],
        "series_support_source": [(source,)],
        **_slots("series_support_source", source, support),
    }
    if _supported(program, required) != {support} or state.base.get("series_support_evidence"):
        raise SupportStatementRecordedTwice("support needs a second record of the same statement")
    for relation in required:
        without = {name: records for name, records in required.items() if name != relation}
        assert _supported(program, without) == set(), relation

    proof = state.proof(PUBLISHED, support)
    manifest, read = state.manifest()
    checker_rules = load_rules(model.rules)
    report = check(proof, manifest, checker_rules, read)
    assert report["valid"] and not report["findings"], report["findings"]
    premises = {(item["row"]["relation"], tuple(json.loads(item["row"]["key"])))
                for witness in proof["witnesses"] for item in witness["premises"]}
    assert premises == {(relation, row) for relation, records in required.items() for row in records}

    for relation in ("product", "series_support_source", "series_support_source__source_sha256"):
        damaged = deepcopy(proof)
        for witness in damaged["witnesses"]:
            witness["premises"] = [item for item in witness["premises"] if item["row"]["relation"] != relation]
        report = check(damaged, manifest, checker_rules, read)
        assert not report["valid"] and any(f["reason"] == "premise_mismatch" for f in report["findings"]), relation

    # The statement cites the maker's page, never the expectations of these tests.
    entries = sources.file_entries(model, ROOT / "facts/kubernetes_support_source.yaml")
    assert len(entries) == 7
    for entry in entries:
        assert not any("acceptance/" in value for item in entry["sources"] for value in item.values()), entry
        assert support[4] in {item.get("url") for item in entry["sources"]}, entry


class MissingSupportDrift(AssertionError):
    pass


DRIFT = "series_support_end_drift"
REFERENCE = "kubernetes-1.32-register"


def test_register_difference_is_support_drift():
    model, program, (state,) = states(ROOT)
    if DRIFT not in program.derived() or not state.base.get("series_support_reference"):
        raise MissingSupportDrift(f"no {DRIFT} over a separate register row")
    support = _published_support()
    product, series, _, end, *_ = support
    source = f"{product}-{series}-source"
    assert state.derived[DRIFT] == set()
    assert state.derived[PUBLISHED] == {support}
    assert set(state.base["series_support_reference__support_end"]) == {(REFERENCE, end)}

    (_, rows), = scenarios.states(model, ROOT)
    calculation = calc.build(model, model.calc) if program.calc_inputs() else None
    for missing in ("series_support_reference", "series_support_reference__support_end"):
        without = {name: records for name, records in rows.items() if name != missing}
        unregistered = State(model, program, "without-register", without, calculation)
        assert unregistered.derived[DRIFT] == set(), missing
        assert unregistered.derived[PUBLISHED] == {support}, missing

    changed = rows | {"series_support_reference__support_end": [(REFERENCE, "2026-03-31")]}
    drift = State(model, program, "changed-support-register", changed, calculation)
    finding = (REFERENCE, source, product, series, "2026-03-31", end)
    assert drift.derived[DRIFT] == {finding}
    assert drift.derived[PUBLISHED] == {support}

    proof = drift.proof(DRIFT, finding)
    manifest, read = drift.manifest()
    report = check(proof, manifest, load_rules(model.rules), read)
    assert report["valid"] and not report["findings"], report["findings"]
    premises = {item["row"]["relation"] for witness in proof["witnesses"] for item in witness["premises"]}
    assert {"series_support_reference__support_end", "series_support_source__support_end"} <= premises

    fact_file = ROOT / "facts/kubernetes_support.yaml"
    assert fact_file.with_suffix(".sources.yaml").exists()
    entries = sources.file_entries(model, fact_file)
    register = [entry for entry in entries if entry["row"]["relation"].split("__", 1)[0] == "series_support_reference"]
    assert register and all(entry["sources"] for entry in register)
    allowed = sources.kinds() - {"pack", "scenario"}
    assert not sources.missing_origins(model, register, ROOT)
    assert all(item["kind"] in allowed for entry in register for item in entry["sources"])
