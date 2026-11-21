"""Strict RFC 8259 JSON parsing across rezono_checker: duplicate object keys and NaN/Infinity constants
are refused fail-closed in snapshots, proof pieces, view inputs, metadata and bundles."""

from __future__ import annotations

import ast
import hashlib
import json
from pathlib import Path

import pytest

import rezono_checker
from rezono_canon import sha256_hex
from rezono_checker import assets, proof, snapshots, sources, state_projections, views
from rezono_checker.canon import encode_key
from rezono_checker.check import check_epoch
from rezono_checker.rules import load_rules


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


@pytest.mark.parametrize("payload", [
    b'[{"key":["hidden"],"key":["a"]}]',
    b'[{"key":["a"],"values":{"v":{"state":"known","value":"1","value":"2"}}}]',
    b'[{"key":["a"],"values":{"v":{"state":"known","value":"1"},"v":{"state":"unknown"}}}]',
])
def test_snapshot_duplicate_keys_are_refused(payload):
    with pytest.raises(ValueError, match="duplicate JSON object key"):
        snapshots.read_rows(payload, "json")


@pytest.mark.parametrize("constant", [b"NaN", b"Infinity", b"-Infinity"])
def test_snapshot_nonstandard_constants_are_refused_at_parse(constant):
    payload = b'[{"key":["a"],"values":{"v":{"state":"known","value":' + constant + b"}}}]"
    with pytest.raises(ValueError, match="non-standard JSON constant"):
        snapshots.read_rows(payload, "json")


def test_check_epoch_refuses_snapshot_with_duplicate_keys():
    snap = b'[{"key":["hidden"],"key":["a"]}]'
    rules_doc = {
        "format": "rezono.rules/1",
        "relations": [{"name": "item", "role": "base", "key": [{"name": "x", "type": "string"}]}],
        "rules": [],
    }
    manifest = {
        "id": "m1",
        "snapshots": [
            {"relation": "item", "role": "all", "format": "json", "uri": "item.json",
             "complete": True, "sha256": sha256_hex(snap)},
        ],
    }
    report = check_epoch([], manifest, load_rules(rules_doc), {"item.json": snap}.__getitem__, derived=frozenset())
    assert not report["valid"]
    assert any(f["reason"] == "malformed_snapshot" for f in report["findings"])


def test_proof_piece_duplicate_keys_are_refused():
    snap = b'[{"key":["a"]}]'
    piece = (
        b'{"format":"rezono.proof/1","tree":"rows","relation":"item","level":0,'
        b'"rows":[{"key":["hidden"]}],"rows":[{"key":["a"]}]}'
    )
    path = "rows/item/0/0.json"
    roots = {"item": {"file": path, "sha256": _sha(piece), "levels": 1, "count": 1}}
    problems = proof.check_rows({"item": snap}, {path: piece}, roots, proof.MAX_PIECE, proof.MAX_FANOUT)
    assert any("duplicate JSON object key" in p for p in problems), problems


@pytest.mark.parametrize("constant", [b"NaN", b"Infinity", b"-Infinity"])
def test_proof_piece_nonstandard_constants_are_refused(constant):
    snap = b'[{"key":["a"]}]'
    piece = (
        b'{"format":"rezono.proof/1","tree":"rows","relation":"item","level":0,'
        b'"rows":[{"key":[' + constant + b"]}]}"
    )
    path = "rows/item/0/0.json"
    roots = {"item": {"file": path, "sha256": _sha(piece), "levels": 1, "count": 1}}
    problems = proof.check_rows({"item": snap}, {path: piece}, roots, proof.MAX_PIECE, proof.MAX_FANOUT)
    assert any("non-standard JSON constant" in p for p in problems), problems


