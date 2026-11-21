"""The landing gate as a rule of the build pack (decisions/landing-gate-as-rule.md).

Every expectation is worked by hand from that decision: the four landing states and their grounds (section 1), the
pull head, the required checks and the paths that need a reading (section 2), readings and findings as std-review
facts bound to the full head commit (section 2.4), and enqueue as a std-loop effect that only the driver holding
the claim may plan (section 3). The read-first paths and the required checks come from the build pack's own facts,
so the tests also hold those facts to decisions/checker-and-access-review.md and to the host's ruleset of
2026-11-21 that the decision lists. Each case is evaluated on the batch backend, without a publication.
"""

import hashlib
import json
from functools import cache
from pathlib import Path

import pytest
import yaml
from rezono_canon import canonical_json

ROOT = Path(__file__).resolve().parents[2]
BUILD = ROOT / "build"
DECISION = "decisions/landing-gate-as-rule.md"

RUN = "current"
TICK = 1_800_000_000
RECEIPT = "receipt"
HEAD = "a1" * 20  # the pull request's head at the cut
OLD = "b2" * 20  # its previous head
BASE = "c3" * 20
ENGINE = "f" * 40
PR, OTHER_PR = "pr-1", "pr-2"

CHECKER_PATH = "checker/rezono_checker/check.py"  # decisions/checker-and-access-review.md, the first path
TEST_PATH = "k8s-admission/test_flow.py"  # a test file under a read-first path, admitted as one
DOC_PATH = "docs/note.md"  # a path nobody reads first

# Section 2.2: the checks the host's ruleset for main required on 2026-11-21.
REQUIRED_CHECKS = {"check", "Inspect test evidence", "Light checks"}

KINDS = {"reading", "reading_finding", "reading_dismissal", "finding_resolution", "build_pull_head",
         "build_required_check", "build_check_reading", "build_queue_plan"}
RELATIONS = {"build_landing", "build_landing_ground", "build_landing_read", "build_reading_needed",
             "build_queue_driver", "effect_planned"}


class MissingLandingGate(AssertionError):
    """The build pack does not declare the kinds or derive the relations of the landing gate."""


class UnreadHeadNotUnknown(AssertionError):
    """A head on a checker path without a reading is not unknown with the path it waits on."""


class FindingDoesNotBlock(AssertionError):
    """A finding for the head is not a ground of `no`, or contradicting readings are not `invalid`."""


class ForeignReadingCounts(AssertionError):
    """A reading of another commit, change or scope counts as a reading of this head."""


class UnclaimedDriverEnqueues(AssertionError):
    """A driver without the claim, or without a `yes` landing state, gets an enqueue effect."""


@cache
def gate_model():
    """The build pack and its rule program, after checking that it has the gate's vocabulary (section 7, task 2)."""
    from rezono_compiler import pack, rules

    model = pack.read(BUILD)
    program = rules.load(model.rules)
    kinds = KINDS - set(model.kinds)
    derived = RELATIONS - set(program.derived())
    if kinds or derived:
        raise MissingLandingGate(f"{DECISION}: build/ lacks the kinds {sorted(kinds)} and the derived "
                                 f"relations {sorted(derived)}")
    return model, program


def evaluate(data, verified_rows, *, explain=False):
    """The build pack's rows for `data` on the batch backend, as pack_records.evaluate gives them; the proofs
    only when a case reads one, because computing every witness of the build pack dominates the time."""
    from rezono_compiler import batch, facts, scenarios
    from rezono_compiler import explain as explaining

    model, program = gate_model()
    inputs = {**scenarios.rule_rows(model, program, facts.rows_of(model, data)), **verified_rows}
    with batch.connect(program, inputs) as con:
        batch.compute(con, program)
        rows = batch.read(con, program, [*program.base_used(), *program.derived()])
        explainer = explaining.Explainer(program, rows, batch.witnesses(con, program)) if explain else None
    return program, rows, explainer


