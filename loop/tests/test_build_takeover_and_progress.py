"""Immediate build-pack cutover with pinned engine, fail-closed safe mode, milestone progress and release-1 completion."""
from importlib.util import find_spec
import inspect
import json
from pathlib import Path
import re
import shutil

import pytest
import yaml

from rezono_canon import canonical_json, sha256_hex
from rezono_publisher import batch, publish, store
from test_build_selection import OBSERVED_AT, capture, git, repository

ROOT = Path(__file__).resolve().parents[2]
UNIVERSE = frozenset({"alpha", "beta", "gamma", "viewer"})
GREEN = {"checks": [{"name": "rezono:proofs", "status": "green"}, {"name": "rezono:schema", "status": "green"}]}
RED_PROOF = {"checks": [{"name": "rezono:proofs", "status": "red"}, {"name": "rezono:schema", "status": "green"}]}
SHA40 = re.compile(r"^[0-9a-f]{40}$")
MILESTONES = [
    {"id": "M1", "scope": "release_1"},
    {"id": "M2", "scope": "release_1"},
    {"id": "M3", "scope": "release_1"},
    {"id": "M4", "scope": "release_1"},
    {"id": "extra", "scope": "outside_release_1"},
    {"id": "later", "scope": "outside_release_1"},
]


class MissingPinnedEngineRunner(AssertionError):
    """The pinned-engine pin file or validator is not implemented yet."""


class MissingBuildCutover(AssertionError):
    """The immediate build-pack cutover selector with fail-closed safe mode is not implemented yet."""


class MissingCoordinatorReader(AssertionError):
    """The thin coordinator reader for published build relations with fail-closed safe mode is not implemented yet."""


class MissingProgressRelations(AssertionError):
    """The build pack does not yet derive milestone progress and release_1_done."""


class MissingOffboardAndRolePublication(AssertionError):
    """The build pack does not yet derive off-board release-1 work or publish for coordinator and owner roles."""


def _rows(*keys):
    return [{"key": list(key)} for key in keys]


def _declared_kinds():
    return {
        name
        for path in sorted((ROOT / "build" / "schema").glob("*.yaml"))
        for name in (yaml.safe_load(path.read_text(encoding="utf-8")).get("classes") or {})
    }


def _publish_roles(tmp, records, roles):
    build = tmp / "build"
    shutil.copytree(ROOT / "build", build)
    for pack in ("std-loop", "std-order", "std-decision", "std-access"):
        shutil.copytree(ROOT / "packs" / pack, tmp / "packs" / pack)
    (build / "facts").mkdir(exist_ok=True)
    (build / "facts" / "input.yaml").write_text(yaml.safe_dump(records), encoding="utf-8")
    archive = store.FileStore(tmp / "archive")
    epoch = batch.epoch(build, epoch=1, knowledge_time="2027-01-15T08:00:00Z", sources=[("facts", "input")])
    manifest = publish.publish(epoch, archive, roles)

    def read(entry):
        data = archive.get(entry["uri"].removeprefix(archive.uri("")))
        assert sha256_hex(data) == entry["sha256"]
        return json.loads(data)

    assert any(check["name"] == "rezono:proofs" and check["status"] == "green" for check in manifest["checks"])
    rows_by_role = {role: {} for role in roles}
    for entry in manifest["snapshots"]:
        rows_by_role[entry["role"]][entry["relation"]] = [row["key"] for row in read(entry)]
    witnesses_by_role = {}
    for entry in manifest["witnesses"]:
        doc = read(entry)
        witnesses_by_role[entry["role"]] = {
            (w["conclusion"]["relation"], w["conclusion"]["key"]) for w in doc["witnesses"]
        }
    return rows_by_role, witnesses_by_role


def _progress_base(tmp_path):
    source = tmp_path / "source"
    base, head, paths = repository(source, "decisions/progress.md")
    records = capture(source, base, head, paths)
    records["build_milestone"] = list(MILESTONES)
    return records


