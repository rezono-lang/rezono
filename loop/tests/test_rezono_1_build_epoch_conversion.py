"""Strict red test for single-pass rule conversion of `build/` and `epoch/` to native `rezono 1`
modules with whole-pack equivalence against their frozen legacy snapshots via `compare_publications`
(decisions/language-rezono-1.md, sections 5.8, 5.10, 6 and 8).
"""

from __future__ import annotations

from contextlib import ExitStack
import importlib.util
from pathlib import Path
import shutil
import sys

import pytest
import yaml


REPO = Path(__file__).resolve().parents[2]
LEGACY_HELPERS_PATH = REPO / "examples" / "fixtures" / "rezono-1-legacy" / "helpers.py"


def _load_legacy_helpers():
    spec = importlib.util.spec_from_file_location("rezono_1_legacy_helpers", LEGACY_HELPERS_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


_LEGACY = _load_legacy_helpers()
TIME = _LEGACY.TIME
CUT_TICK = 1794268800  # 2026-11-10T00:00:00Z

# Synthetic exercise facts (with `kind: synthetic` origins per decisions/fact-origin-required.md §3)
# feeding EVERY rule file in `build/rules/` (`access.dl`, `selection.dl`, `policy_date.dl`,
# `decision_rules.dl`, `progress.dl`, `tasks.dl`, `claims.dl`, `claim_release.dl`) with non-empty input,
# using ISO calendar dates only (no day-number stopgaps; decisions/standard-packs-everywhere.md §1.4).
BUILD_EXERCISE = {
    "loop_active_run": [{"id": "run-1"}],
    "loop_sweep_receipt": [
        {"id": "rcpt-1", "run": "run-1", "event_time": CUT_TICK},
        {"id": "rcpt-after", "run": "run-1", "event_time": CUT_TICK + 100},
    ],
    "loop_step": [{"id": "step-1"}, {"id": "step-2"}],
    "build_run": [
        {
            "id": "run-1",
            "event": "pull_request",
            "base_sha": "a" * 40,
            "head_sha": "b" * 40,
            "engine_sha": "c" * 40,
            "observed_at": CUT_TICK,
            "receipt": "rcpt-1",
        },
    ],
    "build_component": [
        {"id": "comp-a", "run": "run-1", "kind": "python", "folder": "compiler"},
        {"id": "comp-b", "run": "run-1", "kind": "python", "folder": "checker"},
    ],
    "build_manifest": [
        {
            "id": "man-b",
            "component": "comp-b",
            "path": "checker/pyproject.toml",
            "revision": "b" * 40,
            "blob": "d" * 40,
        },
    ],
    "build_dependency": [
        {
            "id": "dep-1",
            "dependency": "comp-a",
            "consumer": "comp-b",
            "kind": "manifest",
            "manifest": "man-b",
            "source": "synthetic",
        },
    ],
    "build_test_file": [
        {"id": "tf-1", "component": "comp-a", "path": "compiler/tests/test_sample.py"},
    ],
    "build_path": [
        {"id": "path-1", "run": "run-1", "path": "compiler/rezono_compiler/pack.py", "coverage": "mapped"},
    ],
    "build_path_reader": [
        {"id": "pr-1", "path": "path-1", "component": "comp-a", "kind": "transitive", "source": "synthetic"},
    ],
    "build_target_rule": [
        {"id": "tr-1", "target": "docs-check", "path_prefix": "docs/", "kind": "full_fallback"},
    ],
    "reference_date": [
        {"id": "ref-1", "title": "2026-11-10", "date": "2026-11-10"},
    ],
    "build_policy_date": [
        {"id": "pd-1", "run": "run-1", "reference": "ref-1", "observed_at": CUT_TICK},
    ],
    "decision": [
        {
            "id": "dec-old",
            "title": "Old policy",
            "state": "superseded",
            "decider": ["owner"],
            "valid_from": "2025-01-01",
        },
        {
            "id": "dec-1",
            "title": "Active policy",
            "state": "in_force",
            "decider": ["owner"],
            "valid_from": "2026-01-01",
            "supersedes": ["dec-old"],
        },
        {
            "id": "dec-2",
            "title": "Open policy",
            "state": "in_force",
            "decider": ["owner"],
            "valid_from": "2026-02-01",
        },
        {
            "id": "dec-3",
            "title": "Uncited policy",
            "state": "in_force",
            "decider": ["owner"],
            "valid_from": "2026-03-01",
        },
    ],
    "build_citation_scan": [
        {"id": "cscan-1", "run": "run-1", "observed_at": CUT_TICK, "source": "synthetic"},
    ],
    "build_decision_citation": [
        {"id": "dc-1", "scan": "cscan-1", "path": "compiler/tests/test_sample.py", "decision": "dec-1"},
    ],
    "build_red_citation": [
        {"id": "rc-1", "scan": "cscan-1", "test": "compiler/tests/test_open.py::test_open", "decision": "dec-2"},
        {"id": "rc-2", "scan": "cscan-1", "test": "compiler/tests/test_old.py::test_old", "decision": "dec-old"},
    ],
    "build_milestone": [
        {"id": "M1", "scope": "release_1"},
        {"id": "M2", "scope": "release_1"},
        {"id": "M3", "scope": "release_1"},
        {"id": "M4", "scope": "release_1"},
    ],
    "build_progress_scan": [
        {"id": "scan-1", "run": "run-1", "observed_at": CUT_TICK, "source": "synthetic-scan"},
    ],
    "build_red_test": [
        {"id": "rt-1", "scan": "scan-1", "test": "example::test_one", "milestone": "M3"},
    ],
    "build_green_transition": [
        {"id": "gt-1", "scan": "scan-1", "test": "example::test_zero", "milestone": "M1", "commit": "e" * 40},
    ],
    "build_offboard_work": [
        {
            "id": "ob-1",
            "scan": "scan-1",
            "item": "pack-dl-conversion",
            "state": "known",
            "completed": 1,
            "total": 124,
            "source": "synthetic-scan",
        },
        {
            "id": "ob-2",
            "scan": "scan-1",
            "item": "other-work",
            "state": "unknown",
            "reason": "pending-scan",
            "source": "synthetic-scan",
        },
    ],
    "build_task": [
        {"id": "task-1", "run": "run-1", "step": "step-1", "track": "track-a", "source": "synthetic"},
        {"id": "task-2", "run": "run-1", "step": "step-2", "track": "track-b", "source": "synthetic"},
    ],
    "build_track_rank": [
        {"id": "rank-1", "decision": "dec-1", "track": "track-a", "rank": 1},
        {"id": "rank-2", "decision": "dec-1", "track": "track-b", "rank": 2},
    ],
    "build_queue_limit": [
        {"id": "ql-1", "decision": "dec-1", "limit": 5},
    ],
    "build_claim": [
        {
            "id": "claim-1",
            "run": "run-1",
            "branch": "task/demo-stale",
            "generation": "f" * 40,
            "observed_at": CUT_TICK,
            "source": "synthetic",
        },
        {
            "id": "claim-2",
            "run": "run-1",
            "branch": "task/demo-active",
            "generation": "1" * 40,
            "observed_at": CUT_TICK,
            "source": "synthetic",
        },
    ],
    "build_claim_activity": [
        {"id": "act-1", "claim": "claim-1", "after": "f" * 40, "pushed_at": CUT_TICK - 8800, "source": "synthetic"},
        {"id": "act-2", "claim": "claim-2", "after": "1" * 40, "pushed_at": CUT_TICK - 800, "source": "synthetic"},
    ],
    "build_claim_lease": [
        {"id": "lease-1", "decision": "dec-1", "seconds": 7200},
    ],
    "build_claim_pull_reading": [
        {
            "id": "cpr-1",
            "claim": "claim-1",
            "observed_at": CUT_TICK,
            "state": "none",
            "source": "synthetic",
            "receipt": "rcpt-1",
        },
        {
            "id": "cpr-2",
            "claim": "claim-2",
            "observed_at": CUT_TICK,
            "state": "open",
            "source": "synthetic",
        },
    ],
    "build_claim_delete": [
        {
            "id": "del-1",
            "run": "run-1",
            "branch": "task/demo-stale",
            "generation": "f" * 40,
            "sent_at": CUT_TICK,
            "outcome": "sent",
            "source": "synthetic",
        },
        {
            "id": "del-2",
            "run": "run-1",
            "branch": "task/demo-pending",
            "generation": "2" * 40,
            "sent_at": CUT_TICK,
            "outcome": "sent",
            "source": "synthetic",
        },
    ],
    "build_claim_ref_read": [
        {
            "id": "rr-1",
            "run": "run-1",
            "branch": "task/demo-stale",
            "observed_at": CUT_TICK + 100,
            "state": "absent",
            "receipt": "rcpt-after",
            "source": "synthetic",
        },
    ],
}

# Representative derived relation per rule module in `build/rules/*.dl` to prove non-vacuous coverage.
BUILD_REQUIRED_NON_EMPTY = (
    "may_read",                 # access.dl
    "build_selected_job",       # selection.dl
    "build_policy_date_at_cut", # policy_date.dl
    "build_decision_done",      # decision_rules.dl
    "build_milestone_progress", # progress.dl
    "build_task_precedes",      # tasks.dl
    "build_claim_release_plan", # claims.dl
    "build_claim_released",     # claim_release.dl
)

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


def test_legacy_build_and_epoch_archive_integrity():
    """Verify the shared legacy archive holds `build/`, `epoch/`, and their imported standard packs,
    and matches live definition files byte-for-byte (LF-normalized) for every pack that is still legacy."""
    expected_packs = {
        "build",
        "epoch",
        "packs/std-access",
        "packs/std-decision",
        "packs/std-loop",
        "packs/std-order",
    }
    _LEGACY.assert_legacy_archive_integrity(
        expected_packs,
        expected_dl_packs={"build", "epoch", "packs/std-decision", "packs/std-loop", "packs/std-order"},
        expected_files={"packs/std-access": {"rezono/access.rezono"}},
    )
    _LEGACY.assert_legacy_packs_match_archive(expected_packs)


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

    build_model = _LEGACY.assert_pack_is_native_rezono_1(build_dir, compile_output=False)
    _LEGACY.assert_pack_is_native_rezono_1(epoch_dir, compile_output=False)

    if str(REPO) not in sys.path:
        sys.path.insert(0, str(REPO))
    from rezono_publisher import batch as publisher_batch
    from scripts import convert_pack

    legacy_root = tmp_path / "legacy"
    _LEGACY.materialize_legacy_packs(legacy_root, ("packs", "build", "epoch"))
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
                _LEGACY.synthetic_sidecar("loop/tests/test_rezono_1_build_epoch_conversion.py", f"{pack_name}-exercise"),
                encoding="utf-8",
                newline="\n",
            )

    build_roles = _LEGACY.roles_for_pack(build_dir, build_model)
    assert {"checker", "coordinator", "owner"} <= set(build_roles), build_roles

    # Compare build/ across all roles via compare_publications (non-vacuous across all 8 build rule modules).
    with ExitStack() as stack:
        _LEGACY.admit_legacy_std_packs(stack, legacy_root)
        legacy_build_epoch = publisher_batch.epoch(
            legacy_root / "build", epoch=1, knowledge_time=TIME, sources=[("rules", "legacy-build")]
        )
        legacy_build = convert_pack.read_publication(legacy_build_epoch, tmp_path / "legacy-build-store", build_roles)
    for rel_name in BUILD_REQUIRED_NON_EMPTY:
        assert legacy_build.rows.get(rel_name), f"build/ exercise must derive non-empty {rel_name} rows"
    native_build_epoch = publisher_batch.epoch(
        native_root / "build", epoch=1, knowledge_time=TIME, sources=[("rules", "native-build")]
    )
    _, build_ir = _LEGACY.assert_epoch_is_rezono_1("build", native_build_epoch)
    build_relations = {r["name"] for r in build_ir.get("relations", []) if r.get("role") != "base"}
    assert {
        "may_read",
        "may_read_full",
        "build_selected_job",
        "build_policy_date_at_cut",
        "build_decision_done",
        "build_milestone_progress",
        "release_1_done",
        "build_offboard_work_count",
        "build_offboard_work_unknown",
        "build_task_precedes",
        "build_claim_release_plan",
        "build_claim_released",
    } <= build_relations, sorted(build_relations)
    convert_pack.compare_publications(legacy_build_epoch, native_build_epoch, build_roles)

    # Compare epoch/ across all derived relations via compare_publications (non-vacuous check on derived rows).
    with ExitStack() as stack:
        _LEGACY.admit_legacy_std_packs(stack, legacy_root)
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
    _, epoch_ir = _LEGACY.assert_epoch_is_rezono_1("epoch", native_epoch_run)
    epoch_relations = {r["name"] for r in epoch_ir.get("relations", []) if r.get("role") != "base"}
    assert {"publish_allowed", "epoch_allowed", "derived_refusal"} <= epoch_relations, sorted(epoch_relations)
    convert_pack.compare_publications(legacy_epoch_run, native_epoch_run, {"checker": "complete"})
