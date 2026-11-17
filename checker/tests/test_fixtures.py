"""The checker against the contract fixtures. Expectations are data: tests/fixtures/expected.yaml."""

import subprocess
import sys
from pathlib import Path

import pytest
import yaml

from rezono_checker import check, render
from rezono_checker.rules import load_rules
from rezono_checker.snapshots import STATES, resolve

CONTRACTS = Path(__file__).resolve().parents[2] / "contracts"
FIXTURES = CONTRACTS / "fixtures"
MANIFEST = FIXTURES / "manifest" / "Manifest" / "valid" / "epoch.yaml"
HERE = Path(__file__).parent / "fixtures"
EXPECTED = yaml.safe_load((HERE / "expected.yaml").read_text())
ROLES = sorted({s["role"] for s in yaml.safe_load(MANIFEST.read_text())["snapshots"]})


def proof_path(name):
    return FIXTURES / "proof" / "Proof" / "valid" / f"{name}.yaml"


def run(name, role=None):
    proof, manifest = yaml.safe_load(proof_path(name).read_text()), yaml.safe_load(MANIFEST.read_text())
    rules = load_rules(yaml.safe_load((HERE / "rules.yaml").read_text()))
    return check(proof, manifest, rules, lambda uri: resolve(uri, FIXTURES).read_bytes(), role)


def test_every_proof_fixture_has_an_expectation():
    assert sorted(EXPECTED) == sorted(p.stem for p in proof_path("x").parent.glob("*.yaml"))


@pytest.mark.parametrize("name", sorted(EXPECTED))
@pytest.mark.parametrize("role", [None, *ROLES])
def test_fixture(name, role):
    """The verdict depends only on the complete snapshots, whatever role the report is for."""
    report = run(name, role)
    errors = sorted(f["reason"] for f in report["findings"] if f["severity"] == "error")
    assert errors == sorted(EXPECTED[name]), report
    assert report["valid"] == (not EXPECTED[name])


@pytest.mark.parametrize("name", sorted(EXPECTED))
def test_cli_is_deterministic(name):
    args = [sys.executable, "-m", "rezono_checker", "--proof", str(proof_path(name)), "--manifest", str(MANIFEST),
            "--rules", str(HERE / "rules.yaml"), "--snapshot-root", str(FIXTURES)]
    first, second = (subprocess.run(args, capture_output=True, text=True) for _ in range(2))
    assert first.returncode == (1 if EXPECTED[name] else 0), first.stderr
    assert first.stdout == second.stdout == render(run(name))


def test_states_follow_the_value_contract():
    schema = yaml.safe_load((CONTRACTS / "value.yaml").read_text())
    assert list(STATES) == list(schema["enums"]["ValueState"]["permissible_values"])


def test_a_release_is_refused_until_it_is_built():
    """O8: the checker does not yet verify a delimited release, so it refuses one on its own."""
    doc = yaml.safe_load((FIXTURES / "rules" / "rejected" / "release_unsupported.yaml").read_text())
    with pytest.raises(ValueError, match="release is not supported yet"):
        load_rules(doc)
