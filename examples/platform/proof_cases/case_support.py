from pathlib import Path
import json
import yaml

ROOT = Path(__file__).resolve().parents[1]


def engine():
    from rules_support import states
    model, _, snapshots = states(ROOT)
    state, = snapshots
    return model, state


def reference():
    return json.loads((ROOT / "oracle-rows.json").read_text())


def exact(name, rows):
    _, snapshot = engine()
    assert name in snapshot.derived, f"Missing derived relation: {name}"
    assert snapshot.derived[name] == {tuple(map(str, row)) for row in rows}, name


def verified(name, key):
    from rezono_checker.check import check
    from rezono_checker.rules import load_rules
    model, snapshot = engine()
    assert key in snapshot.derived.get(name, ()), (name, key)
    proof = snapshot.proof(name, key)
    manifest, read = snapshot.manifest()
    report = check(proof, manifest, load_rules(model.rules), read)
    assert report["valid"] and not report["findings"], report["findings"]
    return {(p["row"]["relation"], tuple(json.loads(p["row"]["key"]))) for w in proof["witnesses"]
            for p in w["premises"] if p["row"]["relation"] not in snapshot.derived}


def imported(name):
    imports = yaml.safe_load((ROOT / "pack.yaml").read_text())["imports"]
    assert name in {entry["name"] for entry in imports}, f"Missing actual platform import: {name}"
