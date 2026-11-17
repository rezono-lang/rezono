"""The satisfaction test of a theory read through a view (M3 of #314; docs/theories.md, step 4). Tests only.

A view is satisfied when the theory concludes through it what it concludes on the domain's instance translated
by hand. The translation is written per case from the view's own words, as a join over the domain's rows; it does
not use the compiler's lowering (`view_rules.bind`). Three comparisons, each as sets:
- `satisfied`: every theory table the view maps holds, through the view, exactly the translated rows, and the
  translation names no table the view leaves unmapped;
- `satisfied`: every relation the theory's rules derive holds, through the view, what the theory compiled on its
  own (no view, no domain) derives from the translated rows;
- `souffle_agrees`: Soufflé on the domain's rule files as written, bound to the view's relations, with the rules
  the view is lowered to (souffle.pack_source), equals the batch backend on every derived relation.
What is left is the theory's axioms: `violations` names the rows of each invariant that has one, so a test states
that each axiom holds in the viewed domain, or which rows break it. A theory joins by a case in
compiler/tests/test_theory_satisfaction.py (a neutral domain) and by its example views in
examples/test_theory_views.py (the test domains' own facts).
"""

from functools import cache
from pathlib import Path

from rezono_compiler import batch, pack
from rezono_compiler import rules as ir
from rezono_compiler.view_rules import table_relation
from support import typed


@cache
def theory(theory_dir: Path):
    """The theory pack and its rules compiled on their own, read once per directory."""
    model = pack.read(theory_dir)
    return model, ir.load(model.rules)


def tables(model) -> list[str]:
    """The theory's tables: one per kind, one per slot (`kind__slot`)."""
    return sorted([k.name for k in model.kinds.values()] + [s.table for k in model.kinds.values() for s in k.slots.values()])


def bound(model, table: str) -> str:
    """The relation that holds a theory table in a domain that reads the theory through a view
    (docs/compiler/schema-operations.md, "Views that execute"): the table and what the view supplies."""
    return table_relation("view_" + model.meta["name"].replace("-", "_"), table)


def text(rows) -> set[tuple[str, ...]]:
    return {tuple(str(v) for v in r) for r in rows}


def run(prog, data, names=None):
    """The batch backend on `data` (rows per input relation, a missing one empty): {relation: set of text tuples}."""
    con = batch.connect(prog, {n: typed(prog, n, rows) for n, rows in data.items() if n in prog.relations}, threads=1)
    try:
        batch.compute(con, prog)
        return batch.read(con, prog, names)
    finally:
        con.close()


def satisfied(prog, data, theory_dir: Path, translated: dict, through=None):
    """Assert that the domain program `prog` on its rows `data` satisfies the theory through its view, against the
    instance `translated` by hand into the theory's own tables. `through` is the domain's result if already
    computed (batch.read with every relation, as `run` gives it). Returns that result."""
    model, own = theory(theory_dir)
    through = through if through is not None else run(prog, data)
    unknown = set(translated) - set(tables(model))
    assert not unknown, f"the translation names no table of the theory: {sorted(unknown)}"
    mapped = {t for t in tables(model) if bound(model, t) in prog.relations}
    assert set(translated) == mapped, f"the translation and the view map different tables: {sorted(set(translated) ^ mapped)}"
    for table in sorted(mapped):
        assert through[bound(model, table)] == text(translated[table]), f"the view supplies other rows for {table}"
    direct = run(own, {t: rows for t, rows in translated.items() if t in own.relations})
    for relation in own.derived():
        assert through[relation] == direct[relation], f"through the view, {relation} differs from the translated instance"
    return through


def violations(theory_dir: Path, rows) -> dict[str, set]:
    """The theory's invariants with a row, and those rows: each is an axiom that does not hold."""
    _, own = theory(theory_dir)
    return {n: rows[n] for n, r in sorted(own.relations.items()) if r.invariant and rows[n]}


def souffle_agrees(prog, data, pack_dir: Path, workdir=None, through=None):
    """Soufflé on the rule files as written, with the rules the view is lowered to, equals the batch backend on
    every derived relation of the domain program."""
    import souffle
    through = through if through is not None else run(prog, data)
    oracle = souffle.run(prog, data, workdir, program_text=souffle.pack_source(prog, pack_dir))
    missing = set(prog.derived()) - set(oracle)
    assert not missing, f"Soufflé returned no result for {sorted(missing)}"
    for name in sorted(oracle):
        assert oracle[name] == through[name], name
    return oracle
