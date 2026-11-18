"""Compare actual migrations of the minimal pack with its independently declared Catlab schema.

Run with the repository's Python packages installed and Julia's locked project instantiated:
    python compiler/tests/catlab/compare.py
"""

import json
import subprocess
import tempfile
from collections import Counter
from pathlib import Path

import yaml

from rezono_compiler import facts, operate, pack, writer


HERE = Path(__file__).resolve().parent
FIXTURE = HERE.parent / "fixtures/minimal"
DECLARED = [["minimal", name] for name in ("Alpha", "Beta", "State")]
KINDS = {"alpha": "minimal#Alpha", "beta": "minimal#Beta"}
TABLES = [
    (KINDS["alpha"], None, False, None), (KINDS["alpha"], "title", False, None),
    (KINDS["alpha"], "size", False, None), (KINDS["beta"], None, False, None),
    (KINDS["beta"], "alpha", True, None), (KINDS["beta"], "state", False, "minimal#State"),
]
# Author-facing operation and the oracle's independently resolved form.
RENAMES = [
    ({"kind": "Alpha", "to": "Gamma"}, {"kind": "Gamma", "to": "Alpha"},
     {"what": "kind", "kind": "minimal#Alpha", "to": "Gamma"}),
    ({"kind": "Beta", "slot": "alpha", "to": "link"}, {"kind": "Beta", "slot": "link", "to": "alpha"},
     {"what": "slot", "kind": "minimal#Beta", "slot": "alpha", "to": "link"}),
]


def state(multiplicity):
    links = ["a"] * multiplicity + ["z"]
    records = {"alpha": [{"id": k, "title": k} for k in ("a", "z")],
               "beta": [{"id": "b-" + k, "alpha": k, "state": "high"} for k in links]}
    rows = {"minimal#Alpha": [["a"], ["z"]], "minimal#Alpha.title": [["a", "a"], ["z", "z"]],
            "minimal#Beta": [["b-" + k] for k in links],
            "minimal#Beta.alpha": [["b-" + k, k] for k in links],
            "minimal#Beta.state": [["b-" + k, "high"] for k in links]}
    return records, {"name": f"copies-{multiplicity}", "rows": rows}


def oracle_case(operation, states):
    tables = [{"key": kind if slot is None else f"{kind}.{slot}", "kind": kind,
               "slot": slot, "arrow": arrow, "enum": enum} for kind, slot, arrow, enum in TABLES]
    return {"op": {"op": "rename", **operation}, "tables": tables, "declared": DECLARED,
            "embedded": [], "states": states}


def multisets(rows):
    return {k: Counter(tuple(row) for row in rs) for k, rs in rows.items() if rs}


def loaded(directory, path):
    model = pack.read(directory)
    names = {}
    for kind in model.kinds.values():
        key = f"{kind.module}#{kind.cls}"
        names[kind.name] = key
        names.update({slot.table: f"{key}.{slot.name}" for slot in kind.slots.values()})
    return multisets({names[t]: [[str(x) for x in row] for row in rs]
                      for t, rs in facts.load(model, path).items()})


def migrated(forward, inverse, inputs):
    actual = {}
    with tempfile.TemporaryDirectory(prefix="rezono-work-") as tmp:
        work = Path(tmp)
        directory = writer.checkout(FIXTURE, work)
        (directory / "facts").mkdir()
        paths = {}
        for records, case in inputs:
            path = directory / "facts" / (case["name"] + ".yaml")
            path.write_text(yaml.safe_dump(records), encoding="utf-8", newline="\n")
            paths[case["name"]] = path
            assert loaded(directory, path) == multisets(case["rows"])
        for direction, operation in (("after", forward), ("back", inverse)):
            spec = work / f"{direction}.yaml"
            spec.write_text(yaml.safe_dump({"format": "rezono.operations/1", "pack": "minimal",
                                            "operations": [{"op": "rename", **operation}]}),
                            encoding="utf-8", newline="\n")
            operate.operate(directory, spec, work / direction)
            actual[direction] = {name: loaded(directory, path) for name, path in paths.items()}
    return actual


def main():
    inputs = [state(n) for n in (1, 2, 3)]
    cases = [oracle_case(oracle, [case for _, case in inputs]) for _, _, oracle in RENAMES]
    with tempfile.TemporaryDirectory() as tmp:
        request, response = (Path(tmp) / f"{n}.json" for n in ("cases", "results"))
        request.write_text(json.dumps(cases), encoding="utf-8")
        subprocess.run(["julia", "--startup-file=no", f"--project={HERE}", str(HERE / "oracle.jl"),
                        str(request), str(response)], check=True)
        results = json.loads(response.read_text(encoding="utf-8"))
    for states, (forward, inverse, _) in zip(results, RENAMES, strict=True):
        actual = migrated(forward, inverse, inputs)
        for result, (_, case) in zip(states, inputs, strict=True):
            name = case["name"]
            assert result["name"] == name
            assert multisets(result["back"]) == multisets(case["rows"])
            for direction in ("after", "back"):
                assert actual[direction][name] == multisets(result[direction]), (forward, direction, name)


if __name__ == "__main__":
    main()