def test_pinned_engine_runner_enforces_earlier_main_commit(tmp_path):
    pin_file = ROOT / "build" / "engine-pin.yaml"
    if not pin_file.is_file():
        raise MissingPinnedEngineRunner("build/engine-pin.yaml is missing")
    if find_spec("loop.build_pinned_runner") is None:
        raise MissingPinnedEngineRunner("loop/build_pinned_runner.py is missing")
    from loop.build_pinned_runner import read_engine_pin, validate_engine_pin

    pinned = read_engine_pin(pin_file)
    assert SHA40.fullmatch(pinned), f"build/engine-pin.yaml must pin a 40-lowercase-hex SHA, got {pinned!r}"

    repo = tmp_path / "repo"
    repo.mkdir()
    git(repo, "init", "-q")
    (repo / "README.md").write_text("v1\n", encoding="utf-8")
    git(repo, "add", ".")
    git(repo, "commit", "-qm", "Initial main commit")
    earlier = git(repo, "rev-parse", "HEAD")

    (repo / "README.md").write_text("v2\n", encoding="utf-8")
    git(repo, "add", ".")
    git(repo, "commit", "-qm", "Second main commit")
    main_head = git(repo, "rev-parse", "HEAD")
    git(repo, "update-ref", "refs/remotes/origin/main", main_head)

    (repo / "README.md").write_text("pr change\n", encoding="utf-8")
    git(repo, "add", ".")
    git(repo, "commit", "-qm", "Candidate PR commit")
    candidate = git(repo, "rev-parse", "HEAD")

    git(repo, "checkout", "-q", "-b", "side", earlier)
    (repo / "side.txt").write_text("off main\n", encoding="utf-8")
    git(repo, "add", ".")
    git(repo, "commit", "-qm", "Off-main commit")
    off_main = git(repo, "rev-parse", "HEAD")

    assert validate_engine_pin(root=repo, engine_sha=earlier, candidate_sha=candidate) == {
        "engine_sha": earlier,
        "candidate_sha": candidate,
        "main_ref": "refs/remotes/origin/main",
        "pinned": True,
    }
    assert validate_engine_pin(root=repo, engine_sha=main_head, candidate_sha=candidate)["pinned"] is True

    # Never evaluate a commit with itself, nor with a commit outside main, nor with a malformed SHA.
    for bad_engine, bad_candidate in (
        (candidate, candidate),
        (main_head, main_head),
        (off_main, candidate),
        ("not-a-sha", candidate),
        (earlier, "not-a-sha"),
    ):
        with pytest.raises(ValueError):
            validate_engine_pin(root=repo, engine_sha=bad_engine, candidate_sha=bad_candidate)

    broken = tmp_path / "broken-pin.yaml"
    broken.write_text("engine_sha: short\n", encoding="utf-8")
    with pytest.raises(ValueError):
        read_engine_pin(broken)


def test_ci_selection_cutover_uses_verified_pack_and_fails_closed_to_safe_mode():
    if find_spec("loop.build_cutover") is None:
        raise MissingBuildCutover("loop/build_cutover.py is missing")
    from loop.build_cutover import select_suites

    assert find_spec("loop.build_transition_choice") is None
    assert not (ROOT / "loop" / "build_transition_choice.py").exists()
    assert "python_fallback" not in inspect.signature(select_suites).parameters

    selected_rows = {
        "build_selected_job": _rows(("current", "beta", "change"), ("current", "alpha", "change")),
        "build_full_selection": [],
    }
    direct = select_suites(
        run="current", manifest=GREEN, rows=selected_rows, engine_error=None, universe=UNIVERSE,
    )
    assert direct == {
        "run": "current",
        "source": "pack",
        "safe_mode": False,
        "safe_mode_reason": None,
        "use": ["alpha", "beta"],
        "findings": [],
    }

    # Verified pack full-selection row selects the full universe directly from the pack.
    full_rows = {
        "build_selected_job": selected_rows["build_selected_job"],
        "build_full_selection": _rows(("current", "unmapped.txt")),
    }
    full = select_suites(
        run="current", manifest=GREEN, rows=full_rows, engine_error=None, universe=UNIVERSE,
    )
    assert full == {
        "run": "current",
        "source": "pack",
        "safe_mode": False,
        "safe_mode_reason": None,
        "use": sorted(UNIVERSE),
        "findings": [],
    }

    # Missing, checker-rejected, or engine-failed publications enter fail-closed safe mode:
    # every suite in the universe runs (unknown never leads to less checking, never a Python subset).
    for label, manifest, rows, err, expected_reason in (
        ("missing", None, None, None, "missing-publication"),
        ("rejected", RED_PROOF, selected_rows, None, "invalid-publication"),
        ("empty-checks", {"checks": []}, selected_rows, None, "invalid-publication"),
        ("missing-rel", GREEN, {"build_selected_job": selected_rows["build_selected_job"]}, None, "invalid-publication"),
        ("engine-err", GREEN, selected_rows, "compile failed", "engine-failure"),
    ):
        outcome = select_suites(
            run="current", manifest=manifest, rows=rows, engine_error=err, universe=UNIVERSE,
        )
        assert outcome == {
            "run": "current",
            "source": "safe_mode",
            "safe_mode": True,
            "safe_mode_reason": expected_reason,
            "use": sorted(UNIVERSE),
            "findings": [{
                "kind": "safe_mode",
                "run": "current",
                "surface": "ci_selection",
                "reason": expected_reason,
            }],
        }, label

    with pytest.raises(ValueError):
        select_suites(
            run="current", manifest=GREEN,
            rows={"build_selected_job": _rows(("other", "alpha", "change")), "build_full_selection": []},
            engine_error=None, universe=UNIVERSE,
        )