def pack_facts():
    """The records of build/facts/*.yaml: the required checks and the read-first target rules among them."""
    records = {}
    for path in sorted((BUILD / "facts").glob("*.yaml")):
        if path.name.endswith(".sources.yaml"):
            continue
        for kind, rows in (yaml.safe_load(path.read_text(encoding="utf-8")) or {}).items():
            records.setdefault(kind, []).extend(rows)
    return records


def commit_hash(sha):
    return hashlib.sha256(canonical_json(["git-commit", sha]).encode("utf-8")).hexdigest()


def change(identifier, head=HEAD):
    """A pull request as the capture writes it (section 2.1)."""
    return {"id": identifier, "author": "worker", "content_sha256": commit_hash(head),
            "support_sha256": commit_hash(BASE)}


def verified(paths, test_files=()):
    """The rows admission gives for the run's one build receipt: each changed path with both reader inventories,
    empty, and each admitted test file (decisions/admission-transport.md section 6)."""
    members = []

    def member(key):
        identifier = canonical_json(key)
        members.extend((RECEIPT, identifier, part, value) for part, value in enumerate(key))

    for path in paths:
        member(["changed-path", path])
        member(["path-readers", path, "direct"])
        member(["path-readers", path, "transitive"])
    for path in test_files:
        member(["test-file", path])
    return {"verified_receipt": [(RECEIPT, "build-fixture", "build-scope", "cut", "inventory", "content")],
            "verified_member": members}


def landing_records(paths, *, test_files=(), checks=None, readings=(), findings=(), dismissals=(),
                    resolutions=(), changes=(PR,)):
    """One verified cut of the head HEAD of pr-1, with its changed paths and every required check green."""
    records = pack_facts()
    required = {row["check"] for row in records.get("build_required_check", [])}
    states = {name: "green" for name in required} if checks is None else checks
    paths_ids = {path: f"path-{index}" for index, path in enumerate(paths)}
    records.update({
        "build_run": [{"id": RUN, "event": "pull_request", "base_sha": BASE, "head_sha": HEAD,
                       "engine_sha": ENGINE, "observed_at": TICK, "receipt": RECEIPT}],
        "loop_sweep_receipt": [{"id": RECEIPT, "run": RUN, "event_time": TICK}],
        "build_path": [{"id": paths_ids[path], "run": RUN, "path": path, "coverage": "mapped"} for path in paths],
        "build_component": [{"id": "k8s-admission", "run": RUN, "kind": "python", "folder": "k8s-admission"}],
        "build_test_file": [{"id": f"test-{index}", "component": "k8s-admission", "path": path}
                            for index, path in enumerate(test_files)],
        "change": [change(identifier) for identifier in changes],
        "build_pull_head": [{"id": "pull-1", "run": RUN, "change": PR, "head_sha": HEAD, "observed_at": TICK,
                             "source": "pulls-listing"}],
        "build_check_reading": [
            {"id": f"check-{index}", "run": RUN, "head_sha": HEAD, "check": name, "state": state,
             "observed_at": TICK, "source": "check-runs", "receipt": RECEIPT}
            for index, (name, state) in enumerate(sorted(states.items()))
        ],
        "reading": [{"id": identifier, "change": of, "commit_sha": commit, "scope": scope, "reader": "reader",
                     "source": f"review-{identifier}"} for identifier, of, commit, scope in readings],
        "reading_finding": [{"id": identifier, "reading": reading, "concern": concern,
                             "source": f"comment-{identifier}"} for identifier, reading, concern in findings],
        "reading_dismissal": [{"id": f"dismiss-{reading}", "reading": reading, "source": "dismissal"}
                              for reading in dismissals],
        "finding_resolution": [{"id": f"resolve-{finding}-{commit[:4]}", "finding": finding, "commit_sha": commit,
                                "source": "resolution"} for finding, commit in resolutions],
    })
    return records, paths_ids


