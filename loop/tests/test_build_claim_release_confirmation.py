"""Confirm a claim release only from a later complete absent read in the same run."""
import hashlib
from pathlib import Path

import pytest
import yaml
from test_build_selection import OBSERVED_AT, capture, published, repository

ROOT = Path(__file__).resolve().parents[2]
KINDS = {"BuildClaimDelete", "BuildClaimRefRead"}


def declared_kinds():
    return {
        name
        for path in sorted((ROOT / "build" / "schema").glob("*.yaml"))
        for name in (yaml.safe_load(path.read_text(encoding="utf-8")).get("classes") or {})
    }


def generation(name):
    return hashlib.sha1(name.encode("utf-8")).hexdigest()


def release_records(records):
    """Hand-worked cases for Confirm and DiscardConfirmation in formal/Claims.tla."""
    t = OBSERVED_AT
    current, = records["build_run"]
    records["build_run"].append(dict(current, id="other"))
    records["loop_sweep_receipt"].extend([
        {"id": "after-delete", "run": "current", "event_time": t + 60},
        {"id": "other-after-delete", "run": "other", "event_time": t + 60},
        {"id": "later", "run": "current", "event_time": t + 90},
    ])
    cases = {
        # branch: (delete outcome, sent_at, ref reads as (run, tick, state, generation name, receipt))
        "task/released": ("sent", t + 10, [("current", t + 60, "absent", None, "after-delete")]),
        "task/uncertain": ("unknown", t + 10, [("current", t + 60, "absent", None, "after-delete")]),
        "task/replaced": ("sent", t + 10, [("current", t + 60, "present", "task/replaced-again", "after-delete")]),
        "task/refused": ("refused", t + 10, [("current", t + 60, "present", "task/refused", "after-delete")]),
        "task/early": ("sent", t + 70, [("current", t + 60, "absent", None, "after-delete")]),
        "task/foreign": ("sent", t + 10, [("other", t + 60, "absent", None, "other-after-delete")]),
        "task/unreceipted": ("sent", t + 10, [("current", t + 30, "absent", None, None)]),
        "task/still": ("sent", t + 10, [("current", t + 60, "present", "task/still", "after-delete")]),
        # A present read that names no generation still shows the branch at that tick.
        "task/unnamed": ("sent", t + 10, [
            ("current", t + 60, "absent", None, "after-delete"),
            ("current", t + 60, "present", None, "after-delete"),
        ]),
        "task/contradicted": ("sent", t + 10, [
            ("current", t + 60, "absent", None, "after-delete"),
            ("current", t + 60, "present", "task/contradicted", "after-delete"),
        ]),
        # The first settling read after the delete decides, as Confirm or DiscardConfirmation does in the model.
        "task/absent-then-back": ("sent", t + 10, [
            ("current", t + 60, "absent", None, "after-delete"),
            ("current", t + 90, "present", "task/absent-then-back", "later"),
        ]),
        "task/replaced-then-absent": ("sent", t + 10, [
            ("current", t + 60, "present", "task/replaced-then-absent-again", "after-delete"),
            ("current", t + 90, "absent", None, "later"),
        ]),
    }
    records.update({"build_claim_delete": [], "build_claim_ref_read": []})
    for branch, (outcome, sent_at, reads) in cases.items():
        records["build_claim_delete"].append({"id": f"{branch}@delete", "run": "current", "branch": branch,
                                              "generation": generation(branch), "sent_at": sent_at,
                                              "outcome": outcome, "source": "claim-delete"})
        for index, (run, tick, state, seen, receipt) in enumerate(reads):
            records["build_claim_ref_read"].append({
                "id": f"{branch}@read-{index}", "run": run, "branch": branch, "observed_at": tick, "state": state,
                **({"generation": generation(seen)} if seen else {}),
                **({"receipt": receipt} if receipt else {}),
                "source": "ref-listing",
            })
    return records


def test_build_claim_release_confirmation(tmp_path):
    assert KINDS <= declared_kinds(), f"The build schema lacks {sorted(KINDS - declared_kinds())}"
    source = tmp_path / "source"
    base, head, paths = repository(source, "decisions/claims.md")
    rows = published(tmp_path, release_records(capture(source, base, head, paths)))

    def keys(relation, width):
        return {tuple(row["key"][:width]) for row in rows.get(relation, [])}

    assert keys("build_claim_released", 3) == {
        ("current", "task/released", generation("task/released")),
        ("current", "task/uncertain", generation("task/uncertain")),
        ("current", "task/absent-then-back", generation("task/absent-then-back")),
    }, f"Only a same-run, receipted absent read after the delete confirms a release: {keys('build_claim_released', 3)}"
    assert all(row["key"][3] for row in rows["build_claim_released"]), "A release must retain its reason"
    assert keys("build_claim_release_discarded", 3) == {
        ("current", "task/replaced", "replaced"),
        ("current", "task/refused", "delete-refused"),
        ("current", "task/replaced-then-absent", "replaced"),
    }
    both = keys("build_claim_released", 2) & keys("build_claim_release_discarded", 2)
    assert not both, f"A delete is either released or discarded, never both: {both}"
    assert keys("build_claim_release_pending", 3) == {
        ("current", "task/early", "readback-missing"),
        ("current", "task/foreign", "readback-missing"),
        ("current", "task/unreceipted", "readback-missing"),
        ("current", "task/still", "still-present"),
        ("current", "task/unnamed", "still-present"),
        ("current", "task/contradicted", "still-present"),
    }


