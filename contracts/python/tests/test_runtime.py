"""rede_ports, the port contract at run time (PC3), against the contract's own fixtures and the real declarations.

The fixtures in contracts/fixtures/port say what LinkML accepts and refuses (contracts/check.py); rede_ports
must give the same verdict on every one of them, with the generated JSON Schema and no LinkML.
"""

from pathlib import Path

import pytest
import yaml

import rede_ports
from rede_ports import PortError

ROOT = Path(__file__).resolve().parents[3]
FIXTURES = ROOT / "contracts" / "fixtures" / "port"
CASES = sorted(FIXTURES.glob("*/*/*.yaml"))
DECLARATIONS = sorted([*ROOT.glob("edge/plugins/*/plugin.yaml"), *ROOT.glob("edge/githost/plugins/*.yaml")])


def name(path: Path) -> str:
    return path.relative_to(ROOT).as_posix()


def test_the_fixtures_cover_both_classes_and_both_verdicts():
    assert {(p.parent.parent.name, p.parent.name) for p in CASES} == {
        (cls, verdict) for cls in ("Port", "PortInvocation") for verdict in ("valid", "invalid")}


@pytest.mark.parametrize("path", CASES, ids=name)
def test_every_fixture_gets_the_verdict_of_its_folder(path):
    found = rede_ports.errors(yaml.safe_load(path.read_text("utf-8")), path.parent.parent.name)
    assert (found == []) == (path.parent.name == "valid"), found


@pytest.mark.parametrize("path", DECLARATIONS, ids=name)
def test_a_declaration_loads_as_its_own_kind_only(path):
    kind = rede_ports.load(path)["kind"]
    assert rede_ports.load(path, kind)["kind"] == kind
    for other in {"in", "out", "effect"} - {kind}:
        with pytest.raises(PortError, match=f"a port of kind '{kind}', not '{other}'"):
            rede_ports.load(path, other)


def checks(*statuses):
    return {"checks": [{"name": f"c{i}", "status": s, "violations": 0} for i, s in enumerate(statuses)]}


@pytest.mark.parametrize("manifest", [checks("green"), checks("green", "warning", "green")])
def test_an_epoch_whose_checks_do_not_block_is_checked(manifest):
    assert rede_ports.unchecked(manifest) == []


@pytest.mark.parametrize("manifest,why", [
    ({}, [rede_ports.NO_RESULTS]),
    ({"checks": []}, [rede_ports.NO_RESULTS]),
    ({"checks": None}, [rede_ports.NO_RESULTS]),
    ({"checks": {"name": "c0", "status": "green"}}, [rede_ports.NO_RESULTS]),
    (None, [rede_ports.NO_RESULTS]),
    (checks("green", "red"), ["check 'c1' is 'red'"]),
    (checks("unavailable", "green", "red"), ["check 'c0' is 'unavailable'", "check 'c2' is 'red'"]),
    (checks("Green"), ["check 'c0' is 'Green'"]),
    ({"checks": [{"name": "c0"}]}, ["check 'c0' is None"]),
    ({"checks": ["green"]}, ["check result 'green' is no record"]),
])
def test_an_epoch_without_results_or_with_a_blocking_check_is_unchecked(manifest, why):
    assert rede_ports.unchecked(manifest) == why
    assert rede_ports.refusal(manifest) == "not a checked epoch: " + "; ".join(why)


VARIANT = {"sweep": "rate", "index": 3, "value": "0.04", "readers": ["viewer"], "status_readers": ["viewer"]}


@pytest.mark.parametrize("more,why", [
    ({"proposal": "p-7"}, "it is the manifest of proposal 'p-7'"),
    ({"variant": VARIANT}, "it is variant 3 of sweep 'rate'"),
    ({"variant": {}}, "it is variant None of sweep None"),
    ({"proposal": "p-7", "variant": VARIANT}, "it is the manifest of proposal 'p-7'; it is variant 3 of sweep 'rate'"),
])
def test_a_what_if_with_green_checks_is_refused_as_a_what_if(more, why):
    """A port reads the state of main only (arbiter, 12-11-2026): the manifest of a proposal or of a variant is
    checked, and it is not a published epoch. The refusal says so, and does not call it unchecked; it names the
    grid position of a variant and not its role lists, which are the access gate's."""
    manifest = {**checks("green", "green"), **more}
    assert rede_ports.unchecked(manifest) == []
    assert rede_ports.refusal(manifest) == "a what-if, not a published epoch: " + why
    assert "viewer" not in rede_ports.refusal(manifest)


