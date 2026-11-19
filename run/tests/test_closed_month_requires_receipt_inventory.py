"""Keep observed receipts separate from the authoritative intake at a close."""

from datetime import datetime
from fractions import Fraction
from hashlib import sha256
import json

import pytest
from rezono_canon import canonical_json, canonical_sha256

from offline_cases import implementation
from test_closed_month import CUT, FEE, FIRST, NEXT_FEE, PERIOD


class UnprovedClosedAmount(AssertionError):
    """The report treated an unverified subset as a final close."""


def archived(store, path, value):
    body = canonical_json(value).encode()
    digest = sha256(body).hexdigest()
    key = f"{path}/{digest}"
    store.put_new(key, body)
    return {"file": path, "uri": store.uri(key), "sha256": digest}


def read_archived(store, ref):
    body = store.get(ref["uri"].removeprefix(store.uri("")))
    assert body is not None and sha256(body).hexdigest() == ref["sha256"]
    value = json.loads(body)
    assert canonical_json(value).encode() == body
    return value


def april_intake(store):
    source = {"kind": "query", "name": "billing-intake", "position": "frontier-42"}
    cut = {"frontier": {"source_id": source["name"], "position": source["position"]}}
    definition = archived(store, "trusted/query.json", {
        "population": "billing-intake", "partitions": ["periods", "setups"],
        "axis": "received_at", "predicate": "received_at < closed_at", "time_zone": "UTC",
    })
    scope = {"definition": definition, "query": "billable-intake", "bindings": [
        {"name": "population", "type": "string", "value": "billing-intake"},
        {"name": "closed_at", "type": "datetime", "value": CUT},
    ]}
    authority = archived(store, "trusted/authorization.json", {
        "source": source, "issuer": "billing-intake-reader", "scope": scope, "cut": cut,
    })
    issuer = {"id": "billing-intake-reader", "authorization": authority}

    def member(partition, values):
        rows = [{"key": [row["id"]], "values": {k: v for k, v in row.items() if k != "id"},
                 "source": dict(source, position=f"{partition}/{row['id']}")} for row in values]
        return {"key": [partition], "rows": rows,
                "terminal": dict(source, position=f"{partition}/{source['position']}")}

    inventory = [["periods"], ["setups"]]
    complete = [member("periods", [PERIOD]), member("setups", [FEE, NEXT_FEE])]
    dropped = [member("periods", [PERIOD]), member("setups", [NEXT_FEE])]
    # These pins belong to the trusted fixture and are never read from the candidate receipt.
    trusted = {"source": source, "issuer": issuer, "scope": scope, "cut": cut,
               "inventory": archived(store, "trusted/inventory.json", inventory),
               "content": archived(store, "trusted/contents.json", complete)}

    def manifest(name, members):
        body = {"source": source, "issuer": issuer, "scope": scope, "cut": cut,
                "inventory": archived(store, f"{name}/inventory.json", inventory),
                "content": archived(store, f"{name}/contents.json", members)}
        receipt = {"id": canonical_sha256(["rezono.completeness-receipt/1", body]), **body}
        return {"completeness_receipts": [archived(store, f"{name}/receipt.json", receipt)]}

    return trusted, manifest("complete", complete), manifest("dropped", dropped)


def test_closed_month_requires_receipt_inventory(tmp_path):
    from rezono_publisher.store import FileStore

    retain = implementation("closed_month.py", "retain")
    report = implementation("closed_month.py", "report")
    store = FileStore(tmp_path)
    decision = {"id": "close-apr", "month": "2032-04", "closed_at": CUT,
                "publication_sha256": retain(store, FIRST)}

    trusted, full, omitted = april_intake(store)
    reopened = FileStore(tmp_path)
    exact, = [read_archived(reopened, ref) for ref in full["completeness_receipts"]]
    subset, = [read_archived(reopened, ref) for ref in omitted["completeness_receipts"]]
    for candidate in (exact, subset):
        assert candidate["id"] == canonical_sha256([
            "rezono.completeness-receipt/1", {key: value for key, value in candidate.items() if key != "id"},
        ])
        assert all(candidate[key] == trusted[key] for key in ("source", "issuer", "scope", "cut"))
        assert read_archived(reopened, candidate["inventory"]) == read_archived(reopened, trusted["inventory"])
    assert read_archived(reopened, exact["issuer"]["authorization"])["cut"] == trusted["cut"]
    assert exact["content"]["sha256"] == trusted["content"]["sha256"]
    assert subset["content"]["sha256"] != trusted["content"]["sha256"]

    whole = read_archived(reopened, trusted["content"])
    partial = read_archived(reopened, subset["content"])
    assert [member["key"] for member in whole] == [member["key"] for member in partial] == [["periods"], ["setups"]]
    assert [member["terminal"] for member in whole] == [member["terminal"] for member in partial]
    assert [row["key"] for member in whole for row in member["rows"]] == [["rental"], ["setup-a"], ["setup-b"]]
    assert [row["key"] for member in partial for row in member["rows"]] == [["rental"], ["setup-b"]]

    starts = datetime.fromisoformat(PERIOD["start"])
    stops = datetime.fromisoformat(PERIOD["stop"])
    may = datetime.fromisoformat(NEXT_FEE["event_at"])
    rates = json.loads(reopened.get(decision["publication_sha256"]))["rates"]
    rental = Fraction(*rates["rent"]) * Fraction((may - starts) // datetime.resolution,
                                                 (stops - starts) // datetime.resolution)
    assert rental == Fraction(91, 60)
    assert rental + Fraction(*rates["setup"]) == Fraction(47, 20)

    submitted = [{"id": row["key"][0], **row["values"]} for member in partial for row in member["rows"]]
    exact_cut = dict(FEE, id="at-cut", received_at=CUT)
    # There is no shared receipt admission in the report yet. The archived fixtures above
    # also carry the positive and mutated inputs for that boundary once it accepts them.
    replay = report(reopened, decision, [*submitted, exact_cut])
    assert replay["late"] == [("at-cut", "close-apr", "arrived_after_cutoff")]
    if replay["total_eur"] is not None:
        raise UnprovedClosedAmount(f"final total without receipt coverage: {replay['total_eur']!r}")
