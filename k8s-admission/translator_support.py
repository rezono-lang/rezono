"""Shared harness for the admission translator: decisions/k8s-admission-translator.md."""

import json
import os
import shutil
import subprocess
from pathlib import Path

import yaml
from rezono_compiler import batch, rules

ROOT = Path(__file__).parent
FIXTURES = ROOT / "fixtures" / "translator"
DIGEST = "334d722c5cdc5e68a8cc9279f82b8968ab7a8c24ea82180832496fc62316036c"
IMAGE_A = "registry.example.org/sample/app@sha256:" + "a" * 64
IMAGE_B = "registry.example.org/sample/app@sha256:" + "b" * 64
IMAGE_C = "registry.example.org/sample/app@sha256:" + "c" * 64


def fixture(name):
    return yaml.safe_load((FIXTURES / name).read_text(encoding="utf-8"))


def load_program(name):
    """Load a checked-in rule program whose strata and witnesses are left out."""
    return rules.load(rules.with_strata(fixture(name)), require_witness=False)


def program(relations, rule_list):
    """Build a small checked program.

    `relations` maps a name to (role, [(column, type), ...]), optionally followed by a dict of further
    IR fields such as {"world": "open"} or {"absence": True}.
    Each rule is (id, (head, terms), [(relation, terms, polarity), ...], [(op, left, right), ...]), optionally
    followed by a dict of further IR fields such as "aggregates" or "assignments".
    """
    doc = {"format": rules.FORMAT, "pack": "translator_sample", "relations": [], "rules": []}
    for name, (role, columns, *extra) in relations.items():
        entry = {"name": name, "role": role, "key": [{"name": c, "type": t} for c, t in columns]}
        if role == "derived":
            entry["module"] = "sample"
        for fields in extra:
            entry.update(fields)
        doc["relations"].append(entry)
    for line, (rule_id, (head, terms), body, conditions, *extra) in enumerate(rule_list, 1):
        entry = {
            "id": rule_id,
            "module": "sample",
            "head": {"relation": head, "terms": list(terms)},
            "body": [{"relation": r, "terms": list(t), "polarity": p} for r, t, p in body],
            "conditions": [{"op": op, "left": left, "right": right} for op, left, right in conditions],
            "origin": {"file": "sample.dl", "line": str(line)},
        }
        for fields in extra:
            entry.update(fields)
        doc["rules"].append(entry)
    return rules.load(rules.with_strata(doc), require_witness=False)


def evaluate(prog, rows, relation):
    """Rezono's own answer: the rows of `relation`, as tuples of canonical text."""
    with batch.connect(prog, {name: list(values) for name, values in rows.items()}, threads=1) as connection:
        batch.compute(connection, prog)
        return batch.read(connection, prog, [relation])[relation]


def run_cel(samples):
    """Evaluate (object, params, expression) samples with cel-go; return one boolean per sample.

    The CI always runs cel-go. Without Go outside the CI, return None: the caller then checks only the
    exact text that decisions/k8s-admission-translator.md specifies.
    """
    if shutil.which("go") is None:
        assert not os.environ.get("CI"), "the CI must run the cel-go oracle"
        return None
    payload = [{"object": obj, "params": params, "variables": [],
                "validations": [{"name": "case", "expression": expression}]}
               for obj, params, expression in samples]
    probe = subprocess.run(["go", "run", "-mod=readonly", "."], cwd=ROOT / "oracles" / "flow-expression",
                           input=json.dumps(payload), text=True, capture_output=True, timeout=300, check=False)
    assert probe.returncode == 0, probe.stderr
    results = json.loads(probe.stdout)
    assert len(results) == len(samples)
    return results
