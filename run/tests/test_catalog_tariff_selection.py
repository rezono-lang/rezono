"""Citable catalog tariff selection via run/ovh_catalog.py and run/packs/provider-terms.

Per decisions/code-does-not-decide.md and decisions/run-price-enforcement.md ("The price list"),
eligible tariff capacities, intervals, and price types belong in `run/packs/provider-terms`, not in
Python conditionals inside `run/ovh_catalog.py`. Following `run/tests/test_ovh_fail_closed_and_guarantee.py`:
- `ovh_catalog.terms()` must fail closed when `provider-terms` supplies no fact states and must read
  its tariff selection / refusal from `run/packs/provider-terms` via `rezono_compiler.batch.read`.
- When one valid tariff combination exists, the derived outcome cites the exact used tariff rows
  (catalog edition digest + row selectors, sensitive to pricing position and plan index) and the
  versioned tariff policy from `run/packs/provider-terms`, and changing the pack's tariff policy facts
  changes which tariff is selected.
- When two equivalent monthly renew tariffs exist, selection is refused citing BOTH candidate rows
  (their selectors and edition) and the conflict/ambiguity reason.
"""

from __future__ import annotations

from copy import deepcopy
from hashlib import sha256
import json
from runpy import run_path

import pytest
import yaml

from offline_cases import RUN

PROVIDER_TERMS = RUN / "packs" / "provider-terms"


def _pricing(
    capacity: str,
    price: int,
    tax: int,
    *,
    interval: int = 1,
    unit: str = "month",
    commitment: int = 0,
    mode: str = "default",
    kind: str = "rental",
) -> dict[str, object]:
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


def _catalog() -> dict[str, object]:
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


def _raw(document: dict[str, object]) -> bytes:
    return json.dumps(document).encode("utf-8")


def _cells(rows_by_rel: list[tuple[str, set[tuple[str, ...]]]]) -> set[str]:
    return {str(cell) for _, rows in rows_by_rel for row in rows for cell in row}


def _mentions_index(tokens: set[str] | str, index: int) -> bool:
    text = " ".join(sorted(tokens)) if isinstance(tokens, set) else tokens
    markers = (f"/pricings/{index}", f"[{index}]", f"/{index}", f":{index}", f"#{index}")
    if any(marker in text for marker in markers):
        return True
    return isinstance(tokens, set) and str(index) in tokens


