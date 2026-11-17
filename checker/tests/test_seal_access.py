"""O8 for a seal with parts (docs/compiler.md#parts), as the checker derives it on its own: whether a run is
refused or accepted depends on all its steps, so a role reads the seal's relations only if its read rules give
every part kind in full. A role that reads a step on a condition gets none of them; handed one, the checker
says `not_readable`; and they do not count as read in full."""

import json

from rezono_checker.access import check_role

SEAL = {"kind": "run", "period": "run__month", "row_sha256": "run__row_sha256", "tables": ["run__month"],
        "closed_until": "period_close__closed_until", "covers": "period_close__covers",
        "element": "closed_run__element", "sha256": "closed_run__sha256", "refused": "run__refused",
        "accepted": "run__accepted",
        "parts": [{"kind": "step", "arrow": "step__run", "owner": "run", "tables": ["step__run"],
                   "accepted": "step__accepted"}]}
WITHHELD = ("run__refused", "run__accepted", "run__row_sha256", "step__accepted")


def atom(rel, *terms):
    return {"relation": rel, "terms": list(terms), "polarity": "positive"}


def grant(rid, who, kind, body):
    return {"id": rid, "head": {"relation": "may_read", "terms": [who, kind, "?x"]}, "body": body}


DOC = {"format": "rezono.rules/1", "pack": "toy", "seals": [SEAL],
       "relations": [{"name": "may_read", "role": "derived", "key": []}],
       "rules": [grant("r-run", "?r", "run", [atom("role", "?r"), atom("run", "?x")]),
                 grant("r-role", "?r", "role", [atom("role", "?r"), atom("role", "?x")]),
                 grant("r-step-guest", "guest", "step", [atom("step__label", "?x", "open")]),  # a condition: not full
                 grant("r-step-host", "host", "step", [atom("step", "?x")])]}
# s2 is hidden from the guest: a step of the same run it may not read.
ROWS = {"run": [["r1"]], "step": [["s1"], ["s2"]], "role": [["guest"], ["host"]], "run__month": [["r1", "2026-10-01"]],
        "step__run": [["s1", "r1"], ["s2", "r1"]], "step__label": [["s1", "open"], ["s2", "hidden"]],
        "run__row_sha256": [["r1", "h"]], "run__refused": [], "run__accepted": [["r1"]],
        "step__accepted": [["s1"], ["s2"]],
        "may_read": [[r, k, x] for r in ("guest", "host") for k, x in (("run", "r1"), ("role", "guest"),
                                                                      ("role", "host"), ("step", "s1"))]
        + [["host", "step", "s2"]]}
COLUMNS = {"run": ("run",), "step": ("step",), "role": ("role",), "run__month": ("run", None),
           "step__run": ("step", "run"), "step__label": ("step", None), "run__row_sha256": ("run", None), "run__refused": ("run", "period_close"),
           "run__accepted": ("run",), "step__accepted": ("step",), "may_read": ("role", None, None)}


def snaps(rows: dict) -> dict:
    return {rel: json.dumps([{"key": r} for r in rs]).encode() for rel, rs in rows.items()}


def check(role: str, mine: dict):
    """The role's full relations and the findings on base relations (may_read, derived, has no proofs here)."""
    mine = {rel: rs for rel, rs in mine.items() if rel != "may_read"}
    full, findings = check_role(role, snaps(ROWS), snaps(mine), None, COLUMNS, ["run", "step", "role", "period_close"],
                                {}, DOC)
    return full, [f for f in findings if f["relation"] != "may_read"]


def test_a_role_that_reads_every_part_in_full_reads_the_status():
    full, findings = check("host", ROWS)
    assert findings == []
    assert {"run__accepted", "run__row_sha256", "step__accepted"} <= full  # run__refused names a close it does not read


def test_a_role_that_reads_a_part_on_a_condition_gets_no_status():
    hidden = lambda r: "s2" not in r  # noqa: E731
    mine = {rel: [r for r in rs if hidden(r)] for rel, rs in ROWS.items() if rel not in WITHHELD}
    full, findings = check("guest", mine)
    assert findings == []  # nothing missing: none of it is the guest's
    assert not set(WITHHELD) & full
    # Handed the status anyway, the checker refuses it.
    _, findings = check("guest", {rel: [r for r in rs if hidden(r)] for rel, rs in ROWS.items()})
    assert sorted({(f["reason"], f["relation"]) for f in findings}) == [
        ("not_readable", "run__accepted"), ("not_readable", "run__row_sha256"), ("not_readable", "step__accepted")]
