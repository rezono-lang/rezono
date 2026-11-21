"""The IRI vectors that the gate runs too (contracts/fixtures/iri/vectors.json): this side's answers, unchanged.

The file is what `iri_vectors.generate()` gives from `rezono_publication.rdf` today. When this side changes an
answer, the file changes with it in the same pull request, and edge/gate/test/iri-vectors.test.ts must give the
new answer as well.
"""

import json

import pytest

from publication.tests import iri_vectors
from rezono_publication import l0, rdf


def test_the_vectors_are_what_this_side_gives():
    assert iri_vectors.VECTORS.read_text(encoding="utf-8") == iri_vectors.text(), (
        "run `python publication/tests/iri_vectors.py` and commit contracts/fixtures/iri/vectors.json")


def test_the_vectors_name_every_kind_of_refusal_and_a_subkind_without_its_root():
    v = json.loads(iri_vectors.VECTORS.read_text(encoding="utf-8"))
    assert all(v[name] for name in ("spell_refused", "unspell_refused", "pin_refused", "parse_refused", "base_refused"))
    narrow = [s for s in v["spaces"] if s["about"].endswith("a subkind without its root")]
    assert narrow and all(c["iri"].split("/")[-2] == "Item" for s in narrow for c in s["conclusions"])


@pytest.mark.parametrize("manifest", ["m-01", "m-00", "m-007"])
def test_a_manifest_id_spells_its_epoch_one_way(manifest):
    """`m-<epoch>` with `<epoch>` a natural number (l0.md §1): a leading zero names no epoch, as in the gate."""
    assert not l0._MID.fullmatch(manifest)
    with pytest.raises(l0.L0Error):
        rdf.pin_iri("https://example.org/tree/Item/p1", dataset="d-" + "0" * 64, manifest=manifest)
    with pytest.raises(l0.L0Error):
        rdf.parse_pin(f"https://example.org/tree/Item/p1?pin={manifest}@d-" + "0" * 64)
    assert l0._MID.fullmatch("m-0") and l0._MID.fullmatch("m-10")