def test_coordinator_reader_uses_published_relations_and_fails_closed_to_safe_mode():
    if find_spec("loop.build_coordinator_reader") is None:
        raise MissingCoordinatorReader("loop/build_coordinator_reader.py is missing")
    from loop.build_coordinator_reader import read_coordinator_state

    assert "python_fallback" not in inspect.signature(read_coordinator_state).parameters

    claims_rules = (ROOT / "build" / "rules" / "claims.dl").read_text(encoding="utf-8")
    release_rules = (ROOT / "build" / "rules" / "claim_release.dl").read_text(encoding="utf-8")
    for rel in ("build_claim_release_plan", "build_claim_held"):
        assert re.search(rf"(?m)^\.output\s+{rel}\b", claims_rules), f"build/rules/claims.dl must export {rel}"
    for rel in ("build_claim_released", "build_claim_release_discarded", "build_claim_release_pending"):
        assert re.search(rf"(?m)^\.output\s+{rel}\b", release_rules), f"build/rules/claim_release.dl must export {rel}"

    gen = "a" * 40
    published_rows = {
        "build_task_ready": _rows(("current", "task-lang", "ready"), ("current", "task-core", "ready")),
        "build_task_waiting": _rows(("current", "task-wait", "tok-1", "prereq")),
        "build_task_stuck": _rows(("current", "task-stuck", "terminal-refusal")),
        "build_claim_release_plan": _rows(("current", "task/expired", gen, "lease-ended")),
        "build_claim_held": _rows(("current", "task/active", "lease-active")),
    }
    state = read_coordinator_state(
        run="current", manifest=GREEN, rows=published_rows, engine_error=None,
    )
    assert state == {
        "run": "current",
        "source": "pack",
        "safe_mode": False,
        "safe_mode_reason": None,
        "assign_new_tasks": True,
        "ready": [{"task": "task-core", "reason": "ready"}, {"task": "task-lang", "reason": "ready"}],
        "waiting": [{"task": "task-wait", "token": "tok-1", "reason": "prereq"}],
        "stuck": [{"task": "task-stuck", "reason": "terminal-refusal"}],
        "claim_release_plan": [{"claim": "task/expired", "generation": gen, "reason": "lease-ended"}],
        "claim_held": [{"claim": "task/active", "reason": "lease-active"}],
        "findings": [],
    }

    # Absent, checker-rejected, or engine-failed publications enter fail-closed safe mode:
    # claims stay intact (never released), zero new tasks are assigned, and a finding is emitted.
    for label, manifest, rows, err, expected_reason in (
        ("missing", None, None, None, "missing-publication"),
        ("rejected", RED_PROOF, published_rows, None, "invalid-publication"),
        ("empty-checks", {"checks": []}, published_rows, None, "invalid-publication"),
        ("missing-rel", GREEN, {"build_task_ready": published_rows["build_task_ready"]}, None, "invalid-publication"),
        ("engine-err", GREEN, published_rows, "engine crashed", "engine-failure"),
    ):
        out = read_coordinator_state(
            run="current", manifest=manifest, rows=rows, engine_error=err,
        )
        assert out == {
            "run": "current",
            "source": "safe_mode",
            "safe_mode": True,
            "safe_mode_reason": expected_reason,
            "assign_new_tasks": False,
            "ready": [],
            "waiting": [],
            "stuck": [],
            "claim_release_plan": [],
            "claim_held": [],
            "findings": [{
                "kind": "safe_mode",
                "run": "current",
                "surface": "coordinator",
                "reason": expected_reason,
            }],
        }, label

    with pytest.raises(ValueError):
        read_coordinator_state(
            run="current", manifest=GREEN,
            rows=dict(published_rows, build_task_ready=_rows(("other", "task-x", "ready"))),
            engine_error=None,
        )


