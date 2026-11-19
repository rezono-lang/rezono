"""Find the third request's first change using the written values and two published witnesses."""
import importlib.util
import json
import shutil
from pathlib import Path

import pytest
import yaml

from case_support import ROOT
from rezono_publisher import publish, store


class MissingThresholdPublication(Exception):
    pass


FIRST, SECOND, THIRD = "elm/ledger", "reed/studio", "reed/fern"


def ledger(values, initial):
    # Only the first and third requests are eligible. The rejected middle request consumes zero.
    output = []
    for capacity in sorted(values):
        free = capacity
        statuses = {}
        for key, size, allowed in [(FIRST, initial, True),(SECOND,2,False),(THIRD,4,True)]:
            status = "denied" if not allowed else "landed" if size <= free else "capacity"
            statuses[key] = status
            if status == "landed":
                free -= size
        output.append((capacity,statuses,free))
    return output


def test_independent_first_change_and_no_change():
    def changes(records):
        return [(l[0],r[0]) for l,r in zip(records,records[1:]) if l[1][THIRD] != r[1][THIRD]]
    assert changes(ledger([6,9,10,12],6)) == [(9,10)]
    assert changes(ledger([6,8,10],4)) == [(6,8)]
    assert changes(ledger([10,12],6)) == []


def scenario(path, values, initial):
    import sys
    # request_preview is the platform's actual typed intake, shared with its ordinary admission scenario.
    sys.path.insert(0,str(ROOT))
    try:
        from request_preview import request_rows
    finally:
        sys.path.pop(0)
    model = path / "examples" / "platform"
    shutil.copytree(ROOT,model)
    shutil.copytree(ROOT.parents[1] / "packs",path / "packs")
    teams = model / "teams"
    first = teams / FIRST / "request.json"
    if initial == 4:
        req = json.loads(first.read_text())
        del req["items"]["database"]
        first.write_text(json.dumps(req))
    third = teams / THIRD / "request.json"
    third.parent.mkdir()
    third.write_text(json.dumps(dict(profile="production", items={"cluster":"medium"},
                     connections=[], submittedAt="2026-01-03T00:00:00Z")))
    catalog = json.loads((model / "tenant-catalog.json").read_text())
    rec = dict(request_rows(teams,catalog))
    rec["offered_cores"] = [dict(id=f"{item}/{size}",cores=x[0]) for item,options in catalog["catalog"].items()
                            for size,x in options["sizes"].items()]
    rec["pool_cores"] = [{"id":"pool","cores":6}]
    rec["outbound_approval"] = [{"id":"permit","connection":FIRST+"/1"}]
    rec["capacity_exploration"] = [{"id":"fern-grid","pool":"pool","request":THIRD,"values":values}]
    (model/"facts"/"capacity-grid.yaml").write_text(yaml.safe_dump(rec))
    return model


@pytest.mark.xfail(strict=True, raises=MissingThresholdPublication,
                   reason="M2: Depends on ordinary admission outputs. Add the written capacity exploration and checked threshold publication under examples/platform. Read decisions/platform-admission-threshold.md.")
def test_first_threshold_is_between_two_real_assumptions(tmp_path):
    runner = ROOT / "portal" / "capacity_exploration.py"
    if not runner.exists():
        raise MissingThresholdPublication("publish_exploration for a written platform capacity series")
    spec = importlib.util.spec_from_file_location("capacity_exploration",runner)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    for n,(values,initial) in enumerate([([12,6,10,9],6),([8,10,6],4),([12,10],6)]):
        path = tmp_path / str(n)
        model = scenario(path,values,initial)
        bucket = store.FileStore(path/"published")
        key = module.publish_exploration(model,bucket,"fern-grid","operator")
        report = json.loads(bucket.get(key))
        expected = ledger(values,initial)
        samples = report["samples"]
        assert [x["capacity"] for x in samples] == [row[0] for row in expected]
        assert len({x["manifest"] for x in samples}) == len(samples)
        by_value = {}
        for sample, (cap, statuses, free) in zip(samples,expected):
            mid = sample["manifest"]
            man = json.loads(bucket.get(f"platform-core/manifests/{mid}.json"))
            assert any(c["name"]=="rezono:proofs" and c["status"]=="green" for c in man["checks"])
            keys = publish.role_objects(bucket,"platform-core",mid,"operator")
            def rows(rel):
                return {tuple(x["key"]) for x in json.loads(bucket.get(keys[f"relations/{rel}.json"]))}
            assert rows("pool_cores__cores") == {("pool",str(cap))}
            assert rows("request_outcome") == set(statuses.items())
            assert rows("landed_request") == {(i,) for i,status in statuses.items() if status=="landed"}
            assert rows("free_cores") == {("pool",str(free))}
            assert sample["outcome"] == statuses[THIRD]
            proof = json.loads(bucket.get(keys["witnesses.json"]))["witnesses"]
            witness, = [w for w in proof if w["conclusion"]["relation"]=="request_outcome"
                        and json.loads(w["conclusion"]["key"])==[THIRD,statuses[THIRD]]]
            assert witness["premises"] and sample["witness"] == witness
            by_value[cap] = dict(capacity=cap,manifest=mid,witness=witness)
        changes = [(a,b) for a,b in zip(expected,expected[1:]) if a[1][THIRD] != b[1][THIRD]]
        assert report["first_change"] == ({"before":by_value[changes[0][0][0]],"after":by_value[changes[0][1][0]]}
                                          if changes else None)
