"""File connector transport keeps signed rows and waits for their actual processing."""

import json
import re
from collections import Counter
from pathlib import PurePosixPath
from types import SimpleNamespace

import pytest

import feldera_file_input as transport
from rezono_compiler import feldera_names


def test_wide_signed_updates_preserve_every_event_and_wait_for_completion(tmp_path, monkeypatch):
    tables = ["interval", "trust_entry__title", 'mixed"Case', *(f"sample_{i}" for i in range(118))]
    feed = transport.FileInputs(tmp_path / "part", tables)
    source = "\n".join(f'CREATE TABLE {feldera_names.quoted(name)} ("id" VARCHAR, "v" BIGINT);' for name in tables)
    source += '\nCREATE MATERIALIZED VIEW "kept" AS SELECT * FROM "__rezono_interval";\n'
    connected = feed.connect(source)
    assert re.sub(r" WITH \('connectors' = '[^']*'\);", ";", connected) == source
    attached = {}
    for sql in connected.splitlines()[:-1]:
        match = re.fullmatch(r'''CREATE TABLE ("(?:[^"]|"")+") .* WITH \('connectors' = '(.*)'\);''', sql)
        [connector] = json.loads(match[2])
        assert connector["format"]["config"] == {"update_format": "insert_delete", "array": False, "lines": "single"}
        assert connector["transport"]["name"] == "file_input" and connector["transport"]["config"]["follow"] is True
        filename = PurePosixPath(connector["transport"]["config"]["path"])
        assert filename.parent == transport.MOUNT / tmp_path.name / "part"
        attached[match[1]] = tmp_path / "part" / filename.name
    # Native endpoint configuration retains SQL identifier quoting in its stream field.
    assert {'"trust_entry__title"', '"mixed""Case"', '"__rezono_interval"'} <= attached.keys()

    requests = []

    def records(path):
        return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]

    def stats(method, path):
        assert (method, path) == ("GET", "/v0/pipelines/example/stats")
        counts = {name: len(records(file)) for name, file in attached.items()}
        total = sum(counts.values())
        phase = len(requests) % 3
        requests.append((phase, total))
        if phase == 0 and counts['"sample_0"']:
            counts['"sample_0"'] -= 1
        completed = total - 1 if phase == 1 else total
        return {
            "inputs": [{"config": {"stream": name}, "metrics": {
                "total_records": n, "num_parse_errors": 0, "num_transport_errors": 0}}
                for name, n in counts.items()],
            "global_metrics": {"total_completed_records": completed, "total_input_records": total},
        }

    monkeypatch.setattr(transport, "call", stats)
    ticks = iter(range(0, 1000, 40))
    monkeypatch.setattr(transport, "time", SimpleNamespace(monotonic=lambda: next(ticks), sleep=lambda _: None))
    row = {"id": "quote' and\nline", "v": None}
    other = {"id": "other", "v": -13}
    plus, minus = {"insert": row}, {"delete": row}
    feed.send("example", {t: [plus, plus, {"insert": other}] for t in tables})
    feed.send("example", {t: [minus, {"delete": other}] for t in tables})
    assert requests == [(n, total) for total in (363, 605) for n in (0, 1, 2)]
    for path in attached.values():
        events = records(path)
        assert events == [plus, plus, {"insert": other}, minus, {"delete": other}]
        balance = Counter()
        for event in events:
            (operation, item), = event.items()
            balance[tuple(item.items())] += 1 if operation == "insert" else -1
        assert +balance == {tuple(row.items()): 1}
    before = {name: f.read_bytes() for name, f in attached.items()}
    feed.send("example", {"interval": []})
    assert before == {name: f.read_bytes() for name, f in attached.items()}


def test_file_input_requires_the_declared_tables_and_healthy_metrics(tmp_path, monkeypatch):
    feed = transport.FileInputs(tmp_path / "part", ["expected"])
    with pytest.raises(ValueError, match="missing input declarations"):
        feed.connect('CREATE TABLE "other" (id VARCHAR);')
    with pytest.raises(ValueError, match="duplicate table declaration"):
        feed.connect('CREATE TABLE "expected" (id VARCHAR);\nCREATE TABLE "expected" (id VARCHAR);')
    monkeypatch.setattr(transport, "call", lambda *_: {
        "inputs": [{"config": {"stream": "expected"}, "metrics": {
            "total_records": 0, "num_parse_errors": 1, "num_transport_errors": 0}}],
        "global_metrics": {"total_completed_records": 25, "total_input_records": 25},
    })
    with pytest.raises(RuntimeError, match="file input failed"):
        feed.send("example", {"expected": [{"insert": {"id": 1}}]})


def test_timeout_counts_missing_and_lagging_streams(tmp_path, monkeypatch):
    feed = transport.FileInputs(tmp_path / "part", ["missing", "pending"])
    ticks = iter((0, 0, 120))
    monkeypatch.setattr(transport, "time", SimpleNamespace(monotonic=lambda: next(ticks)))
    monkeypatch.setattr(transport, "call", lambda *_: {
        "inputs": [{"config": {"stream": '"pending"'}, "metrics": {
            "total_records": 0, "num_parse_errors": 0, "num_transport_errors": 0}}],
        "global_metrics": {"total_input_records": 1, "total_completed_records": 0},
    })
    with pytest.raises(TimeoutError) as failure:
        feed.send("example", {name: [{"insert": {"id": 1}}] for name in feed.paths})
    assert "missing=1 ['missing'], lagging=1 [('pending', 0, 1)]" in str(failure.value)
    assert "accepted/expected=0/2, global completed/input=0/1" in str(failure.value)
