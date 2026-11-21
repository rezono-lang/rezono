"""Boundaries of free `ask ... where ... show` queries over role publications
(decisions/ask-query-boundaries.md)."""

from __future__ import annotations

import json
from pathlib import Path
import subprocess

import pytest

PROBE = Path(__file__).with_name("ask-query-boundaries-probe.mts")


class MissingGroupedAggregates(AssertionError):
    """Grouped aggregates (`group by` with count/sum/min/max, four states, witnesses, role filter) are not served."""


class MissingCrossPackJoin(AssertionError):
    """Multi-binder `ask` combining relations from multiple imported packs with role filter and witnesses is not served."""


class MissingLocalAskRule(AssertionError):
    """Read-only bounded local rules defined during `ask` with witnesses and refusals are not served."""


def _run_probe(mode: str) -> dict:
    result = subprocess.run(
        ["node", str(PROBE), mode],
        cwd=PROBE.parent.parent,
        capture_output=True,
        encoding="utf-8",
    )
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout)


def _diag_codes(reply: dict) -> list[str]:
    body = reply.get("body")
    if not isinstance(body, dict):
        return []
    diags = body.get("diagnostics")
    if not isinstance(diags, list):
        return []
    return [d["code"] for d in diags if isinstance(d, dict) and isinstance(d.get("code"), str)]


def _rows_by_group(body: dict) -> dict[str, dict]:
    rows = body.get("dataset", {}).get("rows", [])
    out: dict[str, dict] = {}
    for row in rows:
        if row.get("$kind") != "Answer":
            continue
        c1 = row.get("c1")
        if isinstance(c1, dict) and isinstance(c1.get("$ref"), str):
            key = c1["$ref"].rsplit("/", 1)[-1]
        else:
            key = str(c1)
        out[key] = row
    return out


def _as_exact_number(val: object) -> str | None:
    if isinstance(val, bool):
        return None
    if isinstance(val, int):
        return str(val)
    if isinstance(val, str):
        return val
    return None


