"""`world open, complete by <relation>` on a kind of a rezono 1 module: the scope in which an observed kind is
closed (decisions/language-rezono-1-defaults.md, section 2, "The scope"). The sources, the form members and the
printed line are written from that decision. The reader resolves no name, so the relation is not declared here."""

import json

import pytest
from reader_probe import read_modules

COVERED = """\
rezono 1
pack sample
kind Observation world open, complete by in_scope
  export: Text
  service: Text
  cluster: Text
"""

# `complete by` follows `world open`: without it, or after `world closed`, the line is not Rezono.
WITHOUT_WORLD = COVERED.replace("world open, complete by", "complete by", 1)
CLOSED = COVERED.replace("world open, complete by", "world closed, complete by", 1)


class MissingCompleteBy(AssertionError):
    """The reader did not read or print `complete by` on a rezono 1 kind, or accepted it without `world open`."""


def test_rezono_1_complete_by_reads_into_the_form():
    covered, without_world, closed = read_modules(COVERED, WITHOUT_WORLD, CLOSED)
    problems = []
    if covered["module"] is None or covered["format"] != "rezono.module/5" or covered["diagnostics"]:
        problems.append({"covered": covered})
    else:
        [observation] = [decl for decl in covered["module"]["decls"] if decl.get("kind") == "Observation"]
        if observation.get("world") != "open" or observation.get("complete") != "in_scope":
            problems.append({"covered form": observation})
        if covered["printed"] != COVERED:
            problems.append({"covered printed": covered["printed"], "want": COVERED})
    for label, read in (("without world open", without_world), ("after world closed", closed)):
        if read["module"] is not None or "R000" not in [d["code"] for d in read["diagnostics"]]:
            problems.append({label: read})
    if problems:
        raise MissingCompleteBy(json.dumps(problems, indent=2))
