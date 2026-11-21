"""A native rule cannot read a personal slot (decisions/personal-data-handling.md section 3, R054).

Two implementations refuse it, and each test here drives one of them alone, so a refusal in the other cannot
stand in for it:

- rezono/src/native-rule-check.ts checks a module's rule form against the schema it is handed. The form comes
  from the Rezono reader; the handed schema marks the slot personal. No Python runs.
- compiler/rezono_compiler/native_rule_signatures.py links in-memory module forms against the pack's schema,
  where the slot carries the `personal: true` annotation. No Rezono reader runs.

A rule reads a slot by a path (`item.display_name`) or by its slot row (`Subject.display_name(item, _)`). The
same rules over a slot that is not personal pass both checks.
"""

import json
import os
from pathlib import Path
import subprocess

import pytest
import yaml

from rezono_compiler import pack
from rezono_compiler.native_rule_signatures import link


ROOT = Path(__file__).resolve().parents[3]
PACK = "registry"
SOURCE = "rezono/reads.rezono"
PERSONAL = "display_name"
PLAIN = "label"

# Reads the module text with the Rezono reader, then checks its rule form against the handed environment.
CHECK = """\
import { readFileSync } from 'node:fs';
import { pathToFileURL } from 'node:url';
const [source, text, environment] = process.argv.slice(2);
const { moduleForm } = await import(pathToFileURL(source + '/module-json.ts').href);
const { checkNativeRules } = await import(pathToFileURL(source + '/native-rule-check.ts').href);
const { form, diagnostics } = moduleForm(readFileSync(text, 'utf8'));
const checked = form ? checkNativeRules(form, JSON.parse(readFileSync(environment, 'utf8'))) : [];
console.log(JSON.stringify({ read: diagnostics.map(d => d.code), checked: checked.map(d => d.code) }));
"""


def _environment():
    """The schema the TypeScript check is handed: one kind with a personal and a plain text slot."""
    text = {"type": "Text", "card": "1", "states": ["known"]}
    return {
        "schema": {
            "rezono": "1.0", "pack": PACK, "base": "https://example.org/registry/",
            "kinds": {"Subject": {"world": "closed", "id": {"type": "Text"},
                                  "slots": {PERSONAL: {**text, "personal": True}, PLAIN: dict(text)}}},
        },
        "relations": {
            "shown": {"role": "derived", "owner": PACK, "world": "closed",
                      "columns": [{"name": "item", "type": "Subject"}, {"name": "value", "type": "Text"}]},
            "listed": {"role": "derived", "owner": PACK, "world": "closed",
                       "columns": [{"name": "item", "type": "Subject"}]},
        },
    }


def _native_check_codes(tmp_path, slot):
    """The codes the reader and then native-rule-check.ts give for a rule by path and a rule by slot row."""
    module = tmp_path / "reads.rezono"
    module.write_text(
        f"rezono 0\npack {PACK}\n"
        f"rule shown(item: Subject, value: Text) when item in Subject and value = item.{slot}\n"
        f"rule listed(item: Subject) when item in Subject and Subject.{slot}(item, _)\n",
        encoding="utf-8", newline="\n",
    )
    environment = tmp_path / "environment.json"
    environment.write_text(json.dumps(_environment()), encoding="utf-8")
    script = tmp_path / "check.mjs"
    script.write_text(CHECK, encoding="utf-8", newline="\n")
    result = subprocess.run(
        [os.environ.get("REZONO_NODE", "node"), str(script), str(ROOT / "rezono/src"), str(module), str(environment)],
        capture_output=True, text=True, encoding="utf-8",
        env={name: value for name, value in os.environ.items() if not name.upper().startswith("NODE_")},
    )
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout)


def _pointers(value, at):
    if isinstance(value, dict):
        yield at
        for name, child in sorted(value.items()):
            yield from _pointers(child, f"{at}/{name}")
    elif isinstance(value, list):
        for index, child in enumerate(value):
            yield from _pointers(child, f"{at}/{index}")


