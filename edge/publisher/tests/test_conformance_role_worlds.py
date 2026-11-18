"""Evaluate the neutral role worlds and check the published rows and proof bytes."""

from collections import defaultdict
import json
from pathlib import Path
from runpy import run_path

import yaml

from rezono_canon import canonical_json, canonical_sha256
from rezono_compiler import modules
from rezono_publisher import batch, publish, store


REPO = Path(__file__).resolve().parents[3]
CORPUS = REPO / "tests/conformance"
NEUTRAL = REPO / "tests/fixtures/neutral"
READ_CASE = run_path(str(CORPUS / "replay.py"))["case_file"]
ROLES = {"checker": "complete", "reader": "may_read", "summary": "may_read"}


def write_facts(path, rows):
    grouped = defaultdict(list)
    for row in rows:
        grouped[row["kind"]].append({key: value for key, value in row.items() if key != "kind"})
    path.write_bytes(yaml.safe_dump(dict(grouped), sort_keys=False).encode("utf-8"))


def published_world(case, world, directory):
    definition = case["input"]["role_worlds"]
    pack = modules.copy_closure(NEUTRAL, directory / "closure")
    (pack / "rules/role_worlds.dl").write_bytes(definition["clauses"].encode("utf-8"))
    facts = pack / "facts"
    baseline = yaml.safe_load((facts / "rows.yaml").read_bytes())
    roles = [{"kind": "role", **role} for role in baseline["role"]]
    write_facts(facts / "rows.yaml", case["input"]["rows"] + roles)
    (facts / "rows.sources.yaml").unlink()
    if world["added_rows"]:
        write_facts(facts / "added.yaml", world["added_rows"])

    epoch = batch.epoch(pack, epoch=1, knowledge_time="2026-01-01T00:00:00Z",
                        sources=[("rules", case["source"])])
    target = store.FileStore(directory / "publication")
    manifest = publish.publish(epoch, target, ROLES)
    assert {"name": publish.PROOFS, "status": "green", "violations": 0} in manifest["checks"]
    role_bytes = {
        role: {name: target.get(key) for name, key in publish.role_objects(target, epoch.pack, manifest["id"], role).items()}
        for role in ("reader", "summary")
    }
    return manifest, role_bytes


def check_witness(actual, expected, value):
    assert actual["rule_id"] == expected["rule"]
    assert actual["premises"] == [
        {"row": {"relation": premise["relation"], "key": canonical_json(premise["key"])},
         "polarity": "positive", "stratum": 0}
        for premise in expected["premises"]
    ]
    if "aggregate" in expected:
        scope = expected["aggregate"]
        aggregate, = actual["aggregates"]
        contributors = sorted((canonical_json(row), f"known:{row[-1]}") for row in scope["members"])
        assert aggregate["relation"] == scope["relation"]
        assert aggregate["group_key"] == canonical_json(value[:1])
        assert aggregate["count"] == len(contributors)
        assert aggregate["contributors_sha256"] == canonical_sha256([list(row) for row in contributors])
        assert aggregate["result"] == f"known:{value[-1]}"
    else:
        assert "aggregates" not in actual


def check_role_worlds(case_id, tmp_path):
    case = READ_CASE(case_id)
    definition = case["input"]["role_worlds"]
    output = definition["output"]
    worlds = {}
    for world in definition["worlds"]:
        name = world["name"]
        assert name not in worlds
        manifest, role_bytes = published_world(case, world, tmp_path / name)
        worlds[name] = role_bytes
        for role, published in role_bytes.items():
            values = [entry["key"] for entry in json.loads(published[f"relations/{output}.json"])]
            assert values == case["expect"]["value"][name][role]
            proofs = json.loads(published["witnesses.json"])
            assert proofs["hidden"] == []
            witnesses = [w for w in proofs["witnesses"] if w["conclusion"]["relation"] == output]
            expected = case["expect"]["witness"][name][role]
            if expected is None:
                assert witnesses == []
            else:
                witness, = witnesses
                value, = values
                assert witness["conclusion"]["key"] == canonical_json(value)
                check_witness(witness, expected, value)
                if "aggregate" in expected:
                    relation = expected["aggregate"]["relation"]
                    full = {entry["role"]: entry["full"] for entry in manifest["snapshots"]
                            if entry["relation"] == relation}
                    assert full[role]
                    assert not full["summary"]
    return worlds


def test_conformance_withholds_hidden_proofs_and_uses_a_readable_alternative(tmp_path):
    worlds = check_role_worlds("value-withheld-screened", tmp_path)
    assert all(b"link-hidden" not in data for world in worlds.values() for data in world["summary"].values())


def test_conformance_total_requires_full_read_and_hidden_rows_change_no_reader_bytes(tmp_path):
    worlds = check_role_worlds("value-withheld-total", tmp_path)
    original, extended = worlds["original"], worlds["more-hidden-links"]
    assert original["summary"] == extended["summary"]
    assert original["reader"]["relations/role_total.json"] != extended["reader"]["relations/role_total.json"]
    assert all(b"link-hidden" not in data for data in extended["summary"].values())
