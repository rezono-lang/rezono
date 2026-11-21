"""End-to-end bitemporal history publication for `examples/zorgtoeslag-slice`
(decisions/bitemporal-history-publication.md).

Publishes 4 successive `(as_of, known)` main epochs into one store and serves them through
`edge/gate/src/local.ts`, proving:
- `bob` transitions `unknown -> 10500` across `2025-12-01` (`m-1` -> `m-2`), and
- `gus` shows the `2026-04-15` retroactive correction `13500 -> 8500` (`m-3` -> `m-4`).
"""

from __future__ import annotations

from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
import zorgtoeslag_history_support as support


EPOCHS = [
    ("2026-02-01", "2025-11-15"),  # m-1: bob has no 2026 income known yet -> unknown
    ("2026-02-01", "2025-12-01"),  # m-2: bob's 2026 income becomes known -> 10500
    ("2026-01-01", "2026-02-01"),  # m-3: gus's initial 2026 income estimate -> 13500
    ("2026-01-01", "2026-05-01"),  # m-4: gus's 2026-04-15 retroactive correction -> 8500
]


def _allowance_schema(bundle_body: dict) -> tuple[str, dict[str, int]]:
    """Locate the published `allowance` calculation relation and its column indices by name."""
    rel = next(
        (r for r in bundle_body.get("relations") or [] if r.get("calc") == "allowance"),
        None,
    )
    assert rel is not None, f"bundle relations missing calc=='allowance': {bundle_body.get('relations')}"
    col_index = {col["name"]: i for i, col in enumerate(rel["columns"])}
    assert {"subject", "state", "value"} <= col_index.keys(), col_index
    return str(rel["id"]), col_index


def _allowance_by_household(rows_body: dict, col_index: dict[str, int]) -> dict[str, tuple[str, str]]:
    """Map household id -> (state, value) using published schema column names."""
    i_subject = col_index["subject"]
    i_state = col_index["state"]
    i_value = col_index["value"]
    out: dict[str, tuple[str, str]] = {}
    for entry in rows_body["rows"]:
        key = entry["key"]
        out[str(key[i_subject])] = (str(key[i_state]), str(key[i_value]))
    return out


def test_bitemporal_history_served_by_local_gate(tmp_path):
    store_dir, manifests = support.publish_history(tmp_path, EPOCHS)
    assert [m["id"] for m in manifests] == ["m-1", "m-2", "m-3", "m-4"]

    # Query /head (latest), /bundle (published schema), and every historical /head?m=m-1..m-4.
    responses = support.ask(
        store_dir,
        "checker",
        "/zorgtoeslag-slice/head",
        "/zorgtoeslag-slice/bundle",
        "/zorgtoeslag-slice/head?m=m-1",
        "/zorgtoeslag-slice/head?m=m-2",
        "/zorgtoeslag-slice/head?m=m-3",
        "/zorgtoeslag-slice/head?m=m-4",
    )
    head_latest, bundle_resp, *epoch_heads = responses
    assert head_latest["status"] == 200 and head_latest["body"]["witness_check"] == "green", head_latest
    assert head_latest["body"]["id"] == "m-4"
    assert bundle_resp["status"] == 200, bundle_resp

    for idx, (_as_of, known) in enumerate(EPOCHS, start=1):
        resp = epoch_heads[idx - 1]
        assert resp["status"] == 200, resp
        head = resp["body"]
        assert head["witness_check"] == "green"
        assert head["id"] == f"m-{idx}"
        assert head["knowledge_time"] == f"{known}T00:00:00Z"

    allowance_rel, col_index = _allowance_schema(bundle_resp["body"])

    row_responses = support.ask(
        store_dir,
        "checker",
        f"/zorgtoeslag-slice/m-1/rows/{allowance_rel}",
        f"/zorgtoeslag-slice/m-2/rows/{allowance_rel}",
        f"/zorgtoeslag-slice/m-3/rows/{allowance_rel}",
        f"/zorgtoeslag-slice/m-4/rows/{allowance_rel}",
    )
    for resp in row_responses:
        assert resp["status"] == 200, resp

    m1 = _allowance_by_household(row_responses[0]["body"], col_index)
    m2 = _allowance_by_household(row_responses[1]["body"], col_index)
    m3 = _allowance_by_household(row_responses[2]["body"], col_index)
    m4 = _allowance_by_household(row_responses[3]["body"], col_index)

    # bob transitions unknown -> 10500 across 2025-12-01 (never collapsing unknown to 0).
    assert m1["bob"] == ("unknown", ""), m1["bob"]
    assert m2["bob"] == ("known", "10500"), m2["bob"]

    # gus shows the 2026-04-15 retroactive correction on January 2026: 13500 -> 8500.
    assert m3["gus"] == ("known", "13500"), m3["gus"]
    assert m4["gus"] == ("known", "8500"), m4["gus"]


def test_dated_totality_parameter_fails_closed():
    """decisions/bitemporal-history-publication.md §1.1: `dated_totality="warning"` requires both
    `as_of` and `known`, and unknown values are refused with `Blocked`."""
    import pytest
    from rezono_publisher import batch

    with pytest.raises(batch.Blocked, match="requires both as_of and known"):
        batch.epoch(
            support.SLICE,
            epoch=1,
            knowledge_time="2026-02-01T00:00:00Z",
            sources=[("facts", "test")],
            dated_totality="warning",
        )
    with pytest.raises(batch.Blocked, match="dated_totality must be"):
        batch.epoch(
            support.SLICE,
            epoch=1,
            knowledge_time="2026-02-01T00:00:00Z",
            sources=[("facts", "test")],
            as_of="2026-02-01",
            known="2026-02-01",
            dated_totality="ignore",
        )