@pytest.mark.xfail(
    strict=True,
    raises=MissingGroupedAggregates,
    reason=(
        "extra: decisions/ask-query-boundaries.md: Support `group by` with `count`, `sum`, "
        "`min`, and `max` in `ask` (rezono/src/parse.ts, check.ts, evaluate.ts, answer-schema.ts, "
        "edge/gate/src/expr.ts, edge/gate/src/local.ts) preserving four value states "
        "(known, absent/n/a, unknown, invalid), role filtering, and contributor witnesses."
    ),
)
def test_ask_grouped_aggregates_four_states_witness_and_role_filter():
    got = _run_probe("grouped")

    # Baseline checks that already hold on current main (plain AssertionError if broken).
    assert got["baseline_ok"]["status"] == 200, got["baseline_ok"]
    assert got["baseline_ok"]["body"]["counts"] == {"rows": 3, "undecided": 0, "not_applicable": 1}
    assert got["baseline_unknown_kind"]["status"] == 400, got["baseline_unknown_kind"]
    assert "R001" in _diag_codes(got["baseline_unknown_kind"])

    # 1. Grouped count/sum/min/max over known and absent (n/a) groups, with absent group key counted.
    weight_reply = got["grouped_weight"]
    if weight_reply["status"] != 200:
        raise MissingGroupedAggregates(f"grouped weight query failed: {weight_reply}")
    weight_body = weight_reply["body"]
    by_group = _rows_by_group(weight_body)
    if "g-ok" not in by_group or "g-absent" not in by_group:
        raise MissingGroupedAggregates(f"expected g-ok and g-absent groups, got {list(by_group)}")
    ok_row = by_group["g-ok"]
    if (
        _as_exact_number(ok_row.get("c2")) != "2"
        or _as_exact_number(ok_row.get("c3")) != "40"
        or _as_exact_number(ok_row.get("c4")) != "10"
        or _as_exact_number(ok_row.get("c5")) != "30"
    ):
        raise MissingGroupedAggregates(f"g-ok aggregate mismatch: {ok_row}")
    # Absent (n/a) optional weight on e4 must propagate as $na in sum/min/max, never 0, while count() is 2.
    absent_row = by_group["g-absent"]
    if (
        _as_exact_number(absent_row.get("c2")) != "2"
        or not (isinstance(absent_row.get("c3"), dict) and "$na" in absent_row["c3"])
        or not (isinstance(absent_row.get("c4"), dict) and "$na" in absent_row["c4"])
        or not (isinstance(absent_row.get("c5"), dict) and "$na" in absent_row["c5"])
    ):
        raise MissingGroupedAggregates(f"g-absent must preserve n/a state (never 0): {absent_row}")
    # Entry e9 has no bucket (n/a group key): excluded from groups and counted in not_applicable.
    if weight_body.get("counts", {}).get("not_applicable", 0) < 1 or len(by_group) != 4:
        raise MissingGroupedAggregates(f"absent group key handling wrong: {weight_body.get('counts')} / {list(by_group)}")

    # Contributor witnesses and steps must ground g-ok in e1 and e2.
    witnesses = weight_body.get("witnesses") or []
    steps = weight_body.get("steps") or []
    contrib_keys = {s.get("premise", {}).get("key") for s in steps if isinstance(s, dict) and s.get("how") == "contributes"}
    if not witnesses or not any("e1" in (k or "") for k in contrib_keys) or not any("e2" in (k or "") for k in contrib_keys):
        raise MissingGroupedAggregates(f"missing contributor witnesses/steps for g-ok: witnesses={witnesses}, steps={steps}")

    # 2. Unknown state propagation (missing required score on e6 must make g-unknown $unknown, never 0 or 5).
    score_reply = got["grouped_score_unknown"]
    if score_reply["status"] != 200:
        raise MissingGroupedAggregates(f"grouped score query failed: {score_reply}")
    unknown_row = _rows_by_group(score_reply["body"]).get("g-unknown")
    if not unknown_row or not all(
        isinstance(unknown_row.get(col), dict) and "$unknown" in unknown_row[col] for col in ("c2", "c3", "c4")
    ):
        raise MissingGroupedAggregates(f"g-unknown must propagate $unknown state: {unknown_row}")

    # 3. Invalid state propagation (100 / 0 on e7 must make g-invalid $invalid).
    invalid_reply = got["grouped_invalid_div"]
    if invalid_reply["status"] != 200:
        raise MissingGroupedAggregates(f"grouped invalid query failed: {invalid_reply}")
    invalid_row = _rows_by_group(invalid_reply["body"]).get("g-invalid")
    if not invalid_row or not all(
        isinstance(invalid_row.get(col), dict) and "$invalid" in invalid_row[col] for col in ("c2", "c3", "c4")
    ):
        raise MissingGroupedAggregates(f"g-invalid must propagate $invalid state: {invalid_row}")

    # 4. Counter-cases: role-filtered partial snapshots MUST be refused with R004 (never answered as complete).
    for label in ("counter_partial_slot", "counter_scoped_partial"):
        reply = got[label]
        codes = _diag_codes(reply)
        if reply["status"] != 400 or "R004" not in codes or "R015" in codes:
            raise MissingGroupedAggregates(f"{label} must fail closed with R004, got {reply}")


