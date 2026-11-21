"""Decision-driven work: red-mark decision citations, open/untested/done relations, and coordinator reader.

The expectations are worked by hand from decisions/decision-driven-work.md:
- section 1: scripts/red_guard.py requires every added or edited red mark to cite an existing headed decision
  right after its milestone prefix, under a monotonically shrinking loop/red-decision-budget.json;
- section 2: build/rules/decision_rules.dl derives build_decision_open, build_decision_open_test,
  build_decision_untested and build_decision_done over the same cut scan as build_red_cites_replaced and
  build_uncited_decision, leaving unscanned and headless decisions unknown (never done);
- section 3: loop/build_decision_work.py exposes read_decision_work and prioritize_headless_decisions for the
  coordinator.
"""
from importlib.util import find_spec
import inspect
import json
from pathlib import Path
import subprocess
import sys

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT / "scripts") not in sys.path:
    sys.path.insert(0, str(ROOT / "scripts"))

GREEN_MANIFEST = {
    "checks": [
        {"name": "rezono:proofs", "status": "green"},
        {"name": "rezono:schema", "status": "green"},
    ]
}
RED_MANIFEST = {
    "checks": [
        {"name": "rezono:proofs", "status": "red"},
        {"name": "rezono:schema", "status": "green"},
    ]
}

HEADED_DECISION = """---
decider: [loop]
decided_on: 2026-11-20
valid_from: 2026-11-20
state: in_force
subject: sample-rule
---

# Sample headed decision

This decision has a valid YAML head.
"""

HEADLESS_DECISION = "# Legacy decision without a head\n\nStill waiting for a track to add its head.\n"

BROKEN_DECISION = HEADED_DECISION.replace("decided_on: 2026-11-20", 'decided_on: "2026-11-20"')


class MissingRedDecisionGuard(AssertionError):
    """scripts/red_guard.py or loop/red-decision-budget.json does not enforce headed-decision citations yet."""


class MissingDecisionStatusRules(AssertionError):
    """The build pack does not yet derive build_decision_open, build_decision_untested and build_decision_done."""


class MissingDecisionWorkReader(AssertionError):
    """loop/build_decision_work.py does not yet expose the coordinator reader or headless priority order."""


def _declared_kinds() -> set[str]:
    return {
        name
        for path in sorted((ROOT / "build" / "schema").glob("*.yaml"))
        for name in (yaml.safe_load(path.read_text(encoding="utf-8")).get("classes") or {})
    }


def _rows(*keys: tuple[str, ...]) -> list[dict[str, list[str]]]:
    return [{"key": list(key)} for key in keys]


def _budget_bytes(entries: list[str]) -> bytes:
    return (json.dumps(sorted(entries), indent=2) + "\n").encode("utf-8")


def _git(root: Path, *args: str) -> str:
    return subprocess.check_output(
        [
            "git",
            "-c",
            "core.autocrlf=false",
            "-c",
            "user.name=Test",
            "-c",
            "user.email=test@example.org",
            "-c",
            "commit.gpgsign=false",
            *args,
        ],
        cwd=root,
        text=True,
        stderr=subprocess.PIPE,
    ).strip()


def _write_files(root: Path, files: dict[str, str]) -> None:
    for rel, text in files.items():
        path = root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8", newline="\n")


