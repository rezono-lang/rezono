"""Explanation questions as data (docs/gui.md, "Questions as data"): std-explain imported and
pinned, a pack's own questions.yaml after it, every name checked, messages merged. The minimal fixture."""

import json
import shutil
from pathlib import Path

import pytest
import yaml

from support import FIXTURE, REPO
from rezono_compiler import emit, modules, pack

STD = REPO / "packs" / "std-explain"
RULES = """
.decl pair(a: symbol, b: symbol)
pair(a, b) :- beta__alpha(b, a).
"""
OWN = {"term": "sources", "start": "present", "steps": [{"trace": {"direction": "back", "depth": 2,
       "keep": {"relations": ["beta__alpha"]}}}], "answer": "route", "limit": 20}


@pytest.fixture
def fixture(tmp_path) -> Path:
    d = Path(shutil.copytree(FIXTURE, tmp_path / "pack"))
    (d / "rules").mkdir()
    (d / "rules" / "pairs.dl").write_text(RULES)
    meta = yaml.safe_load((d / "pack.yaml").read_text())
    meta["imports"] = [{"name": "std-explain", "path": str(STD), "sha256": modules.pack_hash(STD)}]
    (d / "pack.yaml").write_text(yaml.safe_dump(meta, sort_keys=False))
    return d


def own(d: Path, *questions, messages=("sources",)) -> None:
    (d / "questions.yaml").write_text(yaml.safe_dump({"format": "rezono.questions/1", "questions": list(questions)},
                                                     sort_keys=False))
    mf2 = d / "messages" / "nl.mf2"
    mf2.write_text(mf2.read_text() + "".join(f"explain.{t} = {t}\nexplain.{t}.question = {{{{{t} {{$element}}}}}}\n"
                                              for t in messages))


def bundle(d: Path) -> dict:
    return json.loads(emit.compile_pack(pack.read(d))["bundle/schema-bundle.json"])


def test_the_imported_questions_come_first_then_the_packs_own(fixture):
    own(fixture, OWN)
    b = bundle(fixture)
    assert [q["term"] for q in b["questions"]] == ["grounds", "reach", "gap", "scenario", "impact", "sweep",
                                                    "contrast", "consequence", "sources"]
    assert b["questions"][-1] == {"term": "sources", "start": "present", "answer": "route", "limit": 20, "steps": [
        {"trace": {"direction": "back", "depth": "2", "keep": {"relations": ["beta__alpha"]}}}]}
    assert b["questions"][2]["steps"][1] == {"suppose": {"delta": "candidates"}}
    assert [q["start"] for q in b["questions"][3:6]] == ["delta", "delta", "sweep"]
    assert b["questions"][4]["steps"] == [{"suppose": {"delta": "given"}}, {"trace": {"direction": "forward", "depth": "3"}}]
    [nl] = [m["resource"] for m in b["messages"] if m["lang"] == "nl"]
    assert "explain.grounds = Grondslag\n" in nl and "explain.sources = sources\n" in nl
    assert nl.startswith("@locale nl")


def test_the_packs_own_message_wins_over_the_imported_one(fixture):
    mf2 = fixture / "messages" / "nl.mf2"
    mf2.write_text(mf2.read_text() + "explain.grounds = Basis\n")
    [nl] = [m["resource"] for m in bundle(fixture)["messages"] if m["lang"] == "nl"]
    assert "explain.grounds = Basis\n" in nl and "Grondslag" not in nl


def test_a_pack_without_questions_has_no_questions_in_its_bundle(tmp_path):
    d = Path(shutil.copytree(FIXTURE, tmp_path / "pack"))
    assert "questions" not in bundle(d)


def test_the_pack_hash_covers_questions_yaml(fixture):
    before = modules.pack_hash(fixture)
    own(fixture, OWN)
    assert modules.pack_hash(fixture) != before