@pytest.mark.xfail(
    strict=True,
    raises=MissingCrossPackJoin,
    reason=(
        "extra: decisions/ask-query-boundaries.md: Support multi-binder `ask` combining "
        "relations from multiple imported packs (rezono/src/parse.ts, check.ts, evaluate.ts, "
        "answer-schema.ts, edge/gate/src/expr.ts, edge/gate/src/local.ts) with role-filtered "
        "snapshots and published witnesses."
    ),
)
def test_ask_combines_relations_from_multiple_imported_packs_with_role_filter_and_witness():
    got = _run_probe("cross_pack")

    # Baseline checks that already hold on current main (plain AssertionError if broken).
    assert got["baseline_single_pack"]["status"] == 200, got["baseline_single_pack"]
    assert got["baseline_single_pack"]["body"]["counts"]["rows"] == 1
    assert got["baseline_unauthorized_single"]["status"] == 400, got["baseline_unauthorized_single"]
    assert "R001" in _diag_codes(got["baseline_unauthorized_single"])

    # 1. Reader joins alpha_tag (pack_alpha) and beta_metric (pack_beta) in one ask with witnesses.
    reader_reply = got["reader_join"]
    if reader_reply["status"] != 200:
        raise MissingCrossPackJoin(f"cross-pack join failed for reader: {reader_reply}")
    reader_body = reader_reply["body"]
    answer_rows = [r for r in reader_body.get("dataset", {}).get("rows", []) if r.get("$kind") == "Answer"]
    pairs = sorted((r.get("c2"), r.get("c3")) for r in answer_rows)
    if pairs != [("gold", "high"), ("silver", "low")]:
        raise MissingCrossPackJoin(f"expected joined cross-pack pairs, got {pairs}")

    witnesses = reader_body.get("witnesses") or []
    rule_ids = {w.get("rule_id") for w in witnesses if isinstance(w, dict)}
    if not {"pack_alpha.tag_rule", "pack_beta.metric_rule"} <= rule_ids:
        raise MissingCrossPackJoin(f"cross-pack join must attach published witnesses from both packs: {witnesses}")

    # 2. Counter-case: role with access to only pack_alpha MUST be refused with R001 (no R015, no leak).
    alpha_reply = got["alpha_only_join"]
    alpha_codes = _diag_codes(alpha_reply)
    if alpha_reply["status"] != 400 or "R001" not in alpha_codes or "R015" in alpha_codes:
        raise MissingCrossPackJoin(f"alpha-only role must be refused with R001, got {alpha_reply}")

    # 3. Counter-case: narrow role sees only i-1 and zero leakage of i-2 in rows or witnesses.
    narrow_reply = got["narrow_join"]
    if narrow_reply["status"] != 200:
        raise MissingCrossPackJoin(f"narrow role cross-pack join failed: {narrow_reply}")
    narrow_body = narrow_reply["body"]
    narrow_text = json.dumps(narrow_body, sort_keys=True)
    narrow_rows = [r for r in narrow_body.get("dataset", {}).get("rows", []) if r.get("$kind") == "Answer"]
    narrow_pairs = [(r.get("c2"), r.get("c3")) for r in narrow_rows]
    if narrow_pairs != [("gold", "high")] or any(secret in narrow_text for secret in ("i-2", "silver", "low")):
        raise MissingCrossPackJoin(f"narrow role leaked hidden cross-pack rows or witnesses: {narrow_body}")
    narrow_rule_ids = {w.get("rule_id") for w in (narrow_body.get("witnesses") or []) if isinstance(w, dict)}
    if not {"pack_alpha.tag_rule", "pack_beta.metric_rule"} <= narrow_rule_ids:
        raise MissingCrossPackJoin(f"narrow role missing witnesses for its visible joined row: {narrow_body}")


