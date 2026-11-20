"""Regression tests for Explainer aggregate group indexing and Rezono module form memoization/batching."""

from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import subprocess

import pytest
import yaml
from rezono_canon import canonical_json, canonical_sha256

from rezono_compiler import emit, explain, facts, pack, rezono_module, rules, sources
from support import FIXTURE

ROOT = Path(__file__).resolve().parents[2]
WRITE_FORM = ROOT / "rezono" / "src" / "write-form.ts"


class _CountingSet(set):
    """A set subclass that counts full iterations over a relation."""

    def __init__(self, iterable=()):
        super().__init__(iterable)
        self.iterations = 0

    def __iter__(self):
        self.iterations += 1
        return super().__iter__()


def _reference_aggregate(prog, rows: dict[str, set[tuple]], position: int, agg, theta: dict) -> dict:
    """Naive O(|relation|) reference aggregate witness calculation matching the original linear scan."""
    rel = prog.relations[agg.atom.relation]
    nk = len(rel.key)
    fixed = [(i, theta[t] if rules.is_var(t) else t) for i, t in enumerate(agg.atom.terms) if t != "_"]
    members = sorted(
        (explain.key_text(r[:nk]), r)
        for r in rows.get(rel.name, ())
        if all(r[i] == v for i, v in fixed)
    )
    group = explain.key_text(v for _, v in fixed)
    if agg.function == "count":
        contributors, result = [[k] for k, _ in members], str(len(members))
    else:
        contributors = [[k, explain.contribution(prog, agg, r)] for k, r in members]
        numbers = [int(v.removeprefix("known:")) for _, v in contributors]
        result = str({"sum": sum, "min": min, "max": max}[agg.function](numbers))
    return {
        "relation": rel.name,
        "position": position,
        "group_key": group,
        "count": len(members),
        "contributors_sha256": canonical_sha256(contributors),
        "result": f"known:{result}",
    }


def _aggregate_program():
    return rules.load({
        "format": "rezono.rules/1",
        "relations": [
            {"name": "bucket", "role": "base", "key": [{"name": "b", "type": "string"}]},
            {
                "name": "entry",
                "role": "base",
                "key": [
                    {"name": "b", "type": "string"},
                    {"name": "id", "type": "string"},
                    {"name": "val", "type": "integer"},
                ],
            },
            {
                "name": "summary",
                "role": "derived",
                "module": "agg",
                "key": [
                    {"name": "b", "type": "string"},
                    {"name": "cnt", "type": "integer"},
                    {"name": "total", "type": "integer"},
                    {"name": "lo", "type": "integer"},
                    {"name": "hi", "type": "integer"},
                ],
            },
            {
                "name": "empty_summary",
                "role": "derived",
                "module": "agg",
                "key": [
                    {"name": "b", "type": "string"},
                    {"name": "cnt", "type": "integer"},
                    {"name": "total", "type": "integer"},
                ],
            },
            {
                "name": "global_count",
                "role": "derived",
                "module": "agg",
                "key": [
                    {"name": "b", "type": "string"},
                    {"name": "all_cnt", "type": "integer"},
                ],
            },
        ],
        "rules": [
            {
                "id": "r_summary",
                "module": "agg",
                "stratum": "1",
                "head": {"relation": "summary", "terms": ["?b", "?cnt", "?total", "?lo", "?hi"]},
                "body": [{"relation": "bucket", "terms": ["?b"], "polarity": "positive", "stratum": "0"}],
                "aggregates": [
                    {"as": "?cnt", "function": "count", "relation": "entry", "terms": ["?b", "_", "_"], "stratum": "0"},
                    {"as": "?total", "function": "sum", "over": "val", "relation": "entry", "terms": ["?b", "_", "_"], "stratum": "0"},
                    {"as": "?lo", "function": "min", "over": "val", "relation": "entry", "terms": ["?b", "_", "_"], "stratum": "0"},
                    {"as": "?hi", "function": "max", "over": "val", "relation": "entry", "terms": ["?b", "_", "_"], "stratum": "0"},
                ],
                "origin": {"file": "rules/agg.dl", "line": "1"},
            },
            {
                "id": "r_empty",
                "module": "agg",
                "stratum": "1",
                "head": {"relation": "empty_summary", "terms": ["?b", "?cnt", "?total"]},
                "body": [{"relation": "bucket", "terms": ["?b"], "polarity": "positive", "stratum": "0"}],
                "aggregates": [
                    {"as": "?cnt", "function": "count", "relation": "entry", "terms": ["?b", "_", "_"], "stratum": "0"},
                    {"as": "?total", "function": "sum", "over": "val", "relation": "entry", "terms": ["?b", "_", "_"], "stratum": "0"},
                ],
                "origin": {"file": "rules/agg.dl", "line": "2"},
            },
            {
                "id": "r_global",
                "module": "agg",
                "stratum": "1",
                "head": {"relation": "global_count", "terms": ["?b", "?all_cnt"]},
                "body": [{"relation": "bucket", "terms": ["?b"], "polarity": "positive", "stratum": "0"}],
                "aggregates": [
                    {"as": "?all_cnt", "function": "count", "relation": "entry", "terms": ["_", "_", "_"], "stratum": "0"},
                ],
                "origin": {"file": "rules/agg.dl", "line": "3"},
            },
        ],
    }, require_witness=False)


