"""Publish `examples/zorgtoeslag-slice` across successive `(as_of, known)` main epochs into one store
and query it through `edge/gate/src/local.ts` (decisions/bitemporal-history-publication.md)."""

from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import subprocess

import yaml


ROOT = Path(__file__).resolve().parents[1]
SLICE = ROOT / "examples" / "zorgtoeslag-slice"
READER = ROOT / "tests" / "slip" / "reader.mjs"
ROLES = {"checker": "complete"}


def node() -> str:
    return os.environ.get("REZONO_NODE", "node")


def _write_form(source: Path, dest: Path) -> dict:
    run = subprocess.run(
        [node(), str(ROOT / "rezono" / "src" / "write-form.ts"), str(source), str(dest)],
        capture_output=True, text=True, encoding="utf-8",
    )
    assert run.returncode == 0, run.stderr
    return json.loads(dest.read_bytes())


def publish_history(
    directory: Path,
    epochs: list[tuple[str, str]],
) -> tuple[Path, list[dict]]:
    """Publish `examples/zorgtoeslag-slice` for each `(as_of, known)` pair as successive main epochs
    `m-1..m-k` into `directory/store`. Returns `(store_dir, manifests)`."""
    from rezono_publisher import batch, publish, store

    staged = directory / "slice-pack"
    shutil.copytree(
        SLICE,
        staged,
        ignore=shutil.ignore_patterns("facts.rezono", "reference.py", "allowance-cases.yaml"),
    )

    # Declare facts.rezono as a Rezono fact module so batch.epoch resolves dated FactRows
    # natively at each (as_of, known) pair without YAML fact files or mutating ep.checks.
    facts_mod = staged / "rezono" / "facts.rezono"
    facts_form = staged / "rezono" / "facts.json"
    shutil.copyfile(SLICE / "facts.rezono", facts_mod)
    _write_form(facts_mod, facts_form)

    meta_path = staged / "pack.yaml"
    meta = yaml.safe_load(meta_path.read_text(encoding="utf-8"))
    meta["rezono"] = list(meta.get("rezono") or []) + [
        {"module": "rezono/facts.rezono", "form": "rezono/facts.json", "layer": "facts"},
    ]
    meta_path.write_text(yaml.safe_dump(meta, sort_keys=False), encoding="utf-8")

    store_dir = directory / "store"
    file_store = store.FileStore(store_dir)
    manifests: list[dict] = []

    for idx, (as_of_str, known_str) in enumerate(epochs, start=1):
        ep = batch.epoch(
            staged,
            epoch=idx,
            knowledge_time=f"{known_str}T00:00:00Z",
            sources=[("facts", f"{as_of_str}/{known_str}")],
            as_of=as_of_str,
            known=known_str,
            dated_totality="warning",
        )
        manifest = publish.publish(ep, file_store, ROLES)
        manifests.append(manifest)

    return store_dir, manifests


def ask(store_dir: Path, role: str, *requests: str) -> list[dict]:
    """Query `edge/gate/src/local.ts` via `tests/slip/reader.mjs` for `role`."""
    run = subprocess.run(
        [node(), str(READER)],
        input=json.dumps({
            "store": store_dir.as_posix(),
            "role": role,
            "requests": list(requests),
        }),
        capture_output=True, encoding="utf-8", timeout=120, cwd=ROOT,
    )
    assert run.returncode == 0, run.stderr
    return json.loads(run.stdout)
