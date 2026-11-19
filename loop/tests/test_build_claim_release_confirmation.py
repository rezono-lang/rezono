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
        "task/contradicted": ("sent", t + 10, [
            ("current", t + 60, "absent", None, "after-delete"),
            ("current", t + 60, "present", "task/contradicted", "after-delete"),
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
    }, f"Only a same-run, receipted absent read after the delete confirms a release: {keys('build_claim_released', 3)}"
    assert all(row["key"][3] for row in rows["build_claim_released"]), "A release must retain its reason"
    assert keys("build_claim_release_discarded", 3) == {
        ("current", "task/replaced", "replaced"),
        ("current", "task/refused", "delete-refused"),
    }
    assert keys("build_claim_release_pending", 3) == {
        ("current", "task/early", "readback-missing"),
        ("current", "task/foreign", "readback-missing"),
        ("current", "task/unreceipted", "readback-missing"),
        ("current", "task/still", "still-present"),
        ("current", "task/contradicted", "still-present"),
    }


def test_build_claim_release_confirmation_read_order(tmp_path):
    """A later present read or any post-delete replacement prevents release confirmation."""
    source = tmp_path / "source"
    base, head, paths = repository(source, "decisions/claims.md")
    records = capture(source, base, head, paths)
    t = OBSERVED_AT
    records["loop_sweep_receipt"].extend([
        {"id": "read-early", "run": "current", "event_time": t + 20},
        {"id": "read-late", "run": "current", "event_time": t + 30},
    ])
    cases = {
        "task/stale-absent": [
            (t + 20, "absent", None, "read-early"),
            (t + 30, "present", "task/stale-absent", "read-late"),
        ],
        "task/replaced-then-absent": [
            (t + 20, "present", "task/replaced-then-absent-new", "read-early"),
            (t + 30, "absent", None, "read-late"),
        ],
        "task/absent-then-replaced": [
            (t + 20, "absent", None, "read-early"),
            (t + 30, "present", "task/absent-then-replaced-new", "read-late"),
        ],
        "task/present-then-absent": [
            (t + 20, "present", "task/present-then-absent", "read-early"),
            (t + 30, "absent", None, "read-late"),
        ],
    }
    records.update({"build_claim_delete": [], "build_claim_ref_read": []})
    for branch, reads in cases.items():
        records["build_claim_delete"].append({
            "id": f"{branch}@delete", "run": "current", "branch": branch,
            "generation": generation(branch), "sent_at": t + 10, "outcome": "sent", "source": "claim-delete",
        })
        for index, (tick, state, seen, receipt) in enumerate(reads):
            records["build_claim_ref_read"].append({
                "id": f"{branch}@read-{index}", "run": "current", "branch": branch, "observed_at": tick,
                "state": state, **({"generation": generation(seen)} if seen else {}), "receipt": receipt,
                "source": "ref-listing",
            })

    rows = published(tmp_path, records)

    def keys(relation, width):
        return {tuple(row["key"][:width]) for row in rows.get(relation, [])}

    assert keys("build_claim_released", 3) == {
        ("current", "task/present-then-absent", generation("task/present-then-absent")),
    }
    assert keys("build_claim_release_discarded", 3) == {
        ("current", "task/replaced-then-absent", "replaced"),
        ("current", "task/absent-then-replaced", "replaced"),
    }
    assert keys("build_claim_release_pending", 3) == {
        ("current", "task/stale-absent", "still-present"),
    }
