"""Strict red test for single-pass rule conversion of `build/` and `epoch/` to native `rezono 1`
modules with whole-pack equivalence against their frozen legacy snapshots via `compare_publications`
(decisions/language-rezono-1.md, sections 5.8, 5.10, 6 and 8).
"""

from __future__ import annotations

from contextlib import ExitStack
import json
from pathlib import Path
import shutil
import sys
import tarfile

import pytest
import yaml


REPO = Path(__file__).resolve().parents[2]
LEGACY_ARCHIVE = Path(__file__).resolve().parent / "fixtures" / "rezono-1-legacy" / "legacy-packs.tar.gz"
TIME = "2026-11-10T00:00:00Z"

# Synthetic exercise facts (with `kind: synthetic` origins per decisions/fact-origin-required.md §3)
# so `compare_publications` compares non-empty derived conclusions and per-role views for both packs.
BUILD_EXERCISE = {
    "build_run": [
        {
            "id": "run-1",
            "event": "pull_request",
            "base_sha": "a" * 40,
            "head_sha": "b" * 40,
            "engine_sha": "c" * 40,
            "observed_at": 100,
        },
    ],
    "build_milestone": [
        {"id": "M1", "scope": "release_1"},
        {"id": "M2", "scope": "release_1"},
        {"id": "M3", "scope": "release_1"},
        {"id": "M4", "scope": "release_1"},
    ],
    "build_progress_scan": [
        {"id": "scan-1", "run": "run-1", "observed_at": 100, "source": "synthetic-scan"},
    ],
    "build_red_test": [
        {"id": "rt-1", "scan": "scan-1", "test": "example::test_one", "milestone": "M3"},
    ],
    "build_offboard_work": [
        {
            "id": "ob-1",
            "scan": "scan-1",
            "item": "pack-dl-conversion",
            "state": "known",
            "completed": 0,
            "total": 124,
            "source": "synthetic-scan",
        },
    ],
}

EPOCH_EXERCISE = {
    "loop_active_run": [{"id": "run-1"}],
    "epoch_run": [{"id": "run-1", "pack": "demo", "epoch": 1, "commit": "a" * 40, "profile": "edge"}],
    "epoch_engine_pin": [
        {"id": "pin-1", "run": "run-1", "version": "1.0", "wheel_sha256": "b" * 64, "commit": "a" * 40},
    ],
    "epoch_tool": [
        {"id": "t-1", "run": "run-1", "step": "compile", "tool": "compiler", "version": "1.0", "sha256": "c" * 64},
    ],
    "epoch_definition": [
        {"id": "def-1", "run": "run-1", "definition_sha256": "d" * 64, "compiler_sha256": "e" * 64},
    ],
    "epoch_check": [
        {
            "id": "chk-1",
            "run": "run-1",
            "step": "check",
            "check": "rezono:proofs",
            "outcome": "red",
            "violations": 1,
            "source": "synthetic",
        },
    ],
}


def _rel(path: Path) -> str:
    return path.relative_to(REPO).as_posix()


def _synthetic_sidecar(position: str) -> str:
    return yaml.safe_dump(
        {
            "default": {
                "kind": "synthetic",
                "name": "loop/tests/test_rezono_1_build_epoch_conversion.py",
                "position": position,
            }
        },
        sort_keys=False,
    )


def _read_legacy_archive() -> dict[str, dict[str, bytes]]:
    raw: dict[str, bytes] = {}
    with tarfile.open(LEGACY_ARCHIVE, "r:gz") as tf:
        for member in tf.getmembers():
            assert (
                member.isfile()
                and not member.issym()
                and not member.islnk()
                and not member.name.startswith("/")
                and "\\" not in member.name
                and ".." not in member.name.split("/")
            ), member.name
            handle = tf.extractfile(member)
            assert handle is not None
            raw[member.name] = handle.read()
    pack_roots = sorted(
        (name[: -len("/pack.yaml")] for name in raw if name.endswith("/pack.yaml")),
        key=len,
        reverse=True,
    )
    by_pack: dict[str, dict[str, bytes]] = {root: {} for root in pack_roots}
    for name, data in raw.items():
        owner = next(root for root in pack_roots if name.startswith(root + "/"))
        by_pack[owner][name[len(owner) + 1 :]] = data
    return by_pack


def _materialize_legacy_packs(dest_root: Path) -> None:
    for pack_rel, files in _read_legacy_archive().items():
        pack_dir = dest_root / pack_rel
        if pack_dir.exists():
            shutil.rmtree(pack_dir)
        for rel_file, data in files.items():
            target = pack_dir / rel_file
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(data)


def _admit_legacy_std_packs(stack: ExitStack, root: Path) -> None:
    from rezono_compiler import modules, standard_packs

    packs_dir = root / "packs"
    if not packs_dir.is_dir():
        return
    for pack_yaml in sorted(packs_dir.glob("std-*/pack.yaml")):
        std_dir = pack_yaml.parent
        stack.enter_context(standard_packs.trial(std_dir.name, modules.pack_hash(std_dir)))