@pytest.mark.xfail(
    strict=True,
    raises=AssertionError,
    reason=(
        "M4: decisions/code-does-not-decide.md: Move catalog tariff eligibility and selection from "
        "run/ovh_catalog.py:terms() into run/packs/provider-terms (per decisions/run-price-enforcement.md, "
        "'The price list'). Fail closed when provider-terms provides no fact states; derive the selected "
        "tariffs in provider-terms citing the catalog edition, exact used tariff row selectors, and "
        "versioned provider-terms policy so changing pack policy facts changes selection; and refuse two "
        "equivalent monthly renew tariffs citing both candidate rows and the conflict/ambiguity reason."
    ),
)
def test_catalog_tariff_selection_cites_rows_and_refuses_ambiguous_monthly_tariffs(monkeypatch):
    from rezono_compiler import batch, scenarios

    pack_meta = yaml.safe_load((PROVIDER_TERMS / "pack.yaml").read_text(encoding="utf-8"))
    pack_version = str(pack_meta["version"])

    reads: list[tuple[str, str, set[tuple[str, ...]]]] = []
    real_read = batch.read

    def spy_read(connection, program, names=None):
        result = real_read(connection, program, names)
        for name, values in result.items():
            reads.append((program.pack, name, set(values)))
        return result

    monkeypatch.setattr(batch, "read", spy_read)

    module = run_path(str(RUN / "ovh_catalog.py"))
    terms = module["terms"]

    # 1. Single valid tariff combination: ovh_catalog.terms() reads derived rows from provider-terms
    #    citing the catalog edition, exact used tariff row selectors, and versioned provider-terms policy.
    body = _raw(_catalog())
    edition = sha256(body).hexdigest()
    reads.clear()
    result = terms(body, "example-plan", "default")
    assert result == {
        "currency": "EUR",
        "setup": [4999, 100],
        "setup_tax": [4999, 500],
        "period": [8999, 100],
        "period_tax": [8999, 500],
        "interval_months": 1,
        "source_sha256": edition,
    }
    provider_reads = [(rel, rows) for pack_name, rel, rows in reads if pack_name == "provider-terms" and rows]
    assert provider_reads, (
        "run/ovh_catalog.py:terms() did not read derived tariff selection from run/packs/provider-terms"
    )
    cited_cells = _cells(provider_reads)
    assert any(edition in cell for cell in cited_cells), (
        f"derived tariff selection must cite catalog edition {edition!r}; got {provider_reads!r}"
    )
    assert any(pack_version in cell for cell in cited_cells), (
        f"derived tariff selection must cite versioned provider-terms policy ({pack_version!r}); "
        f"got {provider_reads!r}"
    )
    assert _mentions_index(cited_cells, 0) and _mentions_index(cited_cells, 1), (
        f"derived tariff selection must cite used pricing rows 0 and 1; got {provider_reads!r}"
    )

    # Reordering pricings moves the eligible setup/renew rows to indices 2 and 3; selectors must follow.
    reordered_doc = _catalog()
    orig_pricings = reordered_doc["plans"][0]["pricings"]
    reordered_doc["plans"][0]["pricings"] = [orig_pricings[2], orig_pricings[3], orig_pricings[0], orig_pricings[1]]
    reordered_body = _raw(reordered_doc)
    reordered_edition = sha256(reordered_body).hexdigest()
    reads.clear()
    reordered_result = terms(reordered_body, "example-plan", "default")
    assert reordered_result["setup"] == [4999, 100]
    assert reordered_result["period"] == [8999, 100]
    reordered_reads = [(rel, rows) for pack_name, rel, rows in reads if pack_name == "provider-terms" and rows]
    reordered_cells = _cells(reordered_reads)
    assert any(reordered_edition in cell for cell in reordered_cells), reordered_reads
    assert _mentions_index(reordered_cells, 2) and _mentions_index(reordered_cells, 3), (
        f"reordered tariff selection must cite moved pricing rows 2 and 3; got {reordered_reads!r}"
    )
    assert reordered_cells != cited_cells, "reordering tariff rows must change the cited row selectors"

    # 2. Two equivalent monthly renew tariffs: refused citing BOTH candidate rows (indices 1 and 4),
    #    the catalog edition, and an explicit conflict/ambiguity reason.
    ambiguous_doc = _catalog()
    ambiguous_doc["plans"][0]["pricings"].append(deepcopy(ambiguous_doc["plans"][0]["pricings"][1]))
    ambiguous_body = _raw(ambiguous_doc)
    ambiguous_edition = sha256(ambiguous_body).hexdigest()

    reads.clear()
    with pytest.raises(ValueError) as exc_info:
        terms(ambiguous_body, "example-plan", "default")
    message = str(exc_info.value)

    refusal_reads = [(rel, rows) for pack_name, rel, rows in reads if pack_name == "provider-terms" and rows]
    assert refusal_reads, (
        "refusing ambiguous monthly tariffs must derive refusal rows from run/packs/provider-terms"
    )
    refusal_cells = _cells(refusal_reads)
    assert _mentions_index(refusal_cells, 1) and _mentions_index(refusal_cells, 4), (
        f"provider-terms refusal must cite BOTH candidate monthly rows (1 and 4); got {refusal_reads!r}"
    )
    assert _mentions_index(message, 1) and _mentions_index(message, 4), (
        f"ValueError must cite BOTH conflicting candidate rows (1 and 4); got {message!r}"
    )
    assert any(ambiguous_edition in cell for cell in refusal_cells) or ambiguous_edition in message, (
        f"refusal must cite catalog edition {ambiguous_edition!r}; rows={refusal_reads!r}, msg={message!r}"
    )
    assert any(
        word in text.lower()
        for text in (*refusal_cells, message)
        for word in ("ambig", "conflict", "multiple", "duplicate")
    ), (refusal_reads, message)

    # 3. Policy-driven selection (following test_ovh_fail_closed_and_guarantee.py):
    #    (a) Empty provider-terms fact states must fail closed before evaluating rules.
    #    (b) Substituting the pack's renewal interval policy fact from 1 to 12 changes which tariff wins.
    real_fact_states = scenarios.fact_states

    def twelve_month_policy_states(model, directory, *args, **kwargs):
        states = real_fact_states(model, directory, *args, **kwargs)
        updated = []
        for item in states:
            pack_facts = {
                table: [
                    tuple(12 if cell == 1 else ("12" if cell == "1" else cell) for cell in row)
                    if ("interval" in table or "tariff" in table or "catalog" in table)
                    else row
                    for row in rows
                ]
                for table, rows in item[3].items()
            }
            updated.append((*item[:3], pack_facts, *item[4:]))
        return updated

    twelve_month_doc = _catalog()
    twelve_month_doc["plans"][0]["pricings"] = [
        _pricing("installation", 4999000000, 999800000, interval=0, unit="none", kind="purchase"),
        _pricing("renew", 8999000000, 1799800000, interval=1),
        _pricing("renew", 7999000000, 1599800000, interval=12),
    ]
    monkeypatch.setattr(scenarios, "fact_states", twelve_month_policy_states)
    reloaded = run_path(str(RUN / "ovh_catalog.py"))
    policy_result = reloaded["terms"](_raw(twelve_month_doc), "example-plan", "default")
    assert policy_result["interval_months"] == 12, (
        f"changing provider-terms interval policy fact must select the 12-month tariff; got {policy_result!r}"
    )
    assert policy_result["period"] == [7999, 100]

    monkeypatch.setattr(scenarios, "fact_states", lambda *args, **kwargs: [])
    connect_calls: list[str] = []
    real_connect = batch.connect

    def spy_connect(program, *args, **kwargs):
        connect_calls.append(program.pack)
        return real_connect(program, *args, **kwargs)

    monkeypatch.setattr(batch, "connect", spy_connect)
    empty_reloaded = run_path(str(RUN / "ovh_catalog.py"))
    with pytest.raises((ValueError, RuntimeError)):
        empty_reloaded["terms"](body, "example-plan", "default")
    assert connect_calls == [], "ovh_catalog.terms() must fail closed before running rules with empty pack facts"