def test_explainer_aggregate_uses_group_index_cache_and_matches_reference_bytes():
    prog = _aggregate_program()
    group_count = 80
    buckets = [(f"b{i:03d}",) for i in range(group_count)] + [("empty_bucket",)]
    entries = []
    summary_rows = []
    summary_witnesses = []
    r_summary = prog.rules["r_summary"]
    r_empty = prog.rules["r_empty"]
    r_global = prog.rules["r_global"]
    for i in range(group_count):
        b = f"b{i:03d}"
        vals = [i * 3 - 5, i * 3 + 1, i * 3 + 7]
        for j, v in enumerate(vals):
            entries.append((b, f"e{i:03d}_{j}", str(v)))
        cnt, total, lo, hi = str(len(vals)), str(sum(vals)), str(min(vals)), str(max(vals))
        summary_rows.append((b, cnt, total, lo, hi))
        bindings = {"?b": b, "?cnt": cnt, "?total": total, "?lo": lo, "?hi": hi}
        summary_witnesses.append(tuple(bindings[v] for v in r_summary.variables))

    total_entries = str(len(entries))
    global_rows = [(b, total_entries) for (b,) in buckets]
    empty_bindings = {"?b": "empty_bucket", "?cnt": "0", "?total": "0"}
    rows = {
        "bucket": set(buckets),
        "entry": set(entries),
        "summary": set(summary_rows),
        "empty_summary": {("empty_bucket", "0", "0")},
        "global_count": set(global_rows),
    }
    witnesses = {
        "r_summary": summary_witnesses,
        "r_empty": [tuple(empty_bindings[v] for v in r_empty.variables)],
        "r_global": [tuple({"?b": b, "?all_cnt": total_entries}[v] for v in r_global.variables) for (b,) in buckets],
    }

    ex = explain.Explainer(prog, rows, witnesses)
    counting_entries = _CountingSet(ex.rows["entry"])
    ex.rows["entry"] = counting_entries

    chosen = ex.chosen()
    # Two distinct fixed-position masks over `entry`: `(0,)` for grouped aggregates and `()` for global count.
    assert counting_entries.iterations == 2

    # Every chosen aggregate witness must match the uncached linear-scan reference byte-for-byte.
    by_conclusion = {(w["conclusion"]["relation"], w["conclusion"]["key"]): w for w in chosen}
    for head_row, w_row in zip(summary_rows, summary_witnesses, strict=True):
        theta = dict(zip(r_summary.variables, w_row))
        w = by_conclusion[("summary", explain.key_text(head_row))]
        expected_aggs = [_reference_aggregate(prog, rows, pos, agg, theta) for pos, agg in enumerate(r_summary.aggregates)]
        assert canonical_json(w["aggregates"]) == canonical_json(expected_aggs)

    empty_w = by_conclusion[("empty_summary", explain.key_text(("empty_bucket", "0", "0")))]
    assert canonical_json(empty_w["aggregates"]) == canonical_json([
        _reference_aggregate(prog, rows, pos, agg, empty_bindings) for pos, agg in enumerate(r_empty.aggregates)
    ])

    for head_row, w_row in zip(global_rows, witnesses["r_global"], strict=True):
        theta = dict(zip(r_global.variables, w_row))
        w = by_conclusion[("global_count", explain.key_text(head_row))]
        expected_aggs = [_reference_aggregate(prog, rows, 0, r_global.aggregates[0], theta)]
        assert canonical_json(w["aggregates"]) == canonical_json(expected_aggs)

    # Repeated witness queries hit the cache without re-scanning `entry`, and return fresh dicts.
    w1 = ex.instance(r_summary, dict(zip(r_summary.variables, summary_witnesses[0])))
    w2 = ex.instance(r_summary, dict(zip(r_summary.variables, summary_witnesses[0])))
    assert counting_entries.iterations == 2
    assert w1 == w2
    w1["aggregates"][0]["count"] = -1
    assert w2["aggregates"][0]["count"] == 3

    # Empty min/max still raises NoProof and is never silently cached as valid.
    with pytest.raises(explain.NoProof, match="empty group"):
        ex.instance(r_summary, {"?b": "empty_bucket", "?cnt": "0", "?total": "0", "?lo": "0", "?hi": "0"})


