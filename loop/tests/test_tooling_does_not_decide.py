"""Tooling and CI decisions move into five shared pack forms with no Python fallback:
decisions/tooling-does-not-decide.md.

One structural test verifies that every non-test Python script in scripts/ and the workflow `if:`
groups are audited in decisions/tooling-does-not-decide.md. Seven strict `extra:` red tests state
the independent, hand-worked contracts for the five shared decision forms, the components.py-to-
build/ graph migration, and pack-fact pin exceptions.
"""
import ast
import importlib.util
from pathlib import Path
import re
import shutil
import subprocess
import sys

import pytest

from pack_records import LOOP, PACKS, evaluate

ROOT = Path(__file__).resolve().parents[2]
DECISION = ROOT / "decisions" / "tooling-does-not-decide.md"
BUILD = ROOT / "build"
REVIEW = PACKS / "std-review"
ACCESS = PACKS / "std-access"
BUDGET = PACKS / "std-budget"

FATE_MARKER = re.compile(r"\((?:a|b|c|d)\)")


def _table_rows(text: str) -> list[list[str]]:
    rows = []
    for line in text.splitlines():
        if not line.startswith("|"):
            continue
        cells = [cell.strip() for cell in re.split(r"(?<!\\)\|", line.strip("|"))]
        if cells and not all(set(cell) <= {"-", ":", " "} for cell in cells):
            rows.append(cells)
    return rows


def test_every_script_and_workflow_if_is_audited_in_tooling_decision():
    """Every non-test script in scripts/ and every audited workflow `if:` group has a valid fate."""
    assert DECISION.is_file(), "decisions/tooling-does-not-decide.md is missing"
    text = DECISION.read_text(encoding="utf-8")
    assert text.startswith("---\n"), "decision must start with a YAML head"

    rows = _table_rows(text)
    script_fates = {}
    for cells in rows:
        if len(cells) >= 3 and (cells[0].startswith("`scripts/") or cells[0].startswith("`loop/cluster/")):
            name = cells[0].split("`")[1]
            script_fates[name] = cells[2]

    non_test_scripts = sorted(
        f"scripts/{path.name}"
        for path in (ROOT / "scripts").glob("*.py")
        if not path.name.startswith("test_")
    )
    required_audited = [*non_test_scripts, "loop/cluster/base_check.py"]
    assert non_test_scripts, "expected non-test Python scripts under scripts/"
    missing_scripts = [name for name in required_audited if name not in script_fates]
    assert missing_scripts == [], f"scripts missing from audit table: {missing_scripts}"
    bad_script_fates = [name for name in required_audited if not FATE_MARKER.search(script_fates[name])]
    assert bad_script_fates == [], f"scripts without a valid fate (a)-(d): {bad_script_fates}"

    workflow_section = text.split("## 4. Audit table:", 1)[1].split("## 5.", 1)[0]
    workflow_rows = [cells for cells in _table_rows(workflow_section) if len(cells) >= 4 and cells[0] != "Workflow `if:` group"]
    assert len(workflow_rows) >= 8, "expected all logical workflow `if:` groups in section 4"
    bad_workflow_fates = [cells[0] for cells in workflow_rows if not FATE_MARKER.search(cells[3])]
    assert bad_workflow_fates == [], f"workflow groups without a valid fate (a)-(d): {bad_workflow_fates}"

    lower = text.lower()
    assert "no python fallback" in lower, "decision must forbid runtime Python fallback"
    assert "fail-closed" in lower, "decision must state the fail-closed safe state"


