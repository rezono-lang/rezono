"""Place, valid-time, and knowledge-time restrictions in `ask`, plus v2 `show extent`
(decisions/ask-place-time-restrictions.md)."""

from __future__ import annotations

import json
from pathlib import Path
import subprocess

import pytest

PROBE = Path(__file__).with_name("ask-place-time-probe.mts")


class AskRestrictionNotSupported(AssertionError):
    """The gate did not enforce or report an `ask` place/time/knowledge restriction or its witnesses."""


class AskExtentNotSupported(AssertionError):
    """The gate did not serve constructive place x valid-time `show extent` regions."""


def _run_probe(mode: str) -> dict:
    result = subprocess.run(
        ["node", str(PROBE), mode],
        cwd=PROBE.parent.parent,
        capture_output=True,
        encoding="utf-8",
    )
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout)


def _answer_rows(body: dict) -> list[dict]:
    return [row for row in body.get("dataset", {}).get("rows", []) if row.get("$kind") == "Answer"]


def _has_complete_witness(body: dict, expected_key: str, expected_amount_premise: str) -> bool:
    witnesses = body.get("witnesses")
    if not isinstance(witnesses, list) or not witnesses:
        return False
    for witness in witnesses:
        if not isinstance(witness, dict):
            continue
        conclusion = witness.get("conclusion")
        premises = witness.get("premises")
        if (
            isinstance(conclusion, dict)
            and conclusion.get("relation") == "eligible"
            and conclusion.get("key") == expected_key
            and witness.get("rule_id") == "r_eligible"
            and isinstance(witness.get("bindings"), list)
            and len(witness["bindings"]) >= 1
            and isinstance(premises, list)
            and any(
                isinstance(p, dict)
                and isinstance(p.get("row"), dict)
                and p["row"].get("relation") == "entry__amount"
                and p["row"].get("key") == expected_amount_premise
                for p in premises
            )
        ):
            return True
    return False


def test_ask_as_known_on_corrected_fact_returns_distinct_witnessed_answers():
    got = _run_probe("as_known")

    # Baseline sanity that already holds on main: unrestricted ask on m-2 returns the corrected value 150.
    current = got["current_default"]
    assert current["status"] == 200, current
    current_body = current["body"]
    current_rows = _answer_rows(current_body)
    assert len(current_rows) == 1 and current_rows[0].get("c1") == "150", current_body

    problems: list[dict] = []

    # 1. Unrestricted ask must explicitly report default scope and attach the m-2 witness.
    expected_default_restriction = {
        "default": True,
        "at": None,
        "during": None,
        "as_known": None,
        "resolved_manifest": "m-2",
        "knowledge_time": "2026-03-01T00:00:00Z",
    }
    if current_body.get("restriction") != expected_default_restriction:
        problems.append({"current_default_restriction": current_body.get("restriction")})
    key_v2 = '["e-1","north","2026-01-01","2026-07-01","150"]'
    if not _has_complete_witness(current_body, key_v2, '["e-1","150"]'):
        problems.append({"current_default_missing_witness": current_body.get("witnesses")})

    # 2. Same ask with `as known on 2026-02-01` must resolve m-1, return the old value 100, and carry m-1's witness.
    earlier = got["as_known_earlier"]
    if earlier["status"] != 200:
        problems.append({"as_known_earlier_status": earlier})
    else:
        earlier_body = earlier["body"]
        expected_earlier_restriction = {
            "default": False,
            "at": None,
            "during": None,
            "as_known": "2026-02-01",
            "resolved_manifest": "m-1",
            "knowledge_time": "2026-01-15T00:00:00Z",
        }
        if earlier_body.get("restriction") != expected_earlier_restriction:
            problems.append({"as_known_earlier_restriction": earlier_body.get("restriction")})
        earlier_rows = _answer_rows(earlier_body)
        if len(earlier_rows) != 1 or earlier_rows[0].get("c1") != "100":
            problems.append({"as_known_earlier_rows": earlier_rows})
        key_v1 = '["e-1","north","2026-01-01","2026-07-01","100"]'
        if not _has_complete_witness(earlier_body, key_v1, '["e-1","100"]'):
            problems.append({"as_known_earlier_missing_witness": earlier_body.get("witnesses")})
        if earlier_body.get("witnesses") == current_body.get("witnesses"):
            problems.append({"witnesses_must_differ_across_correction": earlier_body.get("witnesses")})

    # 3. `at north` restricts the domain to place `north`, excluding `south`, and keeps e-1's witness.
    at_north = got["at_north"]
    if at_north["status"] != 200:
        problems.append({"at_north_status": at_north})
    else:
        north_body = at_north["body"]
        expected_north_restriction = {
            "default": False,
            "at": "north",
            "during": None,
            "as_known": None,
            "resolved_manifest": "m-2",
            "knowledge_time": "2026-03-01T00:00:00Z",
        }
        if north_body.get("restriction") != expected_north_restriction:
            problems.append({"at_north_restriction": north_body.get("restriction")})
        north_rows = _answer_rows(north_body)
        if len(north_rows) != 1 or north_rows[0].get("c2") != "150":
            problems.append({"at_north_rows": north_rows})
        if not _has_complete_witness(north_body, key_v2, '["e-1","150"]'):
            problems.append({"at_north_missing_witness": north_body.get("witnesses")})

    # 4. Counter-example: `as known on 2026-01-01` (before first publication) returns unknown with reason, never false.
    before = got["before_first_known"]
    if before["status"] != 200:
        problems.append({"before_first_known_status": before})
    else:
        before_body = before["body"]
        expected_before_restriction = {
            "default": False,
            "at": None,
            "during": None,
            "as_known": "2026-01-01",
            "resolved_manifest": None,
            "knowledge_time": None,
        }
        if before_body.get("restriction") != expected_before_restriction:
            problems.append({"before_first_known_restriction": before_body.get("restriction")})
        undecided = before_body.get("undecided", [])
        if (
            before_body.get("nodes") != []
            or before_body.get("counts", {}).get("rows") != 0
            or before_body.get("counts", {}).get("undecided", 0) < 1
            or not any(
                isinstance(u, dict)
                and u.get("state") == "unknown"
                and u.get("reason") == "before_first_known"
                for u in undecided
            )
        ):
            problems.append({"before_first_known_not_unknown_with_reason": before_body})

    if problems:
        raise AskRestrictionNotSupported(json.dumps(problems, sort_keys=True))