def test_check_proof_refuses_duplicate_key_proof_piece_and_snapshot():
    rules_doc = {
        "format": "rezono.rules/1",
        "relations": [
            {"name": "e", "role": "base", "key": [{"name": "x", "type": "string"}]},
            {"name": "p", "role": "derived", "key": [{"name": "x", "type": "string"}]},
        ],
        "rules": [
            {"id": "p", "stratum": "0", "head": {"relation": "p", "terms": ["?x"]},
             "body": [{"relation": "e", "terms": ["?x"], "polarity": "positive", "stratum": "0"}]},
        ],
    }
    witness = {
        "conclusion": {"relation": "p", "key": encode_key(["a"])},
        "rule_id": "p",
        "bindings": [{"variable": "?x", "value": "a"}],
        "premises": [{"row": {"relation": "e", "key": encode_key(["a"])}, "polarity": "positive", "stratum": 0}],
    }
    snaps = {"e": b'[{"key":["a"]}]', "p": b'[{"key":["a"]}]'}
    parsed = {rel: snapshots.read_rows(b, "json") for rel, b in snaps.items()}
    want = proof.expected([witness], proof.steps(rules_doc, [witness], parsed))
    pieces, roots = {}, {}
    for tree_name, by_rel in want.items():
        roots[tree_name] = {}
        for rel, rows in by_rel.items():
            raw = json.dumps(
                {"format": proof.FORMAT, "tree": tree_name, "relation": rel, "level": 0, "rows": rows},
                sort_keys=True, separators=(",", ":"),
            ).encode("utf-8")
            path = f"proof/{tree_name}/{rel}/0/0.json"
            pieces[path] = raw
            roots[tree_name][rel] = {"file": path, "sha256": _sha(raw), "levels": 1}
    sees = {
        "witnesses": [witness],
        "load_bearing_entries": [
            {"conclusion": witness["conclusion"], "premise": witness["premises"][0]["row"],
             "how": "positive", "load_bearing": True},
        ],
    }
    assert proof.check_proof(rules_doc, sees, snaps, pieces, roots, 65536, 128) == []

    dup_path = "proof/back/p/0/0.json"
    dup_bytes = pieces[dup_path][:-1] + b',"level":0}'
    dup_pieces = pieces | {dup_path: dup_bytes}
    dup_roots = {t: dict(by) for t, by in roots.items()}
    dup_roots["back"]["p"] = roots["back"]["p"] | {"sha256": _sha(dup_bytes)}
    problems = proof.check_proof(rules_doc, sees, snaps, dup_pieces, dup_roots, 65536, 128)
    assert any("duplicate JSON object key" in p for p in problems), problems

    dup_snaps = snaps | {"e": b'[{"key":["hidden"],"key":["a"]}]'}
    with pytest.raises(ValueError, match="duplicate JSON object key"):
        proof.check_proof(rules_doc, sees, dup_snaps, pieces, roots, 65536, 128)


@pytest.mark.parametrize("bad_page", [
    b'{"format":"rezono.page/2","kinds":[{"kind":"node","count":99,"first":[]}],"kinds":[]}',
    b'{"format":"rezono.page/2","title":NaN,"kinds":[]}',
    b'{"format":"rezono.page/2","title":Infinity,"kinds":[]}',
    b'{"format":"rezono.page/2","title":-Infinity,"kinds":[]}',
])
def test_views_check_page_refuses_ambiguous_or_nonstandard_json(bad_page):
    bundle = {"kinds": [{"id": "node"}], "attributes": [], "arrows": []}
    problems = views.check_page({}, bundle, bad_page)
    assert problems


@pytest.mark.parametrize("bad_bundle", [
    b'{"attributes":[],"attributes":[],"channels":{}}',
    b'{"attributes":[],"channels":{},"note":NaN}',
    b'{"attributes":[],"channels":{},"note":Infinity}',
])
def test_assets_and_sources_refuse_ambiguous_or_nonstandard_bundle_json(bad_bundle):
    asset_findings = assets.check_role_assets([], bad_bundle, {}, lambda _uri: None)
    assert [f["reason"] for f in asset_findings] == ["asset_cells_unreadable"]
    source_findings = sources.check_role_sources(b"[]", bad_bundle, {})
    assert [f["reason"] for f in source_findings] == ["sources_unreadable"]


def test_state_projections_refuses_duplicate_keys_in_metadata():
    bad_meta = (
        b'[{"relation":"p","source_relation":"s","value_column":"v","origin_column":"o",'
        b'"required":true,"required":false}]'
    )
    manifest = {"compiled": [{"file": state_projections.FILE, "uri": "meta.json", "sha256": sha256_hex(bad_meta)}]}
    findings = state_projections.check(manifest, {"meta.json": bad_meta}.__getitem__, {})
    assert findings == [{"reason": "malformed_state_projection_metadata"}]


def test_every_checker_json_load_enforces_strict_hooks():
    """No module under rezono_checker may call stdlib json.load/json.loads without both hooks."""
    package_dir = Path(rezono_checker.__file__).parent
    unprotected = []
    for module in sorted(package_dir.rglob("*.py")):
        tree = ast.parse(module.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)):
                continue
            if node.func.attr not in ("load", "loads"):
                continue
            if not (isinstance(node.func.value, ast.Name) and node.func.value.id == "json"):
                continue
            keywords = {kw.arg for kw in node.keywords}
            if not {"object_pairs_hook", "parse_constant"} <= keywords:
                unprotected.append(f"{module.name}:{node.lineno}")
    assert unprotected == []