def test_monotonically_shrinking_budget_shared_form():
    """Form 1: packs/std-budget derives budget_raised, budget_exceeded, budget_ratchet_violation and budget_slack."""
    from rezono_compiler import pack, rules

    assert (BUDGET / "pack.yaml").is_file(), "packs/std-budget does not exist yet"
    model = pack.read(BUDGET)
    required = {"budget_raised", "budget_exceeded", "budget_ratchet_violation", "budget_slack"}
    missing = required - set(rules.load(model.rules).derived())
    assert not missing, f"packs/std-budget does not derive {sorted(missing)}"

    data = {
        "budget_entry": [
            {"id": "b-steady", "budget": "docs", "cell": "steady", "ceiling": 3, "revision": "base"},
            {"id": "h-steady", "budget": "docs", "cell": "steady", "ceiling": 3, "revision": "head"},
            {"id": "b-raised", "budget": "docs", "cell": "raised", "ceiling": 2, "revision": "base"},
            {"id": "h-raised", "budget": "docs", "cell": "raised", "ceiling": 3, "revision": "head"},
            {"id": "h-new", "budget": "docs", "cell": "new-cell", "ceiling": 1, "revision": "head"},
            {"id": "b-over", "budget": "docs", "cell": "exceeded", "ceiling": 2, "revision": "base"},
            {"id": "h-over", "budget": "docs", "cell": "exceeded", "ceiling": 2, "revision": "head"},
            {"id": "b-slack", "budget": "docs", "cell": "slack-abuse", "ceiling": 5, "revision": "base"},
            {"id": "h-slack", "budget": "docs", "cell": "slack-abuse", "ceiling": 5, "revision": "head"},
            {"id": "b-lower", "budget": "docs", "cell": "lowered", "ceiling": 4, "revision": "base"},
            {"id": "h-lower", "budget": "docs", "cell": "lowered", "ceiling": 4, "revision": "head"},
        ],
        "budget_reading": [
            {"id": "rb-steady", "budget": "docs", "cell": "steady", "observed": 3, "revision": "base"},
            {"id": "rh-steady", "budget": "docs", "cell": "steady", "observed": 3, "revision": "head"},
            {"id": "rb-raised", "budget": "docs", "cell": "raised", "observed": 2, "revision": "base"},
            {"id": "rh-raised", "budget": "docs", "cell": "raised", "observed": 2, "revision": "head"},
            {"id": "rh-new", "budget": "docs", "cell": "new-cell", "observed": 1, "revision": "head"},
            {"id": "rb-over", "budget": "docs", "cell": "exceeded", "observed": 2, "revision": "base"},
            {"id": "rh-over", "budget": "docs", "cell": "exceeded", "observed": 3, "revision": "head"},
            {"id": "rb-slack", "budget": "docs", "cell": "slack-abuse", "observed": 2, "revision": "base"},
            {"id": "rh-slack", "budget": "docs", "cell": "slack-abuse", "observed": 3, "revision": "head"},
            {"id": "rb-lower", "budget": "docs", "cell": "lowered", "observed": 4, "revision": "base"},
            {"id": "rh-lower", "budget": "docs", "cell": "lowered", "observed": 2, "revision": "head"},
        ],
    }
    _, rows, _ = evaluate(model, data)
    assert rows["budget_raised"] == {("docs", "raised"), ("docs", "new-cell")}
    assert rows["budget_exceeded"] == {("docs", "exceeded")}
    assert rows["budget_ratchet_violation"] == {("docs", "new-cell"), ("docs", "exceeded"), ("docs", "slack-abuse")}
    assert rows["budget_slack"] == {("docs", "slack-abuse"), ("docs", "lowered")}


def _declared_in_pack_sources(pack_dir: Path, names: set[str]) -> set[str]:
    """Return which relation names from `names` appear in the pack's own .dl or .rezono rule sources."""
    sources = "\n".join(
        path.read_text(encoding="utf-8")
        for pattern in ("rules/*.dl", "rezono/**/*.rezono")
        for path in sorted(pack_dir.glob(pattern))
    )
    return {name for name in names if re.search(rf"\b{re.escape(name)}\b", sources)}


