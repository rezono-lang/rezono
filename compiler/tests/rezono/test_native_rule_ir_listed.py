"""Compare the listed rule's checked conclusions and grounds across source forms."""

import json
from pathlib import Path
from shutil import copytree

from rezono_checker.canon import encode_key
from rezono_checker.grounds import checked_grounds
from rezono_checker.rules import load_rules
from rezono_compiler import emit
from rezono_publisher import publish, store
from support import FIXTURE
from test_native_rule_publication_parity import artifact, build, definition_pin, digest, write
from test_rezono_module import declare


FIXTURES = Path(__file__).parent / "fixtures"
LEGACY = "rules/eligibility.dl"
SOURCE = "rezono/eligibility.rezono"
FORM = "rezono/eligibility.json"
FACTS = """alpha:
  - {id: first, title: First}
  - {id: second, title: Second}
beta:
  - {id: first, alpha: first}
  - {id: second, alpha: second}
"""


def example(tmp_path, source):
    directory = copytree(FIXTURE, tmp_path / "minimal")
    write(directory, "facts/base.yaml", FACTS)
    write(directory, "facts/base.sources.yaml",
          'default: {kind: git, name: rezono-lang/rezono, revision: "0000000", '
          'position: compiler/tests/rezono/test_native_rule_ir_listed.py#FACTS}\n')
    with (directory / "labels/nl.yaml").open("a", encoding="utf-8") as labels:
        labels.write("\nlisted: listed\n")
    with (directory / "messages/nl.mf2").open("a", encoding="utf-8") as messages:
        messages.write("\nrule.listed = {{This item is listed.}}\n")
    if source == LEGACY:
        legacy = (FIXTURES / "listed/eligibility.dl").read_text(encoding="utf-8")
        # A different local binding spelling exercises the migration comparison.
        write(directory, LEGACY, legacy.replace("listed(x) :- alpha(x).", "listed(member) :- alpha(member)."))
    else:
        for file in (SOURCE, FORM):
            authored = FIXTURES / "native-rule-ir-listed" / Path(file).name
            write(directory, file, authored.read_text(encoding="utf-8"))
        declare(directory, [{"module": SOURCE, "form": FORM, "layer": "facts"}])
    return directory


def edition(tmp_path, source, line, column):
    directory = example(tmp_path, source)
    epoch = build(directory, source, 1)
    bucket = store.FileStore(tmp_path / "publication")
    manifest = publish.publish(epoch, bucket, {"checker": "complete"})
    assert manifest["definition_sha256"] == definition_pin(directory)
    assert manifest["sources"] == [{"source_id": "rules", "position": digest((directory / source).read_bytes())}]
    assert {check["status"] for check in manifest["checks"]} == {"green"}

    compiled = {entry["file"]: artifact(bucket, entry) for entry in manifest["compiled"]}
    ir = compiled["ir/rules.json"]
    assert ir["format"] == "rezono.rules/1"
    [relation] = [entry for entry in ir["relations"] if entry["name"] == "listed"]
    assert relation["key"] == [{"name": "item", "type": "string"}]
    [rule] = ir["rules"]
    assert rule["head"]["relation"] == "listed"
    assert rule["witness"]["relation"] == f"{rule['id']}__witness"
    assert not any(rule.get(member) for member in ("aggregates", "conditions", "assignments"))

    bundle = compiled["bundle/schema-bundle.json"]
    [published] = bundle["rules"]
    assert published["id"] == rule["id"]
    assert published["stable_id"] == emit.rule_id(published["head"], published["body"])
    assert published["origin"] == {"file": source, "line": line}
    assert published["span"] == {"file": source, "line": line, "column": column}
    [messages] = [entry["resource"] for entry in bundle["messages"] if entry["lang"] == "nl"]
    assert f"{published['message']} = {{{{This item is listed.}}}}" in messages.splitlines()

    snapshots = [entry for entry in manifest["snapshots"] if entry["role"] == "checker"]
    [listing] = [entry for entry in snapshots if entry["relation"] == "listed"]
    keys = {tuple(row["key"]) for row in artifact(bucket, listing)}
    [proof_ref] = [entry for entry in manifest["witnesses"] if entry["role"] == "checker"]
    proofs = artifact(bucket, proof_ref)["witnesses"]
    assert len(proofs) == len(keys)
    assert {proof["rule_id"] for proof in proofs} == {rule["id"]}
    assert {tuple(json.loads(proof["conclusion"]["key"])) for proof in proofs} == keys
    assert all(proof["conclusion"]["relation"] == "listed" for proof in proofs)

    grounds = checked_grounds(
        epoch.witnesses, {"id": manifest["id"], "snapshots": snapshots}, load_rules(ir),
        lambda uri: bucket.get(uri.removeprefix(bucket.uri(""))),
    )
    return keys, grounds


def test_native_rule_ir_listed(tmp_path):
    expected_keys = {("first",), ("second",)}
    expected_grounds = {("listed", encode_key(key)): {("read", "alpha", encode_key(key))} for key in expected_keys}
    legacy = edition(tmp_path / "datalog", LEGACY, "2", "1")
    native = edition(tmp_path / "native", SOURCE, "4", "6")
    assert legacy == native == (expected_keys, expected_grounds)
