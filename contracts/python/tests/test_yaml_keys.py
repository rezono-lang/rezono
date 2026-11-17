"""contracts/yaml_keys.py: a value a YAML flow map split on its comma is refused, every contract passes (#1020)."""

import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
spec = importlib.util.spec_from_file_location("yaml_keys", ROOT / "contracts" / "yaml_keys.py")
assert spec and spec.loader
yaml_keys = importlib.util.module_from_spec(spec)
spec.loader.exec_module(yaml_keys)


def test_text_cut_at_a_comma_is_refused():
    # #1020's two lines before its fix.
    cut = yaml_keys.findings(
        "classes:\n  KindIndex:\n    attributes:\n"
        "      fanout: {range: integer, required: true, minimum_value: 2, description: Children per page, at most.}\n"
        "enums:\n  FacetCase:\n    permissible_values:\n"
        "      enum: {description: An enum slot; its values are the enum's, as the snapshot holds them.}\n", "k.yaml")
    assert cut == ["k.yaml:4: the key 'at most.' is text, not a name; quote the value it came from",
                   "k.yaml:8: the key 'as the snapshot holds them.' is text, not a name; quote the value it came from"]
    # Without a period the flow map entry with no value still shows the cut.
    assert yaml_keys.findings("a: {description: red, green and blue}\n") == [
        "<text>:1: the flow map entry 'green and blue' has no value; quote the text before it if it holds a comma"]
    # A key that is a list or a map.
    assert yaml_keys.findings("a: {description: see, [x]}\n") == [
        "<text>:1: a key that is a list or a map; quote the value it came from"]
    # A key in block style that is a sentence.
    assert yaml_keys.findings("slots:\n  This is a sentence. It is no slot: {}\n") == [
        "<text>:2: the key 'This is a sentence. It is no slot' is text, not a name; quote the value it came from"]


def test_quoted_text_names_and_block_values_pass():
    assert yaml_keys.findings(
        "a: {description: \"Children per page, at most.\", range: integer}\n"
        "b:\n  description: Children per page, at most.\n  rezono.kind-index: {pattern: '^a, b$'}\n"
        "c: [x, y, z]\nd:\n") == []


def test_every_contract_passes():
    assert yaml_keys.main([]) == 0