def test_commit_pinned_evidence_shared_form():
    """Form 2: packs/std-review derives evidence_current, evidence_stale and evidence_missing per commit SHA."""
    from rezono_compiler import pack, rules

    required = {"evidence_current", "evidence_stale", "evidence_missing"}
    missing_sources = required - _declared_in_pack_sources(REVIEW, required)
    assert not missing_sources, f"packs/std-review does not declare {sorted(missing_sources)}"
    model = pack.read(REVIEW)
    missing = required - set(rules.load(model.rules).derived())
    assert not missing, f"packs/std-review does not derive {sorted(missing)}"

    sha_a, sha_b, sha_c, sha_d = "a" * 40, "b" * 40, "c" * 40, "d" * 40
    data = {
        "change": [
            {"id": "pr-1", "author": "alice", "content_sha256": sha_a, "support_sha256": sha_a},
            {"id": "pr-2", "author": "alice", "content_sha256": sha_b, "support_sha256": sha_b},
            {"id": "pr-3", "author": "alice", "content_sha256": sha_c, "support_sha256": sha_c},
            {"id": "pr-4", "author": "alice", "content_sha256": sha_d, "support_sha256": sha_d},
        ],
        "evidence_requirement": [
            {"id": "req-1", "change": "pr-1", "evidence_kind": "feldera-oracle", "commit_sha": sha_a},
            {"id": "req-2", "change": "pr-2", "evidence_kind": "p1-read", "commit_sha": sha_b},
            {"id": "req-3", "change": "pr-3", "evidence_kind": "red-before", "commit_sha": sha_c},
            {"id": "req-4", "change": "pr-4", "evidence_kind": "role-publication", "commit_sha": sha_d},
        ],
        "evidence_attestation": [
            {"id": "att-1", "change": "pr-1", "evidence_kind": "feldera-oracle", "commit_sha": sha_a,
             "outcome": "passed", "source": "run-101"},
            {"id": "att-2-old", "change": "pr-2", "evidence_kind": "p1-read", "commit_sha": sha_a,
             "outcome": "passed", "source": "label-old"},
            {"id": "att-3-ok", "change": "pr-3", "evidence_kind": "red-before", "commit_sha": sha_c,
             "outcome": "passed", "source": "run-301"},
            {"id": "att-3-bad", "change": "pr-3", "evidence_kind": "red-before", "commit_sha": sha_c,
             "outcome": "failed", "source": "run-302"},
        ],
    }
    _, rows, _ = evaluate(model, data)
    assert rows["evidence_current"] == {("pr-1", "feldera-oracle", sha_a)}
    assert rows["evidence_stale"] == {("pr-2", "p1-read", sha_b)}
    assert rows["evidence_missing"] == {
        ("pr-2", "p1-read", sha_b),
        ("pr-3", "red-before", sha_c),
        ("pr-4", "role-publication", sha_d),
    }


def test_change_to_target_selection_shared_form():
    """Form 3: build/ derives build_target_selected and build_target_not_required, failing closed without a receipt."""
    from rezono_compiler import pack, rules

    model = pack.read(BUILD)
    required = {"build_target_selected", "build_target_not_required"}
    missing = required - set(rules.load(model.rules).derived())
    assert not missing, f"build/ does not derive {sorted(missing)}"

    base_sha, head_sha, engine_sha = "1" * 40, "2" * 40, "3" * 40
    target_rules = [
        {"id": "tr-cluster", "target": "cluster-suite", "path_prefix": "alpha/", "kind": "direct"},
        {"id": "tr-cluster-fb", "target": "cluster-suite", "path_prefix": "", "kind": "full_fallback"},
        {"id": "tr-oracle", "target": "live-oracle", "path_prefix": "beta/", "kind": "direct"},
        {"id": "tr-oracle-fb", "target": "live-oracle", "path_prefix": "", "kind": "full_fallback"},
    ]
    # Without an admitted selection receipt, build_full_selection fires and every full_fallback target is selected.
    unreceipted = {
        "build_run": [
            {"id": "r-unverified", "event": "pull_request", "base_sha": base_sha, "head_sha": head_sha,
             "engine_sha": engine_sha, "observed_at": 1_800_000_000, "receipt": "rcpt"},
        ],
        "loop_sweep_receipt": [{"id": "rcpt", "run": "r-unverified", "event_time": 1_800_000_000}],
        "build_path": [{"id": "p-1", "run": "r-unverified", "path": "alpha/executor.py", "coverage": "mapped"}],
        "build_target_rule": target_rules,
    }
    _, rows, _ = evaluate(model, unreceipted)
    assert {row[:2] for row in rows["build_target_selected"]} == {
        ("r-unverified", "cluster-suite"),
        ("r-unverified", "live-oracle"),
    }
    assert rows["build_target_not_required"] == set()


