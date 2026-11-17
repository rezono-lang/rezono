"""The generated Python types against real data, per contract: the valid fixtures in contracts/fixtures/,
the schema bundles the compiler writes and the proofs the explainer writes (examples/**/expected/)."""

import importlib
import json
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[3]
FIXTURES = ROOT / "contracts" / "fixtures"
GENERATED = sorted(p.stem for p in (ROOT / "contracts" / "python" / "rede_contracts").glob("*.py") if p.stem != "__init__")


def fixtures(schema):
    """(class, path, document) for every valid fixture of the contract."""
    return [(p.parent.parent.name, p, yaml.safe_load(p.read_text("utf-8")))
            for p in sorted((FIXTURES / schema.replace("_", "-")).glob("*/valid/*.yaml"))]  # output_index: output-index


def produced(schema):
    """(class, path, document) for every document the compiler or explainer wrote for the contract."""
    if schema == "bundle":
        return [("Bundle", p, json.loads(p.read_text("utf-8")))
                for p in sorted(ROOT.glob("examples/**/expected/compiled/bundle/schema-bundle.json"))]
    if schema == "proof":
        return [("Proof", p, proof) for p in sorted(ROOT.glob("examples/**/expected/explained/*/proofs.json"))
                for proof in json.loads(p.read_text("utf-8"))]
    return []


CASES = {s: fixtures(s) + produced(s) for s in GENERATED}


@pytest.mark.parametrize("schema", GENERATED)
def test_every_contract_has_data_to_load(schema):
    assert CASES[schema], f"{schema}: no fixture and no produced document to test the generated types with"


@pytest.mark.parametrize("schema,cls,path,doc", [(s, *c) for s in GENERATED for c in CASES[s]],
                         ids=lambda x: x.relative_to(ROOT).as_posix() if isinstance(x, Path) else None)
def test_loads_into_generated_type(schema, cls, path, doc):
    getattr(importlib.import_module(f"rede_contracts.{schema}"), cls).model_validate(doc)


def _nulls(v, at="$"):
    if v is None:
        yield at
    elif isinstance(v, dict):
        for k, x in v.items():
            yield from _nulls(x, f"{at}.{k}")
    elif isinstance(v, list):
        for i, x in enumerate(v):
            yield from _nulls(x, f"{at}[{i}]")


@pytest.mark.parametrize("schema,cls,path,doc", [(s, *c) for s in GENERATED for c in produced(s)],
                         ids=lambda x: x.relative_to(ROOT).as_posix() if isinstance(x, Path) else None)
def test_no_null(schema, cls, path, doc):
    """An absent optional slot is left out, never null: the generated types have no null."""
    assert not list(_nulls(doc))[:5]
