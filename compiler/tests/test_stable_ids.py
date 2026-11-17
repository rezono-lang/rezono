"""MOD2: every kind, slot, rule, sentence and channel binding in the schema bundle has a stable id and a span
(file, line, column), on the minimal, domain-free fixture pack. Light: no engine."""

import json
import shutil
from pathlib import Path

import pytest

from support import FIXTURE
from rede_compiler import emit, pack

RULES = """.decl pair(a: symbol, b: symbol)
pair(a, b) :- beta__alpha(b, a).
.decl big(a: symbol)
  big(a) :- alpha__size(a, s), s >= 5.
"""


@pytest.fixture
def fixture(tmp_path) -> Path:
    return Path(shutil.copytree(FIXTURE, tmp_path / "pack"))


def bundle(d: Path, rules: str | None = RULES) -> dict:
    if rules is not None:
        (d / "rules").mkdir(exist_ok=True)
        (d / "rules" / "core.dl").write_text(rules)
    return json.loads(emit.compile_pack(pack.read(d))["bundle/schema-bundle.json"])


def by_id(items):
    return {x["id"]: x for x in items}


def span(file, line, column):
    return {"file": file, "line": str(line), "column": str(column)}


def change(path: Path, old: str, new: str):
    text = path.read_text("utf-8")
    assert old in text, old
    path.write_text(text.replace(old, new), "utf-8")


def test_every_element_has_a_stable_id_and_a_span(fixture):
    b = bundle(fixture)
    schema = "schema/minimal.yaml"
    kinds, slots = by_id(b["kinds"]), by_id(b["arrows"] + b["attributes"])
    assert {k: (x["stable_id"], x["span"]) for k, x in kinds.items()} == {
        "alpha": ("minimal/Alpha", span(schema, 20, 3)), "beta": ("minimal/Beta", span(schema, 30, 3))}
    assert {s: (x["stable_id"], x["span"]) for s, x in slots.items()} == {
        "alpha.title": ("minimal/Alpha#title", span(schema, 24, 7)), "alpha.size": ("minimal/Alpha#size", span(schema, 26, 7)),
        "beta.alpha": ("minimal/Beta#alpha", span(schema, 34, 7)), "beta.state": ("minimal/Beta#state", span(schema, 37, 7))}
    # a sentence is said of one element: it has that element's id and span
    assert {s: (x["sentence"]["id"], x["sentence"]["span"]) for s, x in slots.items()} == {
        s: (f"sentence:{x['stable_id']}", x["span"]) for s, x in slots.items()}
    rules = by_id(b["rules"])
    assert {r: x["span"] for r, x in rules.items()} == {"pair": span("rules/core.dl", 2, 1),
                                                         "big": span("rules/core.dl", 4, 3)}
    assert all(x["stable_id"].startswith(f"{r}~") and len(x["stable_id"]) == len(r) + 13 for r, x in rules.items())
    assert b["channels"]["sources"] == [
        {"id": "arrows/beta.alpha", "span": span("channels.yaml", 5, 5)},
        {"id": "kinds/alpha", "span": span("channels.yaml", 2, 5)},
        {"id": "kinds/beta", "span": span("channels.yaml", 3, 5)}]
    assert not any("renamed_from" in x for x in [*kinds.values(), *slots.values()])


def test_a_rule_keeps_its_stable_id_when_a_rule_is_added_above_it(fixture):
    before = by_id(bundle(fixture)["rules"])
    after = by_id(bundle(fixture, "// one more rule for the same head, above the others\n.decl pair(a: symbol, b: symbol)\n"
                                  "pair(a, a) :- alpha(a).\n" + RULES.replace(".decl pair(a: symbol, b: symbol)\n", ""))["rules"])
    # the runtime id renumbers (pair becomes pair_2); the stable id does not
    assert sorted(after) == ["big", "pair_1", "pair_2"]
    assert after["pair_2"]["stable_id"] == before["pair"]["stable_id"]
    assert after["big"]["stable_id"] == before["big"]["stable_id"]
    assert after["big"]["span"]["line"] == "6" and before["big"]["span"]["line"] == "4"
    assert after["pair_1"]["stable_id"] not in {x["stable_id"] for x in before.values()}


