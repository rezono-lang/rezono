"""A rule clause's sentence lowers to its message in the default language, and its source to the bundle's rule entry
(decisions/language-readable-rules.md, section 2). The module text and the expected message line are written from
that decision; the counter-cases are the same rule without a sentence and a sentence that the message file repeats."""

import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest
from expression_packs import ROOT, register
from rezono_compiler import emit, pack
from support import FIXTURE

KINDS = """rezono 0
pack minimal

kind Offer world closed

kind Product world closed
  offers: Offer*

kind Demand world closed
  product: Product
"""
RULE = "rule offers(d: Demand, o: Offer) when d in Demand and Demand.product(d, p) and Product.offers(p, o)"
SENTENCE = '\n  means "{$d} can buy {$o}."  @ policy#art-3\n'


def compiled(tmp_path: Path, source: str, message_line: str | None = None) -> dict:
    directory = Path(shutil.copytree(FIXTURE, tmp_path / "minimal"))
    if message_line is not None:
        with (directory / "messages/nl.mf2").open("a", encoding="utf-8", newline="\n") as messages:
            messages.write("\n" + message_line + "\n")
    folder = directory / "rezono"
    folder.mkdir()
    module, form = folder / "demand.rezono", folder / "demand.json"
    module.write_text(source, encoding="utf-8", newline="\n")
    result = subprocess.run(
        [os.environ.get("REZONO_NODE", "node"), str(ROOT / "rezono/src/write-form.ts"), str(module), str(form)],
        capture_output=True, text=True, encoding="utf-8", check=False,
    )
    if result.returncode != 0:
        raise MissingRuleSentenceLowering(result.stderr)
    register(directory, {"module": "rezono/demand.rezono", "form": "rezono/demand.json", "layer": "facts"})
    return json.loads(emit.compile_pack(pack.read(directory))["bundle/schema-bundle.json"])


def published(bundle: dict) -> tuple[dict, list[str]]:
    [rule] = [rule for rule in bundle["rules"] if rule["relation"] == "offers"]
    [messages] = [entry["resource"] for entry in bundle["messages"] if entry["lang"] == "nl"]
    return rule, messages.splitlines()


class MissingRuleSentenceLowering(AssertionError):
    """The sentence or source of a rule clause was not published as the decision gives, or a repeated one passed."""


@pytest.mark.xfail(
    strict=True,
    raises=MissingRuleSentenceLowering,
    reason="extra: decisions/language-readable-rules.md: Lower the member means of a rule clause to the line "
           "`<message> = {{TEXT}}` in the messages of the default language and its member source to source in the "
           "bundle's rule entry, in compiler/rezono_compiler/rezono_module.py and the bundle writer; refuse a "
           "means whose message key messages/<default_language>.mf2 also gives. Read section 2. Waits for "
           "test_rule_sentence, which reads the members.",
)
def test_lower_rule_sentence(tmp_path):
    # Counter-case: without a sentence the clause keeps its message key and has no source.
    plain, lines = published(compiled(tmp_path / "plain", KINDS + "\n" + RULE + "\n"))
    assert plain["message"] == "rule.offers" and "source" not in plain
    assert not any(line.startswith("rule.offers ") for line in lines)

    try:
        rule, lines = published(compiled(tmp_path / "sentence", KINDS + "\n" + RULE + SENTENCE))
    except pack.CompileError as error:
        raise MissingRuleSentenceLowering(str(error)) from error
    problems = []
    if rule.get("source") != "policy#art-3":
        problems.append({"rule": rule})
    if "rule.offers = {{{$d} can buy {$o}.}}" not in lines:
        problems.append({"messages": [line for line in lines if line.startswith("rule.")]})
    try:
        compiled(tmp_path / "twice", KINDS + "\n" + RULE + SENTENCE, "rule.offers = {{{$d} buys {$o}.}}")
        problems.append("a sentence that messages/nl.mf2 repeats was not refused")
    except pack.CompileError:
        pass
    if problems:
        raise MissingRuleSentenceLowering(json.dumps(problems, indent=2))