def test_ask_during_outside_validity_returns_unknown_with_reason_not_false():
    got = _run_probe("during")

    # Baseline sanity that already holds on main.
    baseline = got["baseline"]
    assert baseline["status"] == 200, baseline
    assert len(_answer_rows(baseline["body"])) == 1, baseline["body"]

    problems: list[dict] = []

    # 1. `during` outside every validity period returns unknown with explicit reason `no_version_applies`
    #    for BOTH a positive predicate and its negation `not (...)` (proving unknown, never false).
    for label in ("outside_positive", "outside_negated"):
        reply = got[label]
        if reply["status"] != 200:
            problems.append({f"{label}_status": reply})
            continue
        body = reply["body"]
        expected_restriction = {
            "default": False,
            "at": None,
            "during": "2027-01-01..<2027-04-01",
            "as_known": None,
            "resolved_manifest": "m-1",
            "knowledge_time": "2026-01-15T00:00:00Z",
        }
        if body.get("restriction") != expected_restriction:
            problems.append({f"{label}_restriction": body.get("restriction")})
        undecided = body.get("undecided", [])
        if (
            body.get("nodes") != []
            or body.get("counts", {}).get("rows") != 0
            or body.get("counts", {}).get("undecided", 0) < 1
            or not any(
                isinstance(u, dict)
                and u.get("state") == "unknown"
                and u.get("reason") == "no_version_applies"
                for u in undecided
            )
        ):
            problems.append({f"{label}_not_unknown_with_reason": body})

    # 2. Counter-example: `during` within a valid period returns known with its verified witness.
    inside = got["inside_valid"]
    if inside["status"] != 200:
        problems.append({"inside_valid_status": inside})
    else:
        inside_body = inside["body"]
        expected_inside_restriction = {
            "default": False,
            "at": None,
            "during": "2026-03-01..<2026-04-01",
            "as_known": None,
            "resolved_manifest": "m-1",
            "knowledge_time": "2026-01-15T00:00:00Z",
        }
        if inside_body.get("restriction") != expected_inside_restriction:
            problems.append({"inside_valid_restriction": inside_body.get("restriction")})
        inside_rows = _answer_rows(inside_body)
        if (
            inside_body.get("counts", {}).get("rows") != 1
            or inside_body.get("counts", {}).get("undecided") != 0
            or len(inside_rows) != 1
            or inside_rows[0].get("c1") != "100"
        ):
            problems.append({"inside_valid_rows": inside_body})
        key_v1 = '["e-1","north","2026-01-01","2026-07-01","100"]'
        if not _has_complete_witness(inside_body, key_v1, '["e-1","100"]'):
            problems.append({"inside_valid_missing_witness": inside_body.get("witnesses")})

    if problems:
        raise AskRestrictionNotSupported(json.dumps(problems, sort_keys=True))


