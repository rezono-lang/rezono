"""Schema-driven diff classification for multivalued vs single-valued slots, verified by the independent checker.

Expectation source: decisions/viewer-slip.md, section "When a row is the same row" and "Independent checker contract".
Uses a neutral `works` pack (`Person`, `Work` with single-valued `title`/`status` and multivalued `authors`)
published through `rezono_publisher.proposal.publish_proposal` and checked by `rezono_checker`.
"""

from __future__ import annotations

from collections import Counter
import json
from pathlib import Path
import subprocess

import pytest
import yaml

pytest.importorskip("duckdb")
pytest.importorskip("rezono_compiler")

from rezono_checker.check import check as check_witnesses
from rezono_checker.difference import check_difference
from rezono_checker.rules import load_rules
from rezono_compiler import emit, pack as pack_loader
from rezono_publisher import batch, proof, proposal, publish, store, views

PACK_DIR = "packs/works"
ROLES = {"checker": "complete", "viewer": "may_read"}

SCHEMA = {
    "id": "https://rezono.example/works",
    "name": "works",
    "in_language": "en",
    "imports": ["linkml:types"],
    "default_range": "string",
    "annotations": {"layer": "facts"},
    "enums": {
        "WorkStatus": {
            "permissible_values": {"draft": {}, "published": {}},
        }
    },
    "classes": {
        "Person": {
            "attributes": {"id": {"identifier": True}},
        },
        "Work": {
            "attributes": {
                "id": {"identifier": True},
                "title": {"required": True},
                "status": {"range": "WorkStatus", "required": True},
                "authors": {"range": "Person", "multivalued": True},
            },
        },
    },
}

RULES = """\
.decl may_read(role: symbol, kind: symbol, element: symbol)
may_read("viewer", "person", p) :- person(p).
may_read("viewer", "work", w) :- work(w).

.decl credited(work: symbol, author: symbol)
credited(w, a) :- work__authors(w, a).
.output credited
"""

FACTS = {
    "person": [{"id": "ann"}, {"id": "bob"}, {"id": "kim"}],
    "work": [
        {"id": "w1", "title": "Draft", "status": "draft", "authors": ["ann"]},
        {"id": "w2", "title": "Notes", "status": "draft", "authors": ["ann", "kim"]},
    ],
}

LABELS = {
    "person": "Person",
    "work": "Work",
    "work.title": "Title",
    "work.status": "Status",
    "work.authors": "Authors",
    "work_status.draft": "Draft",
    "work_status.published": "Published",
    "credited": "Credited",
    "may_read": "May read",
}

CHANNELS = {
    "kinds": [
        {"kind": "person", "shape": "rect"},
        {"kind": "work", "shape": "rect"},
    ]
}

MESSAGES = """\
@locale en
---
arrow.total = {{Every {$kind} has exactly one {$arrow}.}}
arrow.partial = {{Every {$kind} has at most one {$arrow}.}}
attribute.total = {{Every {$kind} has exactly one {$attribute}.}}
attribute.partial = {{Every {$kind} has at most one {$attribute}.}}
arrow.many.partial = {{Every {$kind} can have more than one {$arrow}.}}
attribute.many.partial = {{Every {$kind} can have more than one {$attribute}.}}
is_a = {{Every {$kind} is a {$parent}.}}
unique_key = {{{$key} belongs to at most one {$kind}.}}
path_equation = {{For every {$kind}: {$equation}.}}
"""


class SchemaDiffContractError(AssertionError):
    """Publisher or checker did not enforce schema-driven multivalued vs single-valued diff semantics."""


def _sh(*args: str, cwd: Path) -> str:
    return subprocess.run(args, cwd=cwd, check=True, capture_output=True, text=True).stdout.strip()


