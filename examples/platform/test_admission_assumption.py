"""Compare two real platform publications with a three-request admission ledger."""
from collections import Counter
import importlib.util
import json
from pathlib import Path
import shutil

import pytest
import yaml

from request_preview import request_rows
from rezono_compiler import pack, rules
from rezono_publisher import batch, publish, store

ROOT = Path(__file__).resolve().parent
RELATIONS = ("request_outcome", "landed_request", "free_cores")
FIRST, DENIED, THIRD = "elm/ledger", "reed/studio", "reed/fern"


def ledger(order, approved):
    free, outcomes, landed = 7, set(), set()
    for request in order:
        cores = {FIRST: 6, DENIED: 2, THIRD: 4}[request]
        if request == DENIED:
            status = "denied"
        elif request == FIRST and not approved:
            status = "review"
        elif cores > free:
            status = "capacity"
        else:
            status = "landed"
            landed.add((request,))
            free -= cores
        outcomes.add((request, status))
    return dict(request_outcome=outcomes, landed_request=landed, free_cores={("pool", str(free))})


def test_independent_admission_order():
    normal = (FIRST, DENIED, THIRD)
    assert ledger(normal, True)["landed_request"] == {(FIRST,)}
    assert ledger(normal, False)["free_cores"] == {("pool", "3")}
    assert ledger(normal[::-1], True)["landed_request"] == {(THIRD,)}
    assert (DENIED, "denied") in ledger(normal[::-1], True)["request_outcome"]


def fixture(root, reverse):
    model = root / "examples/platform"
    shutil.copytree(ROOT, model, ignore=shutil.ignore_patterns("__pycache__"))
    shutil.copytree(ROOT.parents[1] / "packs", root / "packs")
    teams = model / "teams"
    third = teams / THIRD / "request.json"
    third.parent.mkdir()
    third.write_text(json.dumps(dict(profile="production", items={"cluster": "medium"}, connections=[],
                                     submittedAt="2025-12-31T00:00:00Z" if reverse else "2026-01-03T00:00:00Z")))
    catalog = json.loads((model / "tenant-catalog.json").read_text())
    records = dict(request_rows(teams, catalog))
    records["offered_cores"] = [dict(id=f"{item}/{size}", cores=n[0]) for item, value in catalog["catalog"].items()
                                for size, n in value["sizes"].items()]
    records["pool_cores"] = [dict(id="pool", cores=7)]
    records["landing_sighting"] = [dict(id="observation-seven", request=FIRST)]
    (model / "facts/assumption-input.yaml").write_text(yaml.safe_dump(records))
    return model


def world(model, st, approved):
    decision = {"outbound_approval": [dict(id="release", connection=FIRST + "/1")] if approved else []}
    (model / "facts/assumption-decision.yaml").write_text(yaml.safe_dump(decision))
    variant = {} if approved else {"proposal": "1", "base_manifest": "m-1"}
    e = batch.epoch(model, epoch=1 if approved else 2, knowledge_time="2026-02-01T00:00:00Z",
                    sources=[("ledger", "fixed-observation")], **variant)
    m = publish.publish(e, st, {"operator": "complete"})
    objs = publish.role_objects(st, e.pack, m["id"], "operator")
    def read(key):
        return json.loads(st.get(objs[key]))
    rows = {rel: {tuple(r["key"]) for r in read(f"relations/{rel}.json")} for rel in RELATIONS}
    witnesses = {(r["conclusion"]["relation"], tuple(json.loads(r["conclusion"]["key"]))): r
                 for r in read("witnesses.json")["witnesses"]}
    observed = {k: st.get(v) for k, v in objs.items() if k.startswith("relations/landing_sighting")}
    assert [r["key"] for r in read("relations/landing_sighting__request.json")] == [["observation-seven", FIRST]]
    return e.pack, m["id"], rows, witnesses, observed


def check_scene(scene, before, after):
    changes = Counter()
    shared_positions, occupied = {}, {}
    for delta in scene["changes"]:
        rel, key, weight = delta["relation"], tuple(delta["key"]), delta["weight"]
        assert type(weight) is int and weight in (-1, 1)
        side = after if weight == 1 else before
        assert delta["witness"] == side[3][rel, key]
        changes[rel, key, weight] += 1
    expected = [(rel, key, sign) for old, new, sign in [(before, after, 1), (after, before, -1)]
                for rel in RELATIONS for key in new[2][rel] - old[2][rel]]
    assert changes == Counter(expected)
    placed = []
    for p in scene["positions"]:
        row = p["relation"], tuple(p["key"])
        position = p["band"], p["slot"]
        assert shared_positions.setdefault(row, position) == position
        assert occupied.setdefault(position, row) == row
        placed.append((p["side"], *row))
    assert Counter(placed) == Counter((side[1], rel, key) for side in (before, after)
                                       for rel in RELATIONS for key in side[2][rel])


def test_scene_requires_the_removed_witness_and_room_for_both_positions():
    def side(mid, value):
        rows = {r: set() for r in RELATIONS}
        key = ("pool", value)
        rows["free_cores"] = {key}
        return "example", mid, rows, {("free_cores", key): {"side": mid}}, {}

    before, after = side("m-1", "1"), side("p-1-2", "3")
    minus = dict(relation="free_cores", key=["pool", "1"], weight=-1, witness={"side": "m-1"})
    plus = dict(relation="free_cores", key=["pool", "3"], weight=1, witness={"side": "p-1-2"})
    first = dict(side="m-1", relation="free_cores", key=minus["key"], band="capacity", slot=0)
    last = dict(side="p-1-2", relation="free_cores", key=plus["key"], band="capacity", slot=1)
    check_scene(dict(changes=[minus, plus], positions=[first, last]), before, after)
    for changes, positions in [([plus], [first, last]), ([dict(minus, witness=plus["witness"]), plus], [first, last]),
                               ([minus, plus], [first, dict(last, slot=0)])]:
        with pytest.raises(AssertionError):
            check_scene(dict(changes=changes, positions=positions), before, after)


class MissingAssumptionProjection(AssertionError):
    pass


def test_published_withdrawal_releases_capacity_for_a_later_request(tmp_path):
    if not set(RELATIONS) <= set(rules.load(pack.read(ROOT).rules).derived()):
        raise MissingAssumptionProjection("the platform lacks an admission-order projection")
    spec = importlib.util.spec_from_file_location("assumption_scene", ROOT / "portal/assumption_scene.py")
    scene_writer = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(scene_writer)
    for reverse in (False, True):
        case = tmp_path / str(reverse)
        model, st = fixture(case, reverse), store.FileStore(case / "published")
        before, after = world(model, st, True), world(model, st, False)
        order = (THIRD, FIRST, DENIED) if reverse else (FIRST, DENIED, THIRD)
        assert before[2] == ledger(order, True) and after[2] == ledger(order, False)
        assert before[4] == after[4]
        key = scene_writer.publish_scene(st, before[0], before[1], after[1], "operator", RELATIONS)
        check_scene(json.loads(st.get(key)), before, after)