def landing(rows):
    return {row for row in rows.get("build_landing", set()) if row[:3] == (RUN, PR, HEAD)}


def grounds(rows, state=None):
    """(state, ground, row) of every ground of pr-1 at HEAD, or of one state."""
    return {row[3:] for row in rows.get("build_landing_ground", set())
            if row[:3] == (RUN, PR, HEAD) and (state is None or row[3] == state)}


def premise_ids(program, explainer, relation, row):
    """The record ids of the base rows that a row's proof cites as positive premises, at any depth."""
    proof = explainer.proof(relation, row, "fixture")
    ids = set()
    for witness in proof["witnesses"]:
        for premise in witness["premises"]:
            if premise["polarity"] == "positive" and premise["row"]["relation"] in program.base_used():
                key = json.loads(premise["row"]["key"])
                if key:
                    ids.add(key[0])
    return ids


@pytest.mark.xfail(strict=True, raises=AssertionError, reason=(
    "M2: decisions/landing-gate-as-rule.md: build/ derives no landing state yet, so an unread head on a checker "
    "path is not unknown with the reading-missing ground that names its path (sections 1 and 2.3)"))
def test_unread_head_on_a_checker_path_is_unknown():
    gate_model()
    problems = []

    records, ids = landing_records([CHECKER_PATH, TEST_PATH], test_files=[TEST_PATH])
    _, rows, _ = evaluate(records, verified([CHECKER_PATH, TEST_PATH], [TEST_PATH]))
    if landing(rows) != {(RUN, PR, HEAD, "unknown")}:
        problems.append(f"an unread head on {CHECKER_PATH} must be unknown: {sorted(landing(rows))}")
    expected = {("unknown", "reading-missing", ids[CHECKER_PATH])}
    if grounds(rows) != expected:
        problems.append(f"it waits on exactly the reading of {CHECKER_PATH} ({ids[CHECKER_PATH]}); the admitted "
                        f"test file {TEST_PATH} needs none: {sorted(grounds(rows))} != {sorted(expected)}")
    read = {row for row in rows.get("build_landing_read", set()) if row[:3] == (RUN, PR, HEAD)}
    if read != {(RUN, PR, HEAD, "unknown")}:
        problems.append(f"the reading part on its own must be unknown too: {sorted(read)}")

    # The control: the same head changing only a path nobody reads first may land.
    records, _ = landing_records([DOC_PATH])
    _, rows, _ = evaluate(records, verified([DOC_PATH]))
    if landing(rows) != {(RUN, PR, HEAD, "yes")} or grounds(rows):
        problems.append(f"a head changing only {DOC_PATH} with green checks must be yes without grounds: "
                        f"{sorted(landing(rows))} {sorted(grounds(rows))}")
    if problems:
        raise UnreadHeadNotUnknown("\n".join(problems))


@pytest.mark.xfail(strict=True, raises=AssertionError, reason=(
    "M2: decisions/landing-gate-as-rule.md: std-review records no readings or findings and build/ derives no "
    "landing state, so a finding for the head is not a ground of no and contradicting readings are not invalid "
    "(sections 1 and 2.4)"))
