"""A fact that restates a conclusion warns W116 and is never refused (decisions/facts-and-derivations.md, section 5).

The expectations are worked by hand from that decision. The pack counts the parts of each alpha, `part_count(alpha,
size)`, a conclusion that combines several part rows. A beta record with the slots `alpha` and `size` restates that
conclusion when its two values are a row the rules derive without it. The conclusion's address is its canonical IRI
under the pack's default publication base (decisions/publication-conclusion-addresses.md, section 1), spelled with
the publication's own segment speller; a decision cites it pinned to an epoch and a dataset hash (section 3 of
decisions/facts-and-derivations.md).
"""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest
import yaml
from rezono_canon import canonical_json
from rezono_compiler import modules
from rezono_compiler.__main__ import main
from rezono_publication import rdf
from support import FIXTURE, REPO

DECISION = REPO / "packs" / "std-decision"
BASE = "https://rezono.example/minimal/"  # the default base of a pack named minimal without an `iri:` block
DATASET = "d-" + "4d" * 32
WITNESS = f"{BASE}witness/{'5e' * 32}"

TOOL = {"kind": "tool", "name": "Part counter", "position": "run 7"}
DESIGN = {"kind": "git", "name": "example/minimal", "revision": "0123abc", "position": "decisions/sizes.md#beta"}

ALPHA = """\
alpha:
  - {id: a1, title: first}
  - {id: a2, title: second}
part:
  - {id: p1, alpha: a1}
  - {id: p2, alpha: a1}
  - {id: p3, alpha: a2}
  - {id: p4, alpha: a2}
  - {id: p5, alpha: a2}
"""
RULES = """\
// The number of parts of an alpha: a conclusion that combines the part rows.
.decl part_count(alpha: symbol, size: number)
part_count(a, n) :- alpha(a), n = count : { part__alpha(_, a) }.
.output part_count
"""


def schema(cited: bool) -> str:
    imports = '[linkml:types, "std-decision:decision"]' if cited else "[linkml:types]"
    decision = "      decision: {range: Decision}\n" if cited else ""
    return f"""\
id: https://rezono.example/minimal
name: minimal
in_language: nl
imports: {imports}
default_range: string
annotations:
  layer: facts
types:
  Count:
    typeof: integer
classes:
  Alpha:
    attributes:
      id: {{identifier: true}}
      title: {{required: true}}
  Part:
    attributes:
      id: {{identifier: true}}
      alpha: {{range: Alpha, required: true}}
  Beta:
    attributes:
      id: {{identifier: true}}
      alpha: {{range: Alpha, required: true}}
      size: {{range: Count}}
{decision}"""


def address(alpha: str, size: int) -> str:
    """The unpinned conclusion IRI of the row part_count(alpha, size): `<base>PartCount/<spelled id>`, where the id
    is the row's canonical key, every cell as text, as a witness's RowRef names it."""
    return f"{BASE}PartCount/{rdf.spell(canonical_json([alpha, str(size)]))}"


class MissingRestatementWarning(AssertionError):
    """A fact record that restates a conclusion did not warn W116 as the decision gives it."""


def make_pack(tmp_path: Path, name: str, beta: str, *, observed: tuple[str, ...] = (), cited: bool = False,
              decisions: str = "") -> Path:
    """A pack named minimal with the part count rule; the beta records in `observed` have a tool source."""
    directory = Path(shutil.copytree(FIXTURE, tmp_path / name / "minimal"))
    (directory / "schema" / "minimal.yaml").write_text(schema(cited), encoding="utf-8")
    (directory / "rules").mkdir()
    (directory / "rules" / "count.dl").write_text(RULES, encoding="utf-8")
    (directory / "channels.yaml").write_text(
        "kinds:\n  - {kind: alpha, shape: rect}\n  - {kind: part, shape: rect}\n  - {kind: beta, shape: ellipse}\n"
        "arrows:\n  - {arrow: beta.alpha, dash: none}\n  - {arrow: part.alpha, dash: none}\n", encoding="utf-8")
    (directory / "labels" / "nl.yaml").write_text(
        "alpha: alfa\nalpha.title: titel\npart: deel\npart.alpha: alfa\nbeta: bèta\nbeta.alpha: alfa\n"
        "beta.size: grootte\npart_count: aantal delen\n" + ("beta.decision: besluit\n" if cited else ""),
        encoding="utf-8")
    if cited:
        meta = yaml.safe_load((directory / "pack.yaml").read_text(encoding="utf-8"))
        meta["imports"] = [{"name": "std-decision", "path": DECISION.as_posix(), "sha256": modules.pack_hash(DECISION)}]
        (directory / "pack.yaml").write_text(yaml.safe_dump(meta, sort_keys=False), encoding="utf-8")
    facts = directory / "facts"
    facts.mkdir()
    (facts / "alpha.yaml").write_text(ALPHA, encoding="utf-8")
    (facts / "alpha.sources.yaml").write_text(yaml.safe_dump({"default": TOOL}), encoding="utf-8")
    (facts / "beta.yaml").write_text(beta, encoding="utf-8")
    (facts / "beta.sources.yaml").write_text(yaml.safe_dump({
        "default": DESIGN,
        **({"records": [{"of": {"kind": "beta", "id": identifier}, **TOOL} for identifier in observed]}
           if observed else {}),
    }, sort_keys=True), encoding="utf-8")
    if decisions:
        (facts / "decisions.yaml").write_text(decisions, encoding="utf-8")
    return directory


