"""Executable planner red tests for reader-served seal fields (decisions/reader-served-seal-fields.md, #1451).

Verifies that the local reader serves:
1. trust_tier and role-scoped may_propose (both positive grant and negative zero-leak) on GET /<pack>/head;
2. reader_hashes (with per-witness piece_sha256) on GET /<pack>/<manifest>/ask/grounds;
3. declared origin_sign on served fact sources (and omits origin_sign when undeclared).
"""

import hashlib
import json

import pytest
import yaml
from slip_support import PACK, ask, publish_main, row_query


def _head(store, role="reader") -> dict:
    [answer] = ask(store, role, f"/{PACK}/head")
    assert answer["status"] == 200, answer
    return answer["body"]


@pytest.mark.xfail(
    strict=True,
    raises=AssertionError,
    reason="M2: decisions/reader-served-seal-fields.md (#1451): GET /<pack>/head must serve trust_tier and role-scoped may_propose",
)
def test_head_serves_trust_tier_and_may_propose(tmp_path):
    store, manifest = publish_main(tmp_path / "plain")
    got = _head(store, role="reader")
    assert got.get("trust_tier") == "sealed", f"expected trust_tier='sealed', got {sorted(got)}"
    assert got.get("may_propose") is False, f"expected may_propose=False for reader without grants, got {got.get('may_propose')!r}"

    # When the manifest has no rezono:proofs witness_check, trust_tier must be provisional_checked.
    manifest_path = store / PACK / "manifests" / f"{manifest['id']}.json"
    document = json.loads(manifest_path.read_bytes())
    document["checks"] = [c for c in document["checks"] if c["name"] != "rezono:proofs"]
    data = json.dumps(document, sort_keys=True, separators=(",", ":")).encode("utf-8")
    manifest_path.write_bytes(data)
    [head_file] = sorted((store / PACK / "heads").glob("*.json"))
    pointer = json.loads(head_file.read_bytes())
    pointer["sha256"] = hashlib.sha256(data).hexdigest()
    head_file.write_bytes(json.dumps(pointer, separators=(",", ":")).encode("utf-8"))

    without = _head(store, role="reader")
    assert without.get("trust_tier") == "provisional_checked"
    assert without.get("may_propose") is False

    # Positive role-scoped may_propose: grant propose capability to reader only; summary must stay False (zero leak).
    def _grant_reader_propose(pack_dir):
        rows_path = pack_dir / "facts" / "rows.yaml"
        rows = yaml.safe_load(rows_path.read_text(encoding="utf-8"))
        for role_row in rows["role"]:
            if role_row["id"] == "reader":
                role_row["capability"] = [*role_row["capability"], "propose"]
        rows_path.write_text(yaml.safe_dump(rows, sort_keys=False), encoding="utf-8")
        access_path = pack_dir / "rules" / "access.dl"
        access_path.write_text(
            access_path.read_text(encoding="utf-8")
            + '\n.decl may_propose(role: symbol, kind: symbol, element: symbol)\n'
            + 'may_propose(r, "item", i) :- role__capability(r, "propose"), item(i).\n',
            encoding="utf-8",
        )

    granted_store, _ = publish_main(tmp_path / "with_propose", change=_grant_reader_propose)
    assert _head(granted_store, role="reader").get("may_propose") is True
    assert _head(granted_store, role="summary").get("may_propose") is False


@pytest.mark.xfail(
    strict=True,
    raises=AssertionError,
    reason="M2: decisions/reader-served-seal-fields.md (#1451): GET /<pack>/<manifest>/ask/grounds must serve reader_hashes per witness",
)
def test_grounds_serves_reader_hashes_per_witness(tmp_path):
    store, manifest = publish_main(tmp_path)
    [answer] = ask(store, "reader", f"/{PACK}/{manifest['id']}/ask/grounds?{row_query('flagged', 'item-a', '12')}")
    assert answer["status"] == 200, answer
    body = answer["body"]
    rh = body.get("reader_hashes")
    assert isinstance(rh, dict), f"expected reader_hashes object on grounds answer, got {rh!r}"
    assert rh.get("status") == "green"
    checked = rh.get("checked_witnesses")
    assert isinstance(checked, list) and len(checked) >= 1, f"expected checked_witnesses entries, got {checked!r}"
    match = [
        entry
        for entry in checked
        if entry.get("conclusion") == {"relation": "flagged", "key": '["item-a","12"]'}
    ]
    assert len(match) == 1, f"expected one checked_witnesses entry for flagged(item-a, 12), got {checked!r}"
    assert match[0]["status"] == "green"
    digest = match[0]["piece_sha256"]
    assert isinstance(digest, str) and len(digest) == 64 and all(c in "0123456789abcdef" for c in digest)


@pytest.mark.xfail(
    strict=True,
    raises=AssertionError,
    reason="M2: decisions/reader-served-seal-fields.md (#1451): grounds must preserve declared origin_sign on fact sources and omit when undeclared",
)
def test_grounds_preserves_declared_origin_sign_on_sources(tmp_path):
    from rezono_compiler.facts import LoadError
    from rezono_publisher.publish import Blocked

    # Control: unmodified slip fixture declares no origin_sign -> never guessed from kind="synthetic".
    plain_store, plain_manifest = publish_main(tmp_path / "plain")
    [plain_ans] = ask(
        plain_store, "reader", f"/{PACK}/{plain_manifest['id']}/ask/grounds?{row_query('flagged', 'item-a', '12')}"
    )
    assert plain_ans["status"] == 200, plain_ans
    plain_fact_nodes = [n for n in plain_ans["body"]["nodes"] if n.get("sources")]
    assert plain_fact_nodes, "expected at least one base fact node with sources"
    for node in plain_fact_nodes:
        for src in node["sources"]:
            assert "origin_sign" not in src, f"undeclared origin_sign must not be guessed: {src!r}"

    # With explicit origin_sign in facts/rows.sources.yaml -> preserved verbatim on AnswerNode.sources.
    def _set_origin_sign(pack_dir):
        sidecar_path = pack_dir / "facts" / "rows.sources.yaml"
        sidecar = yaml.safe_load(sidecar_path.read_text(encoding="utf-8"))
        sidecar["default"]["origin_sign"] = "origin_observation"
        sidecar_path.write_text(yaml.safe_dump(sidecar, sort_keys=False), encoding="utf-8")

    try:
        signed_store, signed_manifest = publish_main(tmp_path / "with_sign", change=_set_origin_sign)
    except (LoadError, Blocked) as exc:
        raise AssertionError(f"publisher/loader must accept declared origin_sign on fact sources: {exc}") from exc

    [signed_ans] = ask(
        signed_store, "reader", f"/{PACK}/{signed_manifest['id']}/ask/grounds?{row_query('flagged', 'item-a', '12')}"
    )
    assert signed_ans["status"] == 200, signed_ans
    signed_fact_nodes = [n for n in signed_ans["body"]["nodes"] if n.get("sources")]
    assert signed_fact_nodes, "expected base fact nodes with sources"
    for node in signed_fact_nodes:
        for src in node["sources"]:
            assert src.get("origin_sign") == "origin_observation", f"expected origin_sign preserved, got {src!r}"
