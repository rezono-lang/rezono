"""Empty provider inventory requires provable, fresh, account-wide coverage before concluding absence.

Per decisions/admission-transport.md, decisions/scoped-completeness.md, decisions/code-does-not-decide.md,
and decisions/run-price-enforcement.md ("Cleanup"), an empty server listing (`b"[]"`) must never have
`coverage="complete"` and `unfiltered=True` fabricated in Python. Feeding the exact same empty provider
response twice into `run/packs/cleanup`:
- With fresh, provable, account-wide completeness evidence (`rezono_checker.evidence.Evidence`) bound to
  the unfiltered request (`ovh_inventory.request()`), account scope, and an RFC 3339 UTC measurement
  timestamp strictly after the freshness cutoff -> an absence conclusion for the listing is allowed.
- With unknown/missing/mismatched account scope, missing or stale measurement timestamp, filtered
  request, or absent completeness evidence -> absence is refused and yields an explicit `unknown`
  reason, never falsely claiming absent or cleaned.
"""

from __future__ import annotations

from contextlib import closing
from hashlib import sha256
import json

import pytest
from rezono_canon import canonical_json, canonical_sha256

from offline_cases import PLAN_HASH, RUN, implementation

DELIVERED = ["srv-2.example.org", "srv-1.example.org"]
EMPTY_LISTING = b"[]"
EXPECTED_REQUEST = ("GET", "/dedicated/server")
FILTERED_REQUEST = ("GET", "/dedicated/server?tag=run-one")
ACCOUNT_SCOPE = "account-one"
DISPATCHED_US = 100
FRESH_AFTER_AT = "2032-05-04T12:00:00Z"
FRESH_OBSERVED_AT = "2032-05-04T12:00:01Z"
STALE_BEFORE_AT = "2032-05-04T11:59:59Z"
LISTING_ID = "listing-1"


def _archived(store, path: str, value: object) -> dict[str, str]:
    body = canonical_json(value).encode("utf-8")
    digest = sha256(body).hexdigest()
    key = f"{path}/{digest}"
    store.put_new(key, body)
    return {"file": path, "uri": store.uri(key), "sha256": digest}


