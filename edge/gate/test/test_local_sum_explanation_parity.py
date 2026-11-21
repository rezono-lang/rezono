"""Local explanation parity for published aggregate sums over value columns outside the key.

Expectation source: decisions/local-sum-explanation-parity.md.
Uses an inline `rezono.rules/1` program matching the `hours(member, task; h)` -> `member_hours(member, total)`
shape, publishes a verified role archive with `rezono_publisher.proof.plan`, verifies both the witnesses
(`rezono_checker.check.check`) and proof trees (`rezono_checker.proof.check_proof`), then opens the exact
same publication with the exact same role locally (`edge/gate/src/local.ts`) and via the published proof steps.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import subprocess

import pytest

from rezono_canon import canonical_sha256
from rezono_checker.check import check as check_witnesses
from rezono_checker.proof import check_proof
from rezono_checker.rules import load_rules
from rezono_compiler import rules as ir
from rezono_compiler.explain import Explainer, key_text
from rezono_publisher import proof

PROBE = Path(__file__).with_name("local-sum-parity-probe.mts")
PACK = "fixture"
MANIFEST_ID = "m-1"
ROLE = "reader"
QUESTION = "grounds"

RULES_DOC = {
    "format": "rezono.rules/1",
    "pack": PACK,
    "relations": [
        {
            "name": "member",
            "role": "base",
            "key": [{"name": "id", "type": "string"}],
        },
        {
            "name": "hours",
            "role": "base",
            "key": [{"name": "member", "type": "string"}, {"name": "task", "type": "string"}],
            "values": [{"name": "h", "type": "integer"}],
        },
        {
            "name": "member_hours",
            "role": "derived",
            "key": [{"name": "member", "type": "string"}, {"name": "total", "type": "integer"}],
            "module": "load",
            "explain": "materialize",
        },
    ],
    "rules": [
        {
            "id": "member_hours",
            "module": "load",
            "stratum": "1",
            "head": {"relation": "member_hours", "terms": ["?m", "?s"]},
            "body": [
                {"relation": "member", "terms": ["?m"], "polarity": "positive", "stratum": "0"},
            ],
            "aggregates": [
                {
                    "relation": "hours",
                    "terms": ["?m", "_"],
                    "function": "sum",
                    "over": "h",
                    "as": "?s",
                    "stratum": "0",
                }
            ],
            "witness": {"relation": "member_hours__witness", "variables": ["?m", "?s"]},
            "origin": {"file": "rules/load.dl", "line": "4"},
        }
    ],
}


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _write_bytes(root: Path, rel: str, data: bytes) -> str:
    target = root / rel
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(data)
    return _sha256(data)


def _write_object(root: Path, payload: object) -> tuple[dict, bytes]:
    data = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    digest = _sha256(data)
    key = f"{PACK}/objects/{digest}.json"
    _write_bytes(root, key, data)
    return {"uri": f"s3://local-test/{key}", "sha256": digest}, data


def _load_bearing_entries(witnesses: list[dict]) -> list[dict]:
    seen: dict[tuple[str, str, str, str, str], bool] = {}
    for w in witnesses:
        c = w["conclusion"]
        for p in w.get("premises", ()):
            seen[(c["relation"], c["key"], p["row"]["relation"], p["row"]["key"], p["polarity"])] = True
    return [
        {
            "conclusion": {"relation": cr, "key": ck},
            "premise": {"relation": pr, "key": pk},
            "how": how,
            "load_bearing": flag,
        }
        for (cr, ck, pr, pk, how), flag in sorted(seen.items())
    ]


def _build_verified_sum_publication(root: Path) -> tuple[dict[str, str], dict[str, list[tuple[list[str], str]]]]:
    """Build and independently verify a published archive for `hours(member, task; h)` -> `member_hours`."""
    rules_doc = RULES_DOC
    prog = ir.load(rules_doc)

    # Hand-authored base facts: two members with tasks whose hours live in value column `h` (outside key).
    members = [("ada",), ("ben",)]
    hours_entries = [
        ("ada", "t1", "5"),
        ("ada", "t2", "7"),
        ("ben", "t3", "4"),
        ("ben", "t4", "9"),
    ]
    member_totals = [("ada", "12"), ("ben", "13")]

    engine_rows = {
        "member": members,
        "hours": hours_entries,
        "member_hours": member_totals,
    }
    witness_tables = {
        "member_hours": [("ada", "12"), ("ben", "13")],
    }
    chosen_witnesses = Explainer(prog, engine_rows, witness_tables).chosen()
    assert len(chosen_witnesses) == 2

    # Build real snapshot payloads: `hours` carries `h` in `values`, outside `key`.
    snapshot_payloads = {
        "member": [{"key": [m]} for (m,) in members],
        "hours": [
            {"key": [m, task], "values": {"h": {"state": "known", "value": h}}}
            for m, task, h in hours_entries
        ],
        "member_hours": [{"key": [m, total]} for m, total in member_totals],
    }

    snapshots_meta = []
    snapshot_bytes: dict[str, bytes] = {}
    for relation, rows in sorted(snapshot_payloads.items()):
        ref, raw = _write_object(root, rows)
        snapshot_bytes[relation] = raw
        snapshots_meta.append({
            "relation": relation,
            "role": "checker",
            "complete": True,
            "format": "json",
            **ref,
        })
        snapshots_meta.append({
            "relation": relation,
            "role": ROLE,
            "complete": False,
            "full": True,
            "format": "json",
            **ref,
        })

    sees = {
        "witnesses": chosen_witnesses,
        "hidden": [],
        "load_bearing_entries": _load_bearing_entries(chosen_witnesses),
    }
    witness_ref, _ = _write_object(root, sees)

    bundle = {
        "format": "rezono.schema-bundle/1",
        "pack": {"id": PACK, "version": "0.1.0", "default_language": "en", "base": f"https://example.org/{PACK}/"},
        "kinds": [
            {"id": "member", "class": "Member", "world": "closed"},
            {"id": "hours", "class": "Hours", "world": "closed"},
        ],
        "attributes": [],
        "enums": [],
        "questions": [
            {
                "term": QUESTION,
                "start": "present",
                "steps": [{"trace": {"direction": "back", "depth": "all"}}],
                "answer": "tree",
                "limit": 100,
            }
        ],
    }
    bundle_key = f"{PACK}/bundles/schema-bundle.json"
    bundle_bytes = json.dumps(bundle, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    bundle_sha = _write_bytes(root, bundle_key, bundle_bytes)

    rules_key = f"{PACK}/bundles/rules.json"
    rules_bytes = json.dumps(rules_doc, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    rules_sha = _write_bytes(root, rules_key, rules_bytes)

    manifest = {
        "id": MANIFEST_ID,
        "epoch": 1,
        "access_semantics": 2,
        "knowledge_time": "2026-01-01T00:00:00Z",
        "checks": [{"name": "rezono:proofs", "status": "green"}],
        "snapshots": snapshots_meta,
        "witnesses": [{"role": ROLE, **witness_ref}],
        "compiled": [
            {"file": "bundle/schema-bundle.json", "uri": f"s3://local-test/{bundle_key}", "sha256": bundle_sha},
            {"file": "ir/rules.json", "uri": f"s3://local-test/{rules_key}", "sha256": rules_sha},
        ],
    }
    manifest_bytes = json.dumps(manifest, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    manifest_sha = _write_bytes(root, f"{PACK}/manifests/{MANIFEST_ID}.json", manifest_bytes)
    head = {
        "format": "rezono.head/1",
        "manifest": MANIFEST_ID,
        "epoch": 1,
        "sha256": manifest_sha,
    }
    head_bytes = json.dumps(head, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    _write_bytes(root, f"{PACK}/heads/{(10**19 - 1 - 1):019d}.json", head_bytes)

    # Independently verify the witnesses against the manifest snapshots before publishing proof trees.
    def read_store(uri: str) -> bytes:
        return (root / uri.removeprefix("s3://local-test/")).read_bytes()

    proof_doc = {"manifest_id": MANIFEST_ID, "root": None, "witnesses": chosen_witnesses}
    report = check_witnesses(proof_doc, manifest, load_rules(rules_doc), read_store, role=ROLE)
    assert report["valid"] and not report["findings"], report["findings"]

    # Publish the role's proof trees (`proof/witness`, `proof/back`, `proof/forward`) and independently verify them.
    view_base = f"{PACK}/{MANIFEST_ID}/{ROLE}/views"
    made, roots = proof.plan(rules_doc, sees, snapshot_bytes, view_base)
    pieces_rel: dict[str, bytes] = {}
    for full_key, data in made:
        _write_bytes(root, full_key, data)
        pieces_rel[full_key.removeprefix(view_base + "/")] = data
    assert check_proof(rules_doc, sees, snapshot_bytes, pieces_rel, roots, proof.PIECE, proof.FANOUT) == []

    view_index = {
        "format": "rezono.view-index/1",
        "pack": PACK,
        "manifest": MANIFEST_ID,
        "role": ROLE,
        "proof": {
            "format": proof.INDEX,
            "piece": proof.PIECE,
            "fanout": proof.FANOUT,
            "trees": {
                tree_name: {
                    rel: {
                        "uri": f"s3://local-test/{view_base}/{entry['file']}",
                        "sha256": entry["sha256"],
                        "levels": entry["levels"],
                    }
                    for rel, entry in by_rel.items()
                }
                for tree_name, by_rel in roots.items()
            },
        },
    }
    _write_bytes(
        root,
        f"{view_base}/index.json",
        json.dumps(view_index, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8"),
    )

    expected_contributors = {
        "ada": [([ "ada", "t1" ], "known:5"), ([ "ada", "t2" ], "known:7")],
        "ben": [([ "ben", "t3" ], "known:4"), ([ "ben", "t4" ], "known:9")],
    }
    expected_hashes = {
        member: canonical_sha256([[key_text(k), val] for k, val in items])
        for member, items in expected_contributors.items()
    }
    return expected_hashes, expected_contributors


def _contributes_summary(answer: dict) -> list[tuple[list[str], str | None]]:
    steps = [s for s in answer.get("steps", []) if s.get("how") == "contributes"]
    return sorted(
        [(json.loads(s["premise"]["key"]), s.get("value")) for s in steps],
        key=lambda item: item[0],
    )


def _aggregate_proof_hash(answer: dict, conclusion_key: str) -> str:
    matches = [
        w
        for w in answer.get("witnesses", [])
        if w.get("conclusion") == {"relation": "member_hours", "key": conclusion_key}
    ]
    assert len(matches) == 1, matches
    aggregates = matches[0].get("aggregates", [])
    assert len(aggregates) == 1, aggregates
    return aggregates[0]["contributors_sha256"]


@pytest.mark.xfail(
    strict=True,
    raises=AssertionError,
    reason=(
        "M3: decisions/local-sum-explanation-parity.md: Opening a published archive with an aggregate sum over "
        "a value column outside the key (hours(member, task; h) -> member_hours(member, total)) via local gate "
        "edge/gate/src/local.ts must return HTTP 200 with the exact same contributing tasks, hours, and "
        "contributors_sha256 proof hash as the role-published proof steps."
    ),
)
def test_local_gate_sum_explanation_matches_published_proof_steps(tmp_path):
    """Same publication, same role: local Why? route matches published proof steps on tasks, hours, and proof hash."""
    expected_hashes, expected_contributors = _build_verified_sum_publication(tmp_path)

    for member, total in (("ada", "12"), ("ben", "13")):
        conclusion_key = key_text([member, total])
        result = subprocess.run(
            [
                "node",
                str(PROBE),
                str(tmp_path),
                PACK,
                MANIFEST_ID,
                ROLE,
                QUESTION,
                "member_hours",
                conclusion_key,
            ],
            cwd=PROBE.parent.parent,
            capture_output=True,
            encoding="utf-8",
        )
        assert result.returncode == 0, result.stderr
        payload = json.loads(result.stdout)

        # Baseline sanity that already holds on main: the published proof steps carry exact tasks, hours, and hash.
        published = payload["published"]
        assert published is not None
        assert _contributes_summary(published) == expected_contributors[member]
        assert _aggregate_proof_hash(published, conclusion_key) == expected_hashes[member]

        # Parity requirement: the local gate must return HTTP 200 with identical tasks, hours, and proof hash.
        local = payload["local"]
        assert local["status"] == 200, local
        local_body = local["body"]
        assert _contributes_summary(local_body) == _contributes_summary(published)
        assert _aggregate_proof_hash(local_body, conclusion_key) == _aggregate_proof_hash(published, conclusion_key)
        assert local_body["nodes"] == published["nodes"]
        assert local_body["steps"] == published["steps"]
        assert local_body["witnesses"] == published["witnesses"]
