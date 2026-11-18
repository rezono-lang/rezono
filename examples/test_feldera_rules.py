"""Compare each compiled Feldera pipeline with the independent batch run at every example fact state."""

import json
from collections import Counter

import pytest

from feldera import URL, deploy, processed, push, query, stop
from rezono_compiler import facts, rules_split, rules_sql, scenarios
from rules_support import RULED, name, states
from support import compile_dir

pytestmark = pytest.mark.skipif(not URL, reason="set FELDERA_URL to a running Feldera")


def changes(before, after):
    old, new = Counter(before), Counter(after)
    for op, counts in (("delete", old - new), ("insert", new - old)):
        if counts:
            yield op, sorted(counts.elements(), key=repr)


def fact_updates(model, files, example):
    """The original facts as deltas, including the initial parameters and calculation date."""
    params = json.loads(files["engine/parameters.json"]) | json.loads(files.get("engine/calc.json", "{}"))
    delta = {t: [{"insert": r} for r in rs] for t, rs in params.items()}
    previous = {}
    for label, rows in scenarios.states(model, example):
        for table in sorted(rows.keys() | previous.keys()):
            for op, changed in changes(previous.get(table, []), rows.get(table, [])):
                delta.setdefault(table, []).extend(facts.ingress(model, {table: changed}, op)[table])
        yield label, delta
        previous, delta = rows, {}


def export_rows(pipeline, prog, exports):
    """Decode the compiled tagged export by column name, including the calculation's typed selections."""
    result = {rel: [] for rel in exports}
    for row in query(pipeline, 'SELECT * FROM "oracle_export_snapshot"'):
        rel = row["rel"]
        key = prog.relations[rel].key
        result[rel].append(rules_split.decode(prog, rel, [row[f"a{i}"] for i in range(len(key))]))
    return result


def check_views(pipeline, prog, part, state):
    for rel in part["views"]:
        got = {tuple(str(row[c.name]) for c in prog.relations[rel].key)
               for row in query(pipeline, f'SELECT * FROM "{rel}"')}
        assert got == state.derived[rel], (state.label, rel)
        for view, _ in rules_sql.checks(prog, rel):
            assert query(pipeline, f'SELECT * FROM "{view}"') == [], (state.label, view)
    if part["name"] in ("main", "integrity"):
        for rel, want in state.seal.items():
            got = {tuple(str(row[c]) for c in ("id", "period_close") if c in row)
                   for row in query(pipeline, f'SELECT * FROM "{rel}"')}
            assert got == want, (state.label, rel)


@pytest.mark.parametrize("example", RULED, ids=name)
def test_incremental_on_feldera_equals_batch(example, tmp_path):
    files = compile_dir(example, tmp_path)
    model, prog, run = states(example)
    plan = json.loads(files["engine/pipelines.json"])
    parts = plan["pipelines"]
    assert sorted(rel for part in parts for rel in part["views"]) == sorted(prog.derived())
    inputs = list(fact_updates(model, files, example))
    # Replay all states of one producer before its consumers. Only Feldera's output crosses boundaries,
    # and only one running pipeline needs to fit on the runner at a time.
    forwarded = [{} for _ in inputs]
    for part in parts:
        pipeline = f"rezono-rules-{example.name}-{part['name']}"
        sql = "\n".join(files[path] for path in part["sql"])
        if part["exports"]:
            # The production export is a stream. Materialize its rows for snapshot queries after the barrier.
            sql += f'\nCREATE MATERIALIZED VIEW "oracle_export_snapshot" AS SELECT * FROM "{plan["export_view"]}";'
        deploy(pipeline, sql, profile="unoptimized", workers=2)
        try:
            previous = {}
            for (label, facts_delta), state, relay in zip(inputs, run, forwarded, strict=True):
                assert label == state.label
                delta = {t: facts_delta[t] for t in part["tables"] if t in facts_delta}
                delta.update({t: relay[t] for t in part["imports"]})
                processed(pipeline, push(pipeline, delta))
                check_views(pipeline, prog, part, state)
                if part["exports"]:
                    current = export_rows(pipeline, prog, part["exports"])
                    for rel, rows in current.items():
                        assert {tuple(map(str, row)) for row in rows} == state.rows[rel], (label, rel)
                        key = [c.name for c in prog.relations[rel].key]
                        relay[rel] = [{op: dict(zip(key, row, strict=True))}
                                      for op, changed in changes(previous.get(rel, []), rows) for row in changed]
                    previous = current
        finally:
            stop(pipeline)
