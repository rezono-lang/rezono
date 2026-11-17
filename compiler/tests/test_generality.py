"""Property-based: on random packs, valid facts give no violations and each injected error lands in its view."""

import tempfile
from collections import Counter
from pathlib import Path

import pytest
import yaml
from hypothesis import assume, given
from hypothesis import strategies as st

import genpack
from support import compile_dir, row_text, text, violations
from rezono_compiler import facts, pack


def run(data, error):
    spec = genpack.draw_spec(data.draw)
    state = genpack.draw_state(data.draw, spec)
    target = genpack.inject(data.draw, spec, state, error) if error else None
    assume(error is None or target is not None)
    with tempfile.TemporaryDirectory() as tmp:
        d = Path(tmp)
        genpack.write_pack(spec, d / "pack")
        if spec.refused():
            with pytest.raises(pack.CompileError, match="multivalued arrow, which a path equation cannot follow"):
                pack.read(d / "pack")
            assume(False)
        (d / "facts.yaml").write_text(yaml.safe_dump(state.records(), sort_keys=True, allow_unicode=True))
        files = compile_dir(d / "pack", d / "out")
        rows = facts.load(pack.read(d / "pack"), d / "facts.yaml")
    assert {t: Counter(r) for t, r in rows.items()} == {t: Counter(r) for t, r in state.rows().items()}
    got, want = violations(files, rows), text(genpack.reference(spec, state.rows()))
    assert got == want
    return got, target


@given(st.data())
def test_valid_facts_give_no_violations(data):
    got, _ = run(data, None)
    assert got == {}


@given(st.data(), st.sampled_from(genpack.ERRORS))
def test_each_injected_error_lands_in_its_view(data, error):
    got, (view, row) = run(data, error)
    row = row_text(row)
    assert row in got.get(view, set()), f"{error}: expected {row} in {view}, got {got}"
