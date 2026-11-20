"""The check row `rezono:origins` through the real route: the compiler's sources, the batch epoch and the publisher
(decisions/fact-origin-required.md, section 5). It counts main's fact rows without an origin: a warning with that
number on a rezono 0 pack, and green with none.

The pack is the compiler's neutral one (compiler/tests/fixtures/minimal) with facts, read rules and source sidecars
added in a temp dir; it describes no domain.
"""

import shutil
from pathlib import Path

import pytest
import yaml

pytest.importorskip("duckdb")
pytest.importorskip("rezono_compiler")

from rezono_compiler import pack as compiler_pack  # noqa: E402
from rezono_compiler import sources as compiler_sources  # noqa: E402
from rezono_publisher import batch, publish, store  # noqa: E402

ROOT = Path(__file__).resolve().parents[3]
MINIMAL = ROOT / "compiler" / "tests" / "fixtures" / "minimal"
ROLES = {"checker": "complete", "viewer": "may_read"}
RULES = """.decl may_read(role: symbol, kind: symbol, element: symbol)
may_read("viewer", "alpha", x) :- alpha__title(x, "open").
may_read("viewer", "beta", x) :- beta(x).
"""
ALPHAS = "alpha:\n  - {id: a1, title: open, size: 3}\n"
BETAS = "beta:\n  - {id: b1, alpha: a1, state: low}\n"
TOOL = {"kind": "tool", "name": "Register scan", "position": "run 1"}
ORIGINS = "rezono:origins"


class MissingOriginsCheck(AssertionError):
    """The manifest has no `rezono:origins` row with the status and count the decision gives."""


def origin_pack(tmp: Path, sidecars: dict[str, dict]) -> Path:
    d = tmp / "pack"
    shutil.copytree(MINIMAL, d)
    (d / "facts").mkdir()
    (d / "facts" / "a.yaml").write_text(ALPHAS, encoding="utf-8")
    (d / "facts" / "b.yaml").write_text(BETAS, encoding="utf-8")
    for name, doc in sidecars.items():
        (d / "facts" / name).write_text(yaml.safe_dump(doc, sort_keys=True), encoding="utf-8")
    (d / "rules").mkdir()
    (d / "rules" / "access.dl").write_text(RULES, encoding="utf-8")
    return d


def manifest_checks(tmp: Path, d: Path) -> list:
    e = batch.epoch(d, epoch=1, knowledge_time="2026-01-01T00:00:00Z", sources=[("rules", "test")])
    return publish.publish(e, store.FileStore(tmp / "store"), ROLES, None)["checks"]


def test_the_manifest_counts_fact_rows_without_origin(tmp_path):
    warn_dir = origin_pack(tmp_path / "warn", {"b.sources.yaml": {"default": TOOL}})
    # Independent of the publisher: the rows that a.yaml gives with only its own file and line as source.
    entries = compiler_sources.read(compiler_pack.read(warn_dir), warn_dir)
    without = [e["row"] for e in entries if all(s["kind"] == "pack" for s in e["sources"])]
    assert without and all(row["relation"].split("__")[0] == "alpha" for row in without), without

    problems = []
    checks = manifest_checks(tmp_path / "warn", warn_dir)
    expected = {"name": ORIGINS, "status": "warning", "violations": len(without)}
    if expected not in checks:
        problems.append(f"a rezono 0 pack with {len(without)} fact rows without origin must report {expected}: {checks}")

    # Counter-case: every row has an origin.
    green_dir = origin_pack(tmp_path / "green", {"a.sources.yaml": {"default": TOOL}, "b.sources.yaml": {"default": TOOL}})
    checks = manifest_checks(tmp_path / "green", green_dir)
    if {"name": ORIGINS, "status": "green", "violations": 0} not in checks:
        problems.append(f"a pack whose fact rows all have an origin must report {ORIGINS} green with 0: {checks}")
    if problems:
        raise MissingOriginsCheck("\n".join(problems))