def _listing_evidence(
    store,
    label: str,
    *,
    request_pair: tuple[str, str],
    account_scope: str | None,
    observed_at: str | None,
    fresh_after_at: str = FRESH_AFTER_AT,
    listing_bytes: bytes = EMPTY_LISTING,
):
    """Build a verified completeness receipt (`decisions/admission-transport.md`) for an empty listing.

    Member key parts:
    `["listing", listing_id, account_scope, method, path, observed_at, fresh_after_at]`
    where `observed_at` and `fresh_after_at` are RFC 3339 UTC instants (or `""` when missing),
    allowing `run/packs/cleanup` to compare them directly with `utc_instant(obs) > utc_instant(cutoff)`.
    """
    from rezono_checker.evidence import Evidence

    services = json.loads(listing_bytes.decode("utf-8"))
    source = {
        "kind": "query",
        "name": "ovh-dedicated-server-list",
        "position": f"{label}/cut-{observed_at or 'missing'}",
    }
    cut: dict[str, object] = {"frontier": {"source_id": source["name"], "position": source["position"]}}
    if observed_at is not None:
        cut["observed_at"] = observed_at
    cut["fresh_after_at"] = fresh_after_at
    definition = _archived(store, f"observations/retained/{label}-query.json", {
        "method": request_pair[0],
        "path": request_pair[1],
        "unfiltered": request_pair == EXPECTED_REQUEST,
        "account_wide": True,
        "body_sha256": sha256(listing_bytes).hexdigest(),
    })
    bindings = [
        {"name": "method", "type": "string", "value": request_pair[0]},
        {"name": "path", "type": "string", "value": request_pair[1]},
        {"name": "fresh_after_at", "type": "datetime", "value": fresh_after_at},
    ]
    if account_scope is not None:
        bindings.append({"name": "account_scope", "type": "string", "value": account_scope})
    scope = {"definition": definition, "query": "dedicated-server-listing", "bindings": bindings}
    authority_doc = _archived(store, f"observations/retained/{label}-auth.json", {
        "source": source,
        "issuer": "ovh-inventory-reader",
        "scope": scope,
        "cut": cut,
    })
    issuer = {"id": "ovh-inventory-reader", "authorization": authority_doc}

    member_key = [
        "listing",
        LISTING_ID,
        "" if account_scope is None else account_scope,
        request_pair[0],
        request_pair[1],
        "" if observed_at is None else observed_at,
        fresh_after_at,
    ]
    inventory = [member_key]
    rows = [
        {"key": [name], "values": {"service": name}, "source": dict(source, position=f"{label}/{name}")}
        for name in sorted(services)
    ]
    content = [{"key": member_key, "rows": rows, "terminal": dict(source, position=f"{label}/terminal")}]

    trusted_entry = {
        "source": source,
        "issuer": issuer,
        "scope": scope,
        "cut": cut,
        "inventory": _archived(store, f"observations/retained/{label}-inventory.json", inventory),
        "content": _archived(store, f"observations/retained/{label}-content.json", content),
    }
    context_ref = _archived(
        store,
        f"observations/retained/{label}-context.json",
        {"completeness": [trusted_entry], "rounds": []},
    )

    candidate_body = {
        "source": source,
        "issuer": issuer,
        "scope": scope,
        "cut": cut,
        "inventory": _archived(store, f"observations/submitted/{label}-inventory.json", inventory),
        "content": _archived(store, f"observations/submitted/{label}-content.json", content),
    }
    receipt = {"id": canonical_sha256(["rezono.completeness-receipt/1", candidate_body]), **candidate_body}
    receipt_ref = _archived(store, f"observations/submitted/{label}-receipt.json", receipt)
    index_ref = _archived(
        store,
        f"observations/submitted/{label}-index.json",
        {"completeness_receipts": [receipt_ref], "rounds": []},
    )

    def read_bytes(uri: str) -> bytes | None:
        return store.get(uri.removeprefix(store.uri("")))

    return Evidence(context_ref, index_ref, read_bytes)


def _eval_cleanup_listing(
    *,
    listing_bytes: bytes,
    attempt_scope: str,
    evidence,
    claimed_complete_flag: bool = False,
) -> dict[str, set[tuple[str, ...]]]:
    """Evaluate `run/packs/cleanup` on a parsed empty listing with admitted completeness evidence."""
    from rezono_checker.evidence import admit
    from rezono_compiler import batch, facts, pack, rules, scenarios

    model = pack.read(RUN / "packs" / "cleanup")
    program = rules.load(model.rules)
    services = json.loads(listing_bytes.decode("utf-8"))

    listing_row: dict[str, object] = {"id": LISTING_ID}
    if claimed_complete_flag:
        listing_row["coverage"] = "complete"
        listing_row["unfiltered"] = True

    runtime_rows = facts.rows_of(model, {
        "attempt": [{
            "id": "receipt",
            "operation": "delete_resources",
            "run": "run-one",
            "scope": attempt_scope,
            "plan_hash": PLAN_HASH,
            "dispatched_us": DISPATCHED_US,
        }],
        "listing": [listing_row],
        "listed_service": [
            {"id": f"listed/{index}", "listing": LISTING_ID, "service": name}
            for index, name in enumerate(sorted(services))
        ],
        "delivered_service": [
            {"id": f"delivered/{index}", "service": name}
            for index, name in enumerate(sorted(DELIVERED))
        ],
    })
    inputs = scenarios.rule_rows(model, program, runtime_rows)
    if evidence is not None:
        admitted = admit(evidence)
        for rel_name, rows in admitted.rows.items():
            if rel_name in program.relations:
                inputs[rel_name] = list(rows)
    with closing(batch.connect(program, inputs)) as connection:
        batch.compute(connection, program)
        out = batch.read(connection, program)
    return {name: set(rows) for name, rows in out.items()}


