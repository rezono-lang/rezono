from datetime import datetime, timezone
from fractions import Fraction
from hashlib import sha256
import json

import pytest
from rezono_canon import canonical_json, canonical_sha256

from offline_cases import implementation


FIRST = b'{"currency":"EUR","rates":{"rent":[13,3],"setup":[5,6]}}'
CORRECTED = b'{"currency":"EUR","rates":{"rent":[26,3],"setup":[5,6]}}'
PLAN = sha256(b'example order for one host').hexdigest()
START = "2032-05-01T01:30:00+05:00"
STOP = "2032-05-01T06:30:00Z"
CUT = "2032-05-03T12:00:00Z"
RECEIVED = "2032-05-02T09:00:00Z"
PERIOD = {"id": "rental", "plan_hash": PLAN, "item": "rent", "kind": "period", "received_at": RECEIVED,
          "start": START, "stop": STOP}
FEE = {"id": "setup-a", "plan_hash": PLAN, "item": "setup", "kind": "once", "received_at": RECEIVED,
       "event_at": "2032-05-01T00:30:00+01:00"}
NEXT_FEE = dict(FEE, id="setup-b", event_at="2032-05-01T00:00:00Z")


def archived(store, path, value):
    body = canonical_json(value).encode()
    digest = sha256(body).hexdigest()
    key = f"{path}/{digest}"
    store.put_new(key, body)
    return {"file": path, "uri": store.uri(key), "sha256": digest}


def certified(store, decision, intake, *, held=None):
    """Pin a receipt of the billing intake before `closed_at` and the trusted context of the complete intake.

    `held` is what the candidate receipt itself lists (default: the complete `intake`). Returns the decision with
    the candidate receipt, the trusted authorities and the `verified_receipt` row the shared admission gives.
    """
    closed_at = decision["closed_at"]
    source = {"kind": "query", "name": "billing-intake", "position": f"frontier-{closed_at}"}
    cut = {"frontier": {"source_id": source["name"], "position": source["position"]}}
    definition = archived(store, "trusted/query.json", {
        "population": "billing-intake", "partitions": ["periods", "setups"],
        "axis": "received_at", "predicate": "received_at < closed_at", "time_zone": "UTC",
    })
    scope = {"definition": definition, "query": "billable-intake", "bindings": [
        {"name": "population", "type": "string", "value": "billing-intake"},
        {"name": "closed_at", "type": "datetime", "value": closed_at},
    ]}
    issuer = {"id": "billing-intake-reader", "authorization": archived(store, "trusted/authorization.json", {
        "source": source, "issuer": "billing-intake-reader", "scope": scope, "cut": cut,
    })}

    def members(rows):
        unique = {row["id"]: row for row in rows}
        return [{"key": [partition],
                 "rows": [{"key": [i], "values": {k: v for k, v in unique[i].items() if k != "id"},
                           "source": dict(source, position=f"{partition}/{i}")}
                          for i in sorted(unique) if unique[i]["kind"] == kind],
                 "terminal": dict(source, position=f"{partition}/{source['position']}")}
                for partition, kind in (("periods", "period"), ("setups", "once"))]

    inventory = [["periods"], ["setups"]]
    trusted = {"source": source, "issuer": issuer, "scope": scope, "cut": cut,
               "inventory": archived(store, "trusted/inventory.json", inventory),
               "content": archived(store, "trusted/contents.json", members(intake))}
    body = dict(trusted, inventory=archived(store, "candidate/inventory.json", inventory),
                content=archived(store, "candidate/contents.json", members(intake if held is None else held)))
    receipt = {"id": canonical_sha256(["rezono.completeness-receipt/1", body]), **body}
    row = [receipt["id"], source["name"], canonical_sha256(scope), canonical_sha256(cut),
           trusted["inventory"]["sha256"], trusted["content"]["sha256"]]
    pinned = dict(decision, completeness_receipts=[archived(store, "candidate/receipt.json", receipt)])
    return pinned, [trusted], row