def test_red_guard_refuses_new_or_edited_red_mark_without_headed_decision_and_shrinks_budget(tmp_path):
    import red_guard
    import red_list

    budget_path = ROOT / "loop" / "red-decision-budget.json"
    if not budget_path.is_file():
        raise MissingRedDecisionGuard("loop/red-decision-budget.json does not exist")
    for attr in ("RED_DECISION_BUDGET", "decision_citation", "has_valid_decision_head"):
        if not hasattr(red_guard, attr):
            raise MissingRedDecisionGuard(f"scripts/red_guard.py lacks {attr}")
    if "head_tree" not in inspect.signature(red_guard.review).parameters:
        raise MissingRedDecisionGuard("scripts/red_guard.py review() does not accept head_tree")

    assert red_guard.RED_DECISION_BUDGET == "loop/red-decision-budget.json"

    # Repository budget format and full coverage of current uncited red marks.
    raw_budget = budget_path.read_text(encoding="utf-8")
    budget_entries = json.loads(raw_budget)
    assert isinstance(budget_entries, list) and all(isinstance(item, str) for item in budget_entries)
    assert raw_budget == json.dumps(sorted(set(budget_entries)), indent=2) + "\n"

    uncited_in_repo: set[str] = set()
    for test_file in red_list.iter_python_test_files(ROOT):
        rel = test_file.relative_to(ROOT).as_posix()
        inv = red_guard.inventory(test_file.read_bytes())
        for owner, mark in inv.marks:
            cited = red_guard.decision_citation(mark)
            if cited is None:
                uncited_in_repo.add(f"{rel}::{owner}")
                continue
            decision_file = ROOT / cited
            if not decision_file.is_file() or not red_guard.has_valid_decision_head(decision_file.read_bytes()):
                uncited_in_repo.add(f"{rel}::{owner}")
    assert sorted(uncited_in_repo - set(budget_entries)) == []

    # Direct review() checks with an isolated Tree.
    head_tree = red_guard.Tree.of(
        {
            "decisions/headed.md": HEADED_DECISION.encode("utf-8"),
            "decisions/headless.md": HEADLESS_DECISION.encode("utf-8"),
            "decisions/broken.md": BROKEN_DECISION.encode("utf-8"),
        }
    )

    def test_src(reason: str) -> bytes:
        return (
            "import pytest\n\n"
            "@" + f'pytest.mark.xfail(strict=True, reason="{reason}")\n'
            "def test_case():\n"
            "    assert False\n"
        ).encode("utf-8")

    # Reject added red marks without a valid headed decision right after the milestone prefix.
    for bad_reason in (
        "M3: missing decision citation",
        "extra: decisions/nonexistent.md: missing file",
        "extra: decisions/headless.md: exists without head",
        "M3: decisions/broken.md: malformed head",
        "M3: mentions decisions/headed.md too late in sentence",
    ):
        change = red_guard.Change("loop/tests/test_new.py", "A", None, test_src(bad_reason))
        errors, _ = red_guard.review([change], planner=True, head_tree=head_tree)
        assert errors, f"expected refusal for {bad_reason!r}"

    # Accept added red marks naming an existing headed decision immediately after the milestone prefix.
    for good_reason in (
        "M3: decisions/headed.md: section 1.",
        "extra: decisions/headed.md: section 2.",
    ):
        change = red_guard.Change("loop/tests/test_new.py", "A", None, test_src(good_reason))
        errors, _ = red_guard.review([change], planner=True, head_tree=head_tree)
        assert errors == [], f"unexpected error for {good_reason!r}: {errors}"

    # Editing an existing legacy red mark's reason must add a valid headed decision (with or without planner).
    legacy = test_src("M3: legacy uncited reason")
    for edited_bad in (
        test_src("M3: rewritten still without decision"),
        test_src("M3: decisions/headless.md: still headless"),
    ):
        for planner_flag in (False, True):
            errors, _ = red_guard.review(
                [red_guard.Change("loop/tests/test_legacy.py", "M", legacy, edited_bad)],
                planner=planner_flag,
                head_tree=head_tree,
            )
            assert errors, f"expected refusal on edited reason (planner={planner_flag})"

    edited_good = test_src("M3: decisions/headed.md: now cites headed decision")
    for planner_flag in (False, True):
        errors, _ = red_guard.review(
            [red_guard.Change("loop/tests/test_legacy.py", "M", legacy, edited_good)],
            planner=planner_flag,
            head_tree=head_tree,
        )
        assert errors == [], f"unexpected error when adding valid citation (planner={planner_flag}): {errors}"

    # Leaving a pre-existing uncited mark untouched while adding a properly cited test stays green.
    second_test = (
        legacy
        + b"\n"
        + b"@"
        + b'pytest.mark.xfail(strict=True, reason="extra: decisions/headed.md: second test")\n'
        + b"def test_second():\n    assert False\n"
    )
    errors, _ = red_guard.review(
        [red_guard.Change("loop/tests/test_legacy.py", "M", legacy, second_test)],
        planner=True,
        head_tree=head_tree,
    )
    assert errors == [], f"untouched legacy mark should stay green: {errors}"

    # Monotonically shrinking loop/red-decision-budget.json.
    before_budget = _budget_bytes(["loop/tests/test_legacy.py::test_case", "loop/tests/test_other.py::test_other"])
    shrunk_budget = _budget_bytes(["loop/tests/test_other.py::test_other"])
    grown_budget = _budget_bytes(
        [
            "loop/tests/test_added.py::test_added",
            "loop/tests/test_legacy.py::test_case",
            "loop/tests/test_other.py::test_other",
        ]
    )
    unsorted_budget = b'[\n  "loop/tests/test_other.py::test_other",\n  "loop/tests/test_legacy.py::test_case"\n]\n'

    # Shrinking the budget is allowed on its own and alongside lifting the red mark, even without planner.
    lifted = b"import pytest\n\ndef test_case():\n    assert False\n"
    for planner_flag in (False, True):
        errors, _ = red_guard.review(
            [
                red_guard.Change("loop/tests/test_legacy.py", "M", legacy, lifted),
                red_guard.Change("loop/red-decision-budget.json", "M", before_budget, shrunk_budget),
            ],
            planner=planner_flag,
            head_tree=head_tree,
        )
        assert errors == [], f"shrinking budget alongside lift failed (planner={planner_flag}): {errors}"

    # Growing or misformatting the budget is always refused.
    for bad_budget in (grown_budget, unsorted_budget):
        for planner_flag in (False, True):
            errors, _ = red_guard.review(
                [red_guard.Change("loop/red-decision-budget.json", "M", before_budget, bad_budget)],
                planner=planner_flag,
                head_tree=head_tree,
            )
            assert errors, f"expected refusal for bad budget (planner={planner_flag})"

    # End-to-end isolated stdlib CLI check (`python -I scripts/red_guard.py --planner base head`).
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-q")
    _write_files(
        repo,
        {
            "decisions/headed.md": HEADED_DECISION,
            "decisions/headless.md": HEADLESS_DECISION,
            "loop/red-decision-budget.json": "[]\n",
        },
    )
    _git(repo, "add", ".")
    _git(repo, "commit", "-qm", "Base")
    base = _git(repo, "rev-parse", "HEAD")

    _write_files(repo, {"loop/tests/test_cli.py": test_src("extra: decisions/headless.md: no head").decode("utf-8")})
    _git(repo, "add", ".")
    _git(repo, "commit", "-qm", "Add uncited red test")
    bad_head = _git(repo, "rev-parse", "HEAD")

    res_bad = subprocess.run(
        [sys.executable, "-I", str(ROOT / "scripts" / "red_guard.py"), "--planner", base, bad_head],
        cwd=repo,
        capture_output=True,
        text=True,
    )
    assert res_bad.returncode != 0, f"CLI should refuse headless decision citation: {res_bad.stdout}"

    _git(repo, "reset", "--hard", base)
    _write_files(repo, {"loop/tests/test_cli.py": test_src("extra: decisions/headed.md: ok").decode("utf-8")})
    _git(repo, "add", ".")
    _git(repo, "commit", "-qm", "Add cited red test")
    good_head = _git(repo, "rev-parse", "HEAD")

    res_good = subprocess.run(
        [sys.executable, "-I", str(ROOT / "scripts" / "red_guard.py"), "--planner", base, good_head],
        cwd=repo,
        capture_output=True,
        text=True,
    )
    assert res_good.returncode == 0, f"CLI should allow headed decision citation: {res_good.stdout}\n{res_good.stderr}"


