"""The compiler's facts pass admission (rezono_admission, ruling 2 of 11-11-2026). The schema it judges against is
built from the pack (facts.schema) so that loading a fact file does not compile the pack; it must be the schema
the archived bundle states, for every pack with facts. And every refusal reaches the caller, not only the first."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from rezono_admission import Schema
from rezono_compiler import emit, facts, pack

from support import FIXTURE

ROOT = Path(__file__).resolve().parents[2]
PACKS = sorted({p.parent for pattern in ("examples/**/pack.yaml", "packs/*/pack.yaml", "compiler/tests/fixtures/*/pack.yaml")
                for p in ROOT.glob(pattern) if "node_modules" not in p.parts})


@pytest.mark.parametrize("directory", [d for d in PACKS if facts.files(d)], ids=lambda d: d.relative_to(ROOT).as_posix())
def test_the_schema_of_a_pack_is_the_schema_its_bundle_states(directory):
    model = pack.read(directory)
    archived = Schema(json.loads(emit.compile_pack(model)["bundle/schema-bundle.json"]))
    built = facts.schema(model)
    assert (built.pack, built.kinds, built.slots) == (archived.pack, archived.kinds, archived.slots)


def test_every_refusal_is_in_the_load_error():
    model = pack.read(FIXTURE)
    with pytest.raises(facts.LoadError) as err:
        facts.rows_of(model, {"alpha": [{"id": 1, "title": "t"}, {"title": "t"}, {"id": "c", "zz": 1}],
                              "nothing_here": []})
    assert str(err.value) == ("alpha[1].id: is not a VARCHAR; alpha[2]: record without its identifier; "
                              "alpha[3].zz: unknown slot 'zz'; unknown kind 'nothing_here'")