def test_build_pack_derives_milestone_progress_and_release_1_done_with_proofs(tmp_path):
    required = {"BuildMilestone", "BuildProgressScan", "BuildRedTest", "BuildGreenTransition"}
    if not required <= _declared_kinds():
        raise MissingProgressRelations(f"build/schema lacks {sorted(required - _declared_kinds())}")

    c1, c2 = "1" * 40, "2" * 40

    # Case 1: M2 and M3 still have red tests -> release_1_done must be empty; earlier scan is ignored.
    records = _progress_base(tmp_path / "open")
    records.update({
        "build_progress_scan": [
            {"id": "scan-1", "run": "current", "observed_at": OBSERVED_AT, "source": "git-history"},
            {"id": "scan-old", "run": "current", "observed_at": OBSERVED_AT - 1, "source": "git-history"},
        ],
        "build_green_transition": [
            {"id": "g1", "scan": "scan-1", "test": "t-m1-a", "milestone": "M1", "commit": c1},
            {"id": "g2", "scan": "scan-1", "test": "t-m1-b", "milestone": "M1", "commit": c2},
            {"id": "g3", "scan": "scan-1", "test": "t-m2-a", "milestone": "M2", "commit": c1},
            # Duplicate transition record for the same test counts once.
            {"id": "g4", "scan": "scan-1", "test": "t-m2-a", "milestone": "M2", "commit": c2},
            {"id": "g5", "scan": "scan-1", "test": "t-m3-a", "milestone": "M3", "commit": c2},
            {"id": "g6", "scan": "scan-1", "test": "t-ex-a", "milestone": "extra", "commit": c2},
            {"id": "g-old", "scan": "scan-old", "test": "t-m4-old", "milestone": "M4", "commit": c1},
        ],
        "build_red_test": [
            {"id": "r1", "scan": "scan-1", "test": "t-m2-red", "milestone": "M2"},
            {"id": "r2", "scan": "scan-1", "test": "t-m3-red-1", "milestone": "M3"},
            {"id": "r3", "scan": "scan-1", "test": "t-m3-red-2", "milestone": "M3"},
            {"id": "r4", "scan": "scan-1", "test": "t-ex-red", "milestone": "extra"},
            {"id": "r5", "scan": "scan-1", "test": "t-later-red", "milestone": "later"},
        ],
    })
    rows_by_role, witnesses_by_role = _publish_roles(tmp_path / "pub-open", records, {"reader": "complete"})
    rows = rows_by_role["reader"]
    witnesses = witnesses_by_role["reader"]
    if "build_milestone_progress" not in rows or "release_1_done" not in rows:
        raise MissingProgressRelations("build/rules/progress.dl does not derive build_milestone_progress / release_1_done")

    expected_open = [
        ["current", "M1", "2", "0"],
        ["current", "M2", "1", "1"],
        ["current", "M3", "1", "2"],
        ["current", "M4", "0", "0"],
        ["current", "extra", "1", "1"],
        ["current", "later", "0", "1"],
    ]
    assert sorted(rows["build_milestone_progress"]) == sorted(expected_open)
    assert rows["release_1_done"] == []
    for key in expected_open:
        assert ("build_milestone_progress", canonical_json(key)) in witnesses

    # Case 2: Zero red tests on M1-M4, while extra and later remain red -> release_1_done holds with proof.
    records_done = _progress_base(tmp_path / "done")
    records_done.update({
        "build_progress_scan": [
            {"id": "scan-2", "run": "current", "observed_at": OBSERVED_AT, "source": "git-history"},
        ],
        "build_green_transition": [
            {"id": "gd1", "scan": "scan-2", "test": "t-m1-a", "milestone": "M1", "commit": c1},
            {"id": "gd2", "scan": "scan-2", "test": "t-m4-a", "milestone": "M4", "commit": c2},
        ],
        "build_red_test": [
            {"id": "rd1", "scan": "scan-2", "test": "t-ex-red", "milestone": "extra"},
            {"id": "rd2", "scan": "scan-2", "test": "t-later-red", "milestone": "later"},
        ],
    })
    done_rows, done_witnesses = _publish_roles(tmp_path / "pub-done", records_done, {"reader": "complete"})
    assert done_rows["reader"]["release_1_done"] == [["current", "scan-2"]]
    assert ("release_1_done", canonical_json(["current", "scan-2"])) in done_witnesses["reader"]

    # Case 3: No progress scan at the cut -> neither progress rows nor release_1_done may be derived.
    records_stale = _progress_base(tmp_path / "stale")
    records_stale.update({
        "build_progress_scan": [
            {"id": "scan-old", "run": "current", "observed_at": OBSERVED_AT - 1, "source": "git-history"},
        ],
    })
    stale_rows, _ = _publish_roles(tmp_path / "pub-stale", records_stale, {"reader": "complete"})
    assert stale_rows["reader"]["build_milestone_progress"] == []
    assert stale_rows["reader"]["release_1_done"] == []


