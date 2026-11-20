"""Tooling and CI decisions move into five shared pack forms with no Python fallback:
decisions/tooling-does-not-decide.md.

One structural test verifies that every non-test Python script in scripts/ and the workflow `if:`
groups are audited in decisions/tooling-does-not-decide.md. Seven strict `extra:` red tests state
the independent, hand-worked contracts for the five shared decision forms, the components.py-to-
build/ graph migration, and pack-fact pin exceptions.
"""
import ast
from pathlib import Path
import re

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
        cells = [cell.strip() for cell in line.strip("|").split("|")]
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
        if len(cells) >= 3 and cells[0].startswith("`scripts/"):
            name = cells[0].split("`")[1]
            script_fates[name] = cells[2]

    non_test_scripts = sorted(
        f"scripts/{path.name}"
        for path in (ROOT / "scripts").glob("*.py")
        if not path.name.startswith("test_")
    )
    assert non_test_scripts, "expected non-test Python scripts under scripts/"
    missing_scripts = [name for name in non_test_scripts if name not in script_fates]
    assert missing_scripts == [], f"scripts missing from audit table: {missing_scripts}"
    bad_script_fates = [name for name in non_test_scripts if not FATE_MARKER.search(script_fates[name])]
    assert bad_script_fates == [], f"scripts without a valid fate (a)-(d): {bad_script_fates}"

    workflow_section = text.split("## 4. Audit table:", 1)[1].split("## 5.", 1)[0]
    workflow_rows = [cells for cells in _table_rows(workflow_section) if len(cells) >= 4 and cells[0] != "Workflow `if:` group"]
    assert len(workflow_rows) >= 8, "expected all logical workflow `if:` groups in section 4"
    bad_workflow_fates = [cells[0] for cells in workflow_rows if not FATE_MARKER.search(cells[3])]
    assert bad_workflow_fates == [], f"workflow groups without a valid fate (a)-(d): {bad_workflow_fates}"

    lower = text.lower()
    assert "no python fallback" in lower, "decision must forbid runtime Python fallback"
    assert "fail-closed" in lower, "decision must state the fail-closed safe state"


@pytest.mark.xfail(
    strict=True,
    raises=AssertionError,
    reason="extra: decisions/tooling-does-not-decide.md: Form 1 monotonically shrinking budget in packs/std-budget",
)
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


@pytest.mark.xfail(
    strict=True,
    raises=AssertionError,
    reason="extra: decisions/tooling-does-not-decide.md: Form 2 commit-pinned evidence in packs/std-review",
)
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


@pytest.mark.xfail(
    strict=True,
    raises=AssertionError,
    reason="extra: decisions/tooling-does-not-decide.md: Form 3 change-to-target selection in build/",
)
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


@pytest.mark.xfail(
    strict=True,
    raises=AssertionError,
    reason="extra: decisions/tooling-does-not-decide.md: Form 4 single-effect watchdog in packs/std-loop",
)
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
    reason="extra: decisions/tooling-does-not-decide.md: Form 5 who-may-change-what in packs/std-review + std-access",
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
    for sub in ("schema", "rules"):
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
            {"id": "p-ok", "change": "c-ok", "role": "worker", "day": 20261120},
            {"id": "p-denied", "change": "c-denied", "role": "worker", "day": 20261120},
            {"id": "p-planner", "change": "c-planner", "role": "planner", "day": 20261120},
            {"id": "p-gpl", "change": "c-gpl", "role": "planner", "day": 20261120},
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
    missing_kinds = required_kinds - set(model.kinds)
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
    verified = {
        "verified_receipt": {("rcpt", "build-capture", "build-selection", "1800000000", "inv", "cnt")},
        "verified_member": {
            ("rcpt", "m-path-1", 0, "changed-path"), ("rcpt", "m-path-1", 1, "alpha/engine.py"),
            ("rcpt", "m-path-2", 0, "changed-path"), ("rcpt", "m-path-2", 1, "shared/cases.yaml"),
            ("rcpt", "m-path-3", 0, "changed-path"), ("rcpt", "m-path-3", 1, "profiles/epsilon.json"),
        },
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
    selected = {row[1] for row in rows["build_selected_job"] if row[0] == "r1"}
    # Transitive file-consumer edge alpha -> beta -> gamma, plus shared reader delta and job input epsilon.
    assert {"alpha", "beta", "gamma", "delta", "epsilon"} <= selected

    # Changing a full-selection path declared in pack facts derives build_full_selection.
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
    _, full_rows, _ = evaluate(model, full_data)
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
    assert "BuildPinException" in model.kinds, "build/ schema must declare BuildPinException facts"
    required = {"build_pin_exception", "build_unpinned_package"}
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