def _write_works_pack(target: Path) -> Path:
    (target / "schema").mkdir(parents=True, exist_ok=True)
    (target / "rules").mkdir(exist_ok=True)
    (target / "facts").mkdir(exist_ok=True)
    (target / "labels").mkdir(exist_ok=True)
    (target / "messages").mkdir(exist_ok=True)
    (target / "pack.yaml").write_text(
        yaml.safe_dump({"name": "works", "version": "0.1.0", "default_language": "en", "imports": []}, sort_keys=False),
        encoding="utf-8",
        newline="\n",
    )
    (target / "schema" / "works.yaml").write_text(
        yaml.safe_dump(SCHEMA, sort_keys=False), encoding="utf-8", newline="\n"
    )
    (target / "rules" / "works.dl").write_text(RULES, encoding="utf-8", newline="\n")
    (target / "facts" / "works.yaml").write_text(
        yaml.safe_dump(FACTS, sort_keys=False), encoding="utf-8", newline="\n"
    )
    (target / "labels" / "en.yaml").write_text(
        yaml.safe_dump(LABELS, sort_keys=False), encoding="utf-8", newline="\n"
    )
    (target / "messages" / "en.mf2").write_text(MESSAGES, encoding="utf-8", newline="\n")
    (target / "channels.yaml").write_text(
        yaml.safe_dump(CHANNELS, sort_keys=False), encoding="utf-8", newline="\n"
    )
    return target


def _init_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    _write_works_pack(repo / PACK_DIR)
    _sh("git", "init", "-q", "-b", "main", cwd=repo)
    for message in ("seed", "base"):
        (repo / "log.txt").write_text(message + "\n", encoding="utf-8", newline="\n")
        _sh("git", "add", ".", cwd=repo)
        _sh(
            "git",
            "-c",
            "user.name=Seed",
            "-c",
            "user.email=seed@example.invalid",
            "commit",
            "-q",
            "-m",
            message,
            cwd=repo,
        )
    return repo


def _read_difference_tree(st: store.FileStore, base_prefix: str, root_ref: dict) -> list[dict]:
    def visit(key: str, expected_sha: str) -> list[dict]:
        raw = st.get(key)
        assert raw is not None, key
        assert proof.sha256(raw) == expected_sha, key
        piece = json.loads(raw)
        if piece["level"] == 0:
            return piece["rows"]
        out: list[dict] = []
        for child in piece["children"]:
            out.extend(visit(f"{base_prefix}/{child['file']}", child["sha256"]))
        return out

    return visit(views.key_of(root_ref["uri"]), root_ref["sha256"])


def _verify_role_witnesses(st: store.FileStore, manifest_id: str, role: str) -> set[tuple[str, str]]:
    manifest = json.loads(st.get(f"works/manifests/{manifest_id}.json"))
    rules_ref = next(c for c in manifest["compiled"] if c["file"] == "ir/rules.json")
    rules_doc = json.loads(st.get(views.key_of(rules_ref["uri"])))
    witness_ref = next(w for w in manifest["witnesses"] if w["role"] == role)
    sees = json.loads(st.get(views.key_of(witness_ref["uri"])))
    proof_doc = sees | {"manifest_id": manifest_id, "root": None}
    report = check_witnesses(proof_doc, manifest, load_rules(rules_doc), lambda uri: st.get(views.key_of(uri)), role=role)
    assert report["valid"] and not report["findings"], report["findings"]
    return {
        (w["conclusion"]["relation"], w["conclusion"]["key"])
        for w in sees["witnesses"]
    }


def _snap(rows: set[tuple[str, ...]]) -> bytes:
    return json.dumps([{"key": list(r)} for r in sorted(rows)]).encode("utf-8")


def _pack_diff(rel: str, rs: list[dict]) -> tuple[dict[str, bytes], dict, dict]:
    root, levels, files = proof.tree("difference", rel, rs, lambda lv, n: f"difference/{rel}/{lv}/{n}.json")
    counts = Counter(e["change"] for e in rs)
    return (
        files,
        {rel: {k: counts[k] for k in ("added", "removed", "changed")}},
        {rel: {"file": root, "sha256": proof.sha256(files[root]), "levels": levels}},
    )