@pytest.mark.parametrize("more", [{}, {"proposal": ""}, {"proposal": None}, {"variant": None},
                                  {"base_manifest": "m-1"}])
def test_an_epoch_of_main_is_refused_nothing(more):
    """On main the publisher leaves `proposal` and `variant` out of the manifest (rede_publisher.publish); the
    contract also allows the key with an empty value. A base manifest alone makes no what-if."""
    manifest = {**checks("green", "warning"), **more}
    assert rede_ports.what_if(manifest) == [] and rede_ports.refusal(manifest) == ""


def test_a_what_if_that_is_also_unchecked_is_named_a_what_if():
    assert rede_ports.refusal({**checks("red"), "proposal": "p-7"}).startswith("a what-if, not a published epoch")


@pytest.mark.parametrize("path", sorted(FIXTURES.glob("Port/invalid/*.yaml")), ids=name)
def test_an_invalid_declaration_does_not_load(path):
    with pytest.raises(PortError, match="not a port"):
        rede_ports.load(path)


def test_a_missing_or_unreadable_declaration_does_not_load(tmp_path):
    with pytest.raises(PortError, match="no readable port declaration"):
        rede_ports.load(tmp_path / "absent.yaml")
    (tmp_path / "broken.yaml").write_text("kind: [in\n", encoding="utf-8")
    with pytest.raises(PortError, match="no readable port declaration"):
        rede_ports.load(tmp_path / "broken.yaml")
    (tmp_path / "empty.yaml").write_text("", encoding="utf-8")
    with pytest.raises(PortError, match="not a port"):
        rede_ports.load(tmp_path / "empty.yaml")


@pytest.mark.parametrize("path", DECLARATIONS, ids=name)
def test_every_declaration_loads_and_names_its_calls(path):
    port = rede_ports.load(path)
    for operation in rede_ports.operations(port):
        call = rede_ports.invocation(port, operation, "unit", "0" * 64)
        assert call == {"port": port["name"], "kind": port["kind"], "operation": operation, "unit": "unit",
                        "input_sha256": "0" * 64}


def test_the_operations_of_each_kind():
    ports = {p.stem: rede_ports.load(p) for p in FIXTURES.glob("Port/valid/*.yaml")}
    assert rede_ports.operations(ports["in"]) == ("read",)
    assert rede_ports.operations(ports["out"]) == ("write",)
    assert rede_ports.operations(ports["effect"]) == ("lab-plan", "lab-apply", "lab-status")


def test_an_invocation_is_the_contracts_record():
    """The valid PortInvocation fixtures, made again from their declaration."""
    effect = rede_ports.load(FIXTURES / "Port" / "valid" / "effect.yaml")
    want = yaml.safe_load((FIXTURES / "PortInvocation" / "valid" / "effect-apply.yaml").read_text("utf-8"))
    pinned = {**effect, "runtime": "job", "image": want["image"]}
    assert rede_ports.errors(pinned) == []
    assert rede_ports.invocation(pinned, "lab-apply", want["unit"], want["input_sha256"]) == want
    assert "image" not in rede_ports.invocation(effect, "lab-apply", want["unit"], want["input_sha256"])


def test_an_invocation_the_port_does_not_declare_is_refused():
    effect = rede_ports.load(FIXTURES / "Port" / "valid" / "effect.yaml")
    reads = rede_ports.load(FIXTURES / "Port" / "valid" / "in.yaml")
    for port, operation in ((effect, "apply"), (effect, "read"), (reads, "write"), (reads, "lab-apply")):
        with pytest.raises(PortError, match="no operation"):
            rede_ports.invocation(port, operation, "unit", "0" * 64)


@pytest.mark.parametrize("input_sha256", ["", "0" * 63, "0" * 65, "A" * 64, "g" * 64])
def test_an_invocation_without_a_whole_input_hash_is_refused(input_sha256):
    reads = rede_ports.load(FIXTURES / "Port" / "valid" / "in.yaml")
    with pytest.raises(PortError, match="not an invocation"):
        rede_ports.invocation(reads, "read", "unit", input_sha256)