def test_build_claim_release_conflicting_settlement(tmp_path):
    """Conflicting same-tick reads never settle as replaced, and a branch is never both released and discarded."""
    source = tmp_path / "source"
    base, head, paths = repository(source, "decisions/claims.md")
    records = capture(source, base, head, paths)
    t = OBSERVED_AT
    records["loop_sweep_receipt"].extend([
        {"id": "after-delete", "run": "current", "event_time": t + 60},
        {"id": "later", "run": "current", "event_time": t + 90},
    ])
    records["build_claim_delete"] = [
        {"id": "task/absent-and-other@d0", "run": "current", "branch": "task/absent-and-other",
         "generation": generation("task/absent-and-other"), "sent_at": t + 10,
         "outcome": "sent", "source": "claim-delete"},
        {"id": "task/same-and-other@d0", "run": "current", "branch": "task/same-and-other",
         "generation": generation("task/same-and-other"), "sent_at": t + 10,
         "outcome": "sent", "source": "claim-delete"},
        {"id": "task/unnamed-and-other@d0", "run": "current", "branch": "task/unnamed-and-other",
         "generation": generation("task/unnamed-and-other"), "sent_at": t + 10,
         "outcome": "sent", "source": "claim-delete"},
        {"id": "task/refused-and-released@d0", "run": "current", "branch": "task/refused-and-released",
         "generation": generation("task/refused-and-released-old"), "sent_at": t + 5,
         "outcome": "refused", "source": "claim-delete"},
        {"id": "task/refused-and-released@d1", "run": "current", "branch": "task/refused-and-released",
         "generation": generation("task/refused-and-released"), "sent_at": t + 10,
         "outcome": "sent", "source": "claim-delete"},
        {"id": "task/refused-and-pending@d0", "run": "current", "branch": "task/refused-and-pending",
         "generation": generation("task/refused-and-pending-old"), "sent_at": t + 5,
         "outcome": "refused", "source": "claim-delete"},
        {"id": "task/refused-and-pending@d1", "run": "current", "branch": "task/refused-and-pending",
         "generation": generation("task/refused-and-pending"), "sent_at": t + 10,
         "outcome": "unknown", "source": "claim-delete"},
        {"id": "task/mixed-effective@d0", "run": "current", "branch": "task/mixed-effective",
         "generation": generation("task/mixed-effective-old"), "sent_at": t + 10,
         "outcome": "sent", "source": "claim-delete"},
        {"id": "task/mixed-effective@d1", "run": "current", "branch": "task/mixed-effective",
         "generation": generation("task/mixed-effective-new"), "sent_at": t + 20,
         "outcome": "sent", "source": "claim-delete"},
    ]
    records["build_claim_ref_read"] = [
        {"id": "task/absent-and-other@r0", "run": "current", "branch": "task/absent-and-other",
         "observed_at": t + 60, "state": "absent", "receipt": "after-delete", "source": "ref-listing"},
        {"id": "task/absent-and-other@r1", "run": "current", "branch": "task/absent-and-other",
         "observed_at": t + 60, "state": "present", "generation": generation("task/absent-and-other-new"),
         "receipt": "after-delete", "source": "ref-listing"},
        {"id": "task/same-and-other@r0", "run": "current", "branch": "task/same-and-other",
         "observed_at": t + 60, "state": "present", "generation": generation("task/same-and-other"),
         "receipt": "after-delete", "source": "ref-listing"},
        {"id": "task/same-and-other@r1", "run": "current", "branch": "task/same-and-other",
         "observed_at": t + 60, "state": "present", "generation": generation("task/same-and-other-new"),
         "receipt": "after-delete", "source": "ref-listing"},
        {"id": "task/unnamed-and-other@r0", "run": "current", "branch": "task/unnamed-and-other",
         "observed_at": t + 60, "state": "present", "receipt": "after-delete", "source": "ref-listing"},
        {"id": "task/unnamed-and-other@r1", "run": "current", "branch": "task/unnamed-and-other",
         "observed_at": t + 60, "state": "present", "generation": generation("task/unnamed-and-other-new"),
         "receipt": "after-delete", "source": "ref-listing"},
        {"id": "task/refused-and-released@r0", "run": "current", "branch": "task/refused-and-released",
         "observed_at": t + 60, "state": "absent", "receipt": "after-delete", "source": "ref-listing"},
        {"id": "task/mixed-effective@r0", "run": "current", "branch": "task/mixed-effective",
         "observed_at": t + 60, "state": "present", "generation": generation("task/mixed-effective-new"),
         "receipt": "after-delete", "source": "ref-listing"},
        {"id": "task/mixed-effective@r1", "run": "current", "branch": "task/mixed-effective",
         "observed_at": t + 90, "state": "absent", "receipt": "later", "source": "ref-listing"},
    ]
    rows = published(tmp_path, records)

    def keys(relation, width):
        return {tuple(row["key"][:width]) for row in rows.get(relation, [])}

    assert keys("build_claim_released", 3) == {
        ("current", "task/refused-and-released", generation("task/refused-and-released")),
    }
    assert keys("build_claim_release_discarded", 3) == {
        ("current", "task/mixed-effective", "replaced"),
    }
    assert keys("build_claim_release_pending", 3) == {
        ("current", "task/absent-and-other", "readback-missing"),
        ("current", "task/same-and-other", "still-present"),
        ("current", "task/unnamed-and-other", "still-present"),
        ("current", "task/refused-and-pending", "readback-missing"),
    }
    both = keys("build_claim_released", 2) & keys("build_claim_release_discarded", 2)
    assert not both, f"A branch cannot be both released and discarded in one run: {both}"
    settled_and_pending = (
        (keys("build_claim_released", 2) | keys("build_claim_release_discarded", 2))
        & keys("build_claim_release_pending", 2)
    )
    assert not settled_and_pending, f"A branch cannot be both settled and pending: {settled_and_pending}"