def _clean_node_env() -> dict[str, str]:
    return {k: v for k, v in os.environ.items() if not k.upper().startswith("NODE_")}


def _node() -> str:
    return os.environ.get("REZONO_NODE", "node")


def _write_rezono_pack(tmp_path: Path) -> Path:
    directory = Path(shutil.copytree(FIXTURE, tmp_path / "pack"))
    rezono_dir = directory / "rezono"
    rezono_dir.mkdir()

    schema_text = "\n".join([
        "rezono 0",
        "pack minimal",
        "kind Bucket world closed",
        "  label: Text",
        "",
    ])
    dataset_text = "\n".join([
        "rezono 0",
        "pack minimal",
        "kind Metric world closed",
        "  amount: Int",
        "  note: Text?",
        "dataset metrics",
        "  fact Metric",
        "    | id | amount | note |",
        "    | m1 | 10     | ok   |",
        "    | m2 | 25     | -    |",
        "",
    ])
    (rezono_dir / "buckets.rezono").write_text(schema_text, encoding="utf-8", newline="\n")
    (rezono_dir / "metrics.rezono").write_text(dataset_text, encoding="utf-8", newline="\n")

    written = subprocess.run(
        [
            _node(),
            str(WRITE_FORM),
            "--batch",
            "buckets.rezono",
            "buckets.json",
            "metrics.rezono",
            "metrics.json",
        ],
        cwd=rezono_dir,
        capture_output=True,
        encoding="utf-8",
        env=_clean_node_env(),
    )
    assert written.returncode == 0, written.stderr

    meta = yaml.safe_load((directory / "pack.yaml").read_text(encoding="utf-8"))
    meta["rezono"] = [
        {"module": "rezono/buckets.rezono", "form": "rezono/buckets.json", "layer": "facts"},
        {"module": "rezono/metrics.rezono", "form": "rezono/metrics.json", "layer": "facts"},
    ]
    (directory / "pack.yaml").write_text(yaml.safe_dump(meta, sort_keys=False), encoding="utf-8", newline="\n")
    return directory


def test_epoch_invokes_module_reader_at_most_once_and_invalidates_on_edit(tmp_path, monkeypatch):
    pack_dir = _write_rezono_pack(tmp_path)
    rezono_module.clear_form_cache()

    calls: list[list[str]] = []
    real_run = subprocess.run

    def counting_run(cmd, *args, **kwargs):
        if isinstance(cmd, (list, tuple)) and any("write-form." in str(part) for part in cmd):
            calls.append([str(part) for part in cmd])
        return real_run(cmd, *args, **kwargs)

    monkeypatch.setattr(subprocess, "run", counting_run)

    # Full compiler + fact loading + provenance pipeline executed by a publisher epoch.
    model = pack.read(pack_dir)
    compiled = emit.compile_pack(model)
    assert "bundle/schema-bundle.json" in compiled
    loaded: dict[str, list[tuple]] = {}
    for fpath in facts.files(pack_dir):
        for table, rows in facts.load(model, fpath).items():
            loaded.setdefault(table, []).extend(rows)
    provenance = sources.read(model, pack_dir)

    assert len(calls) == 1
    assert "--batch" in calls[0]
    assert loaded["metric__amount"] == [("m1", 10), ("m2", 25)]
    assert loaded["metric__note"] == [("m1", "ok")]
    assert any(entry["row"]["relation"] == "metric__amount" for entry in provenance)

    # Repeated calls across pack.read, facts.files, facts.load, and sources.read reuse the cache (still 1 call).
    model_again = pack.read(pack_dir)
    for fpath in facts.files(pack_dir):
        facts.load(model_again, fpath)
    assert sources.read(model_again, pack_dir) == provenance
    assert len(calls) == 1

    # Editing the authored .rezono file changes its content sha256 and triggers a fresh parse.
    metrics_path = pack_dir / "rezono" / "metrics.rezono"
    metrics_path.write_text(
        metrics_path.read_text(encoding="utf-8").replace("| m2 | 25     | -    |", "| m2 | 99     | -    |"),
        encoding="utf-8",
        newline="\n",
    )
    updated = facts.load(model, pack_dir / "rezono" / "metrics.json")
    assert updated["metric__amount"] == [("m1", 10), ("m2", 99)]
    assert len(calls) == 2

    # Direct dataset discovery on a cold cache with multiple .rezono datasets batches into a single call.
    rezono_module.clear_form_cache()
    calls.clear()
    assert len(facts.files(pack_dir)) == 1
    assert len(calls) == 1