def test_single_effect_watchdog_shared_form():
    """Form 4: packs/std-loop derives watchdog_trigger, watchdog_resolve and watchdog_hold with fail-closed receipt check."""
    from rezono_compiler import pack, rules

    model = pack.read(LOOP)
    required = {"watchdog_trigger", "watchdog_resolve", "watchdog_hold"}
    missing = required - set(rules.load(model.rules).derived())
    assert not missing, f"packs/std-loop does not derive {sorted(missing)}"

    data = {
        "loop_sweep_receipt": [{"id": "rcpt-1", "run": "r1", "event_time": 9000}],
        "watchdog_target": [
            {"id": "stalled", "run": "r1", "cut_tick": 9000, "window_seconds": 7200, "work_pending": "yes",
             "receipt": "rcpt-1"},
            {"id": "already-open", "run": "r1", "cut_tick": 9000, "window_seconds": 7200, "work_pending": "yes",
             "receipt": "rcpt-1"},
            {"id": "recovered", "run": "r1", "cut_tick": 9000, "window_seconds": 7200, "work_pending": "yes",
             "receipt": "rcpt-1"},
            {"id": "active", "run": "r1", "cut_tick": 9000, "window_seconds": 7200, "work_pending": "yes",
             "receipt": "rcpt-1"},
            {"id": "idle", "run": "r1", "cut_tick": 9000, "window_seconds": 7200, "work_pending": "no",
             "receipt": "rcpt-1"},
            {"id": "unreceipted", "run": "r1", "cut_tick": 9000, "window_seconds": 7200, "work_pending": "yes"},
        ],
        "watchdog_activity": [
            {"id": "a-stalled", "target": "stalled", "activity_tick": 1000},
            {"id": "a-open", "target": "already-open", "activity_tick": 1000},
            {"id": "a-recovered", "target": "recovered", "activity_tick": 8800},
            {"id": "a-active", "target": "active", "activity_tick": 8000},
            {"id": "a-unreceipted", "target": "unreceipted", "activity_tick": 1000},
        ],
        "watchdog_active_effect": [
            {"id": "eff-open", "target": "already-open", "created_at": 8500},
            {"id": "eff-rec", "target": "recovered", "created_at": 8500},
        ],
    }
    _, rows, _ = evaluate(model, data)
    assert {row[:2] for row in rows["watchdog_trigger"]} == {("r1", "stalled")}
    assert {row[:3] for row in rows["watchdog_resolve"]} == {("r1", "recovered", "eff-rec")}
    assert rows["watchdog_hold"] >= {
        ("r1", "already-open", "effect-already-open"),
        ("r1", "active", "within-window"),
        ("r1", "idle", "no-pending-work"),
        ("r1", "unreceipted", "receipt-missing"),
    }


