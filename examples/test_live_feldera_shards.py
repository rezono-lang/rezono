"""The live comparison must not publish evidence from a partial or mismatched shard."""

from pathlib import Path
import subprocess
import sys
import xml.etree.ElementTree as ET

import pytest


CI = Path(__file__).resolve().parents[1] / "compiler" / "ci"
EXPECTED = {
    "library": ["examples/test_feldera.py::test_feldera_accepts_the_sql_and_finds_the_errors[library]"],
    "projects": ["examples/test_feldera.py::test_feldera_accepts_the_sql_and_finds_the_errors[projects]"],
    "compiler-calc": [
        "compiler/tests/test_calc.py::test_feldera_gives_what_duckdb_gives[full]",
        "compiler/tests/test_calc.py::test_feldera_gives_what_duckdb_gives[choice]",
    ],
    "compiler-bound": [
        "compiler/tests/test_bound.py::test_the_check_view_on_feldera_holds_the_rows_past_the_bound",
        "compiler/tests/test_boolean_rule_inputs.py::test_native_boolean_rule_inputs",
    ],
    "compiler-rules": [
        "compiler/tests/test_rules_properties.py::test_feldera_runs_generated_programs_as_duckdb_does[0]",
        "compiler/tests/test_rules_properties.py::test_feldera_runs_generated_programs_as_duckdb_does[1]",
    ],
    "tenant-capacity-interface": [
        "examples/test_feldera_rules.py::test_incremental_on_feldera_equals_batch[platform/tenant-capacity/interface]",
    ],
    "platform": [
        "examples/test_feldera_rules.py::test_incremental_on_feldera_equals_batch[platform]",
        "examples/test_platform_incremental_proof.py::test_platform_incremental_delta_and_witnesses_match_batch",
    ],
    "subsidy": ["examples/test_feldera_rules.py::test_incremental_on_feldera_equals_batch[subsidy]"],
}


def run(entry, *args):
    return subprocess.run([sys.executable, str(CI / entry), *map(str, args)],
                          capture_output=True, text=True, timeout=10)


@pytest.fixture
def evidence(tmp_path):
    inputs = tmp_path / "shards"
    for shard, selected in EXPECTED.items():
        folder = inputs / f"feldera-shard-5-{shard}"
        folder.mkdir(parents=True)
        nodes = sorted(node for group in EXPECTED.values() for node in group)
        (folder / "collection.txt").write_text("\n".join(nodes) + "\n", encoding="utf-8")
        (folder / "collected.txt").write_text("\n".join(selected) + "\n", encoding="utf-8")
        suite = ET.Element("testsuite", name=shard)
        for node in selected:
            path, name = node.split("::")
            ET.SubElement(suite, "testcase", classname=path[:-3].replace("/", "."), name=name)
        ET.ElementTree(suite).write(folder / "results.xml", encoding="utf-8")
    return inputs, tmp_path / "aggregate"


@pytest.mark.parametrize("outcome", [None, "failure", "skipped", "error"])
def test_merge_preserves_all_live_cases_and_outcomes(evidence, outcome):
    inputs, output = evidence
    for shard, expected in EXPECTED.items():
        source = inputs / f"feldera-shard-5-{shard}" / "collection.txt"
        chosen = run("feldera_shards.py", "select", shard, source)
        assert chosen.returncode == 0, chosen.stderr
        assert sorted(chosen.stdout.splitlines()) == sorted(expected)
    if outcome:
        path = inputs / "feldera-shard-5-subsidy" / "results.xml"
        tree = ET.parse(path)
        ET.SubElement(tree.getroot().find("testcase"), outcome).text = "original diagnostic"
        tree.write(path, encoding="utf-8")
    merged = run("feldera_shards.py", "merge", inputs, output, 5)
    assert merged.returncode == 0, merged.stderr
    report = ET.parse(output / "results.xml")
    assert len(list(report.iter("testcase"))) == 12
    if outcome:
        assert report.find(f".//{outcome}").text == "original diagnostic"
    verified = run("verify_feldera_run.py", output / "collected.txt", output / "results.xml")
    assert verified.returncode == int(outcome is not None)


@pytest.mark.parametrize("mutation", ["missing", "duplicate", "foreign", "collection", "all-drop", "attempt"])
def test_partial_or_mismatched_shard_cannot_produce_evidence(evidence, mutation):
    inputs, output = evidence
    subsidy = inputs / "feldera-shard-5-subsidy"
    if mutation == "missing":
        (subsidy / "results.xml").unlink()
    elif mutation in {"duplicate", "foreign"}:
        path = subsidy / "results.xml"
        tree = ET.parse(path)
        suite = tree.getroot()
        case = suite.find("testcase")
        if mutation == "duplicate":
            suite.append(case)
        else:
            case.set("name", "test_another_test")
        tree.write(path, encoding="utf-8")
    elif mutation == "collection":
        (subsidy / "collection.txt").write_text(EXPECTED["subsidy"][0] + "\n", encoding="utf-8")
    elif mutation == "all-drop":
        for file in inputs.glob("*/collection.txt"):
            lines = file.read_text(encoding="utf-8").splitlines()
            file.write_text("\n".join(n for n in lines if n not in EXPECTED["tenant-capacity-interface"]) + "\n",
                            encoding="utf-8")
    else:
        subsidy.rename(inputs / "feldera-shard-4-subsidy")
    assert run("feldera_shards.py", "merge", inputs, output, 5).returncode != 0
    assert not output.exists()