def _is_unknown_or_problem_relation(name: str) -> bool:
    low = name.lower()
    return any(tok in low for tok in ("unknown", "invalid", "unproven", "refus", "problem", "block"))


def _listing_absence_rows(derived: dict[str, set[tuple[str, ...]]]) -> set[tuple[str, tuple[str, ...]]]:
    return {
        (rel_name, row)
        for rel_name, rows in derived.items()
        if any(tok in rel_name.lower() for tok in ("clean", "absent"))
        and not _is_unknown_or_problem_relation(rel_name)
        for row in rows
        if LISTING_ID in row
    }


def _listing_unknown_reasons(derived: dict[str, set[tuple[str, ...]]]) -> set[str]:
    return {
        cell
        for rel_name, rows in derived.items()
        if _is_unknown_or_problem_relation(rel_name)
        for row in rows
        if LISTING_ID in row
        for cell in row
        if isinstance(cell, str) and cell.strip() and cell != LISTING_ID
    }


@pytest.mark.xfail(
    strict=True,
    raises=AssertionError,
    reason=(
        "M4: decisions/admission-transport.md: Stop fabricating coverage='complete' and unfiltered=True "
        "in run/ovh_inventory.py:remaining() when reading an empty response, and require verified "
        "completeness coverage (decisions/scoped-completeness.md, decisions/run-price-enforcement.md) "
        "bound to the unfiltered request, account scope, and fresh RFC 3339 UTC measurement timestamp "
        "strictly after the freshness cutoff before run/packs/cleanup allows an absence conclusion for "
        "a listing; unknown/mismatched scope, missing/stale timestamp, filtered request, or absent "
        "evidence must refuse absence and derive an explicit unknown reason."
    ),
)
def test_empty_provider_inventory_requires_proven_coverage(monkeypatch, tmp_path):
    from rezono_checker.evidence import admit
    from rezono_compiler import batch, pack, rules
    from rezono_publisher.store import FileStore

    # 1. Real leak in run/ovh_inventory.remaining(): calling remaining(b"[]", DELIVERED) without verified
    #    completeness evidence must never fabricate coverage='complete' or unfiltered=True on listing rows.
    captured_inputs: list[dict[str, list[tuple]]] = []
    real_connect = batch.connect

    def spy_connect(program, inputs):
        captured_inputs.append({key: list(values) for key, values in inputs.items() if "listing" in key})
        return real_connect(program, inputs)

    monkeypatch.setattr(batch, "connect", spy_connect)
    request = implementation("ovh_inventory.py", "request")
    remaining = implementation("ovh_inventory.py", "remaining")
    assert request() == EXPECTED_REQUEST
    assert remaining(EMPTY_LISTING, DELIVERED) == []
    assert captured_inputs, "ovh_inventory.remaining() must evaluate run/packs/cleanup"
    listing_inputs = captured_inputs[-1]
    assert not any(value == "complete" for _, value in listing_inputs.get("listing__coverage", ())), (
        f"ovh_inventory.remaining() fabricated complete coverage for an unattested empty listing: {listing_inputs!r}"
    )
    assert not any(value in (True, 1, "true", "TRUE") for _, value in listing_inputs.get("listing__unfiltered", ())), (
        f"ovh_inventory.remaining() fabricated unfiltered=True for an unattested empty listing: {listing_inputs!r}"
    )

    # 2. run/packs/cleanup must declare the protected admission relations (decisions/admission-transport.md §6)
    #    rather than accepting plain caller-supplied coverage flags.
    program = rules.load(pack.read(RUN / "packs" / "cleanup").rules)
    assert {"verified_receipt", "verified_member"} <= set(program.relations), (
        "run/packs/cleanup must declare verified_receipt and verified_member (decisions/admission-transport.md)"
    )

    # 3. Feed the exact same empty provider response b"[]" twice through run/packs/cleanup:
    #    (a) Fresh, provable, account-wide coverage bound to request, account scope, and RFC 3339 UTC timestamp.
    store = FileStore(tmp_path / "store")
    valid_evidence = _listing_evidence(
        store,
        "fresh-account-wide",
        request_pair=EXPECTED_REQUEST,
        account_scope=ACCOUNT_SCOPE,
        observed_at=FRESH_OBSERVED_AT,
        fresh_after_at=FRESH_AFTER_AT,
        listing_bytes=EMPTY_LISTING,
    )
    admitted = admit(valid_evidence)
    assert admitted.rows["verified_receipt"], f"expected valid receipt admission; findings={admitted.findings!r}"

    fresh_derived = _eval_cleanup_listing(
        listing_bytes=EMPTY_LISTING,
        attempt_scope=ACCOUNT_SCOPE,
        evidence=valid_evidence,
    )
    assert _listing_absence_rows(fresh_derived), (
        f"fresh provable account-wide empty listing must permit an absence conclusion; got {fresh_derived!r}"
    )
    assert not _listing_unknown_reasons(fresh_derived), fresh_derived
    assert fresh_derived.get("still_listed", set()) == set()

    #    (b) Exact same empty bytes b"[]" with unknown/mismatched scope, missing/stale timestamp, filtered
    #        request, or absent completeness evidence (even when plain listing flags claim complete/unfiltered)
    #        -> MUST NOT conclude absence/cleaned and MUST yield an explicit unknown reason.
    unproven_cases = [
        (
            "unknown-scope",
            _listing_evidence(
                store,
                "unknown-scope",
                request_pair=EXPECTED_REQUEST,
                account_scope=None,
                observed_at=FRESH_OBSERVED_AT,
            ),
            False,
        ),
        (
            "mismatched-scope",
            _listing_evidence(
                store,
                "mismatched-scope",
                request_pair=EXPECTED_REQUEST,
                account_scope="account-other",
                observed_at=FRESH_OBSERVED_AT,
            ),
            False,
        ),
        (
            "missing-timestamp",
            _listing_evidence(
                store,
                "missing-timestamp",
                request_pair=EXPECTED_REQUEST,
                account_scope=ACCOUNT_SCOPE,
                observed_at=None,
            ),
            False,
        ),
        (
            "stale-before-cutoff",
            _listing_evidence(
                store,
                "stale-before",
                request_pair=EXPECTED_REQUEST,
                account_scope=ACCOUNT_SCOPE,
                observed_at=STALE_BEFORE_AT,
            ),
            False,
        ),
        (
            "stale-at-cutoff",
            _listing_evidence(
                store,
                "stale-at",
                request_pair=EXPECTED_REQUEST,
                account_scope=ACCOUNT_SCOPE,
                observed_at=FRESH_AFTER_AT,
            ),
            False,
        ),
        (
            "filtered-request",
            _listing_evidence(
                store,
                "filtered-request",
                request_pair=FILTERED_REQUEST,
                account_scope=ACCOUNT_SCOPE,
                observed_at=FRESH_OBSERVED_AT,
            ),
            False,
        ),
        ("unverified-plain-flags", None, True),
    ]
    for label, ev, claimed_flag in unproven_cases:
        derived = _eval_cleanup_listing(
            listing_bytes=EMPTY_LISTING,
            attempt_scope=ACCOUNT_SCOPE,
            evidence=ev,
            claimed_complete_flag=claimed_flag,
        )
        assert not _listing_absence_rows(derived), (label, derived)
        assert _listing_unknown_reasons(derived), (
            f"{label}: unproven empty listing must yield an explicit unknown reason; got {derived!r}"
        )