@pytest.mark.xfail(
    strict=True,
    raises=AssertionError,
    reason="extra: decisions/tooling-does-not-decide.md: Form 5 who-may-change-what in packs/std-review + std-access. Waits for compiler/tests/test_std_decision_dates.py::test_std_decision_rules_read_dates (and packs/std-review native date migration per decisions/standard-packs-everywhere.md section 1.4 step 5, since loop/shortcut-budget.json caps day_number_fields for packs/std-review at 3).",
)
def test_who_may_change_what_shared_form(tmp_path):
    """Form 5: packs/std-review + packs/std-access derive change_member_unauthorized and change_authorized."""
    from rezono_compiler import modules, pack, rules

    required = {"change_member_unauthorized", "change_authorized"}
    missing_sources = required - _declared_in_pack_sources(REVIEW, required)
    assert not missing_sources, f"packs/std-review does not declare {sorted(missing_sources)}"
    review_model = pack.read(REVIEW)
    missing = required - set(rules.load(review_model.rules).derived())
    assert not missing, f"packs/std-review does not derive {sorted(missing)}"

    # Minimal consumer pack granting worker source edits and planner protected-test edits via std-access.
    consumer = tmp_path / "change-auth-probe"
    for sub in ("schema", "rules", "labels"):
        (consumer / sub).mkdir(parents=True)
    (consumer / "pack.yaml").write_text(
        "name: change-auth-probe\nversion: 0.1.0\ndefault_language: en\nimports:\n"
        f"  - name: std-access\n    path: {ACCESS.as_posix()}\n    sha256: {modules.pack_hash(ACCESS)}\n"
        f"  - name: std-review\n    path: {REVIEW.as_posix()}\n    sha256: {modules.pack_hash(REVIEW)}\n",
        encoding="utf-8",
    )
    (consumer / "schema" / "probe.yaml").write_text(
        "id: https://rezono.example/change-auth-probe\nname: change_auth_probe\nimports: [linkml:types]\n"
        "default_range: string\nannotations:\n  layer: facts\nclasses:\n  PathItem:\n    attributes:\n"
        "      id: {identifier: true}\n",
        encoding="utf-8",
    )
    (consumer / "channels.yaml").write_text(
        "kinds:\n  - {kind: path_item, shape: pill}\n",
        encoding="utf-8",
    )
    (consumer / "labels" / "en.yaml").write_text(
        "path_item: path item\n",
        encoding="utf-8",
    )
    (consumer / "rules" / "grants.dl").write_text(
        ".decl may_propose(role: symbol, kind: symbol, element: symbol)\n"
        'may_propose("worker", "source", e) :- path_item(e).\n'
        'may_propose("planner", "source", e) :- path_item(e).\n'
        'may_propose("planner", "protected_test", e) :- path_item(e).\n',
        encoding="utf-8",
    )
    model = pack.read(consumer)
    h = "a" * 64
    data = {
        "role": [
            {"id": "worker", "title": "Worker", "capability": ["propose"]},
            {"id": "planner", "title": "Planner", "capability": ["propose"]},
        ],
        "path_item": [{"id": "src.py"}, {"id": "test_x.py"}, {"id": "gpl.whl"}],
        "role_grant": [
            {"id": "g-worker", "subject": "bot-w", "role": "worker", "from_day": 20260101},
            {"id": "g-planner", "subject": "bot-p", "role": "planner", "from_day": 20260101},
        ],
        "change": [
            {"id": "c-ok", "author": "bot-w", "content_sha256": h, "support_sha256": h},
            {"id": "c-denied", "author": "bot-w", "content_sha256": h, "support_sha256": h},
            {"id": "c-planner", "author": "bot-p", "content_sha256": h, "support_sha256": h},
            {"id": "c-gpl", "author": "bot-p", "content_sha256": h, "support_sha256": h},
        ],
        "change_proposal": [
            {"id": "p-ok", "change": "c-ok", "role": "worker", "day": "2026-11-20"},
            {"id": "p-denied", "change": "c-denied", "role": "worker", "day": "2026-11-20"},
            {"id": "p-planner", "change": "c-planner", "role": "planner", "day": "2026-11-20"},
            {"id": "p-gpl", "change": "c-gpl", "role": "planner", "day": "2026-11-20"},
        ],
        "change_member": [
            {"id": "m-ok", "change": "c-ok", "kind": "source", "element": "src.py"},
            {"id": "m-denied", "change": "c-denied", "kind": "protected_test", "element": "test_x.py"},
            {"id": "m-planner", "change": "c-planner", "kind": "protected_test", "element": "test_x.py"},
            {"id": "m-gpl", "change": "c-gpl", "kind": "gpl_indicator", "element": "gpl.whl"},
        ],
    }
    _, rows, _ = evaluate(model, data)
    assert rows["change_member_unauthorized"] == {("c-denied", "m-denied"), ("c-gpl", "m-gpl")}
    assert rows["change_authorized"] == {("c-ok",), ("c-planner",)}