@pytest.mark.xfail(
    strict=True,
    raises=AskExtentNotSupported,
    reason=(
        "later: decisions/ask-place-time-restrictions.md: v2 show extent returns a place x valid-time region "
        "partition with one of the four states and a reason per piece, distinguishing not-everywhere-true from "
        "somewhere-false"
    ),
)
def test_ask_show_extent_returns_place_time_regions_with_four_states():
    got = _run_probe("extent")

    # Baseline sanity that already holds on main: both underlying four-valued queries run cleanly.
    c_base = got["constructive"]["baseline"]
    assert c_base["status"] == 200, c_base
    assert c_base["body"]["counts"] == {"rows": 1, "undecided": 1, "not_applicable": 0}, c_base["body"]

    f_base = got["four_states"]["baseline"]
    assert f_base["status"] == 200, f_base
    assert f_base["body"]["counts"] == {"rows": 1, "undecided": 2, "not_applicable": 1}, f_base["body"]

    problems: list[dict] = []

    # 1. Constructive counter-example: known(true) at `north` and unknown at `south`
    #    => everywhere_true is False AND somewhere_false is False (never reported as false!).
    c_ext = got["constructive"]["extent"]
    if c_ext["status"] != 200:
        problems.append({"constructive_extent_status": c_ext})
    else:
        ext = c_ext["body"].get("extent")
        if not isinstance(ext, dict):
            problems.append({"constructive_missing_extent": c_ext["body"]})
        else:
            regions = ext.get("regions", [])
            by_place = {r.get("place"): r for r in regions if isinstance(r, dict)}
            north = by_place.get("north")
            south = by_place.get("south")
            if ext.get("axes") != ["place", "valid"]:
                problems.append({"constructive_axes": ext.get("axes")})
            if (
                not north
                or north.get("state") != "known"
                or north.get("holds") is not True
                or north.get("valid") != {"from": "2026-01-01", "until": "2026-07-01"}
            ):
                problems.append({"constructive_north": north})
            if (
                not south
                or south.get("state") != "unknown"
                or south.get("holds") is not None
                or not south.get("reason")
                or south.get("valid") != {"from": "2026-01-01", "until": "2026-07-01"}
            ):
                problems.append({"constructive_south": south})
            if ext.get("everywhere_true") is not False or ext.get("somewhere_false") is not False:
                problems.append({
                    "constructive_flags": {
                        "everywhere_true": ext.get("everywhere_true"),
                        "somewhere_false": ext.get("somewhere_false"),
                    }
                })
            if any(isinstance(r, dict) and r.get("holds") is False for r in regions):
                problems.append({"constructive_fabricated_false_region": regions})

    # 2. All four epistemic states across place x valid time, each non-known piece carrying an explicit reason.
    f_ext = got["four_states"]["extent"]
    if f_ext["status"] != 200:
        problems.append({"four_states_extent_status": f_ext})
    else:
        ext = f_ext["body"].get("extent")
        if not isinstance(ext, dict):
            problems.append({"four_states_missing_extent": f_ext["body"]})
        else:
            regions = ext.get("regions", [])
            by_place = {r.get("place"): r for r in regions if isinstance(r, dict)}
            expected_states = {
                "north": "known",
                "south": "unknown",
                "east": "not_applicable",
                "west": "invalid",
            }
            for place, state in expected_states.items():
                region = by_place.get(place)
                if not region or region.get("state") != state:
                    problems.append({f"region_{place}_state": region})
                    continue
                if region.get("valid") != {"from": "2026-01-01", "until": "2026-07-01"}:
                    problems.append({f"region_{place}_valid": region})
                if state == "known":
                    if region.get("holds") is not True:
                        problems.append({f"region_{place}_holds": region})
                else:
                    if region.get("holds") is not None or not region.get("reason"):
                        problems.append({f"region_{place}_non_known_reason": region})

    if problems:
        raise AskExtentNotSupported(json.dumps(problems, sort_keys=True))