def test_a_finding_for_the_head_blocks_landing():
    gate_model()
    problems = []
    found = ("r-found", PR, HEAD, "correctness")
    clean = ("r-clean", PR, HEAD, "correctness")
    finding = ("f-correct", "r-found", "correctness")

    # A correctness finding on exactly this head: no, with the finding as ground and as a premise of the proof.
    records, _ = landing_records([CHECKER_PATH], readings=[found], findings=[finding])
    program, rows, explainer = evaluate(records, verified([CHECKER_PATH]), explain=True)
    if landing(rows) != {(RUN, PR, HEAD, "no")}:
        problems.append(f"a correctness finding on the head must give no: {sorted(landing(rows))}")
    elif "f-correct" not in premise_ids(program, explainer, "build_landing", (RUN, PR, HEAD, "no")):
        problems.append("the finding f-correct must be a premise of the proof of no")
    if grounds(rows) != {("no", "correctness-finding", "f-correct")}:
        problems.append(f"the finding is the one ground of no: {sorted(grounds(rows))}")

    # A clean and a found reading of the same head contradict each other: invalid, naming both readings.
    records, _ = landing_records([CHECKER_PATH], readings=[found, clean], findings=[finding])
    _, rows, _ = evaluate(records, verified([CHECKER_PATH]))
    if landing(rows) != {(RUN, PR, HEAD, "invalid")}:
        problems.append(f"a clean and a found reading of one head must give invalid: {sorted(landing(rows))}")
    if grounds(rows) != {("invalid", "reading-conflict", "r-found"), ("invalid", "reading-conflict", "r-clean")}:
        problems.append(f"both readings of the conflict are its grounds: {sorted(grounds(rows))}")

    # Dismissing the found reading settles the conflict: the clean reading stands.
    records, _ = landing_records([CHECKER_PATH], readings=[found, clean], findings=[finding], dismissals=["r-found"])
    _, rows, _ = evaluate(records, verified([CHECKER_PATH]))
    if landing(rows) != {(RUN, PR, HEAD, "yes")} or grounds(rows):
        problems.append(f"a dismissed reading counts for nothing: {sorted(landing(rows))} {sorted(grounds(rows))}")

    # A quality finding found at the previous head stays open for this head until a resolution names this head.
    quality = ("r-quality", PR, OLD, "quality")
    q_finding = ("q-1", "r-quality", "quality")
    for resolutions, state in (((), "no"), ((("q-1", OLD),), "no"), ((("q-1", HEAD),), "yes")):
        records, _ = landing_records([CHECKER_PATH], readings=[clean, quality], findings=[q_finding],
                                     resolutions=resolutions)
        _, rows, _ = evaluate(records, verified([CHECKER_PATH]))
        want = {("no", "quality-finding", "q-1")} if state == "no" else set()
        if landing(rows) != {(RUN, PR, HEAD, state)} or grounds(rows) != want:
            problems.append(f"quality finding q-1 resolved at {[r[1][:4] for r in resolutions]}: expected {state} "
                            f"with {sorted(want)}, got {sorted(landing(rows))} {sorted(grounds(rows))}")
    if problems:
        raise FindingDoesNotBlock("\n".join(problems))


@pytest.mark.xfail(strict=True, raises=AssertionError, reason=(
    "M2: decisions/landing-gate-as-rule.md: build/ derives no landing state yet, so it cannot show that only a "
    "correctness reading of exactly this head and change counts (section 2.4)"))
def test_a_reading_of_another_sha_does_not_count():
    gate_model()
    problems = []
    facts = pack_facts()
    required = {row["check"] for row in facts.get("build_required_check", [])}
    if required != REQUIRED_CHECKS:
        problems.append(f"the required checks are those of section 2.2: {sorted(required)} != "
                        f"{sorted(REQUIRED_CHECKS)}")

    foreign = {
        "the previous head": ("r-old", PR, OLD, "correctness"),
        "this head of another change": ("r-other", OTHER_PR, HEAD, "correctness"),
        "this head, for quality only": ("r-quality", PR, HEAD, "quality"),
    }
    for what, reading in foreign.items():
        records, ids = landing_records([CHECKER_PATH], readings=[reading], changes=(PR, OTHER_PR))
        _, rows, _ = evaluate(records, verified([CHECKER_PATH]))
        if landing(rows) != {(RUN, PR, HEAD, "unknown")}:
            problems.append(f"a clean reading of {what} must leave the head unknown: {sorted(landing(rows))}")
        if grounds(rows) != {("unknown", "reading-missing", ids[CHECKER_PATH])}:
            problems.append(f"with a reading of {what} the head still waits on its own reading: "
                            f"{sorted(grounds(rows))}")

    # The control: a clean correctness reading of exactly this head and change lets it land.
    records, _ = landing_records([CHECKER_PATH], readings=[("r-head", PR, HEAD, "correctness")])
    _, rows, _ = evaluate(records, verified([CHECKER_PATH]))
    if landing(rows) != {(RUN, PR, HEAD, "yes")} or grounds(rows):
        problems.append(f"a clean reading of exactly the head must give yes: {sorted(landing(rows))} "
                        f"{sorted(grounds(rows))}")
    if problems:
        raise ForeignReadingCounts("\n".join(problems))