@pytest.mark.xfail(
    strict=True,
    raises=AssertionError,
    reason="extra: decisions/tooling-does-not-decide.md: build_selected_job derives graph from pack facts not components.py",
)
def test_build_selected_job_derives_graph_from_pack_facts_not_components_py(monkeypatch):
    """build_selected_job derives its component/test graph from build/ pack facts, never from scripts/components.py."""
    from rezono_compiler import pack, rules
    from scripts import components

    # Poison Python tables in scripts/components.py to prove there is zero Python dependency or fallback.
    for table in ("FILE_CONSUMERS", "PR_FILE_CONSUMERS", "SHARED_READERS", "FULL_SELECTION_PATHS", "JOB_INPUTS"):
        monkeypatch.setattr(components, table, {})

    model = pack.read(BUILD)
    required_kinds = {"BuildFileConsumer", "BuildSharedReader", "BuildFullSelectionPath", "BuildJobInput"}
    missing_kinds = required_kinds - {k.cls for k in model.kinds.values()}
    assert not missing_kinds, f"build/ schema is missing graph fact kinds: {sorted(missing_kinds)}"
    assert (BUILD / "facts").is_dir() and any((BUILD / "facts").glob("*.yaml")), (
        "build/facts/ must carry the component/test graph facts"
    )
    program = rules.load(model.rules)
    assert "build_selected_job" in program.derived()

    # Evaluate build/ with pack-fact graph rows and raw changed paths only (no Python-supplied
    # build_dependency/build_path_reader, and poisoned scripts/components.py tables).
    base_sha, head_sha, engine_sha = "1" * 40, "2" * 40, "3" * 40
    components_data = [
        {"id": folder, "run": "r1", "kind": "python", "folder": folder}
        for folder in ("alpha", "beta", "gamma", "delta", "epsilon")
    ]
    graph_facts = {
        "build_file_consumer": [
            {"id": "fc-ab", "source": "alpha", "consumer": "beta"},
            {"id": "fc-bg", "source": "beta", "consumer": "gamma"},
        ],
        "build_shared_reader": [
            {"id": "sr-1", "pattern": "shared/cases.yaml", "reader": "delta"},
        ],
        "build_job_input": [
            {"id": "ji-1", "path": "profiles/epsilon.json", "reader": "epsilon"},
        ],
        "build_full_selection_path": [
            {"id": "fs-1", "prefix": "config/global.yml"},
        ],
    }

    def receipt_members(receipt: str, paths: tuple[str, ...]) -> set[tuple[str, str, int, str]]:
        members: set[tuple[str, str, int, str]] = set()
        for idx, path in enumerate(paths, start=1):
            members.update({
                (receipt, f"m-path-{idx}", 0, "changed-path"),
                (receipt, f"m-path-{idx}", 1, path),
                (receipt, f"m-readers-direct-{idx}", 0, "path-readers"),
                (receipt, f"m-readers-direct-{idx}", 1, path),
                (receipt, f"m-readers-direct-{idx}", 2, "direct"),
                (receipt, f"m-readers-transitive-{idx}", 0, "path-readers"),
                (receipt, f"m-readers-transitive-{idx}", 1, path),
                (receipt, f"m-readers-transitive-{idx}", 2, "transitive"),
            })
        return members

    verified = {
        "verified_receipt": {("rcpt", "build-capture", "build-selection", "1800000000", "inv", "cnt")},
        "verified_member": receipt_members("rcpt", ("alpha/engine.py", "shared/cases.yaml", "profiles/epsilon.json")),
    }
    data = {
        **graph_facts,
        "build_run": [
            {"id": "r1", "event": "pull_request", "base_sha": base_sha, "head_sha": head_sha,
             "engine_sha": engine_sha, "observed_at": 1_800_000_000, "receipt": "rcpt"},
        ],
        "loop_sweep_receipt": [{"id": "rcpt", "run": "r1", "event_time": 1_800_000_000}],
        "build_component": components_data,
        "build_path": [
            {"id": "p-alpha", "run": "r1", "path": "alpha/engine.py", "coverage": "mapped"},
            {"id": "p-shared", "run": "r1", "path": "shared/cases.yaml", "coverage": "mapped"},
            {"id": "p-prof", "run": "r1", "path": "profiles/epsilon.json", "coverage": "mapped"},
        ],
    }
    _, rows, _ = evaluate(model, data, verified=verified)
    assert not any(row[0] == "r1" for row in rows["build_full_selection"])
    selected = {row[1] for row in rows["build_selected_job"] if row[0] == "r1"}
    # Transitive file-consumer edge alpha -> beta -> gamma, plus shared reader delta and job input epsilon.
    assert {"alpha", "beta", "gamma", "delta", "epsilon"} <= selected

    # Changing a full-selection path declared in pack facts derives build_full_selection
    # even with a valid admitted selection receipt.
    full_verified = {
        "verified_receipt": {("rcpt2", "build-capture", "build-selection", "1800000000", "inv", "cnt")},
        "verified_member": receipt_members("rcpt2", ("config/global.yml",)),
    }
    full_data = {
        **graph_facts,
        "build_run": [
            {"id": "r2", "event": "pull_request", "base_sha": base_sha, "head_sha": head_sha,
             "engine_sha": engine_sha, "observed_at": 1_800_000_000, "receipt": "rcpt2"},
        ],
        "loop_sweep_receipt": [{"id": "rcpt2", "run": "r2", "event_time": 1_800_000_000}],
        "build_component": [{**c, "run": "r2"} for c in components_data],
        "build_path": [
            {"id": "p-global", "run": "r2", "path": "config/global.yml", "coverage": "mapped"},
        ],
    }
    _, full_rows, _ = evaluate(model, full_data, verified=full_verified)
    assert any(row[0] == "r2" for row in full_rows["build_full_selection"])