def test_build_pack_derives_decision_open_untested_done_and_keeps_missing_scan_unknown(tmp_path):
    kinds = {"BuildCitationScan", "BuildDecisionCitation", "BuildRedCitation"}
    if not kinds <= _declared_kinds():
        raise MissingDecisionStatusRules(f"build/schema lacks {sorted(kinds - _declared_kinds())}")

    from test_build_selection import OBSERVED_AT, capture, published, repository

    def make_decision(name: str, day: str | None, state: str, **fields):
        row = {
            "id": name,
            "title": f"Decision {name}",
            "subject": "work-rules",
            "decider": ["loop"],
            "state": state,
            **fields,
        }
        if day is not None:
            iso = f"{day[:4]}-{day[4:6]}-{day[6:]}"
            row.update({"decided_on": iso, "valid_from": iso, "valid_from_day": int(day)})
        return row

    decisions = [
        make_decision("old-rule", "20260101", "superseded"),
        make_decision("d-done", "20260601", "in_force", supersedes=["old-rule"]),
        make_decision("d-open", "20260601", "in_force"),
        make_decision("d-doc-only", "20260601", "in_force"),
        make_decision("d-lone", "20260601", "in_force"),
        make_decision("late-rule", "20270601", "in_force"),
        make_decision("draft-rule", None, "proposed"),
    ]

    def run_pack(folder: Path, scans: dict[str, int], citations=(), red=(), *, valid_receipt: bool = True):
        folder.mkdir(parents=True, exist_ok=True)
        source = folder / "source"
        base, head, paths = repository(source, "decisions/work-rules.md")
        records = capture(source, base, head, paths)
        if not valid_receipt:
            records["loop_sweep_receipt"][0]["event_time"] = OBSERVED_AT - 1
        records.update(
            {
                "reference_date": [{"id": "policy-day", "title": "Observed reference day",
                                    "date": "2027-01-15", "day": 20270115}],
                "build_policy_date": [
                    {"id": "policy-cut", "run": "current", "reference": "policy-day", "observed_at": OBSERVED_AT}
                ],
                "subject": [{"id": "work-rules", "title": "work-rules"}],
                "decision": decisions,
                "build_citation_scan": [
                    {"id": scan, "run": "current", "observed_at": tick, "source": "tree"}
                    for scan, tick in scans.items()
                ],
            }
        )
        if citations:
            records["build_decision_citation"] = [
                {"id": f"cites-{idx}", "scan": scan, "path": path, "decision": name}
                for idx, (scan, path, name) in enumerate(citations)
            ]
        if red:
            records["build_red_citation"] = [
                {"id": f"red-{idx}", "scan": scan, "test": test, "decision": name}
                for idx, (scan, test, name) in enumerate(red)
            ]
        return published(folder, records)

    citations = [
        # alpha/test_unit.py and beta/test_unit.py are BuildTestFile entries of "current" from capture().
        ("at-cut", "alpha/test_unit.py", "d-done"),
        ("at-cut", "beta/test_unit.py", "d-open"),
        # handbook/hours.md is NOT a BuildTestFile: d-doc-only is cited by docs, yet still untested.
        ("at-cut", "handbook/hours.md", "d-doc-only"),
        # Earlier scan citations must never leak into the cut.
        ("earlier", "alpha/test_unit.py", "d-lone"),
    ]
    red = [
        ("at-cut", "beta/test_unit.py--test_one", "d-open"),
        ("at-cut", "beta/test_unit.py--test_two", "d-open"),
        # Earlier red citation must not make d-done open at the cut.
        ("earlier", "alpha/test_unit.py--test_old_red", "d-done"),
    ]
    rows = run_pack(
        tmp_path / "scanned",
        {"at-cut": OBSERVED_AT, "earlier": OBSERVED_AT - 1},
        citations=citations,
        red=red,
    )

    required = (
        "build_decision_open",
        "build_decision_open_test",
        "build_decision_untested",
        "build_decision_done",
    )
    missing = [name for name in required if name not in rows]
    if missing:
        raise MissingDecisionStatusRules(f"build/rules does not derive {missing}")

    assert sorted(row["key"] for row in rows["build_decision_open"]) == [["current", "d-open"]]
    assert sorted(row["key"] for row in rows["build_decision_open_test"]) == [
        ["current", "d-open", "beta/test_unit.py--test_one"],
        ["current", "d-open", "beta/test_unit.py--test_two"],
    ]
    assert sorted(row["key"] for row in rows["build_decision_untested"]) == [
        ["current", "d-doc-only"],
        ["current", "d-lone"],
    ]
    assert sorted(row["key"] for row in rows["build_decision_done"]) == [["current", "d-done"]]

    # Narrower than build_uncited_decision: d-doc-only is cited by docs so it is not uncited, yet it is untested.
    if "build_uncited_decision" in rows:
        uncited = {row["key"][1] for row in rows["build_uncited_decision"]}
        assert "d-doc-only" not in uncited and "d-lone" in uncited

    # Missing-scan safety: without a scan at the cut tick, emit NO rows — every decision remains unknown, never done.
    unscanned = run_pack(
        tmp_path / "unscanned",
        {"earlier": OBSERVED_AT - 1},
        citations=[("earlier", "alpha/test_unit.py", "d-done")],
        red=[("earlier", "beta/test_unit.py--test_one", "d-open")],
    )
    for relation in required:
        assert unscanned.get(relation, []) == [], f"{relation} must stay empty without a cut scan"

    # Unverified cut safety: stale sweep receipt yields NO status rows.
    unverified = run_pack(
        tmp_path / "unverified",
        {"at-cut": OBSERVED_AT},
        citations=citations[:3],
        red=red[:2],
        valid_receipt=False,
    )
    for relation in required:
        assert unverified.get(relation, []) == [], f"{relation} must stay empty without a verified cut"

    labels = yaml.safe_load((ROOT / "build" / "labels" / "en.yaml").read_text(encoding="utf-8"))
    for relation in required:
        assert isinstance(labels.get(relation), str) and labels[relation].strip(), f"missing label for {relation}"


