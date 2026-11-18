from datetime import datetime, timezone
from fractions import Fraction
from hashlib import sha256
import json

import pytest

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


def test_closed_month(tmp_path):
    from rezono_publisher.store import FileStore

    retain = implementation("closed_month.py", "retain")
    report = implementation("closed_month.py", "report")
    store = FileStore(tmp_path)
    first = retain(store, FIRST)
    assert first == sha256(FIRST).hexdigest()
    decision = {"id": "close-apr", "month": "2032-04", "closed_at": CUT, "publication_sha256": first}
    timely = [PERIOD, FEE, NEXT_FEE]
    april = {"publication_sha256": first, "total_eur": [47, 20],
             "lines": {"rental": [91, 60], "setup-a": [5, 6]}, "late": []}
    assert report(store, decision, timely) == april
    newest = retain(store, CORRECTED)
    assert newest == sha256(CORRECTED).hexdigest() != first
    late = [dict(FEE, id="at-cut", received_at="2032-05-03T14:00:00+02:00"),
            dict(FEE, id="after", received_at="2032-05-03T12:00:01Z")]
    # Reopen the store after the correction and simulate an out-of-order replay.
    reopened = FileStore(tmp_path)
    assert report(reopened, decision, list(reversed(timely + late))) == dict(
        april, late=[("after", "close-apr", "arrived_after_cutoff"), ("at-cut", "close-apr", "arrived_after_cutoff")])
    assert report(reopened, dict(decision, id="revalue", publication_sha256=newest), timely)["total_eur"] == [58, 15]
    may = dict(decision, id="close-may", month="2032-05", closed_at="2032-06-02T12:00:00Z")
    assert report(reopened, may, timely)["lines"] == {"rental": [169, 60], "setup-b": [5, 6]}
    with pytest.raises(ValueError):
        report(reopened, dict(decision, publication_sha256="0" * 64), timely)

    class CorruptRead:
        def get(self, key):
            original = reopened.get(key)
            return CORRECTED if original == FIRST else original

    with pytest.raises(ValueError):
        report(CorruptRead(), decision, timely)