@pytest.mark.xfail(
    strict=True,
    raises=AssertionError,
    reason="extra: decisions/tooling-does-not-decide.md: check-pinned.py reads pin exceptions from pack facts",
)
def test_check_pinned_reads_exceptions_from_pack_facts():
    """scripts/check-pinned.py holds no hardcoded rezono-* or pip literals and reads exceptions from build/ facts."""
    from rezono_compiler import pack, rules

    source = (ROOT / "scripts" / "check-pinned.py").read_text(encoding="utf-8")
    tree = ast.parse(source, filename="scripts/check-pinned.py")
    literals = {
        node.value for node in ast.walk(tree)
        if isinstance(node, ast.Constant) and isinstance(node.value, str)
    }
    assert "^rezono-" not in literals, "scripts/check-pinned.py still hardcodes ^rezono-"
    assert "pip" not in literals, "scripts/check-pinned.py still hardcodes pip"

    model = pack.read(BUILD)
    assert "BuildPinException" in {k.cls for k in model.kinds.values()}, (
        "build/ schema must declare BuildPinException facts"
    )
    required = {"build_pin_exempt", "build_unpinned_package"}
    missing = required - set(rules.load(model.rules).derived())
    assert not missing, f"build/ does not derive {sorted(missing)}"

    # Removing "pip" from pack facts causes an installed "pip" absent from the lockfile to be flagged.
    data = {
        "build_pin_exception": [
            {"id": "ex-own", "match_kind": "prefix", "pattern": "rezono-"},
        ],
        "build_installed_package": [
            {"id": "pkg-own", "name": "rezono-compiler", "version": "0.1.0"},
            {"id": "pkg-pip", "name": "pip", "version": "25.0"},
            {"id": "pkg-ok", "name": "pyyaml", "version": "6.0.2"},
        ],
        "build_locked_package": [
            {"id": "lock-ok", "name": "pyyaml", "version": "6.0.2"},
        ],
    }
    _, rows, _ = evaluate(model, data)
    assert {row[0] for row in rows["build_unpinned_package"]} == {"pip"}


