"""Read the decision heads in the build pack: a red test that names a replaced decision, and a decision nobody names.

The expectations are worked by hand from decisions/decision-heads.md section 5 and the rules of std-decision
(packs/std-decision/README.md, rules): on the policy day 2027-01-15 of the cut, `old-rule` is replaced by
`new-rule`, which took effect on 2026-06-01; `late-rule` replaces `new-rule` only from 2027-06-01. Only a citation
scan of the run at the cut tick counts.
"""
import pytest

from test_build_queue_count import declared_kinds
from test_build_selection import OBSERVED_AT, capture, published, repository

FINDING = "build_red_cites_replaced"
WARNING = "build_uncited_decision"


class MissingRedCitationRule(AssertionError):
    """The build pack does not report a red test whose reason names a replaced decision."""


class MissingUncitedDecisionRule(AssertionError):
    """The build pack does not warn about a decision in force that no file names."""


def decision(name, day, state, **fields):
    return {"id": name, "title": f"The {name}", "subject": "rules", "decider": ["loop"], "state": state,
            "decided_on": f"{day[:4]}-{day[4:6]}-{day[6:]}", "valid_from": f"{day[:4]}-{day[4:6]}-{day[6:]}",
            "valid_from_day": int(day), **fields}


DECISIONS = [
    decision("old-rule", "20260101", "superseded"),
    decision("new-rule", "20260601", "in_force", supersedes=["old-rule"]),
    decision("late-rule", "20270601", "in_force", supersedes=["new-rule"]),
]


def observations(tmp_path, decisions, scans, citations=(), red=()):
    """The capture of one verified run at OBSERVED_AT, with its policy day, decisions and citation scans.

    `scans` maps a scan id to its tick, `citations` are (scan, path, decision) and `red` are (scan, test, decision).
    """
    tmp_path.mkdir(parents=True, exist_ok=True)
    source = tmp_path / "source"
    base, head, paths = repository(source, "decisions/rules.md")
    records = capture(source, base, head, paths)
    records.update({
        "reference_date": [{"id": "policy-day", "title": "Observed reference day", "day": 20270115}],
        "build_policy_date": [{"id": "policy-cut", "run": "current", "reference": "policy-day",
                               "observed_at": OBSERVED_AT}],
        "subject": [{"id": "rules", "title": "rules"}],
        "decision": decisions,
        "build_citation_scan": [{"id": scan, "run": "current", "observed_at": tick, "source": "tree"}
                                for scan, tick in scans.items()],
    })
    if citations:
        records["build_decision_citation"] = [
            {"id": f"cites-{index}", "scan": scan, "path": path, "decision": name}
            for index, (scan, path, name) in enumerate(citations)
        ]
    if red:
        records["build_red_citation"] = [
            {"id": f"red-{index}", "scan": scan, "test": test, "decision": name}
            for index, (scan, test, name) in enumerate(red)
        ]
    return published(tmp_path, records)


@pytest.mark.xfail(
    strict=True,
    raises=MissingRedCitationRule,
    reason=(
        "extra: decisions/decision-heads.md: section 5. Declare BuildCitationScan {id, run: BuildRun, observed_at: "
        "integer, source} and BuildRedCitation {id, scan: BuildCitationScan, test, decision: Decision}, all "
        "required, in build/schema, and derive build_red_cites_replaced(run, test, decision, successor) in "
        "build/rules: a scan of a verified run whose observed_at is the run's cut tick, a red citation of that "
        "scan, and replaced(decision, successor, day) of std-decision on build_policy_date_at_cut(run, day). "
        "Add labels for the new kinds and the relation to build/labels/en.yaml."
    ),
)
def test_red_test_citing_a_replaced_decision_is_a_finding(tmp_path):
    kinds = {"BuildCitationScan", "BuildRedCitation"}
    if not kinds <= declared_kinds():
        raise MissingRedCitationRule(f"build/schema lacks {sorted(kinds - declared_kinds())}")
    rows = observations(
        tmp_path, DECISIONS, {"at-cut": OBSERVED_AT, "earlier": OBSERVED_AT - 1},
        red=[("at-cut", "t-old", "old-rule"), ("at-cut", "t-new", "new-rule"), ("at-cut", "t-late", "late-rule"),
             ("earlier", "t-earlier", "old-rule")],
    )
    if FINDING not in rows:
        raise MissingRedCitationRule(f"build/rules does not derive {FINDING}")

    # new-rule has replaced old-rule; late-rule has not yet taken effect, and the earlier scan is not at the cut.
    assert [row["key"] for row in rows[FINDING]] == [["current", "t-old", "old-rule", "new-rule"]]
    assert not rows.get("superseded_in_force")


@pytest.mark.xfail(
    strict=True,
    raises=MissingUncitedDecisionRule,
    reason=(
        "extra: decisions/decision-heads.md: section 5. Waits for loop/tests/test_build_decision_rules.py--"
        "test_red_test_citing_a_replaced_decision_is_a_finding (BuildCitationScan, and the same schema and rule "
        "files). Declare BuildDecisionCitation {id, scan: BuildCitationScan, path, decision: Decision}, all "
        "required, in build/schema, and derive build_uncited_decision(run, decision) in build/rules: a scan of a "
        "verified run at the cut tick exists, the decision is in_force_on the run's build_policy_date_at_cut "
        "day, and no citation of a scan at that cut names it. Without such a scan there is no row. Add labels "
        "to build/labels/en.yaml."
    ),
)
def test_uncited_decision_in_force_is_a_warning(tmp_path):
    kinds = {"BuildCitationScan", "BuildDecisionCitation"}
    if not kinds <= declared_kinds():
        raise MissingUncitedDecisionRule(f"build/schema lacks {sorted(kinds - declared_kinds())}")
    decisions = [*DECISIONS, decision("lone-rule", "20260301", "in_force"),
                 decision("named-earlier", "20260301", "in_force")]
    citations = [("at-cut", "docs/guide.md", "new-rule"), ("earlier", "docs/guide.md", "named-earlier")]
    rows = observations(tmp_path / "scanned", decisions, {"at-cut": OBSERVED_AT, "earlier": OBSERVED_AT - 1},
                        citations=citations)
    if WARNING not in rows:
        raise MissingUncitedDecisionRule(f"build/rules does not derive {WARNING}")

    # old-rule is replaced and late-rule not yet in force; new-rule is named at the cut, named-earlier only before.
    assert sorted(row["key"] for row in rows[WARNING]) == [["current", "lone-rule"], ["current", "named-earlier"]]

    # Without a scan at the cut, nobody knows which decision is named.
    rows = observations(tmp_path / "unscanned", decisions, {"earlier": OBSERVED_AT - 1}, citations=citations[1:])
    assert rows.get(WARNING, []) == []
