"""A live-engine result must account for every explicitly selected test case."""

from pathlib import Path
import subprocess
import sys
import xml.etree.ElementTree as ET

import pytest


ROOT = Path(__file__).resolve().parents[2]
VERIFY = ROOT / "compiler/ci/verify_feldera_run.py"
COMPILER = "compiler/tests/test_calc.py::test_feldera_gives_what_duckdb_gives[full]"
CHOICE = "compiler/tests/test_calc.py::test_feldera_gives_what_duckdb_gives[choice]"
PLATFORM = "examples/test_platform_incremental_proof.py::test_platform_incremental_delta_and_witnesses_match_batch"


def test_live_report_accounts_for_every_selected_case(tmp_path):
    if not VERIFY.is_file():
        raise FileNotFoundError("missing live Feldera result verifier")

    def run(nodes, outcomes):
        selected = tmp_path / "selected.txt"
        selected.write_text("\n".join(nodes) + "\n", encoding="utf-8")
        suites = ET.Element("testsuites")
        suite = ET.SubElement(suites, "testsuite", name="pytest")
        for node, outcome in outcomes:
            path, name = node.split("::")
            case = ET.SubElement(suite, "testcase", classname=path[:-3].replace("/", "."), name=name)
            if outcome:
                ET.SubElement(case, outcome)
        report = tmp_path / "results.xml"
        ET.ElementTree(suites).write(report, encoding="utf-8")
        return subprocess.run([sys.executable, str(VERIFY), str(selected), str(report)],
                              capture_output=True, text=True, timeout=10).returncode

    nodes = [COMPILER, CHOICE, PLATFORM]
    good = [(node, None) for node in nodes]
    assert run(nodes, good) == 0
    for outcome in ("skipped", "failure", "error"):
        assert run(nodes, good[:-1] + [(PLATFORM, outcome)]) != 0
    for invalid in ([], good[:-1], good[1:], good + [good[0]], [good[0], good[0], good[2]]):
        assert run(nodes, invalid) != 0
    assert run(nodes[:-1], good[:-1]) != 0
    assert run([PLATFORM], [(PLATFORM, None)]) != 0
    assert run(nodes[1:], good) != 0
    report = tmp_path / "results.xml"
    for broken in (None, "<testsuites>"):
        if broken is None:
            report.unlink()
        else:
            report.write_text(broken, encoding="utf-8")
        assert subprocess.run([sys.executable, str(VERIFY), str(tmp_path / "selected.txt"), str(report)],
                              capture_output=True, timeout=10).returncode != 0
