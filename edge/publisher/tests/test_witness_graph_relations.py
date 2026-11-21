"""The proof graph is data that rules read: stratum and alternative witnesses, derived over the published
witness graph and verified by the checker (decisions/one-structure-space-and-readings.md, section 4 and red
test 5; #1445).

The expectations are the hand-written cases of docs/semantics/witness-alternatives-cases.yaml (written from
docs/semantics/witness-alternatives.md, and recomputed by checker/tests/test_alternatives.py with a fixpoint
of its own). This test takes the cases without a `reads` whose program the batch backend runs (reach and near:
the mutual recursion of p and q is not linear), publishes each one as a pack, and reads the complete role's
publication:
- `stratum(relation, key, depth)`: per derived row its height, the stage at which it enters the least fixpoint;
- `alternative(relation, key, rule, binding)`: per derived row each founded alternative, never a cyclic one,
  as the rule id and its binding values in the alphabetical order of the rule's variables.
`key` and `binding` are canonical keys (`encode_key`), as a witness names its rows. Both relations are derived
by rules, so each published row is the conclusion of a published witness that the checker verified: the
publication's `rezono:proofs` is green.

The pack writes the case program in Rezono's Datalog subset; a relation with two rules names them
`<relation>_1` and `<relation>_2` in the order written, so the case names map to those ids below.
"""

from __future__ import annotations

import json
import re
import shutil
from pathlib import Path

import pytest
import yaml

pytest.importorskip("duckdb")
pytest.importorskip("rezono_compiler")

from rezono_checker.canon import encode_key
from rezono_publisher import batch, publish, store

ROOT = Path(__file__).resolve().parents[3]
MINIMAL = ROOT / "compiler" / "tests" / "fixtures" / "minimal"
CASES = [c for c in yaml.safe_load((ROOT / "docs/semantics/witness-alternatives-cases.yaml").read_text("utf-8"))["cases"]
         if "reads" not in c and c["id"] in {"and-or-two-rules", "finite-alternatives-on-a-cycle",
                                              "alternative-through-its-own-row"}]
RULES = """.decl reach(x: symbol, y: symbol)
reach(x, y) :- node__edge(x, y).
reach(x, z) :- reach(x, y), node__edge(y, z).
.decl near(a: symbol, b: symbol)
near(a, b) :- node__edge(a, b).
near(a, b) :- node__edge(b, a).
.output reach, near
"""
RULE_IDS = {"reach_edge": "reach_1", "reach_step": "reach_2", "near_out": "near_1", "near_in": "near_2"}


class MissingWitnessGraphRelations(AssertionError):
    """The publication has no stratum or alternative relation derived over its witness graph."""


def parse(text: str) -> tuple[str, list[str]]:
    name, args = re.fullmatch(r"(\w+)\((.*)\)", text).groups()
    return name, args.split(",")


def write(path: Path, value) -> None:
    path.write_text(yaml.safe_dump(value, sort_keys=False), encoding="utf-8", newline="\n")


def case_pack(directory: Path, case: dict) -> Path:
    shutil.copytree(MINIMAL, directory)
    write(directory / "schema" / "minimal.yaml", {
        "id": "https://rezono.example/alternatives", "name": "alternatives", "imports": ["linkml:types"],
        "default_range": "string", "annotations": {"layer": "facts"},
        "classes": {"Node": {"attributes": {"id": {"identifier": True},
                                            "edge": {"range": "Node", "multivalued": True}}}}})
    write(directory / "pack.yaml", {"name": "alternatives", "version": "0", "default_language": "nl", "imports": []})
    write(directory / "channels.yaml", {"kinds": [{"kind": "node", "shape": "rect"}],
                                        "arrows": [{"arrow": "node.edge", "dash": "none"}]})
    write(directory / "labels" / "nl.yaml", {})
    (directory / "rules").mkdir()
    (directory / "rules" / "alternatives.dl").write_text(RULES, encoding="utf-8", newline="\n")
    edges: dict[str, list[str]] = {}
    for fact in case["facts"]:
        _, (x, y) = parse(fact)
        edges.setdefault(x, []).append(y)
        edges.setdefault(y, [])
    (directory / "facts").mkdir()
    write(directory / "facts" / "edges.yaml", {"node": [{"id": n, "edge": sorted(e)} if e else {"id": n}
                                                        for n, e in sorted(edges.items())]})
    write(directory / "facts" / "edges.sources.yaml",
          {"default": {"kind": "tool", "name": "witness alternative cases", "position": case["id"]}})
    return directory


def key_of(uri: str) -> str:
    return uri.split("://", 1)[1].split("/", 1)[1] if "://" in uri else uri


def expected(case: dict) -> tuple[set, set]:
    strata, alternatives = set(), set()
    for text, row in case["rows"].items():
        relation, values = parse(text)
        if "height" in row:
            strata.add((relation, encode_key(values), str(row["height"])))
        for alt in row["founded"]:
            rule, binding = parse(alt)
            alternatives.add((relation, encode_key(values), RULE_IDS[rule], encode_key(binding)))
    return strata, alternatives


@pytest.mark.xfail(
    strict=True,
    raises=AssertionError,
    reason=(
        "extra: decisions/one-structure-space-and-readings.md: Red tests, 5 (section 4, The proof graph is "
        "data that rules read): derive stratum(relation, key, depth) and the founded alternative(relation, key, "
        "rule, binding) by rules over the published witness graph, publish them with witnesses, and let the "
        "checker verify them, as docs/semantics/witness-alternatives-cases.yaml states (#1445)."
    ),
)
def test_stratum_and_alternative_witnesses_are_derived_over_the_published_witness_graph(tmp_path: Path):
    assert len(CASES) == 3
    for case in CASES:
        st = store.FileStore(tmp_path / case["id"] / "store")
        ep = batch.epoch(case_pack(tmp_path / case["id"] / "pack", case), epoch=1,
                         knowledge_time="2026-01-01T00:00:00Z", sources=[("rules", "e1")])
        manifest = publish.publish(ep, st, {"checker": "complete"})
        assert {"name": "rezono:proofs", "status": "green", "violations": 0} in manifest["checks"]
        snapshots = {s["relation"]: s for s in manifest["snapshots"] if s["role"] == "checker"}
        if not {"stratum", "alternative"} <= set(snapshots):
            raise MissingWitnessGraphRelations(f"{case['id']}: published relations {sorted(snapshots)}")
        keys = {rel: [item["key"] for item in json.loads(st.get(key_of(snapshots[rel]["uri"])))]
                for rel in ("stratum", "alternative")}
        text = {rel: {tuple(str(v) for v in k) for k in ks} for rel, ks in keys.items()}
        named = {(relation, encode_key(values)) for relation, values in map(parse, case["rows"])}
        strata, alternatives = expected(case)
        assert {r for r in text["stratum"] if r[:2] in named} == strata, case["id"]
        assert {r for r in text["alternative"] if r[:2] in named} == alternatives, case["id"]

        [witness_set] = [w for w in manifest["witnesses"] if w["role"] == "checker"]
        proven = {(w["conclusion"]["relation"], w["conclusion"]["key"])
                  for w in json.loads(st.get(key_of(witness_set["uri"])))["witnesses"]}
        for rel, ks in keys.items():
            for k in ks:
                assert (rel, encode_key(k)) in proven, (case["id"], rel, k)