DRIVERS = ("driver-a", "driver-b")


def queue_records(claims, *, read=True):
    """Two drivers, each with an enqueue plan for HEAD of pr-1 that acts on the gate run's landing state."""
    readings = [("r-head", PR, HEAD, "correctness")] if read else []
    records, _ = landing_records([CHECKER_PATH], readings=readings)
    records.update({
        "loop_active_run": [{"id": driver} for driver in DRIVERS],
        "loop_step": [{"id": "enqueue"}],
        "loop_completion": [{"id": f"def-{driver}", "run": driver, "step": "enqueue", "token": "queued",
                             "reason": f"def-{driver}"} for driver in DRIVERS],
        "loop_expectation": [{"id": "queued", "value": "yes"}],
        "loop_effect_plan": [{"id": f"plan-{driver}", "run": driver, "step": "enqueue", "reason": "queue"}
                             for driver in DRIVERS],
        "build_queue_plan": [{"id": f"queue-{driver}", "plan": f"plan-{driver}", "change": PR, "head_sha": HEAD,
                              "action": "enqueue", "gate_run": RUN} for driver in DRIVERS],
        "loop_claim": [{"id": f"claim-{driver}-{tick}", "run": driver, "subject": PR,
                        "generation": "1" * 40, "observed_at": tick, "source": f"refs/rezono/queue-claims/{PR}"}
                       for driver, tick in claims],
    })
    return records


def enqueues(rows):
    return {row[:3] for row in rows.get("effect_planned", set()) if row[1] == "enqueue"}


@pytest.mark.xfail(strict=True, raises=AssertionError, reason=(
    "M2: decisions/landing-gate-as-rule.md: build/ declares no queue plan and does not extend effect_permitted, "
    "so a driver gets no enqueue effect through the claim and the landing state (section 3)"))
def test_a_second_driver_without_the_claim_gets_no_enqueue():
    gate_model()
    problems = []

    _, rows, _ = evaluate(queue_records([("driver-a", TICK)]), verified([CHECKER_PATH]))
    if landing(rows) != {(RUN, PR, HEAD, "yes")}:
        problems.append(f"the fixture's head must be yes: {sorted(landing(rows))}")
    if enqueues(rows) != {("driver-a", "enqueue", "plan-driver-a")}:
        problems.append(f"only the driver holding the claim plans its enqueue: {sorted(enqueues(rows))}")
    drivers = {row for row in rows.get("build_queue_driver", set()) if row[:2] == (RUN, PR)}
    if drivers != {(RUN, PR, "driver-a")}:
        problems.append(f"driver-a is the one driver of {PR} at the cut: {sorted(drivers)}")

    cases = {
        "no claim": ([], True),
        "a claim by each driver": ([("driver-a", TICK), ("driver-b", TICK)], True),
        "a claim observed at another tick": ([("driver-a", TICK - 1)], True),
        "an unread head": ([("driver-a", TICK)], False),
    }
    for what, (claims, read) in cases.items():
        _, rows, _ = evaluate(queue_records(claims, read=read), verified([CHECKER_PATH]))
        if enqueues(rows):
            problems.append(f"with {what} no driver may plan an enqueue: {sorted(enqueues(rows))}")
    if problems:
        raise UnclaimedDriverEnqueues("\n".join(problems))