def compiled(directory: Path, tmp_path: Path, capsys) -> tuple[int, list[str]]:
    """The command's status and its W116 lines."""
    status = main(["compile", str(directory), str(tmp_path / "out" / directory.parent.name)])
    err = capsys.readouterr().err
    return status, [line for line in err.splitlines() if "W116" in line]


def at(found: list[str], line: int) -> list[str]:
    return [text for text in found if f"facts/beta.yaml:{line}:" in text]


def names(text: str, identifier: str, alpha: str, size: int) -> bool:
    return all(part in text for part in ("beta", identifier, "part_count", address(alpha, size)))


@pytest.mark.xfail(strict=True, raises=AssertionError, reason=(
    "extra: decisions/facts-and-derivations.md: the compiler gives no W116 for a fact record that restates a "
    "derived conclusion without citing its address, and std-decision has no ConclusionCitation (sections 3 and 5)"))
def test_a_fact_that_restates_a_conclusion_warns(tmp_path, capsys):
    problems = []

    # b1 (line 2) restates part_count(a1, 2); b2 (line 3) differs from part_count(a2, 3); b3 (line 4) restates
    # part_count(a1, 2) but has a tool source, an observation.
    beta = ("beta:\n  - {id: b1, alpha: a1, size: 2}\n  - {id: b2, alpha: a2, size: 4}\n"
            "  - {id: b3, alpha: a1, size: 2}\n")
    status, found = compiled(make_pack(tmp_path, "stored", beta, observed=("b3",)), tmp_path, capsys)
    if status != 0:
        problems.append(f"W116 is a warning: a pack with a restated conclusion still compiles (status {status})")
    named = at(found, 2)
    if len(named) != 1 or not names(named[0], "b1", "a1", 2):
        problems.append(f"expected one W116 at facts/beta.yaml:2 naming beta b1, part_count and "
                        f"{address('a1', 2)}: {found}")
    if at(found, 3) or at(found, 4) or len(found) != len(named):
        problems.append(f"no W116 for a record that differs (b2) or has an observation source (b3): {found}")

    # A decision that cites the conclusion's pinned address and witness takes it as a fact: b4 (line 3) is bound
    # to d1, which cites part_count(a1, 2). b5 (line 4) is bound to d2, which cites another row's conclusion.
    decisions = (
        "decision:\n"
        "  - {id: d1, title: Take the part count of a1 as a size, state: in_force, decider: [owner], "
        "decided_on: 2026-11-21}\n"
        "  - {id: d2, title: Take the part count of a2 as a size, state: in_force, decider: [owner], "
        "decided_on: 2026-11-21}\n"
        "conclusion_citation:\n"
        f"  - {{id: c1, decision: d1, conclusion: '{rdf.pin_iri(address('a1', 2), dataset=DATASET, manifest='m-1')}', "
        f"witness: '{WITNESS}'}}\n"
        f"  - {{id: c2, decision: d2, conclusion: '{rdf.pin_iri(address('a2', 3), dataset=DATASET, manifest='m-1')}', "
        f"witness: '{WITNESS}'}}\n"
    )
    beta = ("beta:\n  - {id: b1, alpha: a1, size: 2}\n  - {id: b4, alpha: a1, size: 2, decision: d1}\n"
            "  - {id: b5, alpha: a1, size: 2, decision: d2}\n")
    status, found = compiled(make_pack(tmp_path, "cited", beta, cited=True, decisions=decisions), tmp_path, capsys)
    if status != 0:
        problems.append(f"a pack whose decision cites a conclusion compiles (status {status})")
    else:
        if at(found, 3):
            problems.append(f"b4 is bound to a decision that cites the conclusion it restates: {at(found, 3)}")
        if len(at(found, 4)) != 1 or not names(at(found, 4)[0], "b5", "a1", 2):
            problems.append(f"b5's decision cites another row's conclusion, so b5 still warns: {found}")
        if len(at(found, 2)) != 1:
            problems.append(f"an uncited record beside a cited one still warns: {found}")
    if problems:
        raise MissingRestatementWarning("\n".join(problems))
