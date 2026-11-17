"""Rules on a running Feldera (FELDERA_URL; opt-in), per example pack with rules/: the compiled program
(tables, integrity views and rule views in one pipeline) gets each fact state as a delta on the previous
one, and after the processing barrier every derived view equals the batch backend and the checks of
every named outcome (W7) are empty."""

import json

import pytest

from feldera import URL, deploy, processed, push, query, stop
from rezono_compiler import emit, facts, rules_sql, seal
from rules_support import RULED, name, states
from support import compile_dir

pytestmark = pytest.mark.skipif(not URL, reason="set FELDERA_URL to a running Feldera")


def updates(model, rows, weight):
    return facts.ingress(model, rows, weight)


@pytest.mark.parametrize("example", RULED, ids=name)
def test_incremental_on_feldera_equals_batch(example, tmp_path):
    from rezono_compiler import scenarios

    files = compile_dir(example, tmp_path)
    model, prog, run = states(example)
    plan = json.loads(files["engine/pipelines.json"])
    assert len(plan["pipelines"]) == 1, "split packs are measured by the M2 probe; one pipeline here"
    pipeline = f"rezono-rules-{example.name}"
    deploy(pipeline, "\n".join(files[f] for f in plan["pipelines"][0]["sql"]), profile="unoptimized", workers=2)
    params = {t: [{"insert": r} for r in rs] for t, rs in emit.parameters(model).items()}
    previous = {}
    for (label, rows), s in zip(scenarios.states(model, example), run):
        delta = {}
        for table in sorted(set(rows) | set(previous)):
            old, new = set(previous.get(table, [])), set(rows.get(table, []))
            gone = updates(model, {table: sorted(old - new, key=repr)}, "delete").get(table, [])
            come = updates(model, {table: sorted(new - old, key=repr)}, "insert").get(table, [])
            if gone or come:
                delta[table] = gone + come
        if not previous:
            delta = params | delta
        processed(pipeline, push(pipeline, delta))
        for rel in prog.derived():
            got = {tuple(str(r[c.name]) for c in prog.relations[rel].key)
                   for r in query(pipeline, f'SELECT * FROM "{rel}"')}
            assert got == s.derived[rel], (label, rel)
        for rel, want in sorted(seal.rows(model, rows).items()):  # E3: refused and accepted input, as in batch
            got = {tuple(str(v) for v in r.values()) for r in query(pipeline, f'SELECT * FROM "{rel}"')}
            assert got == {tuple(str(v) for v in r) for r in want}, (label, rel)
        for rel in sorted(prog.relations):  # every check of the rules is empty: W7 outcomes, R16 bounds (RV-K18)
            for view, _ in rules_sql.checks(prog, rel):
                assert query(pipeline, f'SELECT * FROM "{view}"') == [], (label, view)
        previous = rows
    stop(pipeline)
