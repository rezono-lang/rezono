"""A reason declaration must lower to the sentence `reason.<code>` in the pack's default language, as the same line
in its message file gives (decisions/language-reasons.md). The oracle is the pack with that line written in
messages/nl.mf2 instead; the module form is written by hand, independently of the Rezono reader."""

import json
from pathlib import Path
import shutil

import pytest

from support import FIXTURE, compile_dir
from test_rezono_module import add, module
from rezono_compiler import pack

LINE = "reason.no_rate = {{no monthly rate published yet}}\n"
DECLARED = {"reason": "no_rate", "text": '"no monthly rate published yet"'}


def messages(d: Path, out: Path) -> list:
    bundle = json.loads(compile_dir(d, out)["bundle/schema-bundle.json"])
    return sorted((m["lang"], m["resource"]) for m in bundle["messages"])


class MissingReasonLowering(AssertionError):
    """The compiler refused a reason declaration, or lowered it otherwise than the decision gives."""


@pytest.mark.xfail(
    strict=True,
    raises=MissingReasonLowering,
    reason="extra: decisions/language-reasons.md: Lower a reason declaration of a module to the sentence "
           "reason.<code> = {{label}} in the messages of the pack's default language, in "
           "compiler/rezono_compiler/rezono_module.py instead of the refusal of reason in REFUSED, and refuse at "
           "the declaration a code that the message file of that language also gives. Read the sections Lowering "
           "and Considered. Waits for a planner to drop the case 'a reason' from REFUSALS in "
           "compiler/tests/test_rezono_module.py, which still expects a reason declaration to be refused as not "
           "lowered.",
)
def test_lower_reason(tmp_path):
    legacy = Path(shutil.copytree(FIXTURE, tmp_path / "legacy" / "minimal"))
    add(legacy / "messages" / "nl.mf2", LINE)
    module(legacy, [])
    expected = messages(legacy, tmp_path / "legacy-out")
    assert any(LINE.strip() in resource.splitlines() for lang, resource in expected if lang == "nl"), expected

    candidate = Path(shutil.copytree(FIXTURE, tmp_path / "candidate" / "minimal"))
    module(candidate, [DECLARED])
    try:
        actual = messages(candidate, tmp_path / "candidate-out")
    except pack.CompileError as refused:
        raise MissingReasonLowering(str(refused)) from refused
    if actual != expected:
        raise MissingReasonLowering(json.dumps({"expected": expected, "actual": actual}, indent=2))

    # Counter-case: one sentence has one source, so the same code in the module and the message file is refused.
    twice = Path(shutil.copytree(FIXTURE, tmp_path / "twice" / "minimal"))
    add(twice / "messages" / "nl.mf2", LINE)
    module(twice, [DECLARED])
    with pytest.raises(pack.CompileError, match=r"minimal/rezono/m\.rezono:10: .*no_rate"):
        pack.read(twice)