def _form_has_derivation(decls: list[dict]) -> bool:
    for decl in decls:
        if not isinstance(decl, dict):
            continue
        if "derived" in decl and isinstance(decl["derived"], str):
            return True
        if "step" in decl:
            return True
        nested = decl.get("derived")
        if isinstance(nested, list) and nested:
            return True
    return False


def _assert_pack_is_native_rezono_1(pack_dir: Path) -> object:
    dl_files = sorted(_rel(path) for path in pack_dir.rglob("*.dl"))
    assert not dl_files, f"{_rel(pack_dir)} still contains .dl rule files: {dl_files}"

    meta = yaml.safe_load((pack_dir / "pack.yaml").read_bytes()) or {}
    entries = meta.get("rezono") or []
    assert entries, f"{_rel(pack_dir)}/pack.yaml must declare native rezono 1 modules under `rezono:`"

    has_derivation = False
    for entry in entries:
        module_path = pack_dir / entry["module"]
        form_path = pack_dir / entry["form"]
        assert module_path.is_file(), f"missing module {_rel(module_path)}"
        assert form_path.is_file(), f"missing module form {_rel(form_path)}"

        form = json.loads(form_path.read_bytes())
        assert form.get("format") == "rezono.module/5", (
            f"{_rel(form_path)} must use format rezono.module/5, got {form.get('format')!r}"
        )
        module = form.get("module") or {}
        assert module.get("rezono") == "1", (
            f"{_rel(form_path)} must record module.rezono == '1', got {module.get('rezono')!r}"
        )
        decls = module.get("decls") or []
        for decl in decls:
            if isinstance(decl, dict):
                assert "rules" not in decl, f"{_rel(form_path)} still contains a legacy `rules` pipe block"
                assert "rule" not in decl, f"{_rel(form_path)} still contains a rezono 0 `rule` declaration"
        if _form_has_derivation(decls):
            has_derivation = True

    assert has_derivation, f"{_rel(pack_dir)} must define native rezono 1 `derived` (or `step`) declarations"

    from rezono_compiler import pack

    return pack.read(pack_dir)


def _assert_epoch_is_rezono_1(pack_label: str, epoch) -> tuple[dict, dict]:
    bundle = json.loads(epoch.bundle)
    info = bundle.get("pack") or {}
    assert info.get("language_version") == "1", (
        f"{pack_label} bundle/schema-bundle.json must record language_version == '1': {info!r}"
    )
    ir = json.loads(epoch.rules)
    assert any(r.get("role") != "base" for r in ir.get("relations", ())), (
        f"{pack_label} compiled ir/rules.json has no derived or functional relations"
    )
    return bundle, ir


def test_legacy_build_and_epoch_archive_integrity():
    """Verify `loop/tests/fixtures/rezono-1-legacy/legacy-packs.tar.gz` is well-formed (regular files only,
    no symlinks or path traversal) and contains `build/`, `epoch/`, their imported standard packs, and `.dl` rules."""
    assert LEGACY_ARCHIVE.is_file(), f"missing {_rel(LEGACY_ARCHIVE)}"
    by_pack = _read_legacy_archive()
    expected_packs = {
        "build",
        "epoch",
        "packs/std-access",
        "packs/std-decision",
        "packs/std-loop",
        "packs/std-order",
    }
    assert expected_packs <= set(by_pack), f"missing packs in archive: {sorted(expected_packs - set(by_pack))}"
    for pack_rel in sorted(expected_packs):
        meta = yaml.safe_load(by_pack[pack_rel]["pack.yaml"])
        assert isinstance(meta, dict) and meta.get("name"), f"invalid pack.yaml in archive for {pack_rel}"

    for pack_rel in ("build", "epoch", "packs/std-decision", "packs/std-loop", "packs/std-order"):
        dl_files = [rel for rel in by_pack[pack_rel] if rel.endswith(".dl")]
        assert dl_files, f"archive pack {pack_rel} is missing legacy .dl definitions"
    assert "rezono/access.rezono" in by_pack["packs/std-access"], "archive packs/std-access missing access.rezono"