def _form(decls):
    """Supply positions for this in-memory tree without a Rezono reader, one line per declaration."""
    places = []
    for index, node in enumerate(decls):
        line = 3 + index
        for pointer in _pointers(node, f"/decls/{index}"):
            start = str(100 * line)
            places.append({"at": pointer, "line": str(line), "start": start, "end": start})
    body = {"rezono": "0", "pack": PACK, "use": [], "decls": decls}
    return {"format": "rezono.module/3", "module": body, "spans": places}


def _linked(tmp_path, slot):
    """Link a rule by path and a rule by slot row over `slot` against a schema with one personal slot."""
    directory = tmp_path / PACK
    (directory / "schema").mkdir(parents=True)
    (directory / "pack.yaml").write_text(
        yaml.safe_dump({"name": PACK, "version": "1", "default_language": "en"}), encoding="utf-8")
    (directory / "schema/subjects.yaml").write_text(yaml.safe_dump({
        "id": "https://example.org/registry", "name": "subjects", "imports": ["linkml:types"],
        "annotations": {"layer": "facts"},
        "classes": {"Subject": {"attributes": {
            "code": {"identifier": True, "range": "string"},
            PERSONAL: {"range": "string", "required": True, "annotations": {"personal": True}},
            PLAIN: {"range": "string", "required": True},
        }}},
    }), encoding="utf-8")
    item, value = {"path": ["item"]}, {"path": ["value"]}
    member = {"in": [item, {"kind": "Subject"}]}
    decls = [
        {"rule": "shown",
         "columns": [{"name": "item", "type": "Subject"}, {"name": "value", "type": "Text"}],
         "when": {"and": [member, {"cmp": ["=", value, {"path": ["item", slot]}]}]}},
        {"rule": "listed", "columns": [{"name": "item", "type": "Subject"}],
         "when": {"and": [member, {"call": [f"Subject.{slot}", [item, {"wildcard": True}]]}]}},
    ]
    return link(directory, {(PACK, SOURCE): _form(decls)})


def test_native_check_accepts_rule_reading_plain_slot(tmp_path):
    assert _native_check_codes(tmp_path, PLAIN) == {"read": [], "checked": []}


@pytest.mark.xfail(
    strict=True,
    raises=AssertionError,
    reason=(
        "extra: decisions/personal-data-handling.md: rezono/src/native-rule-check.ts refuses a native rule that "
        "reads a personal slot, by a path or by its slot row, with R054 (section 3). Waits for "
        "compiler/tests/test_personal_slots.py--test_rule_reading_personal_slot_is_refused (#1342), which lifts "
        "it with the fix."
    ),
)
def test_native_check_refuses_rule_reading_personal_slot(tmp_path):
    assert _native_check_codes(tmp_path, PERSONAL) == {"read": [], "checked": ["R054", "R054"]}


def test_linker_accepts_rule_reading_plain_slot(tmp_path):
    linked = _linked(tmp_path, PLAIN)
    assert linked.clauses[(PACK, SOURCE, "/decls/0")].relation == "shown"
    assert linked.clauses[(PACK, SOURCE, "/decls/1")].relation == "listed"


@pytest.mark.xfail(
    strict=True,
    raises=AssertionError,
    reason=(
        "extra: decisions/personal-data-handling.md: compiler/rezono_compiler/native_rule_signatures.py refuses "
        "a native rule that reads a personal slot, by a path or by its slot row, with R054 (section 3). Waits "
        "for compiler/tests/test_personal_slots.py--test_rule_reading_personal_slot_is_refused (#1342), which "
        "lifts it with the fix."
    ),
)
def test_linker_refuses_rule_reading_personal_slot(tmp_path):
    try:
        _linked(tmp_path, PERSONAL)
    except pack.CompileError as error:
        assert [diagnostic.code for diagnostic in error.diagnostics] == ["R054", "R054"], error.diagnostics
    else:
        raise AssertionError("the linker accepted native rules that read the personal slot Subject.display_name")