@pytest.mark.xfail(
    strict=True,
    raises=AssertionError,
    reason="extra: decisions/tooling-does-not-decide.md: loop/cluster/base_check.py must share its "
           "selection/summary/base helpers with scripts/red_before.py instead of duplicating them, "
           "while continuing to run both from loop/cluster/ and from the isolated policy directory "
           "created by .github/workflows/disposable-cluster.yml.",
)
def test_cluster_base_check_shares_helpers_with_red_before(tmp_path: Path, monkeypatch):
    """loop/cluster/base_check.py delegates shared helpers to scripts/red_before.py (no duplicate copy)."""
    base_check_path = ROOT / "loop" / "cluster" / "base_check.py"
    red_before_path = ROOT / "scripts" / "red_before.py"
    red_guard_path = ROOT / "scripts" / "red_guard.py"
    assert base_check_path.is_file(), "loop/cluster/base_check.py is missing"
    assert red_before_path.is_file(), "scripts/red_before.py is missing"

    source = base_check_path.read_text(encoding="utf-8")
    tree = ast.parse(source, filename=str(base_check_path))

    # 1. Structural check: base_check.py must import red_before (not copy its helpers).
    imports_red_before = False
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            if any(alias.name in {"red_before", "scripts.red_before"} for alias in node.names):
                imports_red_before = True
        elif isinstance(node, ast.ImportFrom):
            mod = node.module or ""
            if mod in {"red_before", "scripts.red_before"} or (
                mod == "scripts" and any(alias.name == "red_before" for alias in node.names)
            ):
                imports_red_before = True
        elif isinstance(node, ast.Call):
            callee = getattr(node.func, "attr", getattr(node.func, "id", ""))
            if callee in {"import_module", "spec_from_file_location"}:
                if any(
                    isinstance(sub, ast.Constant)
                    and isinstance(sub.value, str)
                    and "red_before" in sub.value
                    for sub in ast.walk(node)
                ):
                    imports_red_before = True
    assert imports_red_before, (
        "loop/cluster/base_check.py must import scripts/red_before.py instead of duplicating its helpers"
    )

    # 2. No duplicated GITHUB_STEP_SUMMARY writer or direct selection file I/O in base_check.py.
    string_literals = {
        node.value
        for node in ast.walk(tree)
        if isinstance(node, ast.Constant) and isinstance(node.value, str)
    }
    assert "GITHUB_STEP_SUMMARY" not in string_literals, (
        "loop/cluster/base_check.py still duplicates GITHUB_STEP_SUMMARY writing instead of delegating "
        "to red_before.summarize"
    )
    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and node.name == "read_selection":
            calls = {
                getattr(sub.func, "attr", getattr(sub.func, "id", ""))
                for sub in ast.walk(node)
                if isinstance(sub, ast.Call)
            }
            assert "read_text" not in calls and "open" not in calls, (
                "loop/cluster/base_check.py read_selection still reads the selection file directly "
                "instead of delegating to red_before.read_selection"
            )

    # 3. Behavioral delegation check: executing base_check actually invokes red_before's shared helpers.
    scripts_dir = str(ROOT / "scripts")
    monkeypatch.syspath_prepend(scripts_dir)
    spec = importlib.util.spec_from_file_location("cluster_base_check_shared_test", base_check_path)
    assert spec is not None and spec.loader is not None
    bc = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(bc)

    rb_modules = [
        mod
        for name, mod in list(sys.modules.items())
        if name in {"red_before", "scripts.red_before"} and mod is not None
    ]
    if getattr(bc, "red_before", None) is not None and bc.red_before not in rb_modules:
        rb_modules.append(bc.red_before)
    assert rb_modules, "loading loop/cluster/base_check.py did not load scripts/red_before.py"

    read_calls: list[Path] = []
    summary_calls: list[tuple[str, list[str]]] = []

    for rb in rb_modules:
        orig_read = rb.read_selection
        orig_sum = rb.summarize

        def wrapped_read(selection, _orig=orig_read):
            read_calls.append(Path(selection))
            return _orig(selection)

        def wrapped_sum(verdict, tests, _orig=orig_sum):
            summary_calls.append((verdict, list(tests)))
            return _orig(verdict, tests)

        monkeypatch.setattr(rb, "read_selection", wrapped_read)
        monkeypatch.setattr(rb, "summarize", wrapped_sum)
        if getattr(bc, "read_selection", None) is orig_read:
            monkeypatch.setattr(bc, "read_selection", wrapped_read)
        if getattr(bc, "summarize", None) is orig_sum:
            monkeypatch.setattr(bc, "summarize", wrapped_sum)

    selection = tmp_path / "selection.txt"
    selection.write_text("", encoding="utf-8")
    summary_file = tmp_path / "step-summary.md"
    monkeypatch.setenv("GITHUB_STEP_SUMMARY", str(summary_file))
    monkeypatch.setattr(sys, "argv", [str(base_check_path), "--root", str(tmp_path), str(selection)])
    rc = bc.main()
    assert rc == 0, f"expected rc=0 on empty selection, got {rc}"
    assert read_calls, "base_check.main() did not delegate selection reading to red_before.read_selection"
    assert summary_calls, "base_check.main() did not delegate summary reporting to red_before.summarize"
    assert summary_file.is_file() and summary_file.read_text(encoding="utf-8").strip(), (
        "red_before.summarize did not write GITHUB_STEP_SUMMARY"
    )

    # 4. Isolated policy-dir check matching .github/workflows/disposable-cluster.yml:
    #    base_check.py must also run when copied beside red_before.py and red_guard.py in $RUNNER_TEMP.
    policy_dir = tmp_path / "policy"
    policy_dir.mkdir()
    for src in (base_check_path, red_before_path, red_guard_path):
        shutil.copy2(src, policy_dir / src.name)
    proc = subprocess.run(
        [sys.executable, str(policy_dir / "base_check.py"), "--root", str(tmp_path), str(selection)],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    assert proc.returncode == 0, (
        f"base_check.py failed when run from isolated policy dir beside red_before.py: "
        f"{proc.stdout}\n{proc.stderr}"
    )
