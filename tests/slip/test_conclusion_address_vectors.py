"""Cross-check contracts/fixtures/conclusion-address-vectors.json against both Python rdf.py and edge/gate TS."""

from __future__ import annotations

import json
from pathlib import Path
import subprocess

import pytest
from rezono_publication import l0, rdf

ROOT = Path(__file__).resolve().parents[2]
VECTORS = ROOT / "contracts/fixtures/conclusion-address-vectors.json"
GATE_MODULE = ROOT / "edge/gate/src/conclusion-address.ts"


def test_conclusion_address_shared_vectors_python_and_gate_agree():
    vectors = json.loads(VECTORS.read_text(encoding="utf-8"))

    # 1. Verify Python rezono_publication.rdf against every shared vector
    for case in vectors["spell_valid"]:
        assert rdf.spell(case["raw"]) == case["spelled"]
        assert rdf.unspell(case["spelled"]) == case["raw"]
    for seg in vectors["unspell_invalid"]:
        with pytest.raises(l0.L0Error):
            rdf.unspell(seg)
    for case in vectors["pin_valid"]:
        pin = case["pin"]
        assert rdf.pin_iri(case["iri"], dataset=pin["dataset"], manifest=pin.get("manifest")) == case["pinned"]
        assert rdf.parse_pin(case["pinned"]) == (case["iri"], pin)
    for bad in vectors["pin_invalid"]:
        with pytest.raises(l0.L0Error):
            rdf.parse_pin(bad)
    schema = vectors["schema"]
    for case in vectors["conclusion_iri"]:
        pin = case["pin"] or {}
        assert (
            rdf.conclusion_iri(
                schema,
                case["kind"],
                case["row_id"],
                manifest=pin.get("manifest"),
                dataset=pin.get("dataset"),
            )
            == case["expected"]
        )

    # 2. Verify edge/gate/src/conclusion-address.ts agrees on every vector (fails on base source without the module)
    assert GATE_MODULE.is_file(), f"missing {GATE_MODULE}"
    probe = (
        "import assert from 'node:assert/strict';"
        "import { readFileSync } from 'node:fs';"
        "import { pathToFileURL } from 'node:url';"
        "const mod = await import(pathToFileURL(process.argv[1]).href);"
        "const v = JSON.parse(readFileSync(process.argv[2], 'utf8'));"
        "for (const c of v.spell_valid) {"
        "  assert.equal(mod.spellSegment(c.raw), c.spelled);"
        "  assert.equal(mod.unspellSegment(c.spelled), c.raw);"
        "}"
        "for (const s of v.unspell_invalid) assert.throws(() => mod.unspellSegment(s));"
        "for (const c of v.pin_valid) {"
        "  assert.equal(mod.pinIri(c.iri, c.pin), c.pinned);"
        "  assert.deepEqual(mod.parsePinnedIri(c.pinned), { iri: c.iri, pin: c.pin });"
        "}"
        "for (const b of v.pin_invalid) assert.throws(() => mod.parsePinnedIri(b));"
        "for (const c of v.conclusion_iri) {"
        "  assert.equal(mod.conclusionIri(v.schema, c.kind, c.row_id, c.pin ?? undefined), c.expected);"
        "}"
    )
    proc = subprocess.run(
        ["node", "--experimental-strip-types", "--no-warnings", "--input-type=module", "-e", probe, str(GATE_MODULE), str(VECTORS)],
        cwd=ROOT,
        capture_output=True,
        encoding="utf-8",
    )
    assert proc.returncode == 0, proc.stderr
