"""Common publisher setup and indexed relation reader for the subsidy tests."""
import json
from pathlib import Path

import yaml

from rezono_publisher import batch, publish, store

HERE = Path(__file__).parent
PACK = "subsidy"
PROFILE = HERE.parents[1] / "deploy" / "profiles" / "edge.yaml"
# The pack's own roles, and the roles of the profile that publishes it (`propose`, `viewer`).
ROLES = {"checker": "complete", "case_officer": "may_read", "policy_adviser": "may_read", "public": "may_read"} | yaml.safe_load(
    PROFILE.read_text(encoding="utf-8"))["access"]["roles"]


def published(pack_dir: Path, root: Path):
    e = batch.epoch(pack_dir, epoch=1, knowledge_time="2026-11-10T00:00:00Z", sources=[("rules", "test")])
    s = store.FileStore(root)
    return s, publish.publish(e, s, ROLES)


def rows(s, role: str, rel: str) -> list[tuple]:
    return [tuple(r["key"]) for r in json.loads(s.get(publish.role_objects(s, PACK, "m-1", role)[f"relations/{rel}.json"]))]
