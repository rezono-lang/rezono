"""Citable catalog tariff selection comes from the provider terms pack: decisions/code-does-not-decide.md.

Per decisions/code-does-not-decide.md, decisions/run-price-enforcement.md ("The price list"), and
decisions/facts-and-derivations.md, eligible tariff capacities, durations, and price types belong in
`run/packs/provider-terms`, not in Python conditionals in `run/ovh_catalog.py`. Selecting one valid
tariff combination must cite the exact used tariff rows (catalog edition digest + JSON Pointer selector)
and the versioned policy from `run/packs/provider-terms`. When two equivalent monthly renew tariffs
exist, selection must be refused citing BOTH candidate rows and the conflict/ambiguity reason.
"""

import ast
from copy import deepcopy
from hashlib import sha256
import json
from runpy import run_path

import pytest
import yaml

from offline_cases import RUN

POLICY_LITERALS = {"installation", "renew", "month", "consumption"}


def _pricing(capacity, price, tax, *, interval=1, unit="month", commitment=0, mode="default", kind="rental"):
    return {
        "capacities": [capacity],
        "commitment": commitment,
        "description": capacity,
        "interval": interval,
        "intervalUnit": unit,
        "mode": mode,
        "mustBeCompleted": False,
        "phase": 1,
        "price": price,
        "promotions": [],
        "quantity": {"max": 1, "min": 1},
        "repeat": {"max": 1, "min": 1},
        "strategy": "tiered",
        "tax": tax,
        "type": kind,
    }


def _catalog():
    pricings = [
        _pricing("installation", 4999000000, 999800000, interval=0, unit="none", kind="purchase"),
        _pricing("renew", 8999000000, 1799800000),
        _pricing("renew", 7999000000, 1599800000, commitment=12),
        _pricing("renew", 9999000000, 1999800000, mode="upfront12"),
    ]
    return {
        "catalogId": 1,
        "locale": {"currencyCode": "EUR", "subsidiary": "FR", "taxRate": 20},
        "addons": [],
        "planFamilies": [],
        "products": [],
        "plans": [
            {
                "planCode": "example-plan",
                "pricingType": "rental",
                "pricings": pricings,
                "family": "",
                "invoiceName": "Example",
                "product": "example",
                "addonFamilies": [],
            },
            {
                "planCode": "other-plan",
                "pricingType": "rental",
                "pricings": deepcopy(pricings[:2]),
                "family": "",
                "invoiceName": "Other",
                "product": "other",
                "addonFamilies": [],
            },
        ],
    }


def _raw(document):
    return json.dumps(document).encode("utf-8")


def _string_literals(filename):
    tree = ast.parse((RUN / filename).read_text(encoding="utf-8"))
    return {
        node.value
        for node in ast.walk(tree)
        if isinstance(node, ast.Constant) and isinstance(node.value, str)
    }


def _pack_reads(monkeypatch):
    """Record `(pack, relation, rows)` read through `rezono_compiler.batch.read`."""
    from rezono_compiler import batch

    reads = []
    original = batch.read

    def spy(connection, program, names=None):
        rows = original(connection, program, names)
        for name, values in rows.items():
            reads.append((program.pack, name, set(values)))
        return rows

    monkeypatch.setattr(batch, "read", spy)
    return reads


def _latest_rows(reads, pack_name, relation_name):
    matches = [rows for pack, rel, rows in reads if (pack, rel) == (pack_name, relation_name)]
    assert matches, f"expected {(pack_name, relation_name)!r} to be read from batch.read; saw {reads!r}"
    return matches[-1]