@pytest.mark.xfail(
    strict=True,
    raises=MissingLocalAskRule,
    reason=(
        "extra: decisions/ask-query-boundaries.md: Support read-only, bounded local rules "
        "defined during `ask` over the role's pinned publication (rezono/src/, "
        "edge/gate/src/expr.ts, edge/gate/src/local.ts), returning derived answers with "
        "witnesses (as in decisions/local-suppose.md) while refusing writes, unauthorized "
        "relations, unsafe/unstratified recursion, and over-budget evaluation."
    ),
)
def test_ask_local_rule_is_read_only_bounded_authorized_and_witnessed():
    got = _run_probe("local_rule")

    # Baseline checks that already hold on current main (plain AssertionError if broken).
    assert got["store_unchanged"] is True, "local ask mutated the publication store"
    assert got["baseline_ok"]["status"] == 200, got["baseline_ok"]
    assert got["baseline_ok"]["body"]["counts"] == {"rows": 2, "undecided": 1, "not_applicable": 0}
    assert got["baseline_write_refused"]["status"] == 405, got["baseline_write_refused"]
    assert got["baseline_suppose_in_ask_refused"]["status"] == 400, got["baseline_suppose_in_ask_refused"]

    # 1. Reader evaluates a request-local rule with computed=True, four-valued undecided row, and witnesses.
    reader_reply = got["reader_local_rule"]
    if reader_reply["status"] != 200:
        raise MissingLocalAskRule(f"local rule ask failed for reader: {reader_reply}")
    reader_body = reader_reply["body"]
    if reader_body.get("computed") is not True:
        raise MissingLocalAskRule(f"local rule answer must set computed=True: {reader_body}")
    reader_ids = sorted(
        r["$id"] for r in reader_body.get("dataset", {}).get("rows", []) if r.get("$kind") == "Answer"
    )
    undecided_ids = [u.get("binder") for u in reader_body.get("undecided", []) if u.get("state") == "unknown"]
    if reader_ids != ["i-1", "i-3"] or undecided_ids != ["i-4"]:
        raise MissingLocalAskRule(f"local rule answer rows/undecided mismatch: ids={reader_ids}, undecided={undecided_ids}")

    witnesses = reader_body.get("witnesses") or []
    witness_text = json.dumps(witnesses, sort_keys=True)
    if not witnesses or "high_score" not in witness_text or "item__score" not in witness_text:
        raise MissingLocalAskRule(f"local rule answer must carry witnesses citing high_score and item__score: {witnesses}")

    # 2. Scoped role evaluates the same local rule strictly over its visible rows (i-3 hidden).
    scoped_reply = got["scoped_local_rule"]
    if scoped_reply["status"] != 200:
        raise MissingLocalAskRule(f"local rule ask failed for scoped role: {scoped_reply}")
    scoped_body = scoped_reply["body"]
    scoped_text = json.dumps(scoped_body, sort_keys=True)
    scoped_ids = [r["$id"] for r in scoped_body.get("dataset", {}).get("rows", []) if r.get("$kind") == "Answer"]
    if scoped_ids != ["i-1"] or "i-3" in scoped_text or "95" in scoped_text:
        raise MissingLocalAskRule(f"scoped role leaked hidden rows or witnesses: {scoped_body}")

    # 3. Counter-case: write/mutation attempt inside rules MUST be refused (400) with zero store mutation.
    write_reply = got["counter_write_in_rules"]
    if write_reply["status"] != 400 or not _diag_codes(write_reply):
        raise MissingLocalAskRule(f"write attempt inside local rules must be refused with diagnostics: {write_reply}")

    # 4. Counter-case: unauthorized slot in local rule MUST be refused with R001.
    unauth_reply = got["counter_unauthorized_slot"]
    if unauth_reply["status"] != 400 or "R001" not in _diag_codes(unauth_reply):
        raise MissingLocalAskRule(f"unauthorized local rule must fail closed with R001: {unauth_reply}")

    # 5. Counter-case: unstratified negation in local rule MUST be refused with R043.
    unstrat_reply = got["counter_unstratified"]
    if unstrat_reply["status"] != 400 or "R043" not in _diag_codes(unstrat_reply):
        raise MissingLocalAskRule(f"unstratified local rule must fail closed with R043: {unstrat_reply}")

    # 6. Counter-case: bounded step budget MUST cut cleanly instead of hanging or returning partial answers.
    budget_cut = got["budget_cut"]
    if not (isinstance(budget_cut, dict) and budget_cut.get("cut") == {"budget": "steps", "limit": 2}):
        raise MissingLocalAskRule(f"local rule evaluation must respect step budget cut: {budget_cut}")
