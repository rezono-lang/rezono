"""Shared subsidy reference and publisher fixtures."""
import importlib.util
import json
from pathlib import Path

import yaml

HERE = Path(__file__).parent
PACK = "subsidy"
PROFILE = HERE.parents[1] / "deploy" / "profiles" / "edge.yaml"


def publication_roles():
    """Combine the pack's grants with those of the edge profile when a test publishes."""
    profile = yaml.safe_load(PROFILE.read_text(encoding="utf-8"))
    return {"checker": "complete", "case_officer": "may_read", "policy_adviser": "may_read",
            "public": "may_read"} | profile["access"]["roles"]


def reference():
    """The pack's reference.py under a name of its own: other packs have a reference.py too."""
    spec = importlib.util.spec_from_file_location("subsidy_reference", HERE / "reference.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


EPOCH = {"epoch": 1, "knowledge_time": "2026-11-10T00:00:00Z", "sources": [("rules", "test")]}


def published(pack_dir: Path, root: Path):
    """The pack published for the roles of `publication_roles` into a store at `root`. The committed pack is
    published once per run and copied into `root` (examples/shared_builds.py); a changed copy is published here."""
    from rezono_publisher import batch, publish, store

    if Path(pack_dir).resolve() == HERE.resolve():
        import shared_builds

        return shared_builds.publication(HERE, root, publication_roles(), **EPOCH)
    e = batch.epoch(pack_dir, **EPOCH)
    s = store.FileStore(root)
    return s, publish.publish(e, s, publication_roles())


def rows(s, role: str, rel: str) -> list[tuple]:
    from rezono_publisher import publish

    return [tuple(r["key"]) for r in json.loads(s.get(publish.role_objects(s, PACK, "m-1", role)[f"relations/{rel}.json"]))]
