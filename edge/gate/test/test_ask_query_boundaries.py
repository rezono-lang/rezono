"""Boundaries of free `ask ... where ... show` queries over role publications
(decisions/ask-query-boundaries.md)."""

from __future__ import annotations

import hashlib
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
    """Read-only bounded local derivations defined during `ask` with witnesses and refusals are not served."""


def _canonical_sha256(value: object) -> str:
    """SHA-256 of canonical JSON (RFC 8785 for nested string arrays)."""
    encoded = json.dumps(value, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


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


def _parse_key(raw: object) -> tuple[str, ...] | None:
    if not isinstance(raw, str):
        return None
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        return None
    if isinstance(parsed, list) and all(isinstance(part, str) for part in parsed):
        return tuple(parsed)
    return None


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


def _witness_tuples(witnesses: object) -> set[tuple[str, str, tuple[str, ...]]]:
    out: set[tuple[str, str, tuple[str, ...]]] = set()
    if not isinstance(witnesses, list):
        return out
    for w in witnesses:
        if not isinstance(w, dict):
            continue
        rule_id = w.get("rule_id")
        concl = w.get("conclusion")
        if not isinstance(rule_id, str) or not isinstance(concl, dict):
            continue
        rel = concl.get("relation")
        key = _parse_key(concl.get("key"))
        if isinstance(rel, str) and key is not None:
            out.add((rule_id, rel, key))
    return out


def _premise_rows(witness: dict) -> set[tuple[str, tuple[str, ...]]]:
    out: set[tuple[str, tuple[str, ...]]] = set()
    for p in witness.get("premises") or []:
        if not isinstance(p, dict):
            continue
        row = p.get("row")
        if not isinstance(row, dict):
            continue
        rel = row.get("relation")
        key = _parse_key(row.get("key"))
        if isinstance(rel, str) and key is not None:
            out.add((rel, key))
    return out


def _all_row_keys(body: dict) -> set[tuple[str, ...]]:
    """Every canonical key tuple appearing in nodes, witnesses (conclusions and premises), and steps."""
    keys: set[tuple[str, ...]] = set()
    for node in body.get("nodes") or []:
        if isinstance(node, dict) and (parsed := _parse_key(node.get("key"))) is not None:
            keys.add(parsed)
    for w in body.get("witnesses") or []:
        if not isinstance(w, dict):
            continue
        concl = w.get("conclusion")
        if isinstance(concl, dict) and (parsed := _parse_key(concl.get("key"))) is not None:
            keys.add(parsed)
        for _, pkey in _premise_rows(w):
            keys.add(pkey)
    for step in body.get("steps") or []:
        if not isinstance(step, dict):
            continue
        for end in ("conclusion", "premise"):
            ref = step.get(end)
            if isinstance(ref, dict) and (parsed := _parse_key(ref.get("key"))) is not None:
                keys.add(parsed)
    return keys


@pytest.mark.xfail(
    strict=True,
    raises=MissingGroupedAggregates,
    reason=(
        "extra: decisions/ask-query-boundaries.md: Support `group by` with `count`, `sum`, "
        "`min`, and `max` in `ask` under `{ allowAskExtensions: true }` (rezono/src/parse.ts, "
        "check.ts, evaluate.ts, answer-schema.ts, edge/gate/src/expr.ts, edge/gate/src/local.ts) "
        "preserving four value states (known, absent/n/a, unknown, invalid), role filtering, and "
        "canonical contributor witnesses."
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

    # Pinned aggregate witness shape (decisions/ask-query-boundaries.md §3, matching explain.py):
    # group_key is canonical JSON '["g-ok"]', count == 2, and contributors_sha256 equals exact digest.
    expected_count_sha = _canonical_sha256([['["e1"]'], ['["e2"]']])
    expected_weight_sha = _canonical_sha256([['["e1","10"]', "known:10"], ['["e2","30"]', "known:30"]])
    expected_ok_aggs = {
        (0, "entry", '["g-ok"]', 2, expected_count_sha, "known:2"),
        (1, "entry__weight", '["g-ok"]', 2, expected_weight_sha, "known:40"),
        (2, "entry__weight", '["g-ok"]', 2, expected_weight_sha, "known:10"),
        (3, "entry__weight", '["g-ok"]', 2, expected_weight_sha, "known:30"),
    }
    witnesses = weight_body.get("witnesses") or []
    ok_aggs = {
        (
            agg.get("position"),
            agg.get("relation"),
            agg.get("group_key"),
            agg.get("count"),
            agg.get("contributors_sha256"),
            agg.get("result"),
        )
        for w in witnesses
        if isinstance(w, dict)
        for agg in (w.get("aggregates") or [])
        if isinstance(agg, dict) and agg.get("group_key") == '["g-ok"]'
    }
    if ok_aggs != expected_ok_aggs:
        raise MissingGroupedAggregates(
            f"g-ok aggregate witnesses mismatch: expected={sorted(expected_ok_aggs)}, got={sorted(ok_aggs)}"
        )

    # Pinned contributes step shape (matching trace.py / edge/gate/src/ask.ts):
    steps = weight_body.get("steps") or []
    contrib_steps = {
        (step.get("position"), step["premise"].get("relation"), _parse_key(step["premise"].get("key")), step.get("value"))
        for step in steps
        if isinstance(step, dict)
        and step.get("how") == "contributes"
        and isinstance(step.get("premise"), dict)
    }
    expected_contrib_steps = {
        (0, "entry", ("e1",), None),
        (0, "entry", ("e2",), None),
        (1, "entry__weight", ("e1", "10"), "known:10"),
        (1, "entry__weight", ("e2", "30"), "known:30"),
        (2, "entry__weight", ("e1", "10"), "known:10"),
        (2, "entry__weight", ("e2", "30"), "known:30"),
        (3, "entry__weight", ("e1", "10"), "known:10"),
        (3, "entry__weight", ("e2", "30"), "known:30"),
    }
    if not expected_contrib_steps <= contrib_steps:
        raise MissingGroupedAggregates(
            f"missing exact contributes steps for g-ok: expected>={sorted(expected_contrib_steps)}, got={sorted(contrib_steps)}"
        )

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
        "relations from multiple imported packs under `{ allowAskExtensions: true }` "
        "(rezono/src/parse.ts, check.ts, evaluate.ts, answer-schema.ts, edge/gate/src/expr.ts, "
        "edge/gate/src/local.ts) with role-filtered snapshots and published witnesses."
    ),
)
def test_ask_combines_relations_from_multiple_imported_packs_with_role_filter_and_witness():
    got = _run_probe("cross_pack")

    # Baseline checks that already hold on current main (plain AssertionError if broken).
    assert got["baseline_single_pack"]["status"] == 200, got["baseline_single_pack"]
    assert got["baseline_single_pack"]["body"]["counts"]["rows"] == 1
    assert got["baseline_unauthorized_single"]["status"] == 400, got["baseline_unauthorized_single"]
    assert "R001" in _diag_codes(got["baseline_unauthorized_single"])

    # 1. Reader joins alpha_tag (pack_alpha) and beta_metric (pack_beta) in one ask with exact witnesses.
    reader_reply = got["reader_join"]
    if reader_reply["status"] != 200:
        raise MissingCrossPackJoin(f"cross-pack join failed for reader: {reader_reply}")
    reader_body = reader_reply["body"]
    answer_rows = [r for r in reader_body.get("dataset", {}).get("rows", []) if r.get("$kind") == "Answer"]
    pairs = sorted((r.get("c2"), r.get("c3")) for r in answer_rows)
    if pairs != [("gold", "high"), ("silver", "low")]:
        raise MissingCrossPackJoin(f"expected joined cross-pack pairs, got {pairs}")

    expected_reader_witnesses = {
        ("pack_alpha.tag_rule", "alpha_tag", ("i-1", "gold")),
        ("pack_alpha.tag_rule", "alpha_tag", ("i-2", "silver")),
        ("pack_beta.metric_rule", "beta_metric", ("i-1", "high")),
        ("pack_beta.metric_rule", "beta_metric", ("i-2", "low")),
    }
    reader_witnesses = _witness_tuples(reader_body.get("witnesses"))
    if not expected_reader_witnesses <= reader_witnesses:
        raise MissingCrossPackJoin(
            f"cross-pack join must attach exact published witnesses from both packs: {sorted(reader_witnesses)}"
        )

    # 2. Counter-case: role with access to only pack_alpha MUST be refused with R001 (no R015, no leak).
    alpha_reply = got["alpha_only_join"]
    alpha_codes = _diag_codes(alpha_reply)
    if alpha_reply["status"] != 400 or "R001" not in alpha_codes or "R015" in alpha_codes:
        raise MissingCrossPackJoin(f"alpha-only role must be refused with R001, got {alpha_reply}")

    # 3. Counter-case: narrow role sees only i-1 with exact rows, counts, and witnesses (zero i-2 rows/keys).
    narrow_reply = got["narrow_join"]
    if narrow_reply["status"] != 200:
        raise MissingCrossPackJoin(f"narrow role cross-pack join failed: {narrow_reply}")
    narrow_body = narrow_reply["body"]
    narrow_rows = [r for r in narrow_body.get("dataset", {}).get("rows", []) if r.get("$kind") == "Answer"]
    narrow_pairs = [(r.get("c2"), r.get("c3")) for r in narrow_rows]
    expected_narrow_witnesses = {
        ("pack_alpha.tag_rule", "alpha_tag", ("i-1", "gold")),
        ("pack_beta.metric_rule", "beta_metric", ("i-1", "high")),
    }
    narrow_witnesses = _witness_tuples(narrow_body.get("witnesses"))
    narrow_keys = _all_row_keys(narrow_body)
    hidden_tokens = {"i-2", "silver", "low"}
    leaked_keys = [k for k in narrow_keys if any(part in hidden_tokens for part in k)]
    if (
        narrow_pairs != [("gold", "high")]
        or narrow_body.get("counts") != {"rows": 1, "undecided": 0, "not_applicable": 0}
        or narrow_body.get("undecided") != []
        or narrow_witnesses != expected_narrow_witnesses
        or leaked_keys
    ):
        raise MissingCrossPackJoin(
            f"narrow role join mismatch or hidden key leak: pairs={narrow_pairs}, "
            f"witnesses={sorted(narrow_witnesses)}, leaked_keys={leaked_keys}"
        )


@pytest.mark.xfail(
    strict=True,
    raises=MissingLocalAskRule,
    reason=(
        "extra: decisions/ask-query-boundaries.md: Support read-only, bounded rezono 1 local "
        "derivations defined during `ask` over the role's pinned publication (rezono/src/, "
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

    # 1. Reader evaluates a request-local rezono 1 derivation with computed=True, undecided row, and exact witnesses.
    reader_reply = got["reader_local_rule"]
    if reader_reply["status"] != 200:
        raise MissingLocalAskRule(f"local derivation ask failed for reader: {reader_reply}")
    reader_body = reader_reply["body"]
    if reader_body.get("computed") is not True:
        raise MissingLocalAskRule(f"local derivation answer must set computed=True: {reader_body}")
    reader_rows = sorted(
        (r["$id"], _as_exact_number(r.get("c1")))
        for r in reader_body.get("dataset", {}).get("rows", [])
        if r.get("$kind") == "Answer"
    )
    undecided_ids = [u.get("binder") for u in reader_body.get("undecided", []) if u.get("state") == "unknown"]
    if reader_rows != [("i-1", "80"), ("i-3", "95")] or undecided_ids != ["i-4"]:
        raise MissingLocalAskRule(f"local derivation answer rows/undecided mismatch: rows={reader_rows}, undecided={undecided_ids}")

    # Pinned local derivation witness shape (decisions/ask-query-boundaries.md §5):
    # conclusion relation == "high_score", key == '["<id>"]', base slot premise == ("item__score", ("<id>", "<v>")).
    witnesses = [
        w
        for w in (reader_body.get("witnesses") or [])
        if isinstance(w, dict)
        and w.get("rule_id") == "high_score"
        and isinstance(w.get("conclusion"), dict)
        and w["conclusion"].get("relation") == "high_score"
    ]
    by_conclusion = {_parse_key(w["conclusion"].get("key")): w for w in witnesses}
    w1 = by_conclusion.get(("i-1",))
    w3 = by_conclusion.get(("i-3",))
    if not w1 or not w3:
        raise MissingLocalAskRule(f"local derivation answer must carry high_score witnesses for exact keys i-1 and i-3: {witnesses}")
    if ("item__score", ("i-1", "80")) not in _premise_rows(w1):
        raise MissingLocalAskRule(f"i-1 witness missing exact item__score premise ('i-1', '80'): {w1}")
    if ("item__score", ("i-3", "95")) not in _premise_rows(w3):
        raise MissingLocalAskRule(f"i-3 witness missing exact item__score premise ('i-3', '95'): {w3}")

    # 2. Scoped role evaluates the same local derivation strictly over its visible rows (exact rows/keys/witnesses).
    scoped_reply = got["scoped_local_rule"]
    if scoped_reply["status"] != 200:
        raise MissingLocalAskRule(f"local derivation ask failed for scoped role: {scoped_reply}")
    scoped_body = scoped_reply["body"]
    scoped_rows = [
        (r["$id"], _as_exact_number(r.get("c1")))
        for r in scoped_body.get("dataset", {}).get("rows", [])
        if r.get("$kind") == "Answer"
    ]
    scoped_undecided = [u.get("binder") for u in scoped_body.get("undecided", []) if u.get("state") == "unknown"]
    scoped_witnesses = {
        _parse_key(w["conclusion"].get("key")): w
        for w in (scoped_body.get("witnesses") or [])
        if isinstance(w, dict)
        and w.get("rule_id") == "high_score"
        and isinstance(w.get("conclusion"), dict)
        and w["conclusion"].get("relation") == "high_score"
    }
    scoped_keys = _all_row_keys(scoped_body)
    leaked_scoped_keys = [k for k in scoped_keys if any(part in {"i-3", "95"} for part in k)]
    if (
        scoped_rows != [("i-1", "80")]
        or scoped_undecided != ["i-4"]
        or scoped_body.get("counts") != {"rows": 1, "undecided": 1, "not_applicable": 0}
        or set(scoped_witnesses) != {("i-1",)}
        or ("item__score", ("i-1", "80")) not in _premise_rows(scoped_witnesses[("i-1",)])
        or leaked_scoped_keys
    ):
        raise MissingLocalAskRule(
            f"scoped role mismatch or hidden key leak: rows={scoped_rows}, undecided={scoped_undecided}, "
            f"witnesses={list(scoped_witnesses)}, leaked_keys={leaked_scoped_keys}"
        )

    # 3. Counter-case: write/mutation attempt inside rules MUST be refused (400) with zero store mutation.
    write_reply = got["counter_write_in_rules"]
    if write_reply["status"] != 400 or not _diag_codes(write_reply):
        raise MissingLocalAskRule(f"write attempt inside local rules must be refused with diagnostics: {write_reply}")

    # 4. Counter-case: unauthorized slot in local derivation MUST be refused with R001.
    unauth_reply = got["counter_unauthorized_slot"]
    if unauth_reply["status"] != 400 or "R001" not in _diag_codes(unauth_reply):
        raise MissingLocalAskRule(f"unauthorized local derivation must fail closed with R001: {unauth_reply}")

    # 5. Counter-case: unstratified negation in local derivation MUST be refused with R043.
    unstrat_reply = got["counter_unstratified"]
    if unstrat_reply["status"] != 400 or "R043" not in _diag_codes(unstrat_reply):
        raise MissingLocalAskRule(f"unstratified local derivation must fail closed with R043: {unstrat_reply}")

    # 6. Counter-case: bounded step budget MUST cut cleanly instead of hanging or returning partial answers.
    budget_cut = got["budget_cut"]
    if not (isinstance(budget_cut, dict) and budget_cut.get("cut") == {"budget": "steps", "limit": 2}):
        raise MissingLocalAskRule(f"local derivation evaluation must respect step budget cut: {budget_cut}")
