"""Compile the native rule from decisions/language-native-rules.md §7 against the authored Datalog rule."""

import json
from pathlib import Path
from shutil import copyfile, copytree

import pytest

from rezono_compiler import pack
from support import FIXTURE, compile_dir
from test_rezono_module import declare


FIXTURES = Path(__file__).parent / "fixtures"
SOURCE = "rezono/eligibility.rezono"
FORM = "rezono/eligibility.json"


def example(tmp_path, spelling):
    directory = copytree(FIXTURE, tmp_path / spelling / "minimal")
    with (directory / "labels/nl.yaml").open("a", encoding="utf-8") as labels:
        labels.write("\nlisted: listed\n")
    with (directory / "messages/nl.mf2").open("a", encoding="utf-8") as messages:
        messages.write("\nrule.listed = {{This item is listed.}}\n")
    if spelling == "datalog":
        (directory / "rules").mkdir()
        copyfile(FIXTURES / "listed/eligibility.dl", directory / "rules/eligibility.dl")
    else:
        (directory / "rezono").mkdir()
        for source in (SOURCE, FORM):
            authored = FIXTURES / "native-rule-ir-listed" / Path(source).name
            (directory / source).write_bytes(authored.read_text(encoding="utf-8").encode("utf-8"))
        declare(directory, [{"module": SOURCE, "form": FORM, "layer": "facts"}])
    return directory


@pytest.mark.xfail(
    strict=True,
    raises=(pack.CompileError, AssertionError),
    reason="Lower the authored listed rule through normal pack compilation with legacy rule identity and the native "
           "head span. Read decisions/language-native-rules.md §§5, 7, 11. Only change implementation under "
           "compiler/rezono_compiler/. Waits for native-rule-form-contract and for rezono.module/3 to be admitted "
           "at the normal compiler entry point. The hand-authored form has no reader dependency.",
)
def test_native_rule_ir_listed(tmp_path):
    legacy = compile_dir(example(tmp_path, "datalog"), tmp_path / "legacy-output")
    [old_rule] = json.loads(legacy["bundle/schema-bundle.json"])["rules"]

    native = compile_dir(example(tmp_path, "native"), tmp_path / "native-output")
    ir = json.loads(native["ir/rules.json"])
    assert ir["format"] == "rezono.rules/1"
    assert len(ir["rules"]) == 1
    [rule] = ir["rules"]
    assert rule["id"] == old_rule["id"] == "listed"
    assert rule["head"] == {"relation": "listed", "terms": ["?x"]}
    assert rule["body"] == [{"relation": "alpha", "terms": ["?x"], "polarity": "positive", "stratum": "0"}]
    assert not any(rule.get(member) for member in ("aggregates", "conditions", "assignments"))

    published_rules = json.loads(native["bundle/schema-bundle.json"])["rules"]
    assert len(published_rules) == 1
    [published] = published_rules
    assert published["stable_id"] == old_rule["stable_id"]
    assert published["origin"] == {"file": SOURCE, "line": "4"}
    assert published["span"] == {"file": SOURCE, "line": "4", "column": "6"}