def test_coordinator_reader_surfaces_open_and_untested_decisions_with_reason_chain(tmp_path):
    if find_spec("loop.build_decision_work") is None:
        raise MissingDecisionWorkReader("loop/build_decision_work.py does not exist")
    from loop import build_decision_work

    for name in ("read_decision_work", "prioritize_headless_decisions"):
        if not hasattr(build_decision_work, name):
            raise MissingDecisionWorkReader(f"loop/build_decision_work.py lacks {name}")

    read_decision_work = build_decision_work.read_decision_work
    prioritize_headless_decisions = build_decision_work.prioritize_headless_decisions

    published_rows = {
        "build_decision_open": _rows(("current", "d-open")),
        "build_decision_open_test": _rows(
            ("current", "d-open", "loop/tests/test_work.py--test_b"),
            ("current", "d-open", "loop/tests/test_work.py--test_a"),
        ),
        "build_decision_untested": _rows(("current", "d-untested")),
        "build_decision_done": _rows(("current", "d-done")),
    }
    work = read_decision_work(
        run="current",
        manifest=GREEN_MANIFEST,
        rows=published_rows,
        headless_decisions=("decisions/headless-one.md",),
        known_decisions=("d-open", "d-untested", "d-done", "d-unscanned"),
    )
    assert work["run"] == "current"
    assert work["verified"] is True
    assert work["open"] == ["d-open"]
    assert work["untested"] == ["d-untested"]
    assert work["done"] == ["d-done"]
    assert work["unknown"] == ["d-unscanned", "headless-one"]
    assert "headless-one" not in work["done"]
    assert work["progress"] == {"open": 1, "untested": 1, "done": 1, "unknown": 2}

    assert work["worker_tasks"] == [
        {
            "role": "worker",
            "status": "open",
            "decision": "d-open",
            "decision_path": "decisions/d-open.md",
            "test": "loop/tests/test_work.py--test_a",
            "reason": "decisions/d-open.md -> loop/tests/test_work.py--test_a",
        },
        {
            "role": "worker",
            "status": "open",
            "decision": "d-open",
            "decision_path": "decisions/d-open.md",
            "test": "loop/tests/test_work.py--test_b",
            "reason": "decisions/d-open.md -> loop/tests/test_work.py--test_b",
        },
    ]
    assert len(work["planner_tasks"]) == 1
    planner_task = work["planner_tasks"][0]
    assert planner_task["role"] == "planner"
    assert planner_task["status"] == "untested"
    assert planner_task["decision"] == "d-untested"
    assert planner_task["decision_path"] == "decisions/d-untested.md"
    assert planner_task["test"] is None
    assert "decisions/d-untested.md" in planner_task["reason"]

    # Missing scan (empty published status relations): everything remains unknown, NEVER done.
    empty_rows = {name: [] for name in published_rows}
    unscanned = read_decision_work(
        run="current",
        manifest=GREEN_MANIFEST,
        rows=empty_rows,
        headless_decisions=("decisions/headless-one.md",),
        known_decisions=("d-done", "d-open"),
    )
    assert unscanned["verified"] is True
    assert unscanned["worker_tasks"] == []
    assert unscanned["planner_tasks"] == []
    assert unscanned["done"] == []
    assert unscanned["unknown"] == ["d-done", "d-open", "headless-one"]
    assert unscanned["progress"] == {"open": 0, "untested": 0, "done": 0, "unknown": 3}

    # Missing or red publication: fail closed, never report done.
    for bad_manifest, bad_rows in (
        (None, published_rows),
        (GREEN_MANIFEST, None),
        (RED_MANIFEST, published_rows),
        (GREEN_MANIFEST, {"build_decision_open": published_rows["build_decision_open"]}),
    ):
        failed = read_decision_work(
            run="current",
            manifest=bad_manifest,
            rows=bad_rows,
            headless_decisions=("decisions/headless-one.md",),
            known_decisions=("d-done",),
        )
        assert failed["verified"] is False
        assert failed["worker_tasks"] == []
        assert failed["planner_tasks"] == []
        assert failed["done"] == []
        assert failed["unknown"] == ["d-done", "headless-one"]

    # Reject foreign run, open decision missing witness edge, or headless decision marked done.
    with pytest.raises(ValueError):
        read_decision_work(
            run="current",
            manifest=GREEN_MANIFEST,
            rows={**published_rows, "build_decision_done": _rows(("other-run", "d-done"))},
        )
    with pytest.raises(ValueError):
        read_decision_work(
            run="current",
            manifest=GREEN_MANIFEST,
            rows={**published_rows, "build_decision_open_test": []},
        )
    with pytest.raises(ValueError):
        read_decision_work(
            run="current",
            manifest=GREEN_MANIFEST,
            rows={**published_rows, "build_decision_done": _rows(("current", "headless-one"))},
            headless_decisions=("decisions/headless-one.md",),
        )

    # Priority ordering for working down loop/decision-head-budget.json.
    tree = tmp_path / "tree"
    _write_files(
        tree,
        {
            "decisions/headed-a.md": HEADED_DECISION
            + "\nSee [headless-headed](headless-headed.md) and decisions/headless-both.md.\n",
            "decisions/headless-both.md": HEADLESS_DECISION,
            "decisions/headless-red.md": HEADLESS_DECISION,
            "decisions/headless-headed.md": HEADLESS_DECISION,
            "decisions/headless-plain.md": HEADLESS_DECISION,
        },
    )
    budget = [
        "decisions/headless-both.md",
        "decisions/headless-headed.md",
        "decisions/headless-plain.md",
        "decisions/headless-red.md",
    ]
    red_tests = [
        {"id": "loop/tests/test_a.py--test_1", "reason": "M3: decisions/headless-red.md: first"},
        {"id": "loop/tests/test_a.py--test_2", "reason": "M3: decisions/headless-red.md: second"},
        {"id": "loop/tests/test_b.py--test_1", "reason": "extra: decisions/headless-both.md: one"},
    ]
    ranked = prioritize_headless_decisions(tree, budget, red_tests)
    assert [item["path"] for item in ranked] == [
        "decisions/headless-red.md",
        "decisions/headless-both.md",
        "decisions/headless-headed.md",
        "decisions/headless-plain.md",
    ]
    assert [item["tier"] for item in ranked] == ["red-cited", "red-cited", "headed-cited", "other"]
    assert ranked[0]["red_tests"] == ["loop/tests/test_a.py--test_1", "loop/tests/test_a.py--test_2"]
    assert ranked[1]["red_tests"] == ["loop/tests/test_b.py--test_1"]
    assert ranked[1]["headed_decisions"] == ["headed-a"]
    assert ranked[2]["headed_decisions"] == ["headed-a"]
    assert ranked[3]["red_tests"] == [] and ranked[3]["headed_decisions"] == []