@pytest.mark.xfail(
    strict=True,
    raises=AssertionError,
    reason=(
        "M4: decisions/code-does-not-decide.md: Move catalog tariff eligibility and selection from "
        "run/ovh_catalog.py into run/packs/provider-terms (per decisions/run-price-enforcement.md, "
        "'The price list', and decisions/facts-and-derivations.md). Export catalog_tariff_selection and "
        "catalog_tariff_refusal from run/packs/provider-terms using versioned provider tariff policy facts "
        "instead of Python literals, and expose select_tariffs(catalog, plan_code, mode) in "
        "run/ovh_catalog.py returning exact tariff row citations (edition + JSON Pointer selector) and "
        "the versioned pack policy on selection, or refusing ambiguous duplicate monthly tariffs citing "
        "both candidate rows and the conflict/ambiguity reason."
    ),
)
def test_catalog_tariff_selection_cites_rows_and_refuses_ambiguous_monthly_tariffs(monkeypatch):
    from rezono_compiler import pack, rules

    pack_dir = RUN / "packs" / "provider-terms"
    pack_meta = yaml.safe_load((pack_dir / "pack.yaml").read_text(encoding="utf-8"))
    pack_version = pack_meta["version"]

    # Tariff eligibility vocabulary belongs in run/packs/provider-terms, not hardcoded in Python.
    assert not (_string_literals("ovh_catalog.py") & POLICY_LITERALS), (
        "tariff capacity/duration/price-type policy literals are still hardcoded in run/ovh_catalog.py"
    )

    program = rules.load(pack.read(pack_dir).rules)
    derived = set(program.derived())
    assert {"catalog_tariff_selection", "catalog_tariff_refusal"} <= derived, (
        f"run/packs/provider-terms must derive catalog_tariff_selection and catalog_tariff_refusal; "
        f"found {sorted(derived)}"
    )

    module = run_path(str(RUN / "ovh_catalog.py"))
    assert "select_tariffs" in module, "run/ovh_catalog.py must expose select_tariffs(catalog, plan_code, mode)"
    select_tariffs = module["select_tariffs"]
    terms = module["terms"]

    reads = _pack_reads(monkeypatch)

    # 1. Single valid tariff combination: cites exact used rows (edition + selector) and versioned pack policy.
    body = _raw(_catalog())
    edition = sha256(body).hexdigest()
    reads.clear()
    selected = select_tariffs(body, "example-plan", "default")
    assert selected["status"] == "selected"
    assert selected["terms"] == {
        "currency": "EUR",
        "setup": [4999, 100],
        "setup_tax": [4999, 500],
        "period": [8999, 100],
        "period_tax": [8999, 500],
        "interval_months": 1,
        "source_sha256": edition,
    }
    citations = selected["citations"]
    assert citations["setup"] == {"edition": edition, "selector": "/plans/0/pricings/0"}
    assert citations["period"] == {"edition": edition, "selector": "/plans/0/pricings/1"}
    policy = citations["policy"]
    assert policy["pack"] == "provider-terms"
    assert policy["version"] == pack_version
    assert isinstance(policy["policy"], str) and policy["policy"].strip()

    selection_rows = _latest_rows(reads, "provider-terms", "catalog_tariff_selection")
    assert selection_rows, "expected catalog_tariff_selection row from run/packs/provider-terms"
    assert any(
        "/plans/0/pricings/0" in row and "/plans/0/pricings/1" in row and policy["policy"] in row
        for row in selection_rows
    ), selection_rows
    assert _latest_rows(reads, "provider-terms", "catalog_tariff_refusal") == set()

    # Non-zero plan index proves selectors reflect the actual catalog row positions.
    reads.clear()
    other_selected = select_tariffs(body, "other-plan", "default")
    assert other_selected["status"] == "selected"
    assert other_selected["citations"]["setup"] == {"edition": edition, "selector": "/plans/1/pricings/0"}
    assert other_selected["citations"]["period"] == {"edition": edition, "selector": "/plans/1/pricings/1"}

    # 2. Two equivalent monthly renew tariffs: refused citing BOTH candidate rows and the conflict/ambiguity reason.
    ambiguous_doc = _catalog()
    ambiguous_doc["plans"][0]["pricings"].append(deepcopy(ambiguous_doc["plans"][0]["pricings"][1]))
    ambiguous_body = _raw(ambiguous_doc)
    ambiguous_edition = sha256(ambiguous_body).hexdigest()

    reads.clear()
    refused = select_tariffs(ambiguous_body, "example-plan", "default")
    assert refused["status"] == "refused"
    assert refused.get("terms") is None
    assert isinstance(refused["reason"], str) and refused["reason"].strip()
    assert any(word in refused["reason"].lower() for word in ("ambig", "conflict", "multiple", "duplicate")), refused
    expected_candidates = [
        {"edition": ambiguous_edition, "selector": "/plans/0/pricings/1"},
        {"edition": ambiguous_edition, "selector": "/plans/0/pricings/4"},
    ]
    assert refused["candidates"] == expected_candidates
    assert refused["policy"] == policy

    assert _latest_rows(reads, "provider-terms", "catalog_tariff_selection") == set()
    refusal_rows = _latest_rows(reads, "provider-terms", "catalog_tariff_refusal")
    assert refusal_rows, "expected catalog_tariff_refusal rows from run/packs/provider-terms"
    cited_selectors = {
        cell for row in refusal_rows for cell in row if isinstance(cell, str) and cell.startswith("/plans/")
    }
    assert cited_selectors == {"/plans/0/pricings/1", "/plans/0/pricings/4"}, refusal_rows
    assert any(refused["reason"] in row for row in refusal_rows), (refused["reason"], refusal_rows)

    # terms() continues raising ValueError for existing callers and names both conflicting candidate selectors.
    with pytest.raises(ValueError) as exc_info:
        terms(ambiguous_body, "example-plan", "default")
    message = str(exc_info.value)
    assert "/plans/0/pricings/1" in message and "/plans/0/pricings/4" in message, message
