"""Certified rounds through batch.epoch, from decisions/admission-transport.md sections 2, 5, 6 and 8.

The round context is retained in the trusted context under `rounds`, the round claim is listed in the
submitted index under `rounds`, and only a claim the round verifier admits fills the protected inputs
`verified_round` and `verified_round_member` before the rules. The round and receipt fixtures are the
hand-authored ones of the checker tasks.
"""

import shutil
import sys
from pathlib import Path

import pytest
from rezono_compiler.pack import CompileError
from rezono_publisher import batch

ROOT = Path(__file__).resolve().parents[3]
MINIMAL = ROOT / "compiler/tests/fixtures/minimal"
RULES = """.decl verified_round(round: symbol, run: symbol, cut: symbol, batch: symbol)
.decl verified_round_member(round: symbol, step: symbol)
.decl chosen(run: symbol, step: symbol)
chosen(r, s) :- verified_round(o, r, _, _), verified_round_member(o, s).
"""
SCHEMA = """id: https://rezono.example/rounds
name: rounds
in_language: en
imports: [linkml:types]
default_range: string
annotations: {layer: facts}
classes:
  Item:
    attributes:
      id: {identifier: true}
"""
INSTANT = "2026-01-01T00:00:00Z"


def pack(root):
    root.mkdir()
    (root / "pack.yaml").write_text('name: rounds\nversion: "1"\ndefault_language: nl\n', encoding="utf-8")
    shutil.copytree(MINIMAL / "messages", root / "messages")
    (root / "channels.yaml").write_text("kinds: [{kind: item, shape: rect}]\n", encoding="utf-8")
    (root / "labels").mkdir()
    (root / "labels/nl.yaml").write_text("item: Item\n", encoding="utf-8")
    for folder, filename, content in (("schema", "rounds.yaml", SCHEMA), ("rules", "chosen.dl", RULES),
                                      ("facts", "items.yaml", "item: [{id: anchor}]\n")):
        (root / folder).mkdir()
        (root / folder / filename).write_text(content, encoding="utf-8")
    return root


def archived(step="replace-link-a"):
    """One archive with a receipt and a round: (evidence arguments, claim reference)."""
    sys.path.insert(0, str(ROOT / "checker/tests"))
    from test_evidence_admission import Archive, layout
    from test_round_verifier import fixture

    rounds, round_context, claim = fixture(step)
    archive = Archive(rounds)
    context, index, _, _, _ = layout(archive, rounds={"contexts": [round_context], "claims": [claim]})
    return (context, index, archive.__getitem__), claim


@pytest.mark.xfail(strict=True, raises=(ImportError, CompileError, TypeError),
                   reason="Waits for checker/tests/test_evidence_admission.py--test_evidence_admits_rounds_after_"
                          "receipts, edge/publisher/tests/test_evidence_batch.py--test_batch_admits_evidence_before_"
                          "the_rules (same batch code) and compiler/tests/test_protected_admission_relations.py--"
                          "test_admission_relations_are_protected_inputs. Then insert the admitted verified_round and "
                          "verified_round_member rows before the rules, as decisions/admission-transport.md sections "
                          "5, 6 and 8 fix. Publisher batch only.")
def test_batch_admits_certified_rounds_before_the_rules(tmp_path):
    from rezono_checker.evidence import Evidence

    root = pack(tmp_path / "pack")
    plain = batch.epoch(root, epoch=1, knowledge_time=INSTANT, sources=[])
    assert (plain.rows.get("verified_round", []), plain.rows.get("chosen", [])) == ([], [])

    arguments, claim = archived()
    epoch = batch.epoch(root, epoch=1, knowledge_time=INSTANT, sources=[], evidence=Evidence(*arguments))
    assert epoch.rows["verified_round"] == [(claim["sha256"], "run-a", "cut-a", "batch-replace-link-a")]
    assert epoch.rows["verified_round_member"] == [(claim["sha256"], "replace-link-a")]
    assert epoch.rows["chosen"] == [("run-a", "replace-link-a")]
    # The receipt in the same index is admitted, but this pack does not declare verified_receipt.
    assert "verified_receipt" not in epoch.rows

    # A preceded choice without refuting evidence is not admitted: no round, nothing chosen.
    arguments, _ = archived("move-link-a")
    epoch = batch.epoch(root, epoch=1, knowledge_time=INSTANT, sources=[], evidence=Evidence(*arguments))
    assert (epoch.rows.get("verified_round", []), epoch.rows.get("verified_round_member", []),
            epoch.rows.get("chosen", [])) == ([], [], [])
