"""Reader questions (RV-C04; docs/gui.md, "Reader questions"): `reader:` in questions.yaml, every name checked
against the pack, the proof resolved, the messages required in every language, and the list in the bundle. The
minimal fixture with std-explain imported."""

import json
import shutil
from pathlib import Path

import pytest
import yaml

from support import FIXTURE, REPO
from rede_compiler import emit, modules, pack

STD = REPO / "packs" / "std-explain"
RULES = """
.decl pair(a: symbol, b: symbol)
pair(a, b) :- beta__alpha(b, a).
.decl sized(a: symbol, n: number)
sized(a, n) :- alpha__size(a, n).
"""
MESSAGES = ("reader.sized", "reader.sized.about", "reader.sized.a", "reader.sized.n")
SIZED = {"id": "how-big", "title_message": "reader.sized", "about_message": "reader.sized.about",
         "relation": "sized", "columns": [{"column": "a", "message": "reader.sized.a", "element": "alpha"},
                                          {"column": "n", "message": "reader.sized.n", "reading": "yyyymmdd"}],
         "context": [{"kind": "alpha", "fields": ["alpha.title", "alpha.size"], "readings": {"alpha.size": "days"}}]}


@pytest.fixture
def fixture(tmp_path) -> Path:
    d = Path(shutil.copytree(FIXTURE, tmp_path / "pack"))
    (d / "rules").mkdir()
    (d / "rules" / "pairs.dl").write_text(RULES)
    meta = yaml.safe_load((d / "pack.yaml").read_text())
    meta["imports"] = [{"name": "std-explain", "path": str(STD), "sha256": modules.pack_hash(STD)}]
    (d / "pack.yaml").write_text(yaml.safe_dump(meta, sort_keys=False))
    return d


def reader(d: Path, *questions, messages=MESSAGES, doc=None) -> None:
    (d / "questions.yaml").write_text(yaml.safe_dump(doc or {"format": "rede.questions/1", "reader": list(questions)},
                                                     sort_keys=False))
    mf2 = d / "messages" / "nl.mf2"
    mf2.write_text(mf2.read_text() + "".join(f"{m} = {m}\n" for m in messages))


def bundle(d: Path) -> dict:
    return json.loads(emit.compile_pack(pack.read(d))["bundle/schema-bundle.json"])


def test_a_reader_question_goes_into_the_bundle_with_its_proof_resolved(fixture):
    reader(fixture, SIZED)
    b = bundle(fixture)
    assert b["reader_questions"] == [{
        "id": "how-big", "title_message": "reader.sized", "about_message": "reader.sized.about",
        "relation": "sized", "proof": "grounds",
        "columns": [{"column": "a", "message": "reader.sized.a", "element": "alpha"},
                    {"column": "n", "message": "reader.sized.n", "reading": "yyyymmdd"}],
        "context": [{"kind": "alpha", "fields": [{"field": "alpha.title"}, {"field": "alpha.size", "reading": "days"}]}]}]
    # A file with only reader questions keeps the imported explanation questions.
    assert [q["term"] for q in b["questions"]][:3] == ["grounds", "reach", "gap"]


def test_a_named_proof_is_kept_and_a_pack_without_reader_questions_has_none(fixture, tmp_path):
    reader(fixture, {**SIZED, "proof": "reach"})
    assert bundle(fixture)["reader_questions"][0]["proof"] == "reach"
    plain = Path(shutil.copytree(FIXTURE, tmp_path / "plain"))
    assert "reader_questions" not in bundle(plain)


def test_removing_the_relation_a_reader_question_names_fails_compilation(fixture):
    reader(fixture, SIZED)
    pack.read(fixture)
    (fixture / "rules" / "pairs.dl").write_text(RULES.split(".decl sized")[0])
    with pytest.raises(pack.CompileError, match="'sized' is not a derived relation of this pack"):
        pack.read(fixture)


@pytest.mark.parametrize("change,message", [
    (lambda q: q.update(relation="alpha"), "'alpha' is not a derived relation"),
    (lambda q: q.update(id="How_big"), "must be kebab case"),
    (lambda q: q["columns"][0].update(column="zz"), "'zz' is not a column of sized"),
    (lambda q: q["columns"][0].pop("message"), "needs column and message"),
    (lambda q: q["columns"][0].update(element="nothing"), "element names a kind, on a text column"),
    (lambda q: q["columns"][1].update(element="alpha", reading=None) or q["columns"][1].pop("reading"),
     "element names a kind, on a text column"),
    (lambda q: q["columns"][1].update(reading="iso"), "reading is days or yyyymmdd, on a whole-number column"),
    (lambda q: q["columns"][0].pop("element") and q["columns"][0].update(reading="days"),
     "reading is days or yyyymmdd, on a whole-number column"),
    (lambda q: q["columns"].append(dict(q["columns"][0])), "a column is shown once"),
    (lambda q: q["context"][0].update(fields=["beta.state"]), "fields are slots of alpha's page"),
    (lambda q: q["context"][0].update(readings={"alpha.title": "days"}), "readings map a whole-number field"),
    (lambda q: q["context"][0].update(kind="nothing"), "is a kind with fields"),
    (lambda q: q.update(proof="gap"), "proof 'gap' is not a question its rows offer"),
    (lambda q: q.pop("columns"), "needs id, title_message, about_message, relation and columns"),
])
def test_a_wrong_reader_question_is_refused(fixture, change, message):
    q = json.loads(json.dumps(SIZED))
    change(q)
    reader(fixture, q)
    with pytest.raises(pack.CompileError, match=message):
        pack.read(fixture)


def test_an_id_once_and_a_file_with_something_in_it(fixture):
    reader(fixture, SIZED, SIZED)
    with pytest.raises(pack.CompileError, match="id how-big is used twice"):
        pack.read(fixture)
    reader(fixture, doc={"format": "rede.questions/1"})
    with pytest.raises(pack.CompileError, match="questions or reader"):
        pack.read(fixture)


def test_a_reader_question_without_its_messages_is_refused(fixture):
    reader(fixture, SIZED, messages=MESSAGES[:-1])
    with pytest.raises(pack.CompileError, match="no message 'reader.sized.n' for reader question how-big"):
        pack.read(fixture)


def test_no_proof_without_a_question_that_offers_one(tmp_path):
    d = Path(shutil.copytree(FIXTURE, tmp_path / "pack"))
    (d / "rules").mkdir()
    (d / "rules" / "pairs.dl").write_text(RULES)
    reader(d, SIZED)
    with pytest.raises(pack.CompileError, match="no question offers a proof of a row of sized"):
        pack.read(d)


def test_a_reading_on_an_amount_is_refused(fixture):
    schema = fixture / "schema" / "minimal.yaml"
    text = schema.read_text()
    old = "        range: Count\n        minimum_value: 0\n        maximum_value: 9\n"
    assert old in text
    schema.write_text(text.replace(old, "        range: integer\n        annotations:\n          currency: EUR\n"))
    reader(fixture, {**SIZED, "context": []})
    with pytest.raises(pack.CompileError, match="column n is an amount in EUR"):
        pack.read(fixture)
    reader(fixture, {**SIZED, "context": [], "columns": [SIZED["columns"][0], {"column": "n", "message": "reader.sized.n"}]})
    assert bundle(fixture)["relations"][[r["id"] for r in bundle(fixture)["relations"]].index("sized")]["columns"][1]["currency"] == "EUR"