def covered(row, *contributors):
    """The coverage of a closed report: its verified receipt row and the aggregate witness of the total."""
    return {"verified_receipt": row, "count": len(contributors),
            "contributors_sha256": canonical_sha256(sorted(contributors, key=lambda row: row["id"]))}


def test_closed_month_reference(tmp_path):
    from rezono_publisher.store import FileStore

    boundary = datetime(2032, 5, 1, tzinfo=timezone.utc)
    begin, end = map(datetime.fromisoformat, (START, STOP))
    fractions = [Fraction(d // datetime.resolution, (end - begin) // datetime.resolution)
                 for d in (boundary - begin, end - boundary)]
    rent = Fraction(*json.loads(FIRST)["rates"]["rent"])
    assert [rent * part for part in fractions] == [Fraction(91, 60), Fraction(169, 60)]
    assert Fraction(91, 60) + Fraction(5, 6) == Fraction(47, 20)
    assert datetime.fromisoformat(FEE["event_at"]) < boundary == datetime.fromisoformat(NEXT_FEE["event_at"])
    store = FileStore(tmp_path)
    for body in (FIRST, CORRECTED):
        key = sha256(body).hexdigest()
        store.put_new(key, body)
    assert FileStore(tmp_path).get(sha256(FIRST).hexdigest()) == FIRST


@pytest.mark.xfail(strict=True, reason=(
    "Read decisions/run-closed-month.md, section Coverage of the intake. Waits for "
    "test_closed_month_requires_receipt_inventory: the change to run/closed_month.py that turns it green "
    "takes the trusted authorities and lifts this mark too."
))
def test_closed_month(tmp_path):
    from rezono_publisher.store import FileStore

    retain = implementation("closed_month.py", "retain")
    report = implementation("closed_month.py", "report")
    store = FileStore(tmp_path)
    first = retain(store, FIRST)
    assert first == sha256(FIRST).hexdigest()
    timely = [PERIOD, FEE, NEXT_FEE]
    decision, trusted, row = certified(
        store, {"id": "close-apr", "month": "2032-04", "closed_at": CUT, "publication_sha256": first}, timely)
    april = {"publication_sha256": first, "total_eur": [47, 20],
             "lines": {"rental": [91, 60], "setup-a": [5, 6]}, "late": [], "coverage": covered(row, PERIOD, FEE)}
    assert report(store, decision, timely, trusted) == april
    newest = retain(store, CORRECTED)
    assert newest == sha256(CORRECTED).hexdigest() != first
    late = [dict(FEE, id="at-cut", received_at="2032-05-03T14:00:00+02:00"),
            dict(FEE, id="after", received_at="2032-05-03T12:00:01Z")]
    # Reopen the store after the correction and simulate an out-of-order replay.
    reopened = FileStore(tmp_path)
    assert report(reopened, decision, list(reversed(timely + late)), trusted) == dict(
        april, late=[("after", "close-apr", "arrived_after_cutoff"), ("at-cut", "close-apr", "arrived_after_cutoff")])
    revalue = dict(decision, id="revalue", publication_sha256=newest)
    assert report(reopened, revalue, timely, trusted)["total_eur"] == [58, 15]
    may, may_trusted, _ = certified(
        reopened, dict(decision, id="close-may", month="2032-05", closed_at="2032-06-02T12:00:00Z"), timely)
    assert report(reopened, may, timely, may_trusted)["lines"] == {"rental": [169, 60], "setup-b": [5, 6]}
    with pytest.raises(ValueError):
        report(reopened, dict(decision, publication_sha256="0" * 64), timely, trusted)

    class CorruptRead:
        def get(self, key):
            original = reopened.get(key)
            return CORRECTED if original == FIRST else original

    with pytest.raises(ValueError):
        report(CorruptRead(), decision, timely, trusted)


@pytest.mark.parametrize(
    "plan_fields",
    [
        pytest.param({}, id="missing"),
        pytest.param({"plan_hash": None}, id="null"),
        pytest.param({"plan_hash": ""}, id="empty"),
        pytest.param({"plan_hash": "plan"}, id="not-a-digest"),
        pytest.param({"plan_hash": "A" * 64}, id="not-canonical"),
    ],
)
def test_close_rejects_receipts_without_a_plan_digest(plan_fields):
    report = implementation("closed_month.py", "report")
    digest = sha256(FIRST).hexdigest()
    decision = {"id": "close-apr", "month": "2032-04", "closed_at": CUT, "publication_sha256": digest}
    receipt = {key: value for key, value in PERIOD.items() if key != "plan_hash"} | plan_fields

    with pytest.raises(ValueError, match="plan hash for billing observation rental"):
        report({digest: FIRST}, decision, [FEE, receipt])


@pytest.mark.xfail(strict=True, reason=(
    "Read decisions/run-closed-month.md, section Coverage of the intake. Waits for "
    "test_closed_month_requires_receipt_inventory: the change to run/closed_month.py that turns it green "
    "takes the trusted authorities and lifts this mark too."
))
def test_close_distinguishes_a_retry_from_a_change_of_plan(tmp_path):
    from rezono_publisher.store import FileStore

    retain = implementation("closed_month.py", "retain")
    report = implementation("closed_month.py", "report")
    store = FileStore(tmp_path)
    digest = retain(store, FIRST)
    decision, trusted, _ = certified(
        store, {"id": "close-apr", "month": "2032-04", "closed_at": CUT, "publication_sha256": digest}, [PERIOD])

    assert report(store, decision, [PERIOD, PERIOD.copy()], trusted)["total_eur"] == [91, 60]
    other_plan = dict(PERIOD, plan_hash=sha256(b"another order").hexdigest())
    with pytest.raises(ValueError, match="conflicting billing observations for rental"):
        report(store, decision, [PERIOD, other_plan], trusted)


@pytest.mark.xfail(strict=True, reason=(
    "Read decisions/run-closed-month.md, section Coverage of the intake. Waits for "
    "test_closed_month_requires_receipt_inventory: the change to run/closed_month.py that turns it green "
    "takes the trusted authorities and lifts this mark too."
))
@pytest.mark.parametrize(
    ("received_at", "timely"),
    [
        pytest.param("2032-05-03T12:00:00.0000001Z", True, id="before"),
        pytest.param("2032-05-03T12:00:00.0000003+00:00:00.0000002", True, id="fractional-offset"),
        pytest.param("2032-05-03T14:00:00.000000200+02:00", False, id="equal-offset"),
        pytest.param("2032-05-03T12:00:00.0000003Z", False, id="after"),
    ],
)
def test_close_preserves_fractional_cutoff_order(tmp_path, received_at, timely):
    from rezono_publisher.store import FileStore

    retain = implementation("closed_month.py", "retain")
    report = implementation("closed_month.py", "report")
    store = FileStore(tmp_path)
    digest = retain(store, FIRST)
    fee = dict(FEE, received_at=received_at)
    # The authoritative intake before the cutoff holds the fee only when it arrived in time.
    decision, trusted, row = certified(store, {
        "id": "close", "month": "2032-04", "closed_at": "2032-05-03T12:00:00.0000002Z", "publication_sha256": digest,
    }, [fee] if timely else [])
    result = report(store, decision, [fee], trusted)

    amount = [5, 6] if timely else [0, 1]
    assert result == {
        "publication_sha256": digest,
        "lines": {"setup-a": amount} if timely else {},
        "total_eur": amount,
        "late": [] if timely else [("setup-a", "close", "arrived_after_cutoff")],
        "coverage": covered(row, fee) if timely else covered(row),
    }


@pytest.mark.xfail(strict=True, reason=(
    "Read decisions/run-closed-month.md, section Coverage of the intake. Waits for "
    "test_closed_month_requires_receipt_inventory: the change to run/closed_month.py that turns it green "
    "takes the trusted authorities and lifts this mark too."
))
def test_close_splits_a_submicrosecond_period_at_the_utc_month_edge(tmp_path):
    from rezono_publisher.store import FileStore

    retain = implementation("closed_month.py", "retain")
    report = implementation("closed_month.py", "report")
    store = FileStore(tmp_path)
    digest = retain(store, FIRST)
    receipt = dict(PERIOD, start="2032-05-01T01:59:59.9999999+02:00",
                   stop="2032-05-01T00:00:00.0000002Z")
    decision, trusted, _ = certified(
        store, {"id": "close-apr", "month": "2032-04", "closed_at": CUT, "publication_sha256": digest}, [receipt])

    assert report(store, decision, [receipt], trusted)["lines"] == {"rental": [13, 9]}
    may, may_trusted, _ = certified(
        store, dict(decision, id="close-may", month="2032-05", closed_at="2032-06-02T12:00:00Z"), [receipt])
    assert report(store, may, [receipt], may_trusted)["lines"] == {"rental": [26, 9]}


@pytest.mark.xfail(strict=True, reason=(
    "Read decisions/run-closed-month.md, section Coverage of the intake. Waits for "
    "test_closed_month_requires_receipt_inventory: the change to run/closed_month.py that turns it green "
    "takes the trusted authorities and lifts this mark too."
))
def test_close_withholds_the_total_without_verified_coverage_of_the_intake(tmp_path):
    from rezono_publisher.store import FileStore

    retain = implementation("closed_month.py", "retain")
    report = implementation("closed_month.py", "report")
    store = FileStore(tmp_path)
    april = {"id": "close-apr", "month": "2032-04", "closed_at": CUT, "publication_sha256": retain(store, FIRST)}
    intake = [PERIOD, FEE, NEXT_FEE]
    decision, trusted, row = certified(store, april, intake)
    pending = {"publication_sha256": april["publication_sha256"], "total_eur": None, "lines": None, "late": []}

    def unknown(result):
        assert {k: v for k, v in result.items() if k != "coverage"} == pending
        return result["coverage"]["unknown"]

    # An empty delivery, or the timely rental alone, is no evidence that the intake was complete.
    assert unknown(report(store, april, [])) == ["receipt_missing"]
    assert unknown(report(store, april, [PERIOD])) == ["receipt_missing"]
    # A candidate receipt without its trusted context, or one that drops a timely row, is not admitted.
    assert unknown(report(store, decision, intake))[0].startswith("receipt_scope_unauthorized")
    dropped, dropped_trusted, _ = certified(store, april, intake, held=[PERIOD, NEXT_FEE])
    assert unknown(report(store, dropped, [PERIOD, NEXT_FEE], dropped_trusted))[0].startswith(
        "receipt_content_mismatch")
    # An admitted receipt covers only the exact timely intake it certifies, at this cutoff.
    assert unknown(report(store, decision, [PERIOD, NEXT_FEE], trusted)) == ["receipt_replay_mismatch: missing setup-a"]
    assert unknown(report(store, decision, [*intake, dict(FEE, id="extra")], trusted)) == [
        "receipt_replay_mismatch: unexpected extra"]
    assert unknown(report(store, decision, [PERIOD, dict(FEE, item="rent"), NEXT_FEE], trusted)) == [
        "receipt_replay_mismatch: changed setup-a"]
    later = dict(decision, closed_at="2032-05-03T12:00:01Z")
    assert unknown(report(store, later, intake, trusted))[0].startswith("receipt_not_at_close")

    # A certified empty intake closes at zero, and the complete intake closes at 47/20.
    empty, empty_trusted, empty_row = certified(store, april, [])
    assert report(store, empty, [], empty_trusted) == dict(pending, total_eur=[0, 1], lines={},
                                                           coverage=covered(empty_row))
    assert report(store, decision, intake, trusted) == dict(
        pending, total_eur=[47, 20], lines={"rental": [91, 60], "setup-a": [5, 6]}, coverage=covered(row, PERIOD, FEE))
