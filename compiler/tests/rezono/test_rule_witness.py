"""One source row proves one listed item. The independent oracle is the authored rule and fact."""

import json
from pathlib import Path
import shutil

import pytest

from rezono_compiler import emit, pack, rules
from rezono_compiler.__main__ import explained
from support import FIXTURE
from test_rezono_module import declare


PAIR = Path(__file__).parent / "fixtures/listed"


def write_example(tmp_path, form):
    directory = Path(shutil.copytree(FIXTURE, tmp_path / form / "minimal"))
    (directory / "facts").mkdir()
    (directory / "facts/case.yaml").write_text("alpha: [{id: a, title: A}]\n", encoding="utf-8")
    with (directory / "labels/nl.yaml").open("a", encoding="utf-8") as labels:
        labels.write("\nlisted: opgenomen\n")
    with (directory / "messages/nl.mf2").open("a", encoding="utf-8") as messages:
        messages.write("\nrule.listed = {{Dit item is opgenomen.}}\n")
    if form == "datalog":
        (directory / "rules").mkdir()
        shutil.copy(PAIR / "eligibility.dl", directory / "rules/eligibility.dl")
    else:
        (directory / "rezono").mkdir()
        for name in ("eligibility.rezono", "eligibility.json"):
            shutil.copy(PAIR / name, directory / "rezono" / name)
        declare(directory, [{"module": "rezono/eligibility.rezono", "form": "rezono/eligibility.json", "layer": "facts"}])
    return directory


def check_meaning_and_origin(directory, source):
    model = pack.read(directory)
    files = explained(model, directory)
    [proof] = json.loads(files["0-case/proofs.json"])
    root = {"relation": "listed", "key": '["a"]'}
    assert proof == {
        "root": root, "manifest_id": "0-case", "witnesses": [{
            "conclusion": root, "rule_id": "listed",
            "bindings": [{"variable": "?x", "value": "a"}],
            "premises": [{"row": {"relation": "alpha", "key": '["a"]'}, "polarity": "positive", "stratum": 0}],
        }],
    }
    for relation in ("alpha", "listed"):
        assert json.loads(files[f"0-case/snapshots/{relation}.json"]) == [{"key": ["a"]}]
    bundle = emit.bundle(model, [], rules.load(model.rules))
    [rule] = bundle["rules"]
    assert {"element": "listed", "lang": "nl", "text": "opgenomen"} in bundle["labels"]
    resources = {entry["lang"]: entry["resource"] for entry in bundle["messages"]}
    assert "rule.listed = {{Dit item is opgenomen.}}" in resources["nl"].splitlines()
    assert (rule["id"], rule["message"], rule["variables"]) == (
        proof["witnesses"][0]["rule_id"], "rule.listed", [{"name": "?x", "type": "string"}],
    )
    assert rule["head"]["relation"] == root["relation"]
    [premise] = rule["body"]
    assert (premise["relation"], premise["polarity"], premise["position"]) == ("alpha", "positive", 1)
    # Locate the clause in this authored representation, independently of all compiler metadata.
    lines = (directory / source).read_text(encoding="utf-8").splitlines()
    [(line, column)] = [(i, text.index("listed(x)") + 1) for i, text in enumerate(lines, 1) if "listed(x)" in text]
    assert rule["origin"] == {"file": source, "line": str(line)}
    assert rule["span"] == {"file": source, "line": str(line), "column": str(column)}


def test_authored_rule_proves_listed_item(tmp_path):
    check_meaning_and_origin(write_example(tmp_path, "datalog"), "rules/eligibility.dl")


@pytest.mark.xfail(strict=True, raises=(pack.CompileError, AssertionError), reason="Publish relational rule blocks with authored clause positions in compiler/rezono_compiler. Read decisions/language-rules.md. Waits for contracts/rezono-module.yaml to admit module/2 rule blocks. The independent hand-authored form allows work before reader completion.")
def test_rezono_rule_proves_listed_item(tmp_path):
    check_meaning_and_origin(write_example(tmp_path, "rezono"), "rezono/eligibility.rezono")