@pytest.mark.parametrize("change,message", [
    (lambda q: q["steps"][0]["trace"]["keep"].update(relations=["nothing"]), "'nothing' does not exist"),
    (lambda q: q["steps"][0]["trace"].update(depth=0), "depth is a whole number from 1"),
    (lambda q: q["steps"][0]["trace"].update(through="rules"), "through rules goes back from an absent start"),
    (lambda q: q.update(term="grounds"), "used twice"),
    (lambda q: q.update(answer="tree"), "answer is one of"),
    (lambda q: q.update(steps=[{"suppose": {"over": "no_sweep"}}]), "over a sweep of this pack"),
    (lambda q: q.update(applies_to={"kinds": ["nothing"]}), "applies_to.kinds: 'nothing'"),
    (lambda q: q.update(start="delta"), "begins with suppose: given"),
    (lambda q: q.update(steps=[{"suppose": "given"}]), "given only from a delta or a sweep"),
    (lambda q: q.update(start="sweep", steps=[{"suppose": "given"}]), "suppose: given alone, with the answer series"),
    (lambda q: q.update(start="delta", steps=[{"suppose": "given"}, {"suppose": "given"}]), "begins with suppose: given, once"),
    (lambda q: q.update(answer="series"), "the answer series comes from a sweep"),
    (lambda q: q.update(start="delta", steps=[{"suppose": "given"}, OWN["steps"][0]], answer="overlay"), "overlay is suppose: given alone"),
    (lambda q: q.update(steps=[{"suppose": "candidates"}]), "candidates follows a trace from an absent start"),
    (lambda q: q.update(steps=[OWN["steps"][0], {"suppose": "without"}]), "without is the first step, once"),
    (lambda q: q.update(start="absent", steps=[{"suppose": "without"}]), "without is the first step, once, from a present"),
    (lambda q: q.update(steps=[{"suppose": "retract"}]), "suppose is given, candidates, without or over"),
    (lambda q: q.pop("limit"), "needs term, start, steps, answer and limit"),
])
def test_a_wrong_question_is_refused(fixture, change, message):
    q = json.loads(json.dumps(OWN))
    change(q)
    own(fixture, q)
    with pytest.raises(pack.CompileError, match=message):
        pack.read(fixture)


def test_a_question_without_its_messages_is_refused(fixture):
    own(fixture, OWN, messages=())
    with pytest.raises(pack.CompileError, match="no message 'explain.sources' for a question"):
        pack.read(fixture)


def test_rules_without_questions_warn(tmp_path):
    d = Path(shutil.copytree(FIXTURE, tmp_path / "pack"))
    (d / "rules").mkdir()
    (d / "rules" / "pairs.dl").write_text(RULES)
    assert any("import std-explain" in w for w in pack.read(d).warnings)


def test_the_computed_questions_contrast_and_consequence(fixture):
    """X5 (RV-X24): contrast walks back through the rules from an absent conclusion, without candidates (its
    closing rows come from `closes` in the bundle); consequence supposes the start row away (the published
    variant that deletes it) and walks forward. Both are in every pack that imports std-explain, in each language."""
    own(fixture, OWN)
    b = bundle(fixture)
    by = {q["term"]: q for q in b["questions"]}
    assert by["contrast"] == {"term": "contrast", "start": "absent", "applies_to": {"derivation": "conclusion"},
                              "answer": "gap", "limit": 50, "steps": [{"trace": {
                                  "direction": "back", "through": "rules", "depth": "4", "fanout": 8}}]}
    assert by["consequence"]["start"] == "present" and by["consequence"]["applies_to"] == {"derivation": "fact"}
    assert by["consequence"]["steps"] == [{"suppose": {"delta": "without"}},
                                          {"trace": {"direction": "forward", "depth": "3"}}]
    assert by["consequence"]["answer"] == "rings"
    for lang in ("nl", "en"):
        text = (STD / "messages" / f"{lang}.mf2").read_text(encoding="utf-8")
        for key in ("explain.contrast", "explain.contrast.question", "explain.consequence",
                    "explain.consequence.question", "explain.computed", "explain.not_computed.no_variant"):
            assert f"\n{key} = " in text, (lang, key)