def test_build_pack_derives_offboard_work_and_publishes_for_coordinator_and_owner_roles(tmp_path):
    if "BuildOffboardWork" not in _declared_kinds():
        raise MissingOffboardAndRolePublication("build/schema lacks BuildOffboardWork")
    pack_meta = yaml.safe_load((ROOT / "build" / "pack.yaml").read_text(encoding="utf-8"))
    imported = {item["name"] for item in (pack_meta.get("imports") or []) if isinstance(item, dict)}
    if "std-access" not in imported:
        raise MissingOffboardAndRolePublication("build/pack.yaml does not import std-access")
    roles_file = ROOT / "build" / "facts" / "roles.yaml"
    if not roles_file.is_file():
        raise MissingOffboardAndRolePublication("build/facts/roles.yaml is missing")

    records = _progress_base(tmp_path / "src")
    records.update({
        "role": [{"id": "unprivileged", "title": "Unprivileged"}],
        "build_progress_scan": [
            {"id": "scan-1", "run": "current", "observed_at": OBSERVED_AT, "source": "progress-scanner"},
        ],
        "build_green_transition": [
            {"id": "g1", "scan": "scan-1", "test": "t-m1-a", "milestone": "M1", "commit": "3" * 40},
        ],
        "build_red_test": [
            {"id": "r1", "scan": "scan-1", "test": "t-extra-1", "milestone": "extra"},
        ],
        "build_offboard_work": [
            {
                "id": "off-1",
                "scan": "scan-1",
                "item": "rezono-1-migration",
                "state": "known",
                "completed": 0,
                "total": 14,
                "source": "language-usage-scan",
            },
            {
                "id": "off-2",
                "scan": "scan-1",
                "item": "release-signoff",
                "state": "unknown",
                "reason": "no-automated-observer",
                "source": "release-checklist",
            },
            {
                "id": "off-3",
                "scan": "scan-1",
                "item": "docs-audit",
                "state": "known",
                "completed": 5,
                "total": 3,
                "source": "audit-script",
            },
        ],
    })

    roles = {"coordinator": "may_read", "owner": "may_read", "unprivileged": "may_read"}
    rows_by_role, witnesses_by_role = _publish_roles(tmp_path / "pub", records, roles)

    expected_counts = [["current", "rezono-1-migration", "0", "14", "14"]]
    expected_unknown = sorted([
        ["current", "release-signoff", "no-automated-observer"],
        ["current", "docs-audit", "incomplete-observation"],
    ])
    expected_done = [["current", "scan-1"]]

    for role in ("coordinator", "owner"):
        r = rows_by_role[role]
        w = witnesses_by_role[role]
        if "build_offboard_work_count" not in r or "build_offboard_work_unknown" not in r:
            raise MissingOffboardAndRolePublication(f"role {role} lacks off-board work relations")
        assert r["build_offboard_work_count"] == expected_counts
        assert sorted(r["build_offboard_work_unknown"]) == expected_unknown
        assert r["release_1_done"] == expected_done
        assert len(r["build_milestone_progress"]) == 6
        for rel, expected in (
            ("build_offboard_work_count", expected_counts),
            ("build_offboard_work_unknown", expected_unknown),
            ("release_1_done", expected_done),
        ):
            for key in expected:
                assert (rel, canonical_json(key)) in w, (role, rel, key)

    denied = rows_by_role["unprivileged"]
    for rel in (
        "build_milestone_progress",
        "release_1_done",
        "build_offboard_work_count",
        "build_offboard_work_unknown",
    ):
        assert denied.get(rel, []) == [], (rel, denied.get(rel))
