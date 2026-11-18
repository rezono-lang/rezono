import shutil

import pytest
import yaml

from case_support import ROOT, engine, imported, verified
from rezono_publisher import batch, publish, store
from rules_support import states


def publish_locally(pack_dir, destination):
    epoch = batch.epoch(pack_dir, epoch=1, knowledge_time="2026-01-01T00:00:00Z",
                        sources=[("rules", "identity-test")])
    return publish.publish(epoch, store.FileStore(destination), {"checker": "complete"})


def test_standard_identity(tmp_path):
    imported("std-identity")
    _, baseline = engine()
    assert ("a", "b") in baseline.derived["equivalent"]
    assert baseline.derived["stated_text"] >= {
        ("a", "edition", "standard"), ("b", "edition", "standard"),
        ("a", "engine", "postgres"), ("b", "engine", "postgres"),
    }
    assert baseline.derived["identity_conflict"] == set()
    assert publish_locally(ROOT, tmp_path / "published")["id"] == "m-1"

    # Preserve the relative import paths and change just one assertion in an isolated copy.
    target = tmp_path / "examples" / "platform"
    shutil.copytree(ROOT, target)
    shutil.copytree(ROOT.parents[1] / "packs", tmp_path / "packs")
    source = target / "facts" / "identity.yaml"
    data = yaml.safe_load(source.read_text(encoding="utf-8"))
    claim, = [r for r in data["database_text_statement"] if r["id"] == "b-edition"]
    assert claim == {"id": "b-edition", "referent": "b", "slot": "edition", "value": "standard"}
    claim["value"] = "enterprise"
    source.write_text(yaml.safe_dump(data), encoding="utf-8")

    model, _, (diagnostic,) = states(target)
    conflicts = {("a", "b", "edition"), ("b", "a", "edition")}
    assert diagnostic.derived["identity_conflict"] == conflicts
    evidence = {("referent__same_as", ("a", "b"))}
    for claim_id, referent, value in [("a-edition", "a", "standard"), ("b-edition", "b", "enterprise")]:
        for slot, expected in [("referent", referent), ("slot", "edition"), ("value", value)]:
            evidence.add((f"database_text_statement__{slot}", (claim_id, expected)))
    for conflict in conflicts:
        assert evidence <= verified("identity_conflict", conflict, state=(model, diagnostic))
    with pytest.raises(publish.Blocked, match=r"^identity_conflict: 2$"):
        publish_locally(target, tmp_path / "refused")