@pytest.mark.xfail(
    strict=True,
    raises=AssertionError,
    reason=(
        "M3: decisions/viewer-slip.md: Use the compiled schema bundle's multivalued flag in "
        "edge/publisher/rezono_publisher/difference.py and checker/rezono_checker/difference.py so multivalued "
        "Work.authors emits identical membership removal + addition for both {ann} -> {bob} and {ann, kim} -> "
        "{bob, kim}, while single-valued Work.title and Work.status remain single value changes."
    ),
)
def test_multivalued_and_single_valued_slot_diffs_follow_schema_cardinality(tmp_path):
    """Published differences for multivalued Work.authors vs single-valued Work.title/status with verified witnesses."""
    repo = _init_repo(tmp_path)
    st = store.FileStore(tmp_path / "store")
    base_commit = _sh("git", "rev-parse", "HEAD", cwd=repo)
    n, knowledge_time = proposal.base_of(repo, base_commit)
    main = publish.publish(
        batch.epoch(repo / PACK_DIR, epoch=n, knowledge_time=knowledge_time, sources=[("rules", base_commit)]),
        st,
        ROLES,
    )
    assert main["id"] == "m-2"

    delta = json.dumps({
        "format": "rezono.delta/1",
        "changes": [
            {"op": "set", "file": "facts/works.yaml", "kind": "work", "key": "w1", "slot": "authors", "value": ["bob"]},
            {"op": "set", "file": "facts/works.yaml", "kind": "work", "key": "w1", "slot": "title", "value": "Final"},
            {"op": "set", "file": "facts/works.yaml", "kind": "work", "key": "w1", "slot": "status", "value": "published"},
            {"op": "set", "file": "facts/works.yaml", "kind": "work", "key": "w2", "slot": "authors", "value": ["bob", "kim"]},
        ],
    })
    proposal_id = proposal.publish_proposal(repo, PACK_DIR, "1", base_commit, delta, st, ROLES)
    assert proposal_id == "p-1-3"

    # Both previous (m-2) and new (p-1-3) publications carry checker-verified witnesses for the same role (`viewer`).
    before_conclusions = _verify_role_witnesses(st, "m-2", "viewer")
    after_conclusions = _verify_role_witnesses(st, proposal_id, "viewer")
    assert {("credited", '["w1","ann"]'), ("credited", '["w2","ann"]'), ("credited", '["w2","kim"]')} <= before_conclusions
    assert {("credited", '["w1","bob"]'), ("credited", '["w2","bob"]'), ("credited", '["w2","kim"]')} <= after_conclusions

    # Read the published difference index & trees for role `viewer`.
    explain_prefix = f"works/{proposal_id}/viewer/explain"
    index = json.loads(st.get(f"{explain_prefix}/index.json"))
    diff = index["difference"]

    # 1. Single-valued slots remain recognizable as single `changed` entries with `was`.
    title_entries = _read_difference_tree(st, explain_prefix, diff["trees"]["work__title"])
    status_entries = _read_difference_tree(st, explain_prefix, diff["trees"]["work__status"])
    assert title_entries == [{"key": ["w1", "Final"], "change": "changed", "was": ["w1", "Draft"]}]
    assert status_entries == [{"key": ["w1", "published"], "change": "changed", "was": ["w1", "draft"]}]
    assert diff["counts"]["work__title"] == {"added": 0, "removed": 0, "changed": 1}
    assert diff["counts"]["work__status"] == {"added": 0, "removed": 0, "changed": 1}

    # 2. Multivalued Work.authors emits identical membership disappearance (ann) and appearance (bob)
    # for BOTH {ann} -> {bob} (w1) and {ann, kim} -> {bob, kim} (w2), with zero `changed` entries.
    authors_entries = _read_difference_tree(st, explain_prefix, diff["trees"]["work__authors"])
    w1_changes = [(e["key"][1], e["change"]) for e in authors_entries if e["key"][0] == "w1"]
    w2_changes = [(e["key"][1], e["change"]) for e in authors_entries if e["key"][0] == "w2"]
    assert w1_changes == [("ann", "removed"), ("bob", "added")], authors_entries
    assert w2_changes == [("ann", "removed"), ("bob", "added")], authors_entries
    assert w1_changes == w2_changes
    assert diff["counts"]["work__authors"] == {"added": 2, "removed": 2, "changed": 0}


