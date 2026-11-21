"""The pack converter converts all LinkML constructs used by the ready standard packs and examples/projects.

The ready standard packs (std-decision, std-identity, std-order, std-part, std-time) and examples/projects use
close_mappings, broad_mappings, class annotations (explain: fold), represents_relationship, unique_keys, class
rules (conditional checks), scalar types and path_equations — all already supported by the language reader and
compiler lowering. The converter must emit them and pass its own schema comparison against each live legacy pack,
while continuing to refuse unknown mapping fields.
"""

from contextlib import ExitStack
import os
from pathlib import Path

import pytest

from model_parity import legacy_helpers
from scripts.convert_pack import ConversionError, candidate, sources


REPO = Path(__file__).resolve().parents[3]
PACKS = (
    "packs/std-identity",
    "packs/std-order",
    "packs/std-part",
    "packs/std-time",
    "packs/std-decision",
    "examples/projects",
)


class MissingConverterConstruct(AssertionError):
    """scripts/convert_pack.py refused a supported LinkML construct used by a ready pack."""


def test_pack_converter_converts_standard_pack_constructs(tmp_path):
    node = os.environ.get("REZONO_NODE", "node")
    legacy_root = tmp_path / "legacy"
    helpers = legacy_helpers()
    helpers.materialize_legacy_packs(legacy_root, PACKS, prefer_live=True)
    with ExitStack() as stack:
        helpers.admit_legacy_std_packs(stack, legacy_root)
        for relative in PACKS:
            name = Path(relative).name
            original = legacy_root / relative
            destination = original.parent / f"{name}-candidate"
            try:
                candidate(original, destination, node)
            except ConversionError as error:
                raise MissingConverterConstruct(f"{relative}: {error}") from error
            assert not list((destination / "schema").rglob("*.yaml")) if (destination / "schema").exists() else True
            assert not list((destination / "rules").glob("*.dl")) if (destination / "rules").exists() else True
            assert list((destination / "rezono").rglob("*.rezono")), relative

    # Counter-case: an unrepresented mapping field is still refused instead of silently dropped.
    extra = tmp_path / "unrepresented"
    (extra / "schema").mkdir(parents=True)
    (extra / "schema/sample.yaml").write_text(
        "id: https://rezono.example/sample/sample\n"
        "name: sample\n"
        "imports: [linkml:types]\n"
        "annotations: {layer: facts}\n"
        "classes:\n"
        "  Item:\n"
        "    attributes:\n"
        "      id: {identifier: true}\n"
        "      note: {narrow_mappings: ['skos:narrowMatch']}\n",
        encoding="utf-8",
    )
    with pytest.raises(ConversionError, match=r"Item\.note: no conversion for narrow_mappings"):
        sources(extra, "sample")
