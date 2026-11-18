"""Engine check on a running Feldera (FELDERA_URL), per example pack: the SQL compiles, and the fact sets
give exactly the expected violations: first valid, then errors, then nothing (insert, retract, retract).
Each step waits for Feldera's processing barrier (completion token) before it reads."""

import json

import pytest

from feldera import URL, comparing, deploy, processed, push, query, stop
from support import compile_dir, expected, load
from rezono_compiler import facts, pack
from test_examples import EXAMPLES, name

# The insert-retract cycle needs a valid and an errors fact file.
CYCLE = [e for e in EXAMPLES if all((e / "facts" / f"{f}.yaml").exists() for f in ("valid", "errors"))]

pytestmark = pytest.mark.skipif(not URL, reason="set FELDERA_URL to a running Feldera")


def read(name):
    """The violations per logical check, as (subject, value): one view is kept per check kind."""
    out = {}
    for r in query(name, "SELECT info, subject, value FROM validation_result"):
        out.setdefault(r["info"], set()).add((r["subject"], r["value"]))
    return out


@pytest.mark.parametrize("example", CYCLE, ids=name)
def test_feldera_accepts_the_sql_and_finds_the_errors(example, tmp_path):
    files = compile_dir(example, tmp_path)
    model = pack.read(example)
    name = f"rezono-{example.name}"
    deploy(name, files["engine/tables.sql"] + files["engine/integrity.sql"])
    params = {t: [{"insert": r} for r in rows] for t, rows in json.loads(files["engine/parameters.json"]).items()}
    valid = load(example, example / "facts" / "valid.yaml")
    errors = load(example, example / "facts" / "errors.yaml")
    steps = [
        ("valid", params | facts.ingress(model, valid), "valid.json"),
        ("errors", merge(facts.ingress(model, valid, "delete"), facts.ingress(model, errors)), "errors.json"),
        ("empty", facts.ingress(model, errors, "delete"), None),
    ]
    for label, updates, want in steps:
        processed(name, push(name, updates))
        with comparing():
            assert read(name) == (expected(example / "expected" / "violations" / want) if want else {}), label
    stop(name)


def merge(a, b):
    return {t: a.get(t, []) + b.get(t, []) for t in sorted(set(a) | set(b))}