@pytest.mark.xfail(
    strict=True,
    raises=AssertionError,
    reason=(
        "M3: decisions/viewer-slip.md: checker/rezono_checker/difference.py::check_difference must accept "
        "bundle: dict | None = None and enforce schema-driven multivalued vs single-valued diff classification, "
        "rejecting `changed` on multivalued slots and `removed`+`added` on single-valued slot replacements."
    ),
)
def test_checker_enforces_schema_driven_difference_classification(tmp_path):
    """Independent checker accepts schema-driven diffs and rejects mismatched multivalued/single-valued classification."""
    pack_dir = _write_works_pack(tmp_path / "works")
    compiled_files = emit.compile_pack(pack_loader.read(pack_dir))
    bundle = json.loads(compiled_files["bundle/schema-bundle.json"])

    # Sanity check: the compiled schema bundle carries explicit cardinality for both slots.
    authors_arrow = next(a for a in bundle["arrows"] if a["table"] == "work__authors")
    title_attr = next(a for a in bundle["attributes"] if a["table"] == "work__title")
    assert authors_arrow["multivalued"] is True
    assert title_attr["multivalued"] is False

    before = {
        "work__authors": _snap({("w1", "ann")}),
        "work__title": _snap({("w1", "Draft")}),
    }
    after = {
        "work__authors": _snap({("w1", "bob")}),
        "work__title": _snap({("w1", "Final")}),
    }

    # Build valid schema-driven diff pieces: removed+added for multivalued work__authors, changed for single-valued work__title.
    p_a, c_a, r_a = _pack_diff(
        "work__authors",
        [
            {"key": ["w1", "ann"], "change": "removed"},
            {"key": ["w1", "bob"], "change": "added"},
        ],
    )
    p_t, c_t, r_t = _pack_diff(
        "work__title",
        [{"key": ["w1", "Final"], "change": "changed", "was": ["w1", "Draft"]}],
    )

    def run_check(pieces, counts, roots):
        try:
            return check_difference(before, after, pieces, counts, roots, proof.PIECE, proof.FANOUT, bundle=bundle)
        except TypeError as exc:
            raise SchemaDiffContractError(
                f"check_difference does not accept schema bundle parameter: {exc}"
            ) from exc

    # 1. Valid schema-driven classification passes with zero problems.
    assert run_check(p_a | p_t, c_a | c_t, r_a | r_t) == []

    # 2. Forged diff classifying multivalued Work.authors {ann} -> {bob} as `changed` is rejected by checker.
    bad_a_pieces, bad_a_counts, bad_a_roots = _pack_diff(
        "work__authors",
        [{"key": ["w1", "bob"], "change": "changed", "was": ["w1", "ann"]}],
    )
    problems_multivalued = run_check(bad_a_pieces | p_t, bad_a_counts | c_t, bad_a_roots | r_t)
    assert problems_multivalued, "checker must reject `changed` on multivalued Work.authors"

    # 3. Forged diff splitting single-valued Work.title Draft -> Final into removed+added is rejected by checker.
    bad_t_pieces, bad_t_counts, bad_t_roots = _pack_diff(
        "work__title",
        [
            {"key": ["w1", "Draft"], "change": "removed"},
            {"key": ["w1", "Final"], "change": "added"},
        ],
    )
    problems_single = run_check(p_a | bad_t_pieces, c_a | bad_t_counts, r_a | bad_t_roots)
    assert problems_single, "checker must reject removed+added on single-valued Work.title"
