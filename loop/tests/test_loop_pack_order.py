"""Run and explain the public relations without supplying any synthetic IR tables."""

import json
from pathlib import Path

import pytest
import yaml

from pack_records import LOOP, ORDER, evaluate, records


def test_loop_pack_order():
    from rezono_compiler import modules, pack

    declaration = yaml.safe_load((LOOP / "pack.yaml").read_text(encoding="utf-8"))
    assert declaration["name"] == "std-loop" and declaration["theory"] is True
    pins = [imp for imp in declaration["imports"] if imp["name"] == "std-order"]
    assert len(pins) == 1
    pin = pins[0]
    assert not Path(pin["path"]).is_absolute() and (LOOP / pin["path"]).resolve() == ORDER
    assert pin["sha256"] == modules.pack_hash(ORDER)
    model = pack.read(LOOP)
    order = yaml.safe_load((ORDER / "pack.yaml").read_text(encoding="utf-8"))
    assert {"name": "std-order", "version": order["version"], "sha256": pin["sha256"]} in model.imports
    for link in (True, False):
        prog, rows, explainer = evaluate(model, records(link))
        assert set(prog.derived()) >= {"needed", "known", "waiting", "ready", "done", "stuck"}
        wanted = {("current", "build", "seeded", "source-a")}
        if link:
            wanted |= {("current", "ship", "seeded", "source-a"), ("current", "ship", "built", "source-b")}
        assert {row for row in rows["needed"] if row[0] == "current"} == wanted
        assert rows["known"] == {("current", "built", "current-evidence")}
        assert rows["done"] == {("current", "build", "current-evidence")}
        waiting = {("current", "ship", "seeded", "source-a")} if link else set()
        assert {row for row in rows["waiting"] if row[0] == "current"} == waiting
        if link:
            proof = explainer.proof("needed", ("current", "ship", "seeded", "source-a"), "fixture")
            witnesses = proof["witnesses"]
            imported = [w for w in witnesses if w["conclusion"]["relation"] in ("before", "direct_before")
                        and prog.rules[w["rule_id"]].origin[0].startswith("std-order:")]
            assert imported
            edges = {tuple(json.loads(p["row"]["key"])) for w in imported for p in w["premises"]
                     if p["polarity"] == "positive" and p["row"]["relation"] == "ordered__precedes"}
            assert edges == {("seed", "build"), ("build", "ship")}
            assert any(p["row"]["relation"] == "loop_completion__reason"
                       and json.loads(p["row"]["key"]) == ["def-a", "source-a"]
                       for w in witnesses for p in w["premises"])
