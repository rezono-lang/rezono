"""Every port declaration in the repository against contracts/port.yaml (PC1, O12a), with LinkML itself.

The contract's fixtures (contracts/check.sh) show the shape; this test holds the real declarations to it
and shows on them the two guarantees of O12a: no port writes curated facts (an `in` port writes
observations only), and an `out` port runs only on a checked, published epoch.
"""

from pathlib import Path

import pytest
import yaml
from linkml.validator import validate

ROOT = Path(__file__).resolve().parents[3]
PORT = str(ROOT / "contracts" / "port.yaml")
DECLARATIONS = sorted([*ROOT.glob("edge/plugins/*/plugin.yaml"), *ROOT.glob("edge/githost/plugins/*.yaml")])


def errors(doc: dict) -> list[str]:
    return [r.message for r in validate(doc, PORT, "Port").results]


def declaration(path: Path) -> dict:
    return yaml.safe_load(path.read_text("utf-8"))


def test_there_are_declarations():
    assert len(DECLARATIONS) >= 5


@pytest.mark.parametrize("path", DECLARATIONS, ids=lambda p: p.relative_to(ROOT).as_posix())
def test_every_declaration_is_a_port(path):
    doc = declaration(path)
    assert errors(doc) == []
    assert doc["kind"] in ("in", "out", "effect")


@pytest.mark.parametrize("path", DECLARATIONS, ids=lambda p: p.relative_to(ROOT).as_posix())
def test_no_port_writes_curated_facts(path):
    # Not as an in-port and not as any other kind: a curated fact changes only through a proposal (I29).
    for kind, runs_on, row_source in (("in", "source", "source"), (declaration(path)["kind"], None, None)):
        doc = {**declaration(path), "kind": kind, "writes": "fact"}
        if runs_on:
            doc.update(runs_on=runs_on, row_source=row_source)
            doc.pop("effect", None)
        assert errors(doc), f"{kind} port writing curated facts was accepted"


@pytest.mark.parametrize("path", DECLARATIONS, ids=lambda p: p.relative_to(ROOT).as_posix())
def test_an_in_port_writes_only_observations(path):
    doc = {**declaration(path), "kind": "in", "runs_on": "source", "row_source": "source"}
    doc.pop("effect", None)
    assert errors({**doc, "writes": "observation"}) == []
    for other in ("projection", "world"):
        assert errors({**doc, "writes": other}), f"an in-port writing {other} was accepted"


@pytest.mark.parametrize("path", DECLARATIONS, ids=lambda p: p.relative_to(ROOT).as_posix())
def test_an_out_port_runs_only_on_a_checked_epoch(path):
    doc = {**declaration(path), "kind": "out", "writes": "projection", "row_source": "output_index"}
    doc.pop("effect", None)
    doc.pop("footprint", None)  # only an in-port has one
    assert errors({**doc, "runs_on": "checked_epoch"}) == []
    for other in ("source", "approved_plan", "unchecked_epoch", "draft"):
        assert errors({**doc, "runs_on": other}), f"an out-port running on {other} was accepted"