@pytest.mark.xfail(
    strict=True,
    raises=AssertionError,
    reason=(
        "extra: decisions/language-rezono-1.md: Convert build/ and epoch/ .dl rules to native rezono 1 modules "
        "(zero .dl files remaining in build/ and epoch/) with whole-pack equivalence against their frozen legacy "
        "snapshots via compare_publications across every derived relation, checked grounds, and per-role views. "
        "Waits for compiler/tests/rezono/test_lower_rezono_1_derived.py--test_lower_rezono_1_derived, "
        "examples/test_calculation_engine_parity.py--test_feldera_calculations_match_duckdb_and_checker, "
        "examples/test_rule_witness_engine_parity.py--test_feldera_rule_witnesses_match_batch, "
        "and examples/test_rezono_1_pack_conversion.py--test_standard_packs_convert_to_rezono_1."
    ),
)
def test_build_and_epoch_packs_convert_to_rezono_1(tmp_path: Path):
    build_dir = REPO / "build"
    epoch_dir = REPO / "epoch"

    build_model = _assert_pack_is_native_rezono_1(build_dir)
    _assert_pack_is_native_rezono_1(epoch_dir)

    if str(REPO) not in sys.path:
        sys.path.insert(0, str(REPO))
    from rezono_compiler import facts as fact_files
    from rezono_publisher import batch as publisher_batch
    from scripts import convert_pack

    legacy_root = tmp_path / "legacy"
    _materialize_legacy_packs(legacy_root)
    native_root = tmp_path / "native"
    shutil.copytree(REPO / "packs", native_root / "packs")
    shutil.copytree(build_dir, native_root / "build")
    shutil.copytree(epoch_dir, native_root / "epoch")

    # Copy build/facts/ (roles.yaml) into the legacy snapshot so both sides share identical base roles.
    if (build_dir / "facts").is_dir():
        shutil.copytree(build_dir / "facts", legacy_root / "build" / "facts", dirs_exist_ok=True)

    # Inject synthetic exercise facts (kind: synthetic) into BOTH legacy and native build/ and epoch/ copies.
    for pack_name, exercise in (("build", BUILD_EXERCISE), ("epoch", EPOCH_EXERCISE)):
        for root in (legacy_root, native_root):
            facts_dir = root / pack_name / "facts"
            facts_dir.mkdir(exist_ok=True)
            (facts_dir / "exercise.yaml").write_text(
                yaml.safe_dump(exercise, sort_keys=False), encoding="utf-8", newline="\n"
            )
            (facts_dir / "exercise.sources.yaml").write_text(
                _synthetic_sidecar(f"{pack_name}-exercise"), encoding="utf-8", newline="\n"
            )

    build_roles: dict[str, str] = {"checker": "complete"}
    for path in fact_files.files(build_dir):
        for row in fact_files.load(build_model, path).get("role", ()):
            build_roles[str(row[0])] = "may_read"
    assert {"checker", "coordinator", "owner"} <= set(build_roles), build_roles

    # Compare build/ across all roles via compare_publications (non-vacuous check on derived rows).
    with ExitStack() as stack:
        _admit_legacy_std_packs(stack, legacy_root)
        legacy_build_epoch = publisher_batch.epoch(
            legacy_root / "build", epoch=1, knowledge_time=TIME, sources=[("rules", "legacy-build")]
        )
        legacy_build = convert_pack.read_publication(legacy_build_epoch, tmp_path / "legacy-build-store", build_roles)
    assert legacy_build.rows["may_read"], "build/ exercise must derive non-empty may_read rows"
    native_build_epoch = publisher_batch.epoch(
        native_root / "build", epoch=1, knowledge_time=TIME, sources=[("rules", "native-build")]
    )
    _, build_ir = _assert_epoch_is_rezono_1("build", native_build_epoch)
    build_relations = {r["name"] for r in build_ir.get("relations", []) if r.get("role") != "base"}
    assert {
        "may_read",
        "may_read_full",
        "build_milestone_progress",
        "release_1_done",
        "build_offboard_work_count",
        "build_offboard_work_unknown",
    } <= build_relations, sorted(build_relations)
    convert_pack.compare_publications(legacy_build_epoch, native_build_epoch, build_roles)

    # Compare epoch/ across all derived relations via compare_publications (non-vacuous check on derived rows).
    with ExitStack() as stack:
        _admit_legacy_std_packs(stack, legacy_root)
        legacy_epoch_run = publisher_batch.epoch(
            legacy_root / "epoch", epoch=1, knowledge_time=TIME, sources=[("rules", "legacy-epoch")]
        )
        legacy_epoch_pub = convert_pack.read_publication(
            legacy_epoch_run, tmp_path / "legacy-epoch-store", {"checker": "complete"}
        )
    assert legacy_epoch_pub.rows["epoch_pinned_engine"] and legacy_epoch_pub.rows["epoch_compiled_definition"], (
        "epoch/ exercise must derive non-empty engine/definition rows"
    )
    native_epoch_run = publisher_batch.epoch(
        native_root / "epoch", epoch=1, knowledge_time=TIME, sources=[("rules", "native-epoch")]
    )
    _, epoch_ir = _assert_epoch_is_rezono_1("epoch", native_epoch_run)
    epoch_relations = {r["name"] for r in epoch_ir.get("relations", []) if r.get("role") != "base"}
    assert {"publish_allowed", "epoch_allowed", "derived_refusal"} <= epoch_relations, sorted(epoch_relations)
    convert_pack.compare_publications(legacy_epoch_run, native_epoch_run, {"checker": "complete"})