def test_write_form_batch_mode_matches_single_file_mode_byte_for_byte(tmp_path):
    env = _clean_node_env()
    node = _node()

    src_a = tmp_path / "a.rezono"
    src_b = tmp_path / "b.rezono"
    src_bad = tmp_path / "bad.rezono"
    src_a.write_text("rezono 0\npack sample\nkind Alpha world closed\n  size: Int\n", encoding="utf-8", newline="\n")
    src_b.write_text(
        "rezono 0\npack sample\ndataset b\n  fact Alpha\n    | id | size |\n    | a1 | 42   |\n",
        encoding="utf-8",
        newline="\n",
    )
    src_bad.write_text(
        "rezono 0\npack sample\nextend Alpha\n  derived before: Int = size at since\n",
        encoding="utf-8",
        newline="\n",
    )

    # Single-file baseline.
    single_a = tmp_path / "single_a.json"
    single_b = tmp_path / "single_b.json"
    single_bad = tmp_path / "single_bad.json"
    single_bad.write_text("stale", encoding="utf-8")

    r_a = subprocess.run([node, str(WRITE_FORM), src_a.name, single_a.name], cwd=tmp_path, capture_output=True, encoding="utf-8", env=env)
    r_b = subprocess.run([node, str(WRITE_FORM), src_b.name, single_b.name], cwd=tmp_path, capture_output=True, encoding="utf-8", env=env)
    r_bad = subprocess.run([node, str(WRITE_FORM), src_bad.name, single_bad.name], cwd=tmp_path, capture_output=True, encoding="utf-8", env=env)
    assert r_a.returncode == 0, r_a.stderr
    assert r_b.returncode == 0, r_b.stderr
    assert r_bad.returncode == 1
    assert not single_bad.exists()

    # Batch argv mode (all valid -> exit 0, exact byte parity).
    batch_a = tmp_path / "batch_a.json"
    batch_b = tmp_path / "batch_b.json"
    r_ok = subprocess.run(
        [node, str(WRITE_FORM), "--batch", src_a.name, batch_a.name, src_b.name, batch_b.name],
        cwd=tmp_path,
        capture_output=True,
        encoding="utf-8",
        env=env,
    )
    assert r_ok.returncode == 0, r_ok.stderr
    assert batch_a.read_bytes() == single_a.read_bytes()
    assert batch_b.read_bytes() == single_b.read_bytes()

    # Batch stdin JSON mode with mixed valid + refused modules -> exit 1, valid written, stale refused removed, exact stderr.
    stdin_a = tmp_path / "stdin_a.json"
    stdin_b = tmp_path / "stdin_b.json"
    stdin_bad = tmp_path / "stdin_bad.json"
    stdin_bad.write_text("stale", encoding="utf-8")
    r_mixed = subprocess.run(
        [node, str(WRITE_FORM), "--batch"],
        cwd=tmp_path,
        input=json.dumps([[src_a.name, stdin_a.name], [src_bad.name, stdin_bad.name], [src_b.name, stdin_b.name]]),
        capture_output=True,
        encoding="utf-8",
        env=env,
    )
    assert r_mixed.returncode == 1
    assert stdin_a.read_bytes() == single_a.read_bytes()
    assert stdin_b.read_bytes() == single_b.read_bytes()
    assert not stdin_bad.exists()
    assert r_mixed.stderr == r_bad.stderr

    # Invalid usage exits with code 2.
    r_odd = subprocess.run([node, str(WRITE_FORM), "--batch", src_a.name], cwd=tmp_path, capture_output=True, encoding="utf-8", env=env)
    assert r_odd.returncode == 2