def test_the_same_rule_twice_is_refused(fixture):
    with pytest.raises(pack.CompileError, match="are the same rule"):
        bundle(fixture, RULES + "big(a) :- alpha__size(a, s), s >= 5.\n")


def test_a_renamed_slot_keeps_its_stable_id_and_records_its_old_name(fixture):
    before = by_id(bundle(fixture, None)["attributes"])["alpha.title"]
    change(fixture / "schema" / "minimal.yaml", "      title:\n        required: true\n",
           "      heading:\n        required: true\n        annotations:\n          renamed_from: title\n")
    change(fixture / "labels" / "nl.yaml", "alpha.title:", "alpha.heading:")
    after = by_id(bundle(fixture, None)["attributes"])["alpha.heading"]
    assert (after["stable_id"], after["renamed_from"]) == (before["stable_id"], "title") == ("minimal/Alpha#title", "title")


def test_a_renamed_kind_keeps_its_stable_id_and_its_slots_theirs(fixture):
    before = bundle(fixture, None)
    change(fixture / "schema" / "minimal.yaml", "  Alpha:\n", "  Gamma:\n    annotations:\n      renamed_from: Alpha\n")
    change(fixture / "schema" / "minimal.yaml", "range: Alpha", "range: Gamma")
    change(fixture / "channels.yaml", "kind: alpha", "kind: gamma")
    labels = fixture / "labels" / "nl.yaml"
    labels.write_text("".join(("gamma" + line[len("alpha"):]) if line.startswith("alpha") else line
                              for line in labels.read_text("utf-8").splitlines(keepends=True)), "utf-8")
    after = bundle(fixture, None)
    kind = by_id(after["kinds"])["gamma"]
    assert (kind["stable_id"], kind["renamed_from"]) == ("minimal/Alpha", "Alpha")
    assert {x["stable_id"] for x in after["attributes"]} == {x["stable_id"] for x in before["attributes"]}
    assert by_id(after["arrows"])["beta.alpha"]["target"] == "gamma"


def test_renamed_from_names_a_name(fixture):
    change(fixture / "schema" / "minimal.yaml", "  Alpha:\n", "  Alpha:\n    annotations:\n      renamed_from: \"1 two\"\n")
    with pytest.raises(pack.CompileError, match="renamed_from is the first name"):
        bundle(fixture, None)


def test_a_renamed_slot_beside_a_new_slot_of_its_first_name_is_refused(fixture):
    change(fixture / "schema" / "minimal.yaml", "      title:\n        required: true\n",
           "      heading:\n        required: true\n        annotations:\n          renamed_from: title\n"
           "      title:\n        required: true\n")
    with pytest.raises(pack.CompileError, match="slots alpha.heading and alpha.title have the same stable id 'minimal/Alpha#title'"):
        bundle(fixture, None)


def test_a_renamed_kind_beside_a_new_kind_of_its_first_name_is_refused(fixture):
    change(fixture / "schema" / "minimal.yaml", "  Beta:\n", "  Beta:\n    annotations:\n      renamed_from: Alpha\n")
    with pytest.raises(pack.CompileError, match="kinds alpha and beta have the same stable id 'minimal/Alpha'"):
        bundle(fixture, None)


def item_module(d: Path, name: str):
    (d / "schema" / f"{name}.yaml").write_text(
        f"id: https://rezono.example/{name}\nname: {name}\nin_language: nl\nimports:\n  - linkml:types\n"
        "default_range: string\nannotations:\n  layer: facts\n"
        "classes:\n  Item:\n    attributes:\n      id:\n        identifier: true\n      note: {}\n", "utf-8")


def test_a_same_named_class_added_in_another_module_changes_no_id(fixture):
    item_module(fixture, "one")
    before = bundle(fixture, None)
    item_module(fixture, "two")
    after = bundle(fixture, None)
    # the engine name of the first Item changes (item becomes one_item); its stable id and its slots' do not
    kinds = lambda b: {x["stable_id"] for x in b["kinds"]}
    slots = lambda b: {x["stable_id"] for x in b["arrows"] + b["attributes"]}
    assert kinds(after) == kinds(before) | {"two/Item"} and "one/Item" in kinds(before)
    assert slots(after) == slots(before) | {"two/Item#note"}
