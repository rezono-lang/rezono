"""Planner red test for a multi-witness conclusion in tests/fixtures/slip (decisions/publish-founded-witnesses.md, #1445).

Verifies that tests/fixtures/slip publishes at least one conclusion with at least two distinct founded
witnesses for `reader`, each carrying its canonical `<base>witness/<64 hex>` IRI, so Cartouche's
`m1-slip-all-witnesses` can record and test it directly from fixtures/10-slip-reader-answers.json.
"""

from collections import Counter
import json
import re
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
import slip_support as slip

WITNESS_IRI_RE = re.compile(r"^.+witness/[0-9a-f]{64}$")


@pytest.mark.xfail(
    strict=True,
    raises=AssertionError,
    reason=(
        "extra: decisions/publish-founded-witnesses.md (#1445): tests/fixtures/slip must publish at least one "
        "conclusion with >= 2 distinct founded witnesses (each carrying its canonical <base>witness/<64 hex> IRI) "
        "for Cartouche m1-slip-all-witnesses"
    ),
)
def test_slip_fixture_publishes_conclusion_with_at_least_two_founded_witnesses(tmp_path):
    store, _manifest = slip.publish_main(tmp_path)
    # Inspect every published proof/witness leaf for role `reader` in the store.
    witness_counts = Counter()
    seen_iris = set()
    for leaf_path in sorted((store / "views").rglob("*.json")):
        doc = json.loads(leaf_path.read_text(encoding="utf-8"))
        if doc.get("format") == "rezono.proof/1" and doc.get("tree") == "witness" and doc.get("level") == 0:
            for row in doc.get("rows", []):
                if "rule_id" in row and "conclusion" in row:
                    cid = (row["conclusion"]["relation"], row["conclusion"]["key"])
                    witness_counts[cid] += 1
                    iri = row.get("iri", "")
                    assert WITNESS_IRI_RE.fullmatch(iri), f"published witness missing canonical IRI: {row}"
                    seen_iris.add(iri)

    multi = [cid for cid, count in witness_counts.items() if count >= 2]
    assert multi, f"expected >= 1 conclusion with >= 2 founded witnesses in tests/fixtures/slip, got {dict(witness_counts)}"
    assert len(seen_iris) >= 2
