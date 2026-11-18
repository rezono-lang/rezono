"""Shared subsidy reference and publisher fixtures."""
import importlib.util
import json
from pathlib import Path

import yaml

HERE = Path(__file__).parent
PACK = "subsidy"
PROFILE = HERE.parents[1] / "deploy" / "profiles" / "edge.yaml"
# The pack's own roles, and the roles of the profile that publishes it (`propose`, `viewer`).
ROLES = {"checker": "complete", "case_officer": "may_read", "policy_adviser": "may_read", "public": "may_read"} | yaml.safe_load(
    PROFILE.read_text(encoding="utf-8"))["access"]["roles"]


def reference():
    """The pack's reference.py under a name of its own: other packs have a reference.py too."""
    spec = importlib.util.spec_from_file_location("subsidy_reference", HERE / "reference.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def published(pack_dir: Path, root: Path):
    from rezono_publisher import batch, publish, store

    e = batch.epoch(pack_dir, epoch=1, knowledge_time="2026-11-10T00:00:00Z", sources=[("rules", "test")])
    s = store.FileStore(root)
    return s, publish.publish(e, s, ROLES)


def rows(s, role: str, rel: str) -> list[tuple]:
    from rezono_publisher import publish

    return [tuple(r["key"]) for r in json.loads(s.get(publish.role_objects(s, PACK, "m-1", role)[f"relations/{rel}.json"]))]
